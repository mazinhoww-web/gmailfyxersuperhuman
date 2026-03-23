"""
Thread Summarizer Module
Generates concise summaries of email threads using Claude.
"""

import os
from typing import Optional
import anthropic
from gmail.client import GmailClient
from utils.logger import get_logger
from utils.rate_limiter import claude_limiter
from utils.model_armor import sanitize_for_llm

logger = get_logger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Minimum messages in a thread to trigger auto-summary
MIN_MESSAGES_FOR_SUMMARY = 3


class ThreadSummarizer:
    """Summarizes email threads to provide context for draft generation."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = MODEL

    def summarize_thread(self, thread: dict) -> Optional[str]:
        """
        Generate a summary of an email thread.

        Args:
            thread: Full Gmail thread dict (from get_email_thread)

        Returns:
            2-3 sentence summary string, or None if thread is too short
        """
        messages = thread.get("messages", [])
        if len(messages) < MIN_MESSAGES_FOR_SUMMARY:
            return None

        thread_text = self._build_thread_text(messages)
        if not thread_text:
            return None

        sanitized = sanitize_for_llm(thread_text, max_length=4000)
        if sanitized.blocked:
            logger.warning(f"Thread blocked by Model Armor: {thread.get('id')}")
            return None

        prompt = f"""Resuma o seguinte thread de e-mail em 2-3 frases curtas.
Inclua: contexto principal, decisões tomadas e próximo passo pendente.
Seja objetivo e direto.

THREAD ({len(messages)} mensagens):
{sanitized.text}

RESUMO:"""

        try:
            claude_limiter.wait()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.content[0].text.strip()
            logger.debug(f"Summarized thread {thread.get('id')}: {len(summary)} chars")
            return summary

        except Exception as e:
            logger.error(f"Thread summarization failed: {e}")
            return None

    def _build_thread_text(self, messages: list[dict], max_chars_per_msg: int = 500) -> str:
        """Build a compact text representation of the thread."""
        parts = []
        for i, msg in enumerate(messages, 1):
            headers = GmailClient.extract_headers(msg)
            body = GmailClient.extract_body(msg, max_chars=max_chars_per_msg)
            parts.append(
                f"[{i}] De: {headers['from']} ({headers['date']})\n"
                f"Assunto: {headers['subject']}\n"
                f"{body}\n"
            )
        return "\n---\n".join(parts)

    def get_thread_context(self, thread: dict) -> str:
        """
        Get thread context for draft generation.
        Returns summary if available, otherwise last few messages.
        """
        messages = thread.get("messages", [])

        if len(messages) >= MIN_MESSAGES_FOR_SUMMARY:
            summary = self.summarize_thread(thread)
            if summary:
                return f"Thread de {len(messages)} mensagens. Resumo: {summary}"

        # For short threads, return previous messages text
        if len(messages) <= 2:
            return "(thread novo, sem histórico relevante)"

        last_msg = messages[-2] if len(messages) >= 2 else messages[0]
        headers = GmailClient.extract_headers(last_msg)
        body = GmailClient.extract_body(last_msg, max_chars=300)
        return f"Mensagem anterior de {headers['from']}: {body}"
