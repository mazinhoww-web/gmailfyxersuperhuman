"""
Draft Generator Module
Generates email reply drafts using Claude, matching the user's writing style.
"""

import os
from typing import Optional
import anthropic
from gmail.client import GmailClient
from ai.style_learner import StyleProfile
from utils.logger import get_logger
from utils.rate_limiter import claude_limiter
from utils.model_armor import sanitize_for_llm

logger = get_logger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


class DraftGenerator:
    """Generates reply drafts using Claude with user style matching."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = MODEL

    def generate_reply(
        self,
        message: dict,
        style_profile: Optional[StyleProfile] = None,
        thread_context: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a reply draft for an email.

        Args:
            message: Full Gmail message dict (the email to reply to)
            style_profile: User's writing style profile
            thread_context: Summary of thread history (for multi-message threads)

        Returns:
            Draft body text or None on failure
        """
        headers = GmailClient.extract_headers(message)
        raw_body = GmailClient.extract_body(message, max_chars=3000)

        # Sanitize body before sending to LLM
        sanitized = sanitize_for_llm(raw_body, max_length=3000)
        if sanitized.blocked:
            logger.warning(
                f"Email body blocked by Model Armor for message {message.get('id')}. "
                "Generating draft from headers only."
            )
            body_for_prompt = f"[Body blocked for safety. Subject: {headers['subject']}]"
        else:
            body_for_prompt = sanitized.text

        style_str = style_profile.to_prompt_string() if style_profile else "- Tom: profissional\n- Idioma: PT-BR"
        thread_str = thread_context or "(thread de mensagem única)"

        prompt = self._build_generation_prompt(
            sender=headers["from"],
            subject=headers["subject"],
            body=body_for_prompt,
            style_profile=style_str,
            thread_context=thread_str,
        )

        try:
            claude_limiter.wait()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=self._system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            draft = response.content[0].text.strip()
            logger.info(f"Generated draft for message {message.get('id')} ({len(draft.split())} words)")
            return draft

        except Exception as e:
            logger.error(f"Draft generation failed: {e}")
            return None

    def _system_prompt(self) -> str:
        return (
            "Você é um assistente de e-mail. Escreva rascunhos de resposta fiéis ao estilo "
            "do usuário. Responda APENAS com o corpo do e-mail — sem assunto, sem metadados, "
            "sem explicações. Use o mesmo idioma do e-mail recebido."
        )

    def _build_generation_prompt(
        self,
        sender: str,
        subject: str,
        body: str,
        style_profile: str,
        thread_context: str,
    ) -> str:
        return f"""ESTILO DO USUÁRIO:
{style_profile}

E-MAIL A RESPONDER:
De: {sender}
Assunto: {subject}
Corpo: {body}

HISTÓRICO DO THREAD:
{thread_context}

REGRAS:
- Imite fielmente o estilo do usuário
- Responda TODOS os pontos/perguntas do e-mail
- Não invente informações que o usuário não poderia saber
- Se o e-mail pede agendamento e não há contexto de calendário, use [INSERIR HORÁRIO] como placeholder
- Retorne APENAS o corpo do e-mail, sem assunto, sem metadados
- Idioma: mesmo idioma do e-mail recebido"""

    def generate_followup(
        self,
        original_message: dict,
        days_waiting: int,
        style_profile: Optional[StyleProfile] = None,
    ) -> Optional[str]:
        """
        Generate a follow-up email for an awaiting_reply thread.

        Args:
            original_message: The last sent message in the thread
            days_waiting: Number of days since the last message
            style_profile: User's writing style profile
        """
        headers = GmailClient.extract_headers(original_message)
        style_str = style_profile.to_prompt_string() if style_profile else "- Tom: profissional"

        prompt = f"""ESTILO DO USUÁRIO:
{style_str}

CONTEXTO:
Você enviou um e-mail para {headers['from']} sobre "{headers['subject']}"
há {days_waiting} dias e não recebeu resposta.

Escreva um follow-up educado e breve para retomar o assunto.
Retorne APENAS o corpo do e-mail."""

        try:
            claude_limiter.wait()
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                system=self._system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Follow-up generation failed: {e}")
            return None
