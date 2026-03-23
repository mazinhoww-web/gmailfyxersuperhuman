#!/usr/bin/env python3
"""
Gmail AI Assistant — Entry Point
Combines Fyxer.ai + Superhuman features:
  - Smart email categorization (8 categories)
  - Auto-generated reply drafts
  - Interactive CLI with keyboard shortcuts
  - Batch inbox processing (inbox zero)
  - Follow-up tracking, snooze, undo send

Usage:
  python main.py                    # Start interactive CLI
  python main.py --setup-labels     # Fetch and save real label IDs
  python main.py --process          # Process new emails once (non-interactive)
  python main.py --batch            # Batch-process full inbox
  python main.py --list             # List 10 most recent inbox emails
  python main.py --dry-run          # Preview changes without applying them
"""

import os
import sys
import argparse
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Load .env for API keys
load_dotenv()

from utils.logger import configure_logging, get_logger
from auth.gmail_auth import get_gmail_service, get_authenticated_user
from gmail.client import GmailClient
from gmail.labels import update_config_with_label_ids, print_all_labels
from gmail.drafts import DraftManager
from ai.classifier import EmailClassifier
from ai.style_learner import StyleLearner
from ai.draft_generator import DraftGenerator
from ai.summarizer import ThreadSummarizer
from features.batch_processor import BatchProcessor
from features.snooze import SnoozeManager
from features.follow_up import FollowUpTracker
from features.undo_send import UndoSendBuffer
from ui.cli import InteractiveCLI
from ui.inbox_view import InboxView

CONFIG_PATH = Path(__file__).parent / "config.yaml"

logger = get_logger(__name__)


def load_config() -> dict:
    """Load configuration from config.yaml."""
    if not CONFIG_PATH.exists():
        logger.warning("config.yaml not found, using defaults")
        return {}
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def build_app(config: dict, dry_run: bool = False):
    """
    Initialize all components and wire them together.

    Returns:
        Tuple of (gmail_client, batch_processor, draft_manager, snooze_manager,
                  undo_buffer, inbox_view, label_map)
    """
    log_cfg = config.get("logging", {})
    configure_logging(
        level=log_cfg.get("level", "INFO"),
        log_to_file=log_cfg.get("log_to_file", True),
    )

    # Authenticate
    logger.info("Authenticating with Gmail...")
    service = get_gmail_service()
    profile = get_authenticated_user(service)
    logger.info(f"Authenticated as: {profile.get('emailAddress')}")

    # Core client
    gmail = GmailClient(service, dry_run=dry_run)

    # Label map
    label_map = config.get("labels", {})
    if not any(label_map.values()):
        logger.warning(
            "Label IDs not configured. Run: python main.py --setup-labels"
        )

    # AI components
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set. Classification and draft generation will fail. "
            "Set it in .env or as an environment variable."
        )

    classifier = EmailClassifier(api_key=anthropic_key)
    draft_gen = DraftGenerator(api_key=anthropic_key)
    summarizer = ThreadSummarizer(api_key=anthropic_key)
    style_learner = StyleLearner(gmail)

    # Build style profile (cached after first build)
    style_profile = None
    draft_cfg = config.get("drafts", {})
    if draft_cfg.get("auto_generate_for_to_respond", True):
        logger.info("Building style profile from sent emails...")
        try:
            style_profile = style_learner.build_style_profile(
                max_emails=draft_cfg.get("style_sample_size", 300)
            )
        except Exception as e:
            logger.warning(f"Could not build style profile: {e}")

    # Feature components
    batch_processor = BatchProcessor(
        gmail_client=gmail,
        classifier=classifier,
        label_map=label_map,
        draft_generator=draft_gen,
        summarizer=summarizer,
        style_profile=style_profile,
    )

    draft_manager = DraftManager(gmail)
    snooze_cfg = config.get("snooze", {})
    snooze_manager = SnoozeManager(gmail, label_map=label_map)
    snooze_manager.start_background_watcher(
        check_interval=snooze_cfg.get("check_interval_seconds", 60)
    )

    undo_cfg = config.get("undo_send", {})
    undo_buffer = UndoSendBuffer(gmail, undo_window=undo_cfg.get("window_seconds", 10))

    inbox_view = InboxView()

    return (
        gmail, batch_processor, draft_manager,
        snooze_manager, undo_buffer, inbox_view, label_map
    )


def cmd_setup_labels(service):
    """Fetch real label IDs and write to config.yaml."""
    print("\nFetching labels from Gmail...")
    print_all_labels(service)
    print("\nSaving canonical label IDs to config.yaml...")
    ids = update_config_with_label_ids(service)
    print("\nLabel IDs saved:")
    for key, label_id in ids.items():
        print(f"  {key:<20} → {label_id}")
    print("\nconfig.yaml updated. You can now run the assistant.")


def cmd_list_emails(gmail: GmailClient, max_results: int = 10):
    """List the N most recent inbox emails."""
    print(f"\nFetching {max_results} most recent inbox emails...\n")
    messages = gmail.get_inbox_emails(max_results=max_results)

    if not messages:
        print("No emails found.")
        return

    print(f"{'#':<4} {'FROM':<35} {'SUBJECT':<45} SNIPPET")
    print("─" * 110)
    for i, msg in enumerate(messages):
        headers = GmailClient.extract_headers(msg)
        snippet = msg.get("snippet", "")[:50]
        labels = msg.get("labelIds", [])
        unread = "*" if "UNREAD" in labels else " "
        sender = InboxView._short_sender(headers["from"])[:33]
        subject = headers["subject"][:44]
        print(f"{unread}{i:<3} {sender:<35} {subject:<45} {snippet}")

    print(f"\nTotal: {len(messages)} emails")


def cmd_process_once(batch_processor: BatchProcessor, config: dict):
    """Process new emails once (non-interactive)."""
    proc_cfg = config.get("processing", {})
    max_emails = proc_cfg.get("max_unread_per_run", 50)
    draft_cfg = config.get("drafts", {})
    generate_drafts = draft_cfg.get("auto_generate_for_to_respond", True)

    print(f"Processing up to {max_emails} unread emails...")
    result = batch_processor.process_new_emails(
        max_emails=max_emails,
        generate_drafts=generate_drafts,
    )

    print(f"\nProcessing complete:")
    print(f"  Total processed: {result.get('total', 0)}")
    for cat, count in sorted(result.get("categories", {}).items()):
        print(f"  {cat}: {count}")
    if result.get("drafts_created"):
        print(f"  Drafts created: {result['drafts_created']}")
    if result.get("errors"):
        print(f"  Errors: {result['errors']}")


def main():
    parser = argparse.ArgumentParser(
        description="Gmail AI Assistant — Fyxer + Superhuman Clone"
    )
    parser.add_argument(
        "--setup-labels",
        action="store_true",
        help="Fetch Gmail label IDs and save to config.yaml",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Process new unread emails once (non-interactive)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch-process the full inbox (inbox zero mode)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List 10 most recent inbox emails and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all operations without actually modifying Gmail",
    )
    parser.add_argument(
        "--followup",
        action="store_true",
        help="Show overdue follow-up report",
    )
    args = parser.parse_args()

    config = load_config()

    # --setup-labels: special mode — only needs Gmail service
    if args.setup_labels:
        service = get_gmail_service()
        cmd_setup_labels(service)
        return

    # Build all components
    (
        gmail, batch_processor, draft_manager,
        snooze_manager, undo_buffer, inbox_view, label_map
    ) = build_app(config, dry_run=args.dry_run)

    if args.dry_run:
        print("DRY-RUN MODE: No changes will be made to Gmail.\n")

    if args.list:
        cmd_list_emails(gmail, max_results=10)
        return

    if args.process:
        cmd_process_once(batch_processor, config)
        return

    if args.batch:
        confirm = input(
            "Process ENTIRE inbox in batch mode? This may take several minutes. [y/N] "
        ).strip().lower()
        if confirm == "y":
            result = batch_processor.batch_categorize_inbox(
                batch_size=config.get("processing", {}).get("batch_size", 100),
                generate_drafts=False,
                dry_run=args.dry_run,
            )
            print(f"\nBatch complete: {result.get('total', 0)} emails processed")
            for cat, count in sorted(result.get("categories", {}).items()):
                print(f"  {cat}: {count}")
        else:
            print("Cancelled.")
        return

    if args.followup:
        follow_up_tracker = FollowUpTracker(
            gmail_client=gmail,
            label_map=label_map,
            draft_generator=batch_processor.draft_generator,
            style_profile=batch_processor.style_profile,
        )
        follow_up_tracker.print_followup_report()
        return

    # Default: start interactive CLI
    cli = InteractiveCLI(
        gmail_client=gmail,
        batch_processor=batch_processor,
        draft_manager=draft_manager,
        snooze_manager=snooze_manager,
        undo_buffer=undo_buffer,
        inbox_view=inbox_view,
        label_map=label_map,
    )
    cli.run()


if __name__ == "__main__":
    main()
