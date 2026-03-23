"""
Rate Limiter Module
Prevents API quota exhaustion for both Gmail API and Anthropic API calls.
"""

import time
import threading
from collections import deque
from typing import Callable, Any
from utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter using a sliding window.

    Usage:
        limiter = RateLimiter(max_calls=10, period=60)  # 10 calls/minute
        limiter.wait()  # blocks if rate exceeded
        api_call()
    """

    def __init__(self, max_calls: int, period: float):
        """
        Args:
            max_calls: Maximum number of calls allowed in the time window
            period: Time window in seconds
        """
        self.max_calls = max_calls
        self.period = period
        self._calls: deque = deque()
        self._lock = threading.Lock()

    def wait(self):
        """Block until a call can be made within the rate limit."""
        with self._lock:
            now = time.monotonic()
            # Remove calls outside the window
            while self._calls and now - self._calls[0] > self.period:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                sleep_time = self.period - (now - self._calls[0])
                if sleep_time > 0:
                    logger.debug(f"Rate limit reached, sleeping {sleep_time:.2f}s")
                    time.sleep(sleep_time)
                # Re-clean after sleep
                now = time.monotonic()
                while self._calls and now - self._calls[0] > self.period:
                    self._calls.popleft()

            self._calls.append(time.monotonic())

    def __call__(self, func: Callable) -> Callable:
        """Decorator: apply rate limiting to a function."""
        def wrapper(*args, **kwargs) -> Any:
            self.wait()
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper


# Pre-configured limiters for this project
gmail_limiter = RateLimiter(max_calls=100, period=1)     # 100 req/sec (Gmail API quota)
claude_limiter = RateLimiter(max_calls=5, period=60)     # 5 calls/min (conservative)
batch_limiter = RateLimiter(max_calls=10, period=1)      # For batch operations


def with_retry(
    func: Callable,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Any:
    """
    Execute a function with exponential backoff retry.

    Args:
        func: Callable to execute
        max_retries: Maximum retry attempts
        backoff_base: Base seconds for exponential backoff
        exceptions: Exception types to catch and retry

    Returns:
        Function return value

    Raises:
        Last exception if all retries are exhausted
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except exceptions as e:
            last_exc = e
            if attempt < max_retries:
                wait = backoff_base ** attempt
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
            else:
                logger.error(f"All {max_retries + 1} attempts failed: {e}")
    raise last_exc
