"""
Model Armor Integration
Sanitizes email content before passing to Claude to prevent prompt injection.
Uses GWS CLI modelarmor command when available, falls back to local sanitization.
"""

import os
import re
import subprocess
import shutil
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Environment configuration
TEMPLATE_ID = os.getenv("GOOGLE_WORKSPACE_CLI_SANITIZE_TEMPLATE", "")
SANITIZE_MODE = os.getenv("GOOGLE_WORKSPACE_CLI_SANITIZE_MODE", "warn")  # warn | block

# Patterns that indicate potential prompt injection attempts
INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all instructions",
    r"disregard.*instructions",
    r"you are now",
    r"act as",
    r"pretend (you are|to be)",
    r"system:\s*",
    r"<\|im_start\|>",
    r"\[INST\]",
    r"###\s*(system|human|assistant)",
    r"forget everything",
    r"new instructions",
    r"override.*instructions",
]

_INJECTION_RE = re.compile(
    "|".join(INJECTION_PATTERNS),
    re.IGNORECASE | re.DOTALL,
)


class ModelArmorResult:
    """Result from content sanitization."""

    def __init__(self, text: str, sanitized: bool, blocked: bool, reason: str = ""):
        self.text = text
        self.sanitized = sanitized  # True if content was modified
        self.blocked = blocked       # True if content was blocked entirely
        self.reason = reason

    def __bool__(self):
        return not self.blocked


def sanitize_for_llm(
    text: str,
    template_id: Optional[str] = None,
    mode: Optional[str] = None,
    max_length: int = 2000,
) -> ModelArmorResult:
    """
    Sanitize text content before passing to Claude.

    Tries GWS CLI first, falls back to local pattern matching.

    Args:
        text: Raw text to sanitize (email body, subject, etc.)
        template_id: Model Armor template ID (overrides env var)
        mode: "warn" (flag but pass) or "block" (reject flagged content)
        max_length: Truncate to this length before sanitization

    Returns:
        ModelArmorResult with sanitized text and flags
    """
    tmpl = template_id or TEMPLATE_ID
    sanitize_mode = mode or SANITIZE_MODE

    # Truncate first
    truncated = text[:max_length] if len(text) > max_length else text

    # Try GWS CLI if template is configured
    if tmpl and shutil.which("gws"):
        return _sanitize_via_gws_cli(truncated, tmpl, sanitize_mode)

    # Fall back to local sanitization
    return _sanitize_local(truncated, sanitize_mode)


def _sanitize_via_gws_cli(
    text: str,
    template_id: str,
    mode: str,
) -> ModelArmorResult:
    """
    Run GWS CLI modelarmor sanitization.

    Command: gws modelarmor +sanitize-prompt --template T --text TEXT
    """
    try:
        result = subprocess.run(
            ["gws", "modelarmor", "+sanitize-prompt", "--template", template_id, "--text", text],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            sanitized_text = result.stdout.strip()
            modified = sanitized_text != text
            logger.debug(f"GWS CLI sanitization: modified={modified}")
            return ModelArmorResult(
                text=sanitized_text,
                sanitized=modified,
                blocked=False,
            )

        # Non-zero return = injection detected
        reason = result.stderr.strip() or "Injection detected by Model Armor"
        logger.warning(f"Model Armor flagged content: {reason}")

        if mode == "block":
            return ModelArmorResult(
                text="",
                sanitized=True,
                blocked=True,
                reason=reason,
            )
        else:
            # warn mode: pass through but log
            return ModelArmorResult(
                text=text,
                sanitized=False,
                blocked=False,
                reason=reason,
            )

    except subprocess.TimeoutExpired:
        logger.warning("GWS CLI timed out, falling back to local sanitization")
        return _sanitize_local(text, mode)
    except FileNotFoundError:
        logger.debug("GWS CLI not found, using local sanitization")
        return _sanitize_local(text, mode)
    except Exception as e:
        logger.error(f"GWS CLI error: {e}, falling back to local sanitization")
        return _sanitize_local(text, mode)


def _sanitize_local(text: str, mode: str) -> ModelArmorResult:
    """
    Local pattern-based sanitization as fallback.
    Detects common prompt injection patterns.
    """
    match = _INJECTION_RE.search(text)

    if match:
        reason = f"Potential injection pattern: '{match.group()[:50]}'"
        logger.warning(f"Local sanitizer flagged content: {reason}")

        if mode == "block":
            return ModelArmorResult(
                text="",
                sanitized=True,
                blocked=True,
                reason=reason,
            )
        else:
            # Redact the matched portion
            cleaned = _INJECTION_RE.sub("[REDACTED]", text)
            return ModelArmorResult(
                text=cleaned,
                sanitized=True,
                blocked=False,
                reason=reason,
            )

    return ModelArmorResult(text=text, sanitized=False, blocked=False)


def extract_safe_headers(message: dict) -> dict:
    """
    Extract only headers (no body) for safe triaging.
    Headers are much less likely to contain injection attacks.

    Returns:
        dict with: from, subject, snippet (200 chars max)
    """
    from gmail.client import GmailClient
    headers = GmailClient.extract_headers(message)
    snippet = message.get("snippet", "")[:200]
    return {
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "snippet": snippet,
        "date": headers.get("date", ""),
    }
