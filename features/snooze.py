"""
Snooze / Remind Me Feature
Hides emails from inbox until a specified time, then restores them.
"""

import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from gmail.client import GmailClient, LABEL_INBOX
from utils.logger import get_logger

logger = get_logger(__name__)

SNOOZE_DB_PATH = Path(__file__).parent.parent / "data" / "snoozed.json"
SNOOZE_LABEL = "snoozed"  # Optional: create this label in Gmail for visibility


class SnoozeManager:
    """
    Manages snoozed emails: removes from inbox temporarily
    and restores them at the specified time.
    """

    def __init__(self, gmail_client: GmailClient, label_map: Optional[dict] = None):
        self.gmail = gmail_client
        self.label_map = label_map or {}
        self._snoozed: dict = self._load_db()
        self._watcher_thread: Optional[threading.Thread] = None

    def snooze_email(self, message_id: str, remind_at: datetime) -> bool:
        """
        Snooze an email until remind_at datetime.

        Args:
            message_id: Gmail message ID
            remind_at: When to restore the email to inbox

        Returns:
            True if snoozed successfully
        """
        # Remove from inbox
        success = self.gmail.remove_from_inbox(message_id)
        if not success:
            return False

        # Persist snooze record
        self._snoozed[message_id] = {
            "message_id": message_id,
            "remind_at": remind_at.isoformat(),
            "snoozed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_db()

        logger.info(
            f"Snoozed {message_id} until {remind_at.strftime('%Y-%m-%d %H:%M')}"
        )
        return True

    def restore_due_emails(self) -> list[str]:
        """
        Check for emails whose snooze has expired and restore them to inbox.

        Returns:
            List of restored message IDs
        """
        now = datetime.now(timezone.utc)
        restored = []

        for msg_id, record in list(self._snoozed.items()):
            remind_at = datetime.fromisoformat(record["remind_at"])
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=timezone.utc)

            if now >= remind_at:
                success = self.gmail.apply_label(msg_id, LABEL_INBOX)
                if success:
                    del self._snoozed[msg_id]
                    restored.append(msg_id)
                    logger.info(f"Restored snoozed email {msg_id} to inbox")

        if restored:
            self._save_db()

        return restored

    def list_snoozed(self) -> list[dict]:
        """Return all currently snoozed emails."""
        return list(self._snoozed.values())

    def cancel_snooze(self, message_id: str) -> bool:
        """Cancel a snooze and immediately restore the email."""
        if message_id not in self._snoozed:
            return False

        success = self.gmail.apply_label(message_id, LABEL_INBOX)
        if success:
            del self._snoozed[message_id]
            self._save_db()
            logger.info(f"Cancelled snooze for {message_id}")
        return success

    def start_background_watcher(self, check_interval: int = 60):
        """
        Start a background thread that checks for due snoozes every N seconds.

        Args:
            check_interval: Seconds between checks
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            return

        def watcher():
            while True:
                try:
                    restored = self.restore_due_emails()
                    if restored:
                        logger.info(f"Auto-restored {len(restored)} snoozed email(s)")
                except Exception as e:
                    logger.error(f"Snooze watcher error: {e}")
                time.sleep(check_interval)

        self._watcher_thread = threading.Thread(target=watcher, daemon=True)
        self._watcher_thread.start()
        logger.info(f"Snooze watcher started (interval: {check_interval}s)")

    def _load_db(self) -> dict:
        SNOOZE_DB_PATH.parent.mkdir(exist_ok=True)
        if SNOOZE_DB_PATH.exists():
            with open(SNOOZE_DB_PATH) as f:
                return json.load(f)
        return {}

    def _save_db(self):
        with open(SNOOZE_DB_PATH, "w") as f:
            json.dump(self._snoozed, f, indent=2)
