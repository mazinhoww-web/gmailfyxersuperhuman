"""
Draft management endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.routes.auth import get_credentials_for_session
from gmail.client import GmailClient
from gmail.drafts import DraftManager
from ai.draft_generator import DraftGenerator
from ai.style_learner import StyleLearner

router = APIRouter()


class SendDraftRequest(BaseModel):
    draft_id: str


class GenerateDraftRequest(BaseModel):
    message_id: str
    thread_id: str | None = None


def _make_client(session: str) -> GmailClient:
    creds = get_credentials_for_session(session)
    return GmailClient(credentials=creds)


@router.get("")
async def list_drafts(session: str):
    """List all drafts."""
    client = _make_client(session)
    manager = DraftManager(client)
    drafts = manager.list_all_drafts()
    return {"drafts": drafts}


@router.get("/{draft_id}")
async def get_draft(draft_id: str, session: str):
    """Get a draft by ID."""
    client = _make_client(session)
    manager = DraftManager(client)
    content = manager.view_draft(draft_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"draft_id": draft_id, "content": content}


@router.post("/generate")
async def generate_draft(body: GenerateDraftRequest, session: str):
    """Generate an AI draft for an email."""
    client = _make_client(session)
    msg = client.get_message(body.message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Email not found")

    # Learn user style from sent emails
    style_learner = StyleLearner(client)
    style_profile = style_learner.build_profile()

    # Generate draft
    generator = DraftGenerator(style_profile=style_profile)
    draft_text = generator.generate_reply(msg, client)
    if not draft_text:
        raise HTTPException(status_code=500, detail="Failed to generate draft")

    # Save as Gmail draft
    manager = DraftManager(client)
    thread_id = body.thread_id or msg.get("threadId")
    draft_id = manager.create_reply_draft(body.message_id, draft_text, thread_id=thread_id)

    return {
        "draft_id": draft_id,
        "content": draft_text,
        "message_id": body.message_id,
    }


@router.post("/{draft_id}/send")
async def send_draft(draft_id: str, session: str):
    """Send a draft."""
    client = _make_client(session)
    manager = DraftManager(client)
    result = manager.send_draft_confirmed(draft_id)
    return {"success": result, "draft_id": draft_id}


@router.delete("/{draft_id}")
async def delete_draft(draft_id: str, session: str):
    """Delete a draft."""
    client = _make_client(session)
    manager = DraftManager(client)
    manager.discard_draft(draft_id)
    return {"success": True, "draft_id": draft_id}
