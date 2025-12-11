"""
Bitrix24 OAuth2 Authentication Module
"""
import os
import httpx
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse

# Bitrix24 OAuth2 Configuration
BITRIX_DOMAIN = os.getenv("BITRIX_DOMAIN", "")  # e.g., "yourcompany.bitrix24.ru"
BITRIX_CLIENT_ID = os.getenv("BITRIX_CLIENT_ID", "")
BITRIX_CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET", "")
BITRIX_REDIRECT_URI = os.getenv("BITRIX_REDIRECT_URI", "")

# Admin user IDs (Bitrix24 user IDs that have admin access)
# Set this in environment as comma-separated IDs: "1,2,3"
ADMIN_USER_IDS = [int(x) for x in os.getenv("BITRIX_ADMIN_IDS", "1").split(",") if x.strip()]

# Session cookie name
SESSION_COOKIE = "mos_gsm_session"


def get_auth_url() -> str:
    """Generate Bitrix24 OAuth2 authorization URL"""
    if not BITRIX_DOMAIN or not BITRIX_CLIENT_ID:
        return ""

    return (
        f"https://{BITRIX_DOMAIN}/oauth/authorize/"
        f"?client_id={BITRIX_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={BITRIX_REDIRECT_URI}"
    )


async def exchange_code_for_token(code: str) -> Optional[dict]:
    """Exchange authorization code for access token"""
    if not BITRIX_CLIENT_ID or not BITRIX_CLIENT_SECRET:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://oauth.bitrix.info/oauth/token/",
                params={
                    "grant_type": "authorization_code",
                    "client_id": BITRIX_CLIENT_ID,
                    "client_secret": BITRIX_CLIENT_SECRET,
                    "redirect_uri": BITRIX_REDIRECT_URI,
                    "code": code
                },
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Token exchange failed: {response.status_code} - {response.text}")
                return None
    except Exception as e:
        print(f"❌ Token exchange error: {e}")
        return None


async def refresh_access_token(refresh_token: str) -> Optional[dict]:
    """Refresh expired access token"""
    if not BITRIX_CLIENT_ID or not BITRIX_CLIENT_SECRET:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://oauth.bitrix.info/oauth/token/",
                params={
                    "grant_type": "refresh_token",
                    "client_id": BITRIX_CLIENT_ID,
                    "client_secret": BITRIX_CLIENT_SECRET,
                    "refresh_token": refresh_token
                },
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ Token refresh failed: {response.status_code}")
                return None
    except Exception as e:
        print(f"❌ Token refresh error: {e}")
        return None


async def get_bitrix_user(access_token: str, domain: str) -> Optional[dict]:
    """Get current user info from Bitrix24"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://{domain}/rest/user.current.json",
                params={"auth": access_token},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    return data["result"]

            print(f"❌ Get user failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Get user error: {e}")
        return None


def determine_role(bitrix_id: int) -> str:
    """Determine user role based on Bitrix24 ID"""
    if bitrix_id in ADMIN_USER_IDS:
        return "admin"
    return "employee"


def is_auth_configured() -> bool:
    """Check if Bitrix24 auth is configured"""
    return bool(BITRIX_DOMAIN and BITRIX_CLIENT_ID and BITRIX_CLIENT_SECRET)


# Simple in-memory session storage (for production, use Redis or database)
sessions = {}


def create_session(user_data: dict) -> str:
    """Create a new session and return session ID"""
    import secrets
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = {
        "user": user_data,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(hours=24)
    }
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    """Get session data by ID"""
    if not session_id or session_id not in sessions:
        return None

    session = sessions[session_id]

    # Check if expired
    if datetime.utcnow() > session["expires_at"]:
        del sessions[session_id]
        return None

    return session


def delete_session(session_id: str):
    """Delete a session"""
    if session_id in sessions:
        del sessions[session_id]


def get_current_user(request: Request) -> Optional[dict]:
    """Get current user from session cookie"""
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None

    session = get_session(session_id)
    if not session:
        return None

    return session["user"]


def require_auth(request: Request) -> dict:
    """Require authentication, raise exception if not authenticated"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request) -> dict:
    """Require admin role"""
    user = require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
