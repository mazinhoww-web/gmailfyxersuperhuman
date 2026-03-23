"""
Gmail OAuth2 Authentication Module
Handles OAuth2 flow and token management for Gmail API access.
"""

import os
import json
import pickle
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Gmail API scopes required for full functionality
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",    # Read/write/label
    "https://www.googleapis.com/auth/gmail.compose",   # Create drafts and send
    "https://www.googleapis.com/auth/gmail.readonly",  # Read-only fallback
]

AUTH_DIR = Path(__file__).parent
CREDENTIALS_FILE = AUTH_DIR / "credentials.json"
TOKEN_FILE = AUTH_DIR / "token.pickle"


def get_gmail_service(credentials_path: Optional[str] = None, token_path: Optional[str] = None):
    """
    Build and return an authenticated Gmail API service.

    On first run, opens a browser for OAuth2 consent.
    Subsequent runs use the cached token.

    Args:
        credentials_path: Path to OAuth2 credentials JSON (default: auth/credentials.json)
        token_path: Path to store/load token pickle (default: auth/token.pickle)

    Returns:
        googleapiclient.discovery.Resource: Authenticated Gmail service
    """
    creds_path = Path(credentials_path) if credentials_path else CREDENTIALS_FILE
    tok_path = Path(token_path) if token_path else TOKEN_FILE

    if not creds_path.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {creds_path}\n"
            "Download your OAuth2 credentials from Google Cloud Console:\n"
            "  https://console.cloud.google.com/apis/credentials\n"
            "Save as auth/credentials.json"
        )

    creds = _load_credentials(tok_path)

    if not creds or not creds.valid:
        creds = _refresh_or_authorize(creds, creds_path, tok_path)

    service = build("gmail", "v1", credentials=creds)
    return service


def _load_credentials(token_path: Path) -> Optional[Credentials]:
    """Load credentials from token file if it exists."""
    if token_path.exists():
        with open(token_path, "rb") as f:
            return pickle.load(f)
    return None


def _refresh_or_authorize(
    creds: Optional[Credentials],
    credentials_path: Path,
    token_path: Path,
) -> Credentials:
    """Refresh expired token or run full OAuth2 flow."""
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path), SCOPES
        )
        creds = flow.run_local_server(port=0)

    with open(token_path, "wb") as f:
        pickle.dump(creds, f)

    return creds


def get_authenticated_user(service) -> dict:
    """
    Get info about the authenticated Gmail user.

    Returns:
        dict with emailAddress and messagesTotal
    """
    profile = service.users().getProfile(userId="me").execute()
    return profile


def revoke_credentials(token_path: Optional[str] = None):
    """Remove cached token to force re-authentication."""
    tok_path = Path(token_path) if token_path else TOKEN_FILE
    if tok_path.exists():
        tok_path.unlink()
        print(f"Credentials revoked. Token removed: {tok_path}")
    else:
        print("No cached credentials found.")


if __name__ == "__main__":
    # Quick test: authenticate and show user profile
    print("Authenticating with Gmail...")
    service = get_gmail_service()
    profile = get_authenticated_user(service)
    print(f"Authenticated as: {profile.get('emailAddress')}")
    print(f"Total messages: {profile.get('messagesTotal')}")
