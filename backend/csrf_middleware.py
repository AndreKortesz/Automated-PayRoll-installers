"""
CSRF Protection Middleware for FastAPI
Mos-GSM Salary Service

SECURITY NOTE: Set CSRF_SECRET_KEY environment variable in production!
Without it, a random key is generated on each restart, invalidating all tokens.
"""

import os
import secrets
import hashlib
import time
from typing import Optional, Callable
from functools import wraps

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware


# ============================================================================
# CONFIGURATION
# ============================================================================
# CRITICAL: In production, set CSRF_SECRET_KEY environment variable!
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
CSRF_SECRET_KEY = os.getenv("CSRF_SECRET_KEY")
if not CSRF_SECRET_KEY:
    CSRF_SECRET_KEY = secrets.token_hex(32)
    print("⚠️  WARNING: CSRF_SECRET_KEY not set in environment.")
    print("   Using random key - CSRF tokens will be invalidated on restart!")
    print("   Set CSRF_SECRET_KEY env variable for production.")

CSRF_TOKEN_LENGTH = 64
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_COOKIE_MAX_AGE = 3600 * 24  # 24 hours
CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths exempt from CSRF validation (public APIs, webhooks, health checks)
CSRF_EXEMPT_PATHS = {
    "/api/health",
    "/api/detect-file-type",  # File type detection is read-only
    "/auth/callback",  # OAuth callback from Bitrix24
}


# ============================================================================
# TOKEN GENERATION & VALIDATION
# ============================================================================

def generate_csrf_token(session_id: str = None) -> str:
    """
    Generate a new CSRF token.
    Format: timestamp:random:signature
    """
    timestamp = str(int(time.time()))
    random_part = secrets.token_hex(16)
    
    # Create signature
    data = f"{timestamp}:{random_part}:{session_id or ''}"
    signature = hashlib.sha256(
        f"{data}:{CSRF_SECRET_KEY}".encode()
    ).hexdigest()[:16]
    
    return f"{timestamp}:{random_part}:{signature}"


def validate_csrf_token(token: str, max_age: int = CSRF_COOKIE_MAX_AGE) -> bool:
    """
    Validate CSRF token.
    Returns True if token is valid and not expired.
    """
    if not token:
        return False
    
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        
        timestamp, random_part, signature = parts
        
        # Check expiration
        token_time = int(timestamp)
        if time.time() - token_time > max_age:
            return False
        
        # Verify signature (without session_id for simplicity)
        data = f"{timestamp}:{random_part}:"
        expected_signature = hashlib.sha256(
            f"{data}:{CSRF_SECRET_KEY}".encode()
        ).hexdigest()[:16]
        
        # Use constant-time comparison to prevent timing attacks
        return secrets.compare_digest(signature, expected_signature)
    
    except (ValueError, TypeError):
        return False


# ============================================================================
# MIDDLEWARE
# ============================================================================

class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF Protection Middleware.
    
    - Sets CSRF cookie on all responses
    - Validates CSRF token on state-changing requests (POST, PUT, DELETE, PATCH)
    - Skips validation for safe methods and exempt paths
    
    Usage:
        from csrf_middleware import CSRFMiddleware
        app.add_middleware(CSRFMiddleware)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate CSRF token
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        
        if csrf_cookie and validate_csrf_token(csrf_cookie):
            csrf_token = csrf_cookie
        else:
            csrf_token = generate_csrf_token()
        
        # Store token in request state for templates
        request.state.csrf_token = csrf_token
        
        # Check if validation is needed
        method = request.method.upper()
        path = request.url.path
        
        needs_validation = (
            method not in CSRF_SAFE_METHODS and
            path not in CSRF_EXEMPT_PATHS and
            not path.startswith("/static/")
        )
        
        if needs_validation:
            # Get token from request header
            request_token = request.headers.get(CSRF_HEADER_NAME)
            
            # For form submissions, try to get from form data
            if not request_token:
                content_type = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in content_type:
                    try:
                        form = await request.form()
                        request_token = form.get(CSRF_FORM_FIELD)
                    except Exception:
                        pass
            
            # Validate token
            if not request_token or not validate_csrf_token(request_token):
                # Return JSON error for API requests
                if path.startswith("/api/") or request.headers.get("accept") == "application/json":
                    return JSONResponse(
                        status_code=403,
                        content={
                            "success": False,
                            "error": "CSRF validation failed",
                            "detail": "Invalid or missing CSRF token. Please refresh the page."
                        }
                    )
                # Return HTML error for browser requests
                return Response(
                    content="CSRF validation failed. Please refresh the page and try again.",
                    status_code=403,
                    media_type="text/html"
                )
        
        # Process request
        response = await call_next(request)
        
        # Set/refresh CSRF cookie
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=csrf_token,
            max_age=CSRF_COOKIE_MAX_AGE,
            httponly=False,  # Must be readable by JavaScript for AJAX requests
            samesite="strict",
            secure=request.url.scheme == "https"
        )
        
        return response


# ============================================================================
# HELPERS FOR TEMPLATES AND DECORATORS
# ============================================================================

def get_csrf_token(request: Request) -> str:
    """
    Get CSRF token from request state.
    Usage in route: token = get_csrf_token(request)
    """
    return getattr(request.state, 'csrf_token', generate_csrf_token())


def csrf_protect(func: Callable) -> Callable:
    """
    Decorator for explicit CSRF protection on specific endpoints.
    Use when middleware is disabled but you want protection on certain routes.
    
    Usage:
        @app.post("/sensitive-action")
        @csrf_protect
        async def sensitive_action(request: Request):
            ...
    """
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        token = request.headers.get(CSRF_HEADER_NAME)
        if not token or not validate_csrf_token(token):
            raise HTTPException(
                status_code=403,
                detail="CSRF validation failed"
            )
        return await func(request, *args, **kwargs)
    return wrapper


def csrf_context(request: Request) -> dict:
    """
    Returns context dict with CSRF token for Jinja2 templates.
    
    Usage in route:
        return templates.TemplateResponse("page.html", {
            "request": request,
            **csrf_context(request)
        })
    
    Usage in template:
        {{ csrf_input | safe }}
        or
        <meta name="csrf-token" content="{{ csrf_token }}">
    """
    token = getattr(request.state, 'csrf_token', generate_csrf_token())
    return {
        "csrf_token": token,
        "csrf_input": f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{token}">',
        "csrf_meta": f'<meta name="csrf-token" content="{token}">'
    }
