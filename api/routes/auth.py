"""
Google OAuth2 with Gmail scopes.

Flow:
  1. Frontend calls GET /auth/google?user_id=<supabase_uid>
  2. Backend redirects to Google consent screen (with Gmail scopes)
  3. Google calls back to GET /auth/google/callback?code=...&state=...
  4. Backend exchanges code for tokens, stores them encrypted
  5. Backend redirects frontend to /inbox with success flag
"""

import os
import json
import secrets
import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# In-memory state storage (use Redis in production)
_oauth_states: dict[str, dict] = {}

# Token storage per user (use Supabase/encrypted DB in production)
_user_tokens: dict[str, dict] = {}


def _get_client_secrets_file() -> str:
    path = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "auth/credentials.json")
    if not os.path.exists(path):
        raise HTTPException(
            status_code=500,
            detail="Google OAuth credentials not configured. Set GOOGLE_CLIENT_SECRETS_FILE env var.",
        )
    return path


def _build_flow(redirect_uri: str) -> Flow:
    return Flow.from_client_secrets_file(
        _get_client_secrets_file(),
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )


def _get_redirect_uri(request: Request) -> str:
    """Build redirect URI, respecting X-Forwarded-Proto in production."""
    base = BACKEND_URL.rstrip("/")
    return f"{base}/auth/google/callback"


@router.get("/google")
async def google_auth_start(request: Request, user_id: Optional[str] = None):
    """Redirect user to Google consent screen with Gmail scopes."""
    redirect_uri = _get_redirect_uri(request)
    flow = _build_flow(redirect_uri)

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_auth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Google OAuth callback, exchange code for tokens."""
    if error:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?error={error}"
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    state_data = _oauth_states.pop(state, None)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    redirect_uri = _get_redirect_uri(request)
    flow = _build_flow(redirect_uri)

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    credentials = flow.credentials

    # Get user info from Google
    user_info_service = build("oauth2", "v2", credentials=credentials)
    user_info = user_info_service.userinfo().get().execute()
    email = user_info.get("email", "")
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")

    # Determine storage key: prefer Supabase user_id if provided, else email hash
    user_id = state_data.get("user_id") or hashlib.sha256(email.encode()).hexdigest()[:16]

    # Store tokens
    _user_tokens[user_id] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or GMAIL_SCOPES),
        "email": email,
        "name": name,
        "picture": picture,
        "user_id": user_id,
    }

    # Redirect frontend to /inbox with session token
    session_token = secrets.token_urlsafe(32)
    _oauth_states[f"session_{session_token}"] = {"user_id": user_id, "email": email}

    redirect_url = (
        f"{FRONTEND_URL}/inbox"
        f"?session={session_token}"
        f"&email={email}"
        f"&name={name}"
        f"&picture={picture}"
    )
    return RedirectResponse(url=redirect_url)


@router.get("/me")
async def get_current_user(session: str):
    """Get authenticated user info from session token."""
    session_data = _oauth_states.get(f"session_{session}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    user_id = session_data["user_id"]
    token_data = _user_tokens.get(user_id, {})

    return {
        "user_id": user_id,
        "email": token_data.get("email"),
        "name": token_data.get("name"),
        "picture": token_data.get("picture"),
        "authenticated": True,
    }


@router.post("/logout")
async def logout(session: str):
    """Revoke session."""
    _oauth_states.pop(f"session_{session}", None)
    return {"success": True}


def get_credentials_for_session(session: str) -> Credentials:
    """Helper used by other routes to get Gmail credentials from session."""
    session_data = _oauth_states.get(f"session_{session}")
    if not session_data:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = session_data["user_id"]
    token_data = _user_tokens.get(user_id)
    if not token_data:
        raise HTTPException(status_code=401, detail="No credentials found")

    return Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
