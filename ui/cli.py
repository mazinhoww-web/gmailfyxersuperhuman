"""
Interactive CLI Module
Implements the interactive command loop with keyboard shortcuts.
"""

import sys
from datetime import datetime, timezone, timedelta
from typing import Optional
from gmail.client import GmailClient
from gmail.drafts import DraftManager
from features.batch_processor import BatchProcessor
from features.snooze import SnoozeManager
from features.undo_send import UndoSendBuffer
from ui.inbox_view import InboxView
from utils.logger import get_logger

logger = get_logger(__name__)

HELP_TEXT = """
COMMANDS:
  e          Process new unread emails (classify + generate drafts)
  l          List current inbox with categories
  r [id]     View draft for email [id]
  s [id]     Send draft for email [id] (with undo countdown)
  a [id]     Archive email [id] (mark as actioned)
  d [id]     Manually generate draft for email [id]
  ? [id]     Show thread summary for email [id]
  snooze [id] [hours]   Snooze email for N hours (default: 24)
  followup   Show overdue follow-up suggestions
  batch      Process full inbox in batch mode (inbox zero)
  dry        Toggle dry-run mode (current changes not applied to Gmail)
  h / help   Show this help
  q / quit   Exit
"""


class InteractiveCLI:
    """Interactive command-line interface for the email assistant."""

    def __init__(
        self,
        gmail_client: GmailClient,
        batch_processor: BatchProcessor,
        draft_manager: DraftManager,
        snooze_manager: SnoozeManager,
        undo_buffer: UndoSendBuffer,
        inbox_view: InboxView,
        label_map: dict,
    ):
        self.gmail = gmail_client
        self.processor = batch_processor
        self.drafts = draft_manager
        self.snooze = snooze_manager
        self.undo = undo_buffer
        self.view = inbox_view
        self.label_map = label_map

        # Local cache of current inbox emails for quick access by index
        self._inbox_cache: list[dict] = []
        self._draft_map: dict = {}  # index → draft_id

    def run(self):
        """Start the interactive command loop."""
        print("\nGmail AI Assistant — Fyxer + Superhuman")
        print("Type 'h' for help, 'q' to quit\n")

        while True:
            try:
                raw = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            if not raw:
                continue

            parts = raw.split()
            cmd = parts[0].lower()
            args = parts[1:]

            try:
                self._dispatch(cmd, args)
            except KeyboardInterrupt:
                print("\n(interrupted)")
            except Exception as e:
                logger.error(f"Command error: {e}")
                print(f"Error: {e}")

    def _dispatch(self, cmd: str, args: list[str]):
        if cmd in ("q", "quit", "exit"):
            print("Goodbye.")
            sys.exit(0)

        elif cmd in ("h", "help"):
            print(HELP_TEXT)

        elif cmd == "e":
            self._cmd_process_new()

        elif cmd == "l":
            self._cmd_list_inbox()

        elif cmd == "r":
            self._cmd_view_draft(args)

        elif cmd == "s":
            self._cmd_send_draft(args)

        elif cmd == "a":
            self._cmd_archive(args)

        elif cmd == "d":
            self._cmd_generate_draft(args)

        elif cmd == "?":
            self._cmd_thread_summary(args)

        elif cmd == "snooze":
            self._cmd_snooze(args)

        elif cmd == "followup":
            self._cmd_followup()

        elif cmd == "batch":
            self._cmd_batch()

        elif cmd == "dry":
            self.gmail.dry_run = not self.gmail.dry_run
            status = "ON" if self.gmail.dry_run else "OFF"
            print(f"Dry-run mode: {status}")

        else:
            print(f"Unknown command: '{cmd}'. Type 'h' for help.")

    # ─── COMMANDS ───────────────────────────────────────────────────────────

    def _cmd_process_new(self):
        print("Processing new emails...")
        result = self.processor.process_new_emails(max_emails=50, generate_drafts=True)
        total = result.get("total", 0)
        categories = result.get("categories", {})
        drafts = result.get("drafts_created", 0)
        errors = result.get("errors", 0)

        print(f"\nProcessed {total} emails:")
        for cat, count in sorted(categories.items()):
            print(f"  {cat}: {count}")
        if drafts:
            print(f"  Drafts generated: {drafts}")
        if errors:
            print(f"  Errors: {errors}")

    def _cmd_list_inbox(self):
        print("Loading inbox...")
        messages = self.gmail.get_inbox_emails(max_results=30)
        self._inbox_cache = messages

        if not messages:
            print("Inbox is empty.")
            return

        print(f"\n{'#':<4} {'FROM':<30} {'SUBJECT':<45} {'LABELS'}")
        print("-" * 90)
        for i, msg in enumerate(messages):
            headers = GmailClient.extract_headers(msg)
            labels = msg.get("labelIds", [])
            unread = "*" if "UNREAD" in labels else " "
            sender = self.view._short_sender(headers["from"])
            subject = headers["subject"][:44]
            label_str = self._format_labels(labels)
            print(f"{unread}{i:<3} {sender:<30} {subject:<45} {label_str}")

    def _cmd_view_draft(self, args: list[str]):
        idx = self._parse_index(args)
        if idx is None:
            return
        draft_id = self._draft_map.get(idx)
        if not draft_id:
            print(f"No draft found for email #{idx}. Use 'd {idx}' to generate one.")
            return
        body = self.drafts.view_draft(draft_id)
        if body:
            print(f"\n{'─' * 60}\n{body}\n{'─' * 60}")
        else:
            print("Could not load draft.")

    def _cmd_send_draft(self, args: list[str]):
        idx = self._parse_index(args)
        if idx is None:
            return
        draft_id = self._draft_map.get(idx)
        if not draft_id:
            print(f"No draft for email #{idx}.")
            return
        self.undo.send_with_undo(draft_id)

    def _cmd_archive(self, args: list[str]):
        idx = self._parse_index(args)
        if idx is None:
            return
        msg = self._get_cached_msg(idx)
        if not msg:
            return
        msg_id = msg["id"]
        actioned_label = self.label_map.get("actioned")
        if actioned_label:
            self.gmail.apply_labels_and_archive(msg_id, actioned_label, archive=True)
        else:
            self.gmail.remove_from_inbox(msg_id)
        print(f"Email #{idx} archived.")

    def _cmd_generate_draft(self, args: list[str]):
        idx = self._parse_index(args)
        if idx is None:
            return
        msg = self._get_cached_msg(idx)
        if not msg:
            return

        print(f"Generating draft for email #{idx}...")
        self.processor._generate_draft_for_message(msg)
        print("Draft created and saved to Gmail Drafts.")

    def _cmd_thread_summary(self, args: list[str]):
        idx = self._parse_index(args)
        if idx is None:
            return
        msg = self._get_cached_msg(idx)
        if not msg:
            return

        thread_id = msg.get("threadId")
        if not thread_id:
            print("No thread ID found.")
            return

        thread = self.gmail.get_email_thread(thread_id)
        if not thread:
            print("Could not load thread.")
            return

        messages = thread.get("messages", [])
        print(f"\nThread: {len(messages)} messages")

        if self.processor.summarizer and len(messages) >= 3:
            summary = self.processor.summarizer.summarize_thread(thread)
            if summary:
                print(f"Summary: {summary}")
                return

        # Show last few messages
        for i, m in enumerate(messages[-3:], 1):
            h = GmailClient.extract_headers(m)
            print(f"  [{i}] {h['from'][:30]}: {h['subject'][:50]}")

    def _cmd_snooze(self, args: list[str]):
        if not args:
            print("Usage: snooze <email_index> [hours]")
            return
        idx = self._parse_index([args[0]])
        hours = int(args[1]) if len(args) > 1 else 24

        msg = self._get_cached_msg(idx)
        if not msg:
            return

        remind_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        success = self.snooze.snooze_email(msg["id"], remind_at)
        if success:
            print(f"Email #{idx} snoozed for {hours}h (returns at {remind_at.strftime('%H:%M')})")

    def _cmd_followup(self):
        from features.follow_up import FollowUpTracker
        tracker = FollowUpTracker(
            gmail_client=self.gmail,
            label_map=self.label_map,
            draft_generator=self.processor.draft_generator,
            style_profile=self.processor.style_profile,
        )
        tracker.print_followup_report()

    def _cmd_batch(self):
        confirm = input(
            "Process entire inbox in batch mode? This may take several minutes. [y/N] "
        ).strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return
        print("Starting batch processing...")
        result = self.processor.batch_categorize_inbox(
            batch_size=100,
            generate_drafts=False,
        )
        print(f"\nBatch complete: {result.get('total', 0)} emails processed")
        for cat, count in sorted(result.get("categories", {}).items()):
            print(f"  {cat}: {count}")

    # ─── HELPERS ────────────────────────────────────────────────────────────

    def _parse_index(self, args: list[str]) -> Optional[int]:
        if not args:
            print("Please provide an email index number.")
            return None
        try:
            return int(args[0])
        except ValueError:
            print(f"Invalid index: {args[0]}")
            return None

    def _get_cached_msg(self, idx: int) -> Optional[dict]:
        if not self._inbox_cache:
            print("No emails loaded. Run 'l' first to list inbox.")
            return None
        if idx < 0 or idx >= len(self._inbox_cache):
            print(f"Index {idx} out of range (0–{len(self._inbox_cache) - 1})")
            return None
        return self._inbox_cache[idx]

    def _format_labels(self, label_ids: list[str]) -> str:
        """Format label IDs as a short string for display."""
        system_labels = {"INBOX", "UNREAD", "SENT", "DRAFT", "IMPORTANT", "STARRED"}
        custom = [l for l in label_ids if l not in system_labels]
        if custom:
            return ",".join(custom[:2])
        flags = []
        if "UNREAD" in label_ids:
            flags.append("unread")
        if "STARRED" in label_ids:
            flags.append("★")
        return " ".join(flags)
