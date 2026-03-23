"""
Batch Processor Module
Processes inbox in batches: classify emails and optionally generate drafts.
Supports dry-run mode. Never deletes — only moves/labels.
"""

import time
from typing import Optional, Callable
from gmail.client import GmailClient
from ai.classifier import EmailClassifier
from ai.draft_generator import DraftGenerator
from ai.style_learner import StyleProfile
from ai.summarizer import ThreadSummarizer
from utils.logger import get_logger

logger = get_logger(__name__)

# Categories that get archived (removed from inbox)
MOVE_OUT_CATEGORIES = {
    "comment",
    "notification",
    "meeting_update",
    "awaiting_reply",
    "actioned",
    "marketing",
}

# Categories that stay in inbox
KEEP_IN_INBOX_CATEGORIES = {
    "to_respond",
    "fyi",
}


def chunks(lst: list, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i: i + n]


class BatchProcessor:
    """
    Processes emails in batches: classify → label → archive → generate drafts.
    """

    def __init__(
        self,
        gmail_client: GmailClient,
        classifier: EmailClassifier,
        label_map: dict,
        draft_generator: Optional[DraftGenerator] = None,
        summarizer: Optional[ThreadSummarizer] = None,
        style_profile: Optional[StyleProfile] = None,
    ):
        """
        Args:
            gmail_client: Authenticated GmailClient
            classifier: EmailClassifier instance
            label_map: {"to_respond": "Label_123", ...}
            draft_generator: Optional DraftGenerator for auto-drafts
            summarizer: Optional ThreadSummarizer
            style_profile: User's style profile for drafts
        """
        self.gmail = gmail_client
        self.classifier = classifier
        self.label_map = label_map
        self.draft_generator = draft_generator
        self.summarizer = summarizer
        self.style_profile = style_profile

    def process_new_emails(
        self,
        max_emails: int = 50,
        generate_drafts: bool = True,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Process new unread emails: classify, label, archive, and optionally draft.

        Args:
            max_emails: Max emails to process in this run
            generate_drafts: Whether to generate reply drafts for to_respond
            progress_callback: Optional function(processed, total, email_info) for UI updates

        Returns:
            dict with counts per category and any errors
        """
        logger.info(f"Fetching up to {max_emails} unread emails...")
        messages = self.gmail.get_unread_emails(max_results=max_emails)

        if not messages:
            logger.info("No unread emails found.")
            return {"total": 0}

        return self._process_messages(
            messages=messages,
            generate_drafts=generate_drafts,
            progress_callback=progress_callback,
        )

    def batch_categorize_inbox(
        self,
        batch_size: int = 100,
        generate_drafts: bool = False,
        dry_run: Optional[bool] = None,
    ) -> dict:
        """
        Process the full inbox in batches. For inbox zero / historical processing.

        Args:
            batch_size: Emails per batch
            generate_drafts: Whether to generate drafts for to_respond emails
            dry_run: Override client's dry_run setting for this operation

        Returns:
            Aggregated results dict
        """
        original_dry_run = self.gmail.dry_run
        if dry_run is not None:
            self.gmail.dry_run = dry_run

        try:
            logger.info("Fetching all inbox emails (this may take a moment)...")
            messages = self.gmail.get_inbox_emails(max_results=5000)
            total = len(messages)
            logger.info(f"Found {total} inbox emails to process")

            aggregated: dict = {"total": total, "categories": {}, "errors": 0, "drafts_created": 0}

            for batch_num, batch in enumerate(chunks(messages, batch_size), 1):
                logger.info(f"Processing batch {batch_num} ({len(batch)} emails)...")
                result = self._process_messages(batch, generate_drafts=generate_drafts)

                for cat, count in result.get("categories", {}).items():
                    aggregated["categories"][cat] = aggregated["categories"].get(cat, 0) + count
                aggregated["errors"] += result.get("errors", 0)
                aggregated["drafts_created"] += result.get("drafts_created", 0)

                time.sleep(1)  # Rate limiting between batches

            logger.info(
                f"Batch processing complete: {total} emails processed. "
                f"Categories: {aggregated['categories']}"
            )
            return aggregated

        finally:
            self.gmail.dry_run = original_dry_run

    def _process_messages(
        self,
        messages: list[dict],
        generate_drafts: bool = True,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """Core processing loop for a list of messages."""
        result: dict = {"total": len(messages), "categories": {}, "errors": 0, "drafts_created": 0}

        for i, msg in enumerate(messages):
            msg_id = msg.get("id", "?")
            try:
                # Classify
                category = self.classifier.classify_with_body(msg)
                label_id = self.label_map.get(category)

                if not label_id:
                    logger.warning(f"No label ID for category '{category}', skipping {msg_id}")
                    continue

                # Archive if needed
                should_archive = category in MOVE_OUT_CATEGORIES
                self.gmail.apply_labels_and_archive(msg_id, label_id, archive=should_archive)

                # Mark as read for archived categories
                if should_archive:
                    self.gmail.mark_as_read(msg_id)

                # Generate draft for to_respond
                if category == "to_respond" and generate_drafts and self.draft_generator:
                    self._generate_draft_for_message(msg)
                    result["drafts_created"] += 1

                result["categories"][category] = result["categories"].get(category, 0) + 1

                if progress_callback:
                    progress_callback(i + 1, len(messages), {
                        "id": msg_id,
                        "category": category,
                        "archived": should_archive,
                    })

            except Exception as e:
                logger.error(f"Error processing message {msg_id}: {e}")
                result["errors"] += 1

        return result

    def _generate_draft_for_message(self, message: dict):
        """Generate and save a reply draft for a to_respond email."""
        thread_id = message.get("threadId")
        thread_context = None

        if thread_id and self.summarizer:
            thread = self.gmail.get_email_thread(thread_id)
            if thread and len(thread.get("messages", [])) >= 3:
                thread_context = self.summarizer.get_thread_context(thread)

        draft_body = self.draft_generator.generate_reply(
            message=message,
            style_profile=self.style_profile,
            thread_context=thread_context,
        )

        if draft_body:
            headers = GmailClient.extract_headers(message)
            subject = headers["subject"]
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            self.gmail.create_draft(
                body=draft_body,
                subject=subject,
                to=headers["from"],
                thread_id=thread_id,
            )
            logger.info(f"Draft created for thread {thread_id}")
