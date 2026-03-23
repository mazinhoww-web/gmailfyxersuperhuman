"""
Draft Management Module
Higher-level draft creation and management built on top of GmailClient.
"""

from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class DraftManager:
    """Manages email drafts: creation, retrieval, sending with undo buffer."""

    def __init__(self, gmail_client):
        self.client = gmail_client
        # draft_id → {"thread_id", "to", "subject", "body"}
        self._draft_registry: dict = {}

    def create_reply_draft(
        self,
        original_message: dict,
        reply_body: str,
    ) -> Optional[str]:
        """
        Create a reply draft linked to the original message's thread.

        Args:
            original_message: Full Gmail message dict being replied to
            reply_body: The plain-text reply body

        Returns:
            Draft ID or None on failure
        """
        headers = self.client.extract_headers(original_message)
        thread_id = original_message.get("threadId")
        message_id = original_message.get("id")
        msg_id_header = headers.get("message_id", "")

        # Build reply subject
        subject = headers["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        draft_id = self.client.create_draft(
            body=reply_body,
            subject=subject,
            to=headers["from"],
            thread_id=thread_id,
            reply_to_message_id=msg_id_header,
        )

        if draft_id:
            self._draft_registry[draft_id] = {
                "thread_id": thread_id,
                "original_message_id": message_id,
                "to": headers["from"],
                "subject": subject,
                "body": reply_body,
            }

        return draft_id

    def get_drafts_for_thread(self, thread_id: str) -> list[dict]:
        """Find all drafts associated with a specific thread."""
        matching = []
        for draft_id, info in self._draft_registry.items():
            if info.get("thread_id") == thread_id:
                matching.append({"draft_id": draft_id, **info})
        return matching

    def list_all_drafts(self) -> list[dict]:
        """List all drafts from Gmail API."""
        return self.client.list_drafts()

    def view_draft(self, draft_id: str) -> Optional[str]:
        """
        Retrieve and return the body text of a draft.

        Returns:
            Draft body string or None
        """
        draft = self.client.get_draft(draft_id)
        if not draft:
            return None

        message = draft.get("message", {})
        return self.client.extract_body(message)

    def send_draft_confirmed(self, draft_id: str) -> bool:
        """
        Send a draft. Should be called only after user confirmation.

        Returns:
            True if sent successfully
        """
        logger.info(f"Sending draft {draft_id} (confirmed by user)")
        success = self.client.send_draft(draft_id)
        if success and draft_id in self._draft_registry:
            del self._draft_registry[draft_id]
        return success

    def discard_draft(self, draft_id: str) -> bool:
        """Delete a draft."""
        success = self.client.delete_draft(draft_id)
        if success and draft_id in self._draft_registry:
            del self._draft_registry[draft_id]
        return success
