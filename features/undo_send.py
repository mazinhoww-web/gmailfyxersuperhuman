"""
Undo Send Feature
Provides a configurable countdown before actually sending a draft.
User can press Ctrl+C to cancel within the undo window.
"""

import time
import sys
from typing import Optional
from gmail.client import GmailClient
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_UNDO_WINDOW = 10  # seconds


class UndoSendBuffer:
    """Manages the undo send countdown and cancellation."""

    def __init__(self, gmail_client: GmailClient, undo_window: int = DEFAULT_UNDO_WINDOW):
        """
        Args:
            gmail_client: Authenticated GmailClient
            undo_window: Seconds to wait before sending (user can Ctrl+C to cancel)
        """
        self.gmail = gmail_client
        self.undo_window = undo_window

    def send_with_undo(self, draft_id: str) -> bool:
        """
        Send a draft with an undo countdown.

        Displays countdown and waits undo_window seconds.
        If user presses Ctrl+C, send is cancelled.

        Args:
            draft_id: The Gmail draft ID to send

        Returns:
            True if sent, False if cancelled
        """
        print(f"\nSending in {self.undo_window} seconds... [Ctrl+C to cancel]")

        try:
            for remaining in range(self.undo_window, 0, -1):
                sys.stdout.write(f"\r  {remaining}s remaining... ")
                sys.stdout.flush()
                time.sleep(1)

            sys.stdout.write("\r  Sending...               \n")
            sys.stdout.flush()

            success = self.gmail.send_draft(draft_id)
            if success:
                print("Email sent!")
            else:
                print("Failed to send email. Check logs for details.")
            return success

        except KeyboardInterrupt:
            sys.stdout.write("\r  Send cancelled.          \n")
            sys.stdout.flush()
            logger.info(f"Send cancelled by user (draft {draft_id} preserved)")
            return False

    def send_immediate(self, draft_id: str) -> bool:
        """
        Send immediately without undo window (for automated/confirmed sends).
        Requires explicit call — never called automatically.
        """
        logger.info(f"Sending draft {draft_id} immediately (no undo)")
        return self.gmail.send_draft(draft_id)
