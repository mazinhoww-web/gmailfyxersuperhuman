"""
Follow-up Tracker
Detects awaiting_reply threads that haven't been responded to
and generates follow-up suggestions.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from gmail.client import GmailClient
from ai.draft_generator import DraftGenerator
from ai.style_learner import StyleProfile
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_FOLLOWUP_DAYS = 3  # Suggest follow-up after N days without reply


class FollowUpTracker:
    """Tracks awaiting_reply emails and generates follow-up suggestions."""

    def __init__(
        self,
        gmail_client: GmailClient,
        label_map: dict,
        draft_generator: Optional[DraftGenerator] = None,
        style_profile: Optional[StyleProfile] = None,
        followup_after_days: int = DEFAULT_FOLLOWUP_DAYS,
    ):
        self.gmail = gmail_client
        self.label_map = label_map
        self.draft_generator = draft_generator
        self.style_profile = style_profile
        self.followup_after_days = followup_after_days

    def find_overdue_threads(self) -> list[dict]:
        """
        Find awaiting_reply emails older than followup_after_days with no reply.

        Returns:
            List of dicts: {message, days_waiting, headers}
        """
        awaiting_label_id = self.label_map.get("awaiting_reply")
        if not awaiting_label_id:
            logger.warning("No awaiting_reply label ID configured")
            return []

        # Fetch messages with awaiting_reply label
        stubs = self.gmail.list_messages(
            label_ids=[awaiting_label_id],
            max_results=100,
        )

        overdue = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.followup_after_days)

        for stub in stubs:
            msg = self.gmail.get_message(stub["id"])
            if not msg:
                continue

            # Parse internal date
            internal_date_ms = int(msg.get("internalDate", 0))
            msg_date = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)

            if msg_date < cutoff:
                days_waiting = (datetime.now(timezone.utc) - msg_date).days
                overdue.append({
                    "message": msg,
                    "days_waiting": days_waiting,
                    "headers": GmailClient.extract_headers(msg),
                })

        logger.info(f"Found {len(overdue)} overdue follow-up threads")
        return overdue

    def generate_followup_suggestions(self) -> list[dict]:
        """
        Find overdue threads and generate follow-up draft suggestions.

        Returns:
            List of dicts: {message, days_waiting, headers, draft_body}
        """
        overdue = self.find_overdue_threads()
        suggestions = []

        for item in overdue:
            draft_body = None
            if self.draft_generator:
                draft_body = self.draft_generator.generate_followup(
                    original_message=item["message"],
                    days_waiting=item["days_waiting"],
                    style_profile=self.style_profile,
                )

            suggestions.append({
                **item,
                "draft_body": draft_body,
            })

        return suggestions

    def create_followup_drafts(self) -> int:
        """
        Generate and save follow-up drafts for overdue threads.

        Returns:
            Number of drafts created
        """
        suggestions = self.generate_followup_suggestions()
        created = 0

        for item in suggestions:
            if not item.get("draft_body"):
                continue

            msg = item["message"]
            headers = item["headers"]
            subject = headers["subject"]
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            draft_id = self.gmail.create_draft(
                body=item["draft_body"],
                subject=subject,
                to=headers["from"],
                thread_id=msg.get("threadId"),
            )

            if draft_id:
                logger.info(
                    f"Follow-up draft created for '{headers['subject']}' "
                    f"({item['days_waiting']} days waiting)"
                )
                created += 1

        return created

    def print_followup_report(self):
        """Print a summary of overdue follow-ups to stdout."""
        overdue = self.find_overdue_threads()
        if not overdue:
            print("No overdue follow-ups found.")
            return

        print(f"\n{'=' * 60}")
        print(f"FOLLOW-UP NEEDED ({len(overdue)} threads)")
        print(f"{'=' * 60}")
        for item in overdue:
            h = item["headers"]
            print(
                f"  [{item['days_waiting']}d] {h['from'][:30]:<32} {h['subject'][:40]}"
            )
