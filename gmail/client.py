"""
Gmail API Client Wrapper
Provides a clean interface over the Gmail REST API.
"""

import base64
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Gmail system label IDs
LABEL_INBOX = "INBOX"
LABEL_SENT = "SENT"
LABEL_UNREAD = "UNREAD"
LABEL_TRASH = "TRASH"
LABEL_DRAFT = "DRAFT"


class GmailClient:
    """
    Wrapper around the Gmail API service.
    All operations default to userId='me' (authenticated user).
    """

    def __init__(self, service, dry_run: bool = False):
        """
        Args:
            service: Authenticated Gmail API service from get_gmail_service()
            dry_run: If True, write operations are logged but not executed
        """
        self.service = service
        self.dry_run = dry_run
        self._label_cache: dict = {}

    # ─── READ OPERATIONS ────────────────────────────────────────────────────

    def get_unread_emails(self, max_results: int = 50) -> list[dict]:
        """
        Fetch unread messages from the inbox.

        Returns:
            List of full message dicts (with id, threadId, snippet, payload, etc.)
        """
        results = (
            self.service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[LABEL_INBOX, LABEL_UNREAD],
                maxResults=max_results,
            )
            .execute()
        )

        messages = results.get("messages", [])
        full_messages = []
        for msg in messages:
            full = self.get_message(msg["id"])
            if full:
                full_messages.append(full)
        return full_messages

    def get_inbox_emails(self, max_results: int = 50) -> list[dict]:
        """Fetch all inbox messages (read + unread)."""
        results = (
            self.service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[LABEL_INBOX],
                maxResults=max_results,
            )
            .execute()
        )
        messages = results.get("messages", [])
        return [self.get_message(m["id"]) for m in messages if m]

    def get_message(self, message_id: str) -> Optional[dict]:
        """Fetch a single message by ID (full format)."""
        try:
            return (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except Exception as e:
            logger.error(f"Failed to fetch message {message_id}: {e}")
            return None

    def get_email_thread(self, thread_id: str) -> Optional[dict]:
        """Fetch a full thread by thread ID."""
        try:
            return (
                self.service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except Exception as e:
            logger.error(f"Failed to fetch thread {thread_id}: {e}")
            return None

    def get_sent_emails(self, max_results: int = 300) -> list[dict]:
        """
        Fetch sent messages for style analysis.

        Returns:
            List of full message dicts from SENT folder
        """
        results = (
            self.service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[LABEL_SENT],
                maxResults=max_results,
            )
            .execute()
        )
        messages = results.get("messages", [])
        full_messages = []
        for msg in messages:
            full = self.get_message(msg["id"])
            if full:
                full_messages.append(full)
        return full_messages

    def list_messages(
        self,
        query: str = "",
        label_ids: Optional[list] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Generic message listing with Gmail search query support.

        Args:
            query: Gmail search query (e.g. "from:user@example.com after:2024/01/01")
            label_ids: Filter by label IDs
            max_results: Maximum number of results

        Returns:
            List of message stubs (id + threadId only)
        """
        kwargs = {"userId": "me", "maxResults": max_results}
        if query:
            kwargs["q"] = query
        if label_ids:
            kwargs["labelIds"] = label_ids

        results = self.service.users().messages().list(**kwargs).execute()
        return results.get("messages", [])

    # ─── WRITE OPERATIONS ───────────────────────────────────────────────────

    def apply_label(self, message_id: str, label_id: str) -> bool:
        """Add a label to a message."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would apply label {label_id} to {message_id}")
            return True
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            logger.debug(f"Applied label {label_id} to {message_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply label {label_id} to {message_id}: {e}")
            return False

    def remove_label(self, message_id: str, label_id: str) -> bool:
        """Remove a label from a message."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would remove label {label_id} from {message_id}")
            return True
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": [label_id]},
            ).execute()
            logger.debug(f"Removed label {label_id} from {message_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove label {label_id} from {message_id}: {e}")
            return False

    def remove_from_inbox(self, message_id: str) -> bool:
        """Archive a message (remove INBOX label)."""
        return self.remove_label(message_id, LABEL_INBOX)

    def mark_as_read(self, message_id: str) -> bool:
        """Mark a message as read (remove UNREAD label)."""
        return self.remove_label(message_id, LABEL_UNREAD)

    def move_to_trash(self, message_id: str) -> bool:
        """Move message to trash (safe delete — retains for 30 days)."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would trash message {message_id}")
            return True
        try:
            self.service.users().messages().trash(
                userId="me", id=message_id
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to trash {message_id}: {e}")
            return False

    def apply_labels_and_archive(
        self,
        message_id: str,
        label_id: str,
        archive: bool = False,
    ) -> bool:
        """
        Apply a category label and optionally archive.

        Args:
            message_id: The Gmail message ID
            label_id: The category label ID to apply
            archive: If True, also remove from INBOX

        Returns:
            True if all operations succeeded
        """
        body = {"addLabelIds": [label_id]}
        if archive:
            body["removeLabelIds"] = [LABEL_INBOX]

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would modify {message_id}: add={label_id}, "
                f"archive={archive}"
            )
            return True

        try:
            self.service.users().messages().modify(
                userId="me", id=message_id, body=body
            ).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to modify {message_id}: {e}")
            return False

    # ─── DRAFT OPERATIONS ───────────────────────────────────────────────────

    def create_draft(
        self,
        body: str,
        subject: str,
        to: str,
        thread_id: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a draft email (linked to thread if thread_id provided).

        Args:
            body: Plain text email body
            subject: Email subject line
            to: Recipient email address
            thread_id: Gmail thread ID to attach the draft to
            reply_to_message_id: Original message ID for In-Reply-To header

        Returns:
            Draft ID if successful, None otherwise
        """
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would create draft to={to} subject='{subject}' "
                f"thread={thread_id}"
            )
            return "dry-run-draft-id"

        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
            msg["References"] = reply_to_message_id
        msg.attach(MIMEText(body, "plain", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft_body: dict = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        try:
            draft = (
                self.service.users()
                .drafts()
                .create(userId="me", body=draft_body)
                .execute()
            )
            draft_id = draft.get("id")
            logger.info(f"Created draft {draft_id} for thread {thread_id}")
            return draft_id
        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            return None

    def send_draft(self, draft_id: str) -> bool:
        """
        Send a draft immediately.
        NOTE: Should only be called after explicit user confirmation.
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would send draft {draft_id}")
            return True
        try:
            self.service.users().drafts().send(
                userId="me", body={"id": draft_id}
            ).execute()
            logger.info(f"Sent draft {draft_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send draft {draft_id}: {e}")
            return False

    def get_draft(self, draft_id: str) -> Optional[dict]:
        """Fetch a draft by ID."""
        try:
            return (
                self.service.users()
                .drafts()
                .get(userId="me", id=draft_id, format="full")
                .execute()
            )
        except Exception as e:
            logger.error(f"Failed to fetch draft {draft_id}: {e}")
            return None

    def list_drafts(self) -> list[dict]:
        """List all drafts."""
        result = self.service.users().drafts().list(userId="me").execute()
        return result.get("drafts", [])

    def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would delete draft {draft_id}")
            return True
        try:
            self.service.users().drafts().delete(userId="me", id=draft_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to delete draft {draft_id}: {e}")
            return False

    # ─── HELPERS ────────────────────────────────────────────────────────────

    @staticmethod
    def extract_headers(message: dict) -> dict:
        """
        Extract key headers from a message payload.

        Returns:
            dict with keys: from, to, subject, date, message_id
        """
        headers = {}
        payload = message.get("payload", {})
        header_list = payload.get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in header_list}

        headers["from"] = header_map.get("from", "")
        headers["to"] = header_map.get("to", "")
        headers["subject"] = header_map.get("subject", "(no subject)")
        headers["date"] = header_map.get("date", "")
        headers["message_id"] = header_map.get("message-id", "")
        return headers

    @staticmethod
    def extract_body(message: dict, max_chars: int = 5000) -> str:
        """
        Extract plain text body from a message payload.

        Args:
            message: Full Gmail message dict
            max_chars: Truncate body to this length

        Returns:
            Plain text body string
        """
        payload = message.get("payload", {})
        body = GmailClient._get_plain_text(payload)
        return body[:max_chars] if body else message.get("snippet", "")

    @staticmethod
    def _get_plain_text(payload: dict) -> str:
        """Recursively extract plain/text part from MIME payload."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

        if mime_type in ("multipart/alternative", "multipart/mixed", "multipart/related"):
            for part in payload.get("parts", []):
                text = GmailClient._get_plain_text(part)
                if text:
                    return text

        return ""

    @staticmethod
    def format_email_summary(message: dict) -> str:
        """Return a single-line summary of an email for display."""
        headers = GmailClient.extract_headers(message)
        snippet = message.get("snippet", "")[:80]
        labels = message.get("labelIds", [])
        unread = "UNREAD" in labels
        prefix = "* " if unread else "  "
        return (
            f"{prefix}{headers['from'][:30]:<32} "
            f"{headers['subject'][:45]:<47} "
            f"{snippet}"
        )
