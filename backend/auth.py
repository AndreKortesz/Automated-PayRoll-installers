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
# Set this in environment as comma-separated IDs: "1,9,311"
ADMIN_USER_IDS = [int(x) for x in os.getenv("BITRIX_ADMIN_IDS", "9").split(",") if x.strip()]

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


async def exchange_code_for_token(code: str, server_domain: str = None) -> Optional[dict]:
    """Exchange authorization code for access token"""
    if not BITRIX_CLIENT_ID or not BITRIX_CLIENT_SECRET:
        print("❌ Missing BITRIX_CLIENT_ID or BITRIX_CLIENT_SECRET")
        return None

    # IMPORTANT: Use the server_domain from callback, or default to oauth.bitrix.info
    # Bitrix24 can use different OAuth servers: oauth.bitrix.info, oauth.bitrix24.tech, etc.
    oauth_server = server_domain or "oauth.bitrix.info"
    token_url = f"https://{oauth_server}/oauth/token/"

    print(f"🔐 Exchanging code at: {token_url}")
    print(f"🔐 Using redirect_uri: {BITRIX_REDIRECT_URI}")

    try:
        async with httpx.AsyncClient() as client:
            # IMPORTANT: Use POST method, not GET!
            # Bitrix24 OAuth requires POST for token exchange
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": BITRIX_CLIENT_ID,
                    "client_secret": BITRIX_CLIENT_SECRET,
                    "redirect_uri": BITRIX_REDIRECT_URI,
                    "code": code
                },
                timeout=30
            )

            print(f"🔐 Token response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Token exchange successful")
                return data
            else:
                print(f"❌ Token exchange failed: {response.status_code} - {response.text}")
                
                # Try alternative: GET method (some Bitrix versions use GET)
                print(f"🔄 Trying GET method...")
                response = await client.get(
                    token_url,
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
                    data = response.json()
                    print(f"✅ Token exchange successful (GET)")
                    return data
                else:
                    print(f"❌ GET also failed: {response.status_code} - {response.text}")
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
            response = await client.post(
                "https://oauth.bitrix.info/oauth/token/",
                data={
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
    # Clean domain (remove protocol if present)
    if domain.startswith("http://"):
        domain = domain[7:]
    elif domain.startswith("https://"):
        domain = domain[8:]
    domain = domain.rstrip("/")
    
    url = f"https://{domain}/rest/user.current"
    print(f"🔐 Getting user info from: {url}")
    
    try:
        async with httpx.AsyncClient() as client:
            # Try POST method first (more reliable)
            response = await client.post(
                url,
                data={"auth": access_token},
                timeout=30
            )
            
            print(f"🔐 User info response: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"🔐 User data: {data}")
                if "result" in data:
                    return data["result"]
                # Some endpoints return data directly
                if "ID" in data:
                    return data

            # Try GET method as fallback
            print(f"🔄 Trying GET method for user info...")
            response = await client.get(
                url,
                params={"auth": access_token},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if "result" in data:
                    return data["result"]
                if "ID" in data:
                    return data

            print(f"❌ Get user failed: {response.status_code} - {response.text[:200]}")
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


# Simple in-memory session storage
# WARNING: Sessions will be lost on server restart
# For production with multiple instances, use Redis or database
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
