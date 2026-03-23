"""
Split Inbox View
Renders a formatted split inbox showing categorized emails.
Uses the `rich` library for terminal formatting.
"""

from typing import Optional
from gmail.client import GmailClient
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

CATEGORY_COLORS = {
    "to_respond": "bold red",
    "fyi": "orange3",
    "comment": "yellow",
    "notification": "green",
    "meeting_update": "cyan",
    "awaiting_reply": "blue",
    "actioned": "purple",
    "marketing": "pink1",
}

CATEGORY_LABELS = {
    "to_respond": "TO RESPOND",
    "fyi": "FYI",
    "comment": "COMMENT",
    "notification": "NOTIFICATION",
    "meeting_update": "MEETING UPDATE",
    "awaiting_reply": "AWAITING REPLY",
    "actioned": "ACTIONED",
    "marketing": "MARKETING",
}


class InboxView:
    """Renders the split inbox using rich or plain text."""

    def __init__(self):
        self.console = Console() if HAS_RICH else None

    def render_split_inbox(
        self,
        categorized_emails: dict,
        draft_thread_ids: Optional[set] = None,
    ):
        """
        Render the split inbox view.

        Args:
            categorized_emails: {"to_respond": [msg, ...], "fyi": [msg, ...], ...}
            draft_thread_ids: Set of thread IDs that have pending drafts
        """
        draft_ids = draft_thread_ids or set()

        if HAS_RICH:
            self._render_rich(categorized_emails, draft_ids)
        else:
            self._render_plain(categorized_emails, draft_ids)

    def _render_rich(self, categorized: dict, draft_ids: set):
        """Rich-formatted split inbox."""
        console = self.console

        console.print()
        console.print(Panel.fit("[bold cyan]INBOX[/bold cyan]", border_style="cyan"))

        # INBOX SECTION: to_respond + fyi
        inbox_cats = ["to_respond", "fyi"]
        for cat in inbox_cats:
            emails = categorized.get(cat, [])
            if not emails:
                continue

            color = CATEGORY_COLORS.get(cat, "white")
            label = CATEGORY_LABELS.get(cat, cat.upper())

            table = Table(
                title=f"[{color}]{label}[/{color}] ({len(emails)})",
                box=box.SIMPLE,
                show_header=False,
                padding=(0, 1),
            )
            table.add_column("from", style="bold", max_width=30)
            table.add_column("subject", max_width=45)
            table.add_column("note", style="dim", max_width=15)

            for msg in emails:
                headers = GmailClient.extract_headers(msg)
                thread_id = msg.get("threadId", "")
                draft_note = "[green]Draft pronto ✓[/green]" if thread_id in draft_ids else ""
                sender = self._short_sender(headers["from"])
                table.add_row(sender, headers["subject"][:45], draft_note)

            console.print(table)

        # ARCHIVED TODAY SECTION
        archived_cats = ["comment", "notification", "meeting_update", "awaiting_reply", "actioned", "marketing"]
        archived_counts = {
            cat: len(categorized.get(cat, []))
            for cat in archived_cats
            if categorized.get(cat)
        }

        if archived_counts:
            console.print()
            console.print("[dim]ARCHIVED THIS RUN[/dim]")
            for cat, count in archived_counts.items():
                color = CATEGORY_COLORS.get(cat, "white")
                label = CATEGORY_LABELS.get(cat, cat.upper())
                console.print(f"  [{color}]{label}[/{color}]: {count}")

        console.print()

    def _render_plain(self, categorized: dict, draft_ids: set):
        """Plain text fallback (no rich library)."""
        print("\n" + "=" * 60)
        print("INBOX")
        print("=" * 60)

        for cat in ["to_respond", "fyi"]:
            emails = categorized.get(cat, [])
            if not emails:
                continue
            label = CATEGORY_LABELS.get(cat, cat.upper())
            print(f"\n[{label}] ({len(emails)} emails)")
            for msg in emails:
                headers = GmailClient.extract_headers(msg)
                thread_id = msg.get("threadId", "")
                draft_mark = " [Draft ✓]" if thread_id in draft_ids else ""
                sender = self._short_sender(headers["from"])
                print(f"  {sender:<30} {headers['subject'][:45]}{draft_mark}")

        archived_cats = ["notification", "marketing", "actioned", "meeting_update", "awaiting_reply", "comment"]
        archived_any = any(categorized.get(c) for c in archived_cats)
        if archived_any:
            print("\nARCHIVED THIS RUN:")
            for cat in archived_cats:
                count = len(categorized.get(cat, []))
                if count:
                    label = CATEGORY_LABELS.get(cat, cat.upper())
                    print(f"  {label}: {count}")

        print()

    @staticmethod
    def _short_sender(from_header: str) -> str:
        """Extract display name from 'Name <email>' format."""
        if "<" in from_header:
            return from_header.split("<")[0].strip().strip('"')[:28]
        return from_header[:28]
