"""
Follow-up tracking endpoints.
"""

from fastapi import APIRouter
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.routes.auth import get_credentials_for_session
from gmail.client import GmailClient
from features.follow_up import FollowUpTracker

router = APIRouter()


def _make_tracker(session: str) -> FollowUpTracker:
    from ai.draft_generator import DraftGenerator
    from ai.style_learner import StyleLearner

    creds = get_credentials_for_session(session)
    client = GmailClient(credentials=creds)
    style_learner = StyleLearner(client)
    style_profile = style_learner.build_profile()
    generator = DraftGenerator(style_profile=style_profile)
    return FollowUpTracker(gmail_client=client, draft_generator=generator)


@router.get("")
async def get_followups(session: str, days: int = 3):
    """Get overdue follow-up threads."""
    tracker = _make_tracker(session)
    overdue = tracker.find_overdue_threads(days_threshold=days)
    return {"followups": overdue, "total": len(overdue)}


@router.post("/drafts")
async def create_followup_drafts(session: str, days: int = 3):
    """Create follow-up draft suggestions for overdue threads."""
    tracker = _make_tracker(session)
    created = tracker.create_followup_drafts(days_threshold=days)
    return {"created": created}
