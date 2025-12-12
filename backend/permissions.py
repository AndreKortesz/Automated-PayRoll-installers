"""
Permission checking utilities for Salary Service
"""

from fastapi import Request, HTTPException
from functools import wraps
from typing import Optional

from database import (
    PeriodStatus,
    can_user_edit_period,
    can_user_upload,
    can_user_delete_row,
    can_user_delete_period,
    can_user_send_to_workers,
    can_user_send_to_accountant,
    can_user_unlock_period,
    can_user_change_status,
    is_latest_period,
    get_period_status,
    log_action,
)
from auth import get_current_user


async def check_edit_permission(request: Request, period_id: int) -> dict:
    """
    Check if current user can edit the specified period.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    # Get period status
    period = await get_period_status(period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Период не найден")
    
    status = period.get("status", PeriodStatus.DRAFT)
    is_latest = await is_latest_period(period_id)
    
    can_edit, reason = can_user_edit_period(user, status, is_latest)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail=reason)
    
    # Add period info to user for logging
    user["_period_status"] = status
    user["_is_latest"] = is_latest
    
    return user


async def check_upload_permission(request: Request, period_id: int = None) -> dict:
    """
    Check if current user can upload files.
    If period_id is None, checks for new upload.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    if period_id:
        # Check existing period
        period = await get_period_status(period_id)
        if not period:
            raise HTTPException(status_code=404, detail="Период не найден")
        
        status = period.get("status", PeriodStatus.DRAFT)
        is_latest = await is_latest_period(period_id)
        
        can_upload, reason = can_user_upload(user, status, is_latest)
        
        if not can_upload:
            raise HTTPException(status_code=403, detail=reason)
    else:
        # New upload - only check if employee is creating new period
        # Employee can always create new periods (they become the "latest")
        pass
    
    return user


async def check_delete_row_permission(request: Request, period_id: int) -> dict:
    """
    Check if current user can delete a ROW in report.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    period = await get_period_status(period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Период не найден")
    
    status = period.get("status", PeriodStatus.DRAFT)
    is_latest = await is_latest_period(period_id)
    
    can_delete, reason = can_user_delete_row(user, status, is_latest)
    
    if not can_delete:
        raise HTTPException(status_code=403, detail=reason)
    
    return user


async def check_delete_period_permission(request: Request) -> dict:
    """
    Check if current user can delete entire PERIOD.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    can_delete, reason = can_user_delete_period(user)
    
    if not can_delete:
        raise HTTPException(status_code=403, detail=reason)
    
    return user


async def check_send_permission(request: Request, period_id: int) -> dict:
    """
    Check if current user can send reports to workers.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    period = await get_period_status(period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Период не найден")
    
    status = period.get("status", PeriodStatus.DRAFT)
    is_latest = await is_latest_period(period_id)
    
    can_send, reason = can_user_send_to_workers(user, status, is_latest)
    
    if not can_send:
        raise HTTPException(status_code=403, detail=reason)
    
    return user


async def check_send_to_accountant_permission(request: Request, period_id: int) -> dict:
    """
    Check if current user can send to accountant (marks as PAID).
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    period = await get_period_status(period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Период не найден")
    
    status = period.get("status", PeriodStatus.DRAFT)
    is_latest = await is_latest_period(period_id)
    
    can_send, reason = can_user_send_to_accountant(user, status, is_latest)
    
    if not can_send:
        raise HTTPException(status_code=403, detail=reason)
    
    return user


async def check_unlock_permission(request: Request) -> dict:
    """
    Check if current user can unlock a PAID period.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    can_unlock, reason = can_user_unlock_period(user)
    
    if not can_unlock:
        raise HTTPException(status_code=403, detail=reason)
    
    return user


async def check_status_change_permission(request: Request, period_id: int, new_status: str) -> dict:
    """
    Check if current user can change period status.
    Returns user dict if allowed, raises HTTPException if not.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    period = await get_period_status(period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Период не найден")
    
    current_status = period.get("status", PeriodStatus.DRAFT)
    
    can_change, reason = can_user_change_status(user, current_status, new_status)
    
    if not can_change:
        raise HTTPException(status_code=403, detail=reason)
    
    return user


def get_client_ip(request: Request) -> str:
    """Get client IP address from request"""
    # Check X-Forwarded-For header (for proxied requests)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct client
    if request.client:
        return request.client.host
    
    return "unknown"


async def log_user_action(
    request: Request,
    action: str,
    entity_type: str = None,
    entity_id: int = None,
    period_id: int = None,
    details: dict = None
):
    """Log user action with request context"""
    user = get_current_user(request)
    ip_address = get_client_ip(request)
    
    await log_action(
        user=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        period_id=period_id,
        details=details,
        ip_address=ip_address
    )


# ============== PERMISSION SUMMARY FOR UI ==============

async def get_user_permissions(request: Request, period_id: int = None) -> dict:
    """
    Get summary of what current user can do.
    Useful for UI to show/hide buttons.
    """
    user = get_current_user(request)
    
    if not user:
        return {
            "authenticated": False,
            "can_view": False,
            "can_edit": False,
            "can_upload": False,
            "can_delete_row": False,
            "can_delete_period": False,
            "can_send_to_workers": False,
            "can_send_to_accountant": False,
            "can_unlock": False,
        }
    
    role = user.get("role", "employee")
    is_admin = role == "admin"
    
    # Default permissions
    permissions = {
        "authenticated": True,
        "user": {
            "id": user.get("id"),
            "bitrix_id": user.get("bitrix_id"),
            "name": user.get("name"),
            "role": role,
        },
        "is_admin": is_admin,
        "can_view": True,  # Everyone can view
        "can_edit": is_admin,
        "can_upload": is_admin,
        "can_delete_row": is_admin,
        "can_delete_period": is_admin,  # Only admin
        "can_send_to_workers": is_admin,
        "can_send_to_accountant": is_admin,
        "can_unlock": is_admin,  # Only admin can unlock PAID periods
    }
    
    # Check period-specific permissions
    if period_id:
        period = await get_period_status(period_id)
        if period:
            status = period.get("status", PeriodStatus.DRAFT)
            is_latest = await is_latest_period(period_id)
            
            permissions["period_status"] = status
            permissions["period_status_label"] = {
                PeriodStatus.DRAFT: "Черновик",
                PeriodStatus.SENT: "Отправлено монтажникам",
                PeriodStatus.PAID: "Оплачено",
            }.get(status, status)
            permissions["is_latest"] = is_latest
            permissions["sent_at"] = period.get("sent_at")
            permissions["paid_at"] = period.get("paid_at")
            
            # Employee permissions for latest non-paid period
            if not is_admin:
                if status != PeriodStatus.PAID and is_latest:
                    permissions["can_edit"] = True
                    permissions["can_upload"] = True
                    permissions["can_delete_row"] = True
                    permissions["can_send_to_workers"] = True
                    permissions["can_send_to_accountant"] = True
                else:
                    # Cannot do anything on old or paid periods
                    permissions["can_edit"] = False
                    permissions["can_upload"] = False
                    permissions["can_delete_row"] = False
                    permissions["can_send_to_workers"] = False
                    permissions["can_send_to_accountant"] = False
    
    return permissions
