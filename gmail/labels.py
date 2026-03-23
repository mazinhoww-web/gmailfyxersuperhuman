"""
Gmail Labels Module
Lists, maps, and manages Gmail labels.
Fetches real label IDs from the API and persists them to config.yaml.
"""

import yaml
from pathlib import Path
from typing import Dict, Optional

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

# The 8 canonical label names used by this system
CANONICAL_LABELS = {
    "to respond",
    "FYI",
    "comment",
    "notification",
    "meeting update",
    "awaiting reply",
    "actioned",
    "marketing",
}

# Internal key → display name mapping
LABEL_KEY_MAP = {
    "to_respond": "to respond",
    "fyi": "FYI",
    "comment": "comment",
    "notification": "notification",
    "meeting_update": "meeting update",
    "awaiting_reply": "awaiting reply",
    "actioned": "actioned",
    "marketing": "marketing",
}


def list_all_labels(service) -> list[dict]:
    """
    Fetch all labels from Gmail account.

    Returns:
        List of label dicts: [{"id": "...", "name": "...", "type": "..."}, ...]
    """
    result = service.users().labels().list(userId="me").execute()
    return result.get("labels", [])


def build_label_map(service) -> Dict[str, str]:
    """
    Build a mapping of label_name → label_id from the Gmail account.

    Returns:
        dict: {"to respond": "Label_123", "FYI": "Label_456", ...}
    """
    all_labels = list_all_labels(service)
    label_map: Dict[str, str] = {}

    for label in all_labels:
        name = label.get("name", "")
        label_id = label.get("id", "")
        label_map[name] = label_id

    return label_map


def get_canonical_label_ids(service) -> Dict[str, str]:
    """
    Get label IDs only for the 8 canonical system labels.

    Returns:
        dict: {"to_respond": "Label_123", "fyi": "Label_456", ...}

    Raises:
        ValueError: If any canonical label is missing from the Gmail account
    """
    all_labels = build_label_map(service)
    result: Dict[str, str] = {}
    missing = []

    for key, display_name in LABEL_KEY_MAP.items():
        if display_name in all_labels:
            result[key] = all_labels[display_name]
        else:
            missing.append(display_name)

    if missing:
        raise ValueError(
            f"The following required labels were not found in your Gmail account:\n"
            + "\n".join(f"  - {name}" for name in missing)
            + "\nPlease create them manually in Gmail before running this tool."
        )

    return result


def update_config_with_label_ids(service, config_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Fetch label IDs and write them into config.yaml under the `labels` key.

    Returns:
        dict: The label ID mapping that was written
    """
    path = config_path or CONFIG_PATH
    label_ids = get_canonical_label_ids(service)

    if path.exists():
        with open(path, "r") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    config["labels"] = label_ids

    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    return label_ids


def print_all_labels(service):
    """Print all Gmail labels in a formatted table."""
    labels = list_all_labels(service)
    print(f"\n{'ID':<30} {'Type':<10} {'Name'}")
    print("-" * 70)
    for label in sorted(labels, key=lambda x: x.get("name", "")):
        print(f"{label.get('id', ''):<30} {label.get('type', ''):<10} {label.get('name', '')}")
    print(f"\nTotal: {len(labels)} labels")


if __name__ == "__main__":
    from auth.gmail_auth import get_gmail_service

    service = get_gmail_service()
    print("All Gmail labels:")
    print_all_labels(service)

    print("\nCanonical system labels:")
    ids = get_canonical_label_ids(service)
    for key, label_id in ids.items():
        display = LABEL_KEY_MAP[key]
        print(f"  {key:<20} → {display:<20} → {label_id}")
