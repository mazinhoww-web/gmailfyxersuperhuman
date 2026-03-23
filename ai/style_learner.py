"""
Style Learner Module
Analyzes the user's sent emails to build a writing style profile
for use in draft generation.
"""

import json
import re
from typing import Optional
from gmail.client import GmailClient
from utils.logger import get_logger

logger = get_logger(__name__)

# Number of example pairs to include in the style profile
MAX_EXAMPLES = 5
MAX_SENT_EMAILS = 300


class StyleProfile:
    """Represents a user's email writing style."""

    def __init__(
        self,
        tone: str = "misto",
        greeting: str = "",
        closing: str = "",
        avg_length: str = "médio",
        language: str = "PT-BR",
        examples: Optional[list] = None,
    ):
        self.tone = tone
        self.greeting = greeting
        self.closing = closing
        self.avg_length = avg_length
        self.language = language
        self.examples = examples or []

    def to_prompt_string(self) -> str:
        """Format profile as a string for inclusion in LLM prompts."""
        lines = [
            f"- Tom: {self.tone}",
            f"- Saudação típica: {self.greeting or '(sem saudação)'}",
            f"- Fechamento típico: {self.closing or '(sem fechamento)'}",
            f"- Comprimento médio: {self.avg_length}",
            f"- Idioma predominante: {self.language}",
        ]

        if self.examples:
            lines.append("- Exemplos de respostas reais:")
            for i, ex in enumerate(self.examples[:MAX_EXAMPLES], 1):
                lines.append(f"  Exemplo {i}: {ex[:200]}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "tone": self.tone,
            "greeting": self.greeting,
            "closing": self.closing,
            "avg_length": self.avg_length,
            "language": self.language,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StyleProfile":
        return cls(
            tone=data.get("tone", "misto"),
            greeting=data.get("greeting", ""),
            closing=data.get("closing", ""),
            avg_length=data.get("avg_length", "médio"),
            language=data.get("language", "PT-BR"),
            examples=data.get("examples", []),
        )


class StyleLearner:
    """Learns writing style from sent email history."""

    def __init__(self, gmail_client: GmailClient):
        self.client = gmail_client
        self._cached_profile: Optional[StyleProfile] = None

    def build_style_profile(self, max_emails: int = MAX_SENT_EMAILS) -> StyleProfile:
        """
        Analyze sent emails and return a StyleProfile.

        Args:
            max_emails: Number of sent emails to analyze

        Returns:
            StyleProfile with tone, greeting, closing, language, examples
        """
        logger.info(f"Fetching up to {max_emails} sent emails for style analysis...")
        sent_messages = self.client.get_sent_emails(max_results=max_emails)

        if not sent_messages:
            logger.warning("No sent emails found, using default style profile")
            return StyleProfile()

        logger.info(f"Analyzing {len(sent_messages)} sent emails...")

        bodies = []
        for msg in sent_messages:
            body = self.client.extract_body(msg, max_chars=1000)
            if body and len(body.strip()) > 20:
                bodies.append(body.strip())

        if not bodies:
            return StyleProfile()

        profile = StyleProfile(
            tone=self._detect_tone(bodies),
            greeting=self._detect_greeting(bodies),
            closing=self._detect_closing(bodies),
            avg_length=self._detect_avg_length(bodies),
            language=self._detect_language(bodies),
            examples=self._extract_examples(bodies),
        )

        self._cached_profile = profile
        logger.info(
            f"Style profile built: tone={profile.tone}, lang={profile.language}, "
            f"length={profile.avg_length}"
        )
        return profile

    def get_cached_profile(self) -> Optional[StyleProfile]:
        return self._cached_profile

    # ─── ANALYSIS METHODS ───────────────────────────────────────────────────

    def _detect_tone(self, bodies: list[str]) -> str:
        """Detect formal vs informal tone from email bodies."""
        formal_signals = [
            r"\bAtenciosamente\b", r"\bCordialmente\b", r"\bRespeitosamente\b",
            r"\bDear\b", r"\bBest regards\b", r"\bSincerely\b",
            r"\bSenhor\b", r"\bSenhora\b", r"\bV\.Sa\b",
        ]
        informal_signals = [
            r"\bOi\b", r"\bOlá\b", r"\bEi\b", r"\bHey\b",
            r"\bAbração\b", r"\bBjss?\b", r"\bValeu\b", r"\bFalou\b",
        ]

        formal_count = sum(
            1 for body in bodies
            for pat in formal_signals
            if re.search(pat, body, re.IGNORECASE)
        )
        informal_count = sum(
            1 for body in bodies
            for pat in informal_signals
            if re.search(pat, body, re.IGNORECASE)
        )

        if formal_count > informal_count * 2:
            return "formal"
        if informal_count > formal_count * 2:
            return "informal"
        return "misto"

    def _detect_greeting(self, bodies: list[str]) -> str:
        """Find the most common greeting pattern."""
        greetings: dict = {}
        patterns = [
            r"^(Olá[,\s][^,\n]{0,30})",
            r"^(Oi[,\s][^,\n]{0,30})",
            r"^(Bom dia[,\s][^,\n]{0,20})",
            r"^(Boa tarde[,\s][^,\n]{0,20})",
            r"^(Dear [^,\n]{0,30})",
            r"^(Hi [^,\n]{0,30})",
            r"^(Hello[,\s][^,\n]{0,30})",
        ]
        for body in bodies:
            first_line = body.split("\n")[0].strip()
            for pat in patterns:
                m = re.match(pat, first_line, re.IGNORECASE)
                if m:
                    key = re.sub(r"\b[A-Z][a-z]+\b", "[nome]", m.group(1))
                    greetings[key] = greetings.get(key, 0) + 1
                    break

        if greetings:
            return max(greetings, key=greetings.get)
        return ""

    def _detect_closing(self, bodies: list[str]) -> str:
        """Find the most common closing/signature pattern."""
        closings: dict = {}
        patterns = [
            r"(Abraços?[,.]?)\s*$",
            r"(Att[,.]?)\s*$",
            r"(Atenciosamente[,.]?)\s*$",
            r"(Best regards?[,.]?)\s*$",
            r"(Thanks?[,.]?)\s*$",
            r"(Obrigad[oa][,.]?)\s*$",
            r"(\[\])\s*$",
        ]
        for body in bodies:
            last_lines = " ".join(body.split("\n")[-3:])
            for pat in patterns:
                m = re.search(pat, last_lines, re.IGNORECASE | re.MULTILINE)
                if m:
                    closing = m.group(1).strip()
                    closings[closing] = closings.get(closing, 0) + 1
                    break

        if closings:
            return max(closings, key=closings.get)
        return ""

    def _detect_avg_length(self, bodies: list[str]) -> str:
        """Classify typical email length as short/medium/long."""
        word_counts = [len(b.split()) for b in bodies]
        avg = sum(word_counts) / len(word_counts) if word_counts else 50

        if avg < 50:
            return "curto"
        if avg < 150:
            return "médio"
        return "longo"

    def _detect_language(self, bodies: list[str]) -> str:
        """Detect predominant language (PT-BR, EN, or mixed)."""
        pt_words = {"de", "do", "da", "para", "com", "que", "uma", "por", "não", "como"}
        en_words = {"the", "and", "for", "with", "from", "this", "that", "have", "you"}

        text = " ".join(bodies[:50]).lower()
        words = set(text.split())

        pt_score = len(words & pt_words)
        en_score = len(words & en_words)

        if pt_score > en_score * 2:
            return "PT-BR"
        if en_score > pt_score * 2:
            return "EN"
        return "misto (PT-BR/EN)"

    def _extract_examples(self, bodies: list[str]) -> list[str]:
        """Extract representative short response examples."""
        examples = []
        # Prefer short-to-medium length responses (more typical)
        candidates = sorted(bodies, key=lambda b: abs(len(b.split()) - 60))
        for body in candidates[:MAX_EXAMPLES]:
            # Anonymize: remove email addresses and proper nouns (simple heuristic)
            anonymized = re.sub(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                "[email]",
                body,
            )
            examples.append(anonymized[:300])
        return examples
