"""
Email operations endpoints.
"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.routes.auth import get_credentials_for_session
from gmail.client import GmailClient
from ai.classifier import EmailClassifier
from ai.summarizer import ThreadSummarizer
from features.batch_processor import BatchProcessor

router = APIRouter()


class ProcessResult(BaseModel):
    processed: int
    categories: dict
    drafts_created: int
    errors: int


def _make_gmail_client(session: str, dry_run: bool = False) -> GmailClient:
    creds = get_credentials_for_session(session)
    return GmailClient(credentials=creds, dry_run=dry_run)


@router.get("")
async def list_emails(
    session: str,
    folder: str = "inbox",
    max_results: int = Query(default=50, le=200),
):
    """List emails from inbox or a folder."""
    client = _make_gmail_client(session)

    if folder == "inbox":
        messages = client.get_inbox_emails(max_results=max_results)
    elif folder == "unread":
        messages = client.get_unread_emails(max_results=max_results)
    elif folder == "sent":
        messages = client.get_sent_emails(max_results=max_results)
    else:
        messages = client.list_messages(query=f"in:{folder}", max_results=max_results)

    emails = []
    for msg in messages:
        headers = client.extract_headers(msg)
        snippet = msg.get("snippet", "")
        label_ids = msg.get("labelIds", [])

        emails.append(
            {
                "id": msg["id"],
                "thread_id": msg.get("threadId"),
                "subject": headers.get("subject", "(sem assunto)"),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "date": headers.get("date", ""),
                "snippet": snippet[:200],
                "is_unread": "UNREAD" in label_ids,
                "label_ids": label_ids,
                "category": _extract_category_label(label_ids),
            }
        )

    return {"emails": emails, "total": len(emails)}


@router.get("/{message_id}")
async def get_email(message_id: str, session: str):
    """Get a single email with full body."""
    client = _make_gmail_client(session)
    msg = client.get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Email not found")

    headers = client.extract_headers(msg)
    body = client.extract_body(msg)

    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "subject": headers.get("subject", "(sem assunto)"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "body": body,
        "label_ids": msg.get("labelIds", []),
        "category": _extract_category_label(msg.get("labelIds", [])),
    }


@router.get("/{message_id}/thread")
async def get_thread(message_id: str, session: str):
    """Get full email thread with summary."""
    client = _make_gmail_client(session)
    msg = client.get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Email not found")

    thread_id = msg.get("threadId", message_id)
    thread = client.get_email_thread(thread_id)

    summarizer = ThreadSummarizer()
    summary = summarizer.summarize_thread(thread)

    return {
        "thread_id": thread_id,
        "summary": summary,
        "messages": [
            {
                "id": m["id"],
                "from": client.extract_headers(m).get("from", ""),
                "date": client.extract_headers(m).get("date", ""),
                "body": client.extract_body(m)[:1000],
            }
            for m in thread.get("messages", [])
        ],
    }


@router.post("/{message_id}/classify")
async def classify_email(message_id: str, session: str):
    """Classify a single email with AI."""
    client = _make_gmail_client(session)
    msg = client.get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Email not found")

    classifier = EmailClassifier()
    category = classifier.classify_email(msg)

    return {"message_id": message_id, "category": category}


@router.post("/{message_id}/archive")
async def archive_email(message_id: str, session: str):
    """Archive an email (remove from inbox)."""
    client = _make_gmail_client(session)
    client.remove_from_inbox(message_id)
    client.mark_as_read(message_id)
    return {"success": True, "message_id": message_id}


@router.post("/{message_id}/label")
async def apply_label(message_id: str, session: str, label_id: str):
    """Apply a label to an email."""
    client = _make_gmail_client(session)
    client.apply_label(message_id, label_id)
    return {"success": True, "message_id": message_id, "label_id": label_id}


@router.post("/process")
async def process_emails(
    session: str,
    max_emails: int = Query(default=50, le=200),
    dry_run: bool = False,
):
    """Process unread emails: classify, label, archive, generate drafts."""
    from config import load_config
    config = load_config()

    client = _make_gmail_client(session, dry_run=dry_run)
    classifier = EmailClassifier()

    processed = 0
    categories: dict = {}
    drafts_created = 0
    errors = 0

    def progress_callback(msg: str, category: str, email_id: str):
        nonlocal processed, drafts_created
        processed += 1
        categories[category] = categories.get(category, 0) + 1

    processor = BatchProcessor(
        gmail_client=client,
        classifier=classifier,
        config=config,
        progress_callback=progress_callback,
    )

    result = processor.process_new_emails(max_emails=max_emails)
    return {
        "processed": result.get("processed", 0),
        "categories": result.get("categories", {}),
        "drafts_created": result.get("drafts_created", 0),
        "errors": result.get("errors", 0),
        "dry_run": dry_run,
    }


def _extract_category_label(label_ids: list[str]) -> Optional[str]:
    """Try to detect category from label IDs (best-effort, label IDs are dynamic)."""
    # These are the canonical category names we look for
    # In practice the frontend should call /labels to map IDs to names
    return None
