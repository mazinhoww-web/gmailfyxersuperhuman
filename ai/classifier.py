"""
Email Classifier Module
Uses Claude to classify emails into one of 8 categories.
"""

import json
import os
from typing import Optional
import anthropic
from utils.logger import get_logger
from utils.rate_limiter import claude_limiter
from utils.model_armor import sanitize_for_llm, extract_safe_headers

logger = get_logger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

CATEGORIES = {
    "to_respond",
    "fyi",
    "comment",
    "notification",
    "meeting_update",
    "awaiting_reply",
    "actioned",
    "marketing",
}

SYSTEM_PROMPT = """Você é um classificador de e-mails. Analise o e-mail e retorne APENAS um JSON com o campo "category" sendo um dos valores:
"to_respond" | "fyi" | "comment" | "notification" | "meeting_update" | "awaiting_reply" | "actioned" | "marketing"

Regras de classificação:
- to_respond: e-mail contém pergunta direta, pedido de ação, prazo ou solicita resposta do destinatário. É o mais importante.
- fyi: informativo, não requer ação, agenda, avisos
- comment: menções de Google Docs, Notion, Figma, ferramentas colaborativas
- notification: alertas automáticos de sistemas, apps, plataformas
- meeting_update: convites de calendário, mudanças de reunião, cancelamentos
- awaiting_reply: thread onde o destinatário já respondeu e aguarda o outro lado
- actioned: conversa encerrada, aprovação final, "obrigado, resolvido"
- marketing: newsletters, promos, cold outreach, vendas

Analise: remetente, assunto, primeiras 500 chars do corpo. Retorne SOMENTE o JSON. Sem explicação."""


class EmailClassifier:
    """Classifies emails using Claude AI."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = MODEL

    def classify_email(self, message: dict) -> str:
        """
        Classify a Gmail message into one of 8 categories.

        Uses only headers + snippet for safety (no raw body to LLM without sanitization).

        Args:
            message: Full Gmail message dict

        Returns:
            Category string (e.g. "to_respond", "marketing")
        """
        safe_data = extract_safe_headers(message)

        # Build the analysis prompt with sanitized data
        user_content = self._build_classification_prompt(safe_data)

        try:
            claude_limiter.wait()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )

            raw = response.content[0].text.strip()
            return self._parse_category(raw)

        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return "fyi"  # Safe default

    def classify_with_body(self, message: dict) -> str:
        """
        Classify using sanitized body content (for more accurate results).

        Use this when header-only classification is insufficient.
        """
        from gmail.client import GmailClient

        safe_headers = extract_safe_headers(message)
        raw_body = GmailClient.extract_body(message, max_chars=500)

        # Sanitize body before sending to LLM
        sanitized = sanitize_for_llm(raw_body, max_length=500)
        if sanitized.blocked:
            logger.warning(f"Body blocked by Model Armor for msg {message.get('id')}, using headers only")
            return self.classify_email(message)

        user_content = self._build_classification_prompt(
            safe_headers, body=sanitized.text
        )

        try:
            claude_limiter.wait()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = response.content[0].text.strip()
            return self._parse_category(raw)

        except Exception as e:
            logger.error(f"Classification (with body) failed: {e}")
            return "fyi"

    def _build_classification_prompt(self, headers: dict, body: str = "") -> str:
        parts = [
            f"De: {headers.get('from', '')}",
            f"Assunto: {headers.get('subject', '')}",
            f"Data: {headers.get('date', '')}",
            f"Snippet: {headers.get('snippet', '')}",
        ]
        if body:
            parts.append(f"Corpo (primeiros 500 chars): {body}")
        return "\n".join(parts)

    def _parse_category(self, raw: str) -> str:
        """Parse Claude's JSON response and validate the category."""
        try:
            # Handle markdown code blocks
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw.strip())
            category = data.get("category", "fyi").lower().replace(" ", "_")
            if category in CATEGORIES:
                return category
            logger.warning(f"Unknown category returned: {category}, defaulting to fyi")
            return "fyi"
        except json.JSONDecodeError:
            logger.warning(f"Could not parse classification response: {raw!r}")
            return "fyi"

    def batch_classify(self, messages: list[dict], use_body: bool = True) -> list[tuple[str, str]]:
        """
        Classify a batch of messages.

        Args:
            messages: List of Gmail message dicts
            use_body: Whether to use sanitized body for classification

        Returns:
            List of (message_id, category) tuples
        """
        results = []
        for msg in messages:
            msg_id = msg.get("id", "unknown")
            if use_body:
                category = self.classify_with_body(msg)
            else:
                category = self.classify_email(msg)
            results.append((msg_id, category))
            logger.info(f"Classified {msg_id}: {category}")
        return results
