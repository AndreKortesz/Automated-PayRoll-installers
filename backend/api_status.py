"""
API endpoints for period status management and notifications
Mos-GSM Salary Service
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from typing import List

from database import (
    database, PeriodStatus, 
    get_period_status, update_period_status, is_latest_period,
    save_notification, get_period_notifications, get_audit_log
)
from auth import get_current_user
from permissions import (
    check_send_permission, check_send_to_accountant_permission,
    check_unlock_permission, get_user_permissions, log_user_action
)

router = APIRouter(prefix="/api", tags=["status"])


# ============== PERMISSIONS API ==============

@router.get("/permissions")
async def api_get_permissions(request: Request, period_id: int = None):
    """Get current user's permissions, optionally for a specific period"""
    try:
        permissions = await get_user_permissions(request, period_id)
        return JSONResponse({"success": True, "permissions": permissions})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.get("/period/{period_id}/permissions")
async def api_get_period_permissions(request: Request, period_id: int):
    """Get current user's permissions for a specific period"""
    try:
        permissions = await get_user_permissions(request, period_id)
        return JSONResponse({"success": True, "permissions": permissions})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


# ============== STATUS API ==============

@router.get("/period/{period_id}/status")
async def api_get_period_status(request: Request, period_id: int):
    """Get period status and info"""
    try:
        period = await get_period_status(period_id)
        if not period:
            return JSONResponse({"success": False, "error": "Период не найден"}, status_code=404)
        
        is_latest = await is_latest_period(period_id)
        
        return JSONResponse({
            "success": True,
            "period": {
                "id": period["id"],
                "name": period["name"],
                "status": period["status"],
                "status_label": {
                    PeriodStatus.DRAFT: "Черновик",
                    PeriodStatus.SENT: "Отправлено монтажникам",
                    PeriodStatus.PAID: "Оплачено",
                }.get(period["status"], period["status"]),
                "sent_at": str(period["sent_at"]) if period.get("sent_at") else None,
                "paid_at": str(period["paid_at"]) if period.get("paid_at") else None,
                "is_latest": is_latest,
            }
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.post("/period/{period_id}/send-to-workers")
async def api_send_to_workers(request: Request, period_id: int):
    """
    Send reports to workers via Bitrix24 chat.
    Changes status to SENT.
    """
    try:
        # Check permission
        user = await check_send_permission(request, period_id)
        
        # Get request body
        body = await request.json()
        worker_ids = body.get("worker_ids", [])  # List of Bitrix24 user IDs to send to
        
        if not worker_ids:
            return JSONResponse({"success": False, "error": "Не выбраны монтажники"})
        
        # Get period details
        period = await get_period_status(period_id)
        if not period:
            return JSONResponse({"success": False, "error": "Период не найден"}, status_code=404)
        
        sent_count = 0
        errors = []
        
        for worker_info in worker_ids:
            worker_name = worker_info.get("name", "")
            bitrix_user_id = worker_info.get("bitrix_id")
            
            try:
                # Save notification record
                await save_notification(
                    period_id=period_id,
                    worker=worker_name,
                    bitrix_user_id=bitrix_user_id,
                    notification_type="chat",
                    sent_by=user.get("id")
                )
                sent_count += 1
                
            except Exception as e:
                errors.append(f"{worker_name}: {str(e)}")
        
        # Update period status to SENT
        if sent_count > 0:
            await update_period_status(period_id, PeriodStatus.SENT, user)
        
        # Log action
        await log_user_action(
            request, "send_to_workers",
            entity_type="period",
            entity_id=period_id,
            period_id=period_id,
            details={"sent_count": sent_count, "errors": errors}
        )
        
        return JSONResponse({
            "success": True,
            "sent_count": sent_count,
            "errors": errors,
            "new_status": PeriodStatus.SENT
        })
        
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.post("/period/{period_id}/send-to-accountant")
async def api_send_to_accountant(request: Request, period_id: int):
    """
    Send payment request to accountant via Bitrix24 chat.
    Changes status to PAID - no more editing allowed (except admin unlock).
    """
    try:
        # Check permission
        user = await check_send_to_accountant_permission(request, period_id)
        
        # Get request body
        body = await request.json()
        accountant_bitrix_id = body.get("accountant_bitrix_id")
        payment_details = body.get("payment_details", [])
        # payment_details = [{"worker": "Иванов Иван", "amount": 50000, "bank": "Т-Банк"}, ...]
        
        if not accountant_bitrix_id:
            return JSONResponse({"success": False, "error": "Не указан бухгалтер"})
        
        # Get period details
        period = await get_period_status(period_id)
        if not period:
            return JSONResponse({"success": False, "error": "Период не найден"}, status_code=404)
        
        # Build message for accountant
        message_lines = [f"💰 Запрос на оплату зарплаты за период {period['name']}:"]
        message_lines.append("")
        
        total_amount = 0
        for detail in payment_details:
            worker = detail.get("worker", "")
            amount = detail.get("amount", 0)
            bank = detail.get("bank", "")
            total_amount += amount
            message_lines.append(f"• {worker}: {amount:,.0f} ₽ ({bank})")
        
        message_lines.append("")
        message_lines.append(f"Итого к оплате: {total_amount:,.0f} ₽")
        message_lines.append("")
        message_lines.append(f"Отправил: {user.get('name', 'Неизвестно')}")
        
        message = "\n".join(message_lines)
        
        # STUB: Bitrix24 messaging integration not yet implemented
        # When ready, uncomment and implement:
        # await send_bitrix_message(access_token, accountant_bitrix_id, message)
        
        # Update period status to PAID
        await update_period_status(period_id, PeriodStatus.PAID, user)
        
        # Log action
        await log_user_action(
            request, "send_to_accountant",
            entity_type="period",
            entity_id=period_id,
            period_id=period_id,
            details={
                "accountant_bitrix_id": accountant_bitrix_id,
                "total_amount": total_amount,
                "workers_count": len(payment_details)
            }
        )
        
        return JSONResponse({
            "success": True,
            "message": "Запрос отправлен бухгалтеру",
            "new_status": PeriodStatus.PAID
        })
        
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.post("/period/{period_id}/unlock")
async def api_unlock_period(request: Request, period_id: int):
    """
    Unlock a PAID period for editing (admin only).
    Changes status back to SENT.
    """
    try:
        # Check permission (admin only)
        user = await check_unlock_permission(request)
        
        # Get period
        period = await get_period_status(period_id)
        if not period:
            return JSONResponse({"success": False, "error": "Период не найден"}, status_code=404)
        
        if period["status"] != PeriodStatus.PAID:
            return JSONResponse({"success": False, "error": "Период не заблокирован"})
        
        # Update status back to SENT
        await update_period_status(period_id, PeriodStatus.SENT, user)
        
        # Log action
        await log_user_action(
            request, "unlock_period",
            entity_type="period",
            entity_id=period_id,
            period_id=period_id,
            details={"previous_status": PeriodStatus.PAID}
        )
        
        return JSONResponse({
            "success": True,
            "message": "Период разблокирован для редактирования",
            "new_status": PeriodStatus.SENT
        })
        
    except HTTPException as e:
        return JSONResponse({"success": False, "error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


# ============== AUDIT LOG API ==============

@router.get("/period/{period_id}/audit-log")
async def api_get_period_audit_log(request: Request, period_id: int):
    """Get audit log for a period"""
    try:
        user = get_current_user(request)
        if not user:
            return JSONResponse({"success": False, "error": "Необходима авторизация"}, status_code=401)
        
        logs = await get_audit_log(period_id=period_id, limit=100)
        
        # Format for display
        formatted_logs = []
        for log in logs:
            formatted_logs.append({
                "id": log["id"],
                "user_name": log["user_name"],
                "user_role": log["user_role"],
                "action": log["action"],
                "action_label": {
                    "upload_files": "Загрузил файлы",
                    "edit_calculation": "Изменил расчёт",
                    "delete_row": "Удалил строку",
                    "send_to_workers": "Отправил монтажникам",
                    "send_to_accountant": "Отправил бухгалтеру",
                    "unlock_period": "Разблокировал период",
                    "status_change_to_draft": "Статус: Черновик",
                    "status_change_to_sent": "Статус: Отправлено",
                    "status_change_to_paid": "Статус: Оплачено",
                }.get(log["action"], log["action"]),
                "details": log["details"],
                "created_at": str(log["created_at"]),
                "period_status": log["period_status"],
            })
        
        return JSONResponse({"success": True, "logs": formatted_logs})
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.get("/audit-log")
async def api_get_global_audit_log(request: Request, limit: int = 100):
    """Get global audit log (admin only)"""
    try:
        user = get_current_user(request)
        if not user:
            return JSONResponse({"success": False, "error": "Необходима авторизация"}, status_code=401)
        
        if user.get("role") != "admin":
            return JSONResponse({"success": False, "error": "Только для администратора"}, status_code=403)
        
        logs = await get_audit_log(limit=limit)
        
        return JSONResponse({"success": True, "logs": logs})
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


# ============== NOTIFICATIONS HISTORY ==============

@router.get("/period/{period_id}/notifications")
async def api_get_period_notifications(request: Request, period_id: int):
    """Get notification history for a period"""
    try:
        user = get_current_user(request)
        if not user:
            return JSONResponse({"success": False, "error": "Необходима авторизация"}, status_code=401)
        
        notifications = await get_period_notifications(period_id)
        
        return JSONResponse({"success": True, "notifications": notifications})
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


# ============== BITRIX24 WORKERS LIST ==============

@router.get("/bitrix/workers")
async def api_get_bitrix_workers(request: Request):
    """
    Get list of workers from Bitrix24.
    
    NOTE: This is a stub endpoint. Bitrix24 API integration is not yet implemented.
    Returns empty list until integration is complete.
    """
    try:
        user = get_current_user(request)
        if not user:
            return JSONResponse({"success": False, "error": "Необходима авторизация"}, status_code=401)
        
        # STUB: Bitrix24 workers list integration not implemented
        # Implementation would use: user's access_token to call Bitrix24 REST API
        # Endpoint: https://{domain}/rest/user.get with department filter
        
        workers = []
        
        # Example of what real data would look like:
        # workers = [
        #     {"bitrix_id": 10, "name": "Ветренко Дмитрий", "position": "Монтажник"},
        #     {"bitrix_id": 11, "name": "Викулин Андрей", "position": "Монтажник"},
        # ]
        
        return JSONResponse({"success": True, "workers": workers})
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@router.get("/bitrix/accountants")
async def api_get_bitrix_accountants(request: Request):
    """
    Get list of accountants from Bitrix24.
    
    NOTE: This is a stub endpoint. Bitrix24 API integration is not yet implemented.
    Returns empty list until integration is complete.
    """
    try:
        user = get_current_user(request)
        if not user:
            return JSONResponse({"success": False, "error": "Необходима авторизация"}, status_code=401)
        
        # STUB: Bitrix24 accountants list integration not implemented
        # Implementation would filter by department (e.g., "Бухгалтерия")
        
        accountants = []
        
        return JSONResponse({"success": True, "accountants": accountants})
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})
