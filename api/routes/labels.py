"""
Label management endpoints.
"""

from fastapi import APIRouter
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.routes.auth import get_credentials_for_session
from gmail.client import GmailClient
from gmail.labels import list_all_labels, build_label_map, get_canonical_label_ids

router = APIRouter()

CATEGORY_COLORS = {
    "to_respond": "#FF4D4F",
    "fyi": "#FF7A45",
    "comment": "#FFCC00",
    "notification": "#2ECC71",
    "meeting_update": "#3B82F6",
    "awaiting_reply": "#A78BFA",
    "actioned": "#6F7276",
    "marketing": "#E01B6D",
}

CATEGORY_NAMES_PT = {
    "to_respond": "Responder",
    "fyi": "FYI",
    "comment": "Comentário",
    "notification": "Notificação",
    "meeting_update": "Reunião",
    "awaiting_reply": "Aguardando",
    "actioned": "Acionado",
    "marketing": "Marketing",
}


@router.get("")
async def list_labels(session: str):
    """List all Gmail labels."""
    creds = get_credentials_for_session(session)
    client = GmailClient(credentials=creds)
    labels = list_all_labels(client.service)
    return {"labels": labels}


@router.get("/categories")
async def get_categories(session: str):
    """Get ARIA category labels with IDs, colors and counts."""
    creds = get_credentials_for_session(session)
    client = GmailClient(credentials=creds)

    label_map = build_label_map(client.service)

    categories = []
    for key, color in CATEGORY_COLORS.items():
        label_name_candidates = [
            key.replace("_", " "),
            key.replace("_", "-"),
            key,
        ]
        label_id = None
        for name in label_name_candidates:
            label_id = label_map.get(name) or label_map.get(name.title())
            if label_id:
                break

        categories.append(
            {
                "key": key,
                "name": CATEGORY_NAMES_PT.get(key, key),
                "label_id": label_id,
                "color": color,
                "count": 0,  # TODO: fetch count per label
            }
        )

    return {"categories": categories}


@router.post("/setup")
async def setup_labels(session: str):
    """Create the 8 ARIA category labels in Gmail if they don't exist."""
    from gmail.labels import update_config_with_label_ids

    creds = get_credentials_for_session(session)
    client = GmailClient(credentials=creds)

    canonical_names = [
        "to respond",
        "FYI",
        "comment",
        "notification",
        "meeting update",
        "awaiting reply",
        "actioned",
        "marketing",
    ]

    label_map = build_label_map(client.service)
    created = []
    existing = []

    for name in canonical_names:
        if name.lower() in {k.lower() for k in label_map.keys()}:
            existing.append(name)
        else:
            try:
                client.service.users().labels().create(
                    userId="me",
                    body={"name": name},
                ).execute()
                created.append(name)
            except Exception as e:
                pass

    return {
        "created": created,
        "existing": existing,
        "total": len(canonical_names),
    }
