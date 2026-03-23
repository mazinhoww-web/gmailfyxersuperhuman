"""
Snooze endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.routes.auth import get_credentials_for_session
from gmail.client import GmailClient
from features.snooze import SnoozeManager

router = APIRouter()


class SnoozeRequest(BaseModel):
    message_id: str
    snooze_until: datetime  # ISO datetime


def _make_snooze_manager(session: str) -> SnoozeManager:
    creds = get_credentials_for_session(session)
    client = GmailClient(credentials=creds)
    return SnoozeManager(client)


@router.get("")
async def list_snoozed(session: str):
    """List all snoozed emails."""
    manager = _make_snooze_manager(session)
    snoozed = manager.list_snoozed()
    return {"snoozed": snoozed}


@router.post("")
async def snooze_email(body: SnoozeRequest, session: str):
    """Snooze an email until a specific datetime."""
    manager = _make_snooze_manager(session)
    manager.snooze_email(body.message_id, snooze_until=body.snooze_until)
    return {"success": True, "message_id": body.message_id, "snooze_until": body.snooze_until}


@router.delete("/{message_id}")
async def cancel_snooze(message_id: str, session: str):
    """Cancel a snooze and restore email to inbox."""
    manager = _make_snooze_manager(session)
    manager.cancel_snooze(message_id)
    return {"success": True, "message_id": message_id}


@router.post("/restore")
async def restore_due(session: str):
    """Restore all emails whose snooze time has passed."""
    manager = _make_snooze_manager(session)
    restored = manager.restore_due_emails()
    return {"restored": restored}
