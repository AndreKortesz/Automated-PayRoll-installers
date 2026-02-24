"""
Salary calculation logic
"""

import pandas as pd
from typing import List, Dict

from utils.helpers import extract_address_from_order, parse_percent
from utils.workers import normalize_worker_name
from .geocoding import calculate_fuel_cost


async def calculate_row(row: dict, config: dict, days_map: dict) -> dict:
    """Calculate additional columns for a row"""
    result = row.copy()
    
    result["fuel_payment"] = 0
    result["transport"] = 0
    result["diagnostic_50"] = 0
    result["total"] = 0
    
    if row.get("is_worker_total") or "В прошлом расчете" in str(row.get("order", "")):
        service_payment = float(row.get("service_payment", 0)) if pd.notna(row.get("service_payment")) and row.get("service_payment") != "" else 0
        result["total"] = service_payment
        return result
    
    order = str(row.get("order", ""))
    address = extract_address_from_order(order)
    
    specialist_fee = row.get("specialist_fee", 0)
    specialist_fee = float(specialist_fee) if pd.notna(specialist_fee) and specialist_fee != "" else 0
    
    revenue_services = row.get("revenue_services", 0)
    revenue_services = float(revenue_services) if pd.notna(revenue_services) and revenue_services != "" else 0
    
    percent = parse_percent(row.get("percent", 0))
    
    service_payment = row.get("service_payment", 0)
    service_payment = float(service_payment) if pd.notna(service_payment) and service_payment != "" else 0
    
    diagnostic = row.get("diagnostic", 0)
    diagnostic = float(diagnostic) if pd.notna(diagnostic) and diagnostic != "" else 0
    
    # Get worker name for company car check
    worker = row.get("worker", "").replace(" (оплата клиентом)", "")
    worker_normalized = normalize_worker_name(worker)
    
    # Get list of workers on company car (transport = 0)
    company_car_workers = config.get("company_car_workers", [])
    company_car_normalized = [normalize_worker_name(w) for w in company_car_workers]
    is_on_company_car = worker_normalized in company_car_normalized
    
    # 1. Fuel payment - only if specialist_fee is empty and has real address in Moscow/MO
    if specialist_fee == 0 and address:
        # Priority: days_on_site from Excel > days_map from user input > default 1
        days_from_excel = row.get("days_on_site")
        if days_from_excel and days_from_excel > 0:
            days = int(days_from_excel)
        else:
            days = days_map.get(order, 1)
        result["fuel_payment"] = await calculate_fuel_cost(address, config, days)
    
    # 2. Transport - only for revenue > 10k with percent between 20% and 40%, and NOT on company car
    percent_min = config.get("transport_percent_min", 20)
    percent_max = config.get("transport_percent_max", 40)
    if revenue_services > config["transport_min_revenue"] and percent_min <= percent <= percent_max:
        if is_on_company_car:
            result["transport"] = 0  # On company car - no transport payment
        else:
            result["transport"] = config["transport_amount"]
    
    # 3. Diagnostic -50% - only for "оплата клиентом" rows with diagnostic
    if row.get("is_client_payment") and diagnostic > 0:
        result["diagnostic_50"] = diagnostic * config["diagnostic_percent"] / 100
    
    # 4. Total = service_payment + fuel + transport
    result["total"] = service_payment + result["fuel_payment"] + result["transport"]
    
    return result


def generate_alarms(data: List[dict], config: dict) -> Dict[str, List[Dict]]:
    """Generate warning alarms for manual review - AFTER calculation, grouped by category"""
    alarms = {
        "high_payment": [],
        "non_standard_percent": [],
        "high_specialist_fee": [],
        "high_fuel": []
    }
    
    for row in data:
        worker = row.get("worker", "")
        order = row.get("order", "")
        is_client_payment = row.get("is_client_payment", False)
        
        # Skip worker total rows
        if row.get("is_worker_total"):
            continue
        
        # Determine section type for display
        section = "оплата клиентом" if is_client_payment else "основная"
        
        # Full row data for display - filter out zeros and empty values
        row_info = {}
        fields = [
            ("Монтажник", worker),
            ("Секция", section),
            ("Заказ", order),
            ("Выручка итого", row.get("revenue_total", "")),
            ("Выручка от услуг", row.get("revenue_services", "")),
            ("Диагностика", row.get("diagnostic", "")),
            ("Оплата диагностики", row.get("diagnostic_payment", "")),
            ("Выручка (выезд)", row.get("specialist_fee", "")),
            ("Доп. расходы", row.get("additional_expenses", "")),
            ("Сумма оплаты", row.get("service_payment", "")),
            ("Процент", row.get("percent", "")),
            ("Оплата бензина", row.get("fuel_payment", "")),
            ("Транспортные", row.get("transport", "")),
            ("Итого", row.get("total", "")),
            ("Диагностика -50%", row.get("diagnostic_50", ""))
        ]
        
        for key, val in fields:
            if val is not None and val != "" and val != 0 and not (isinstance(val, float) and pd.isna(val)):
                row_info[key] = val
        
        # Alarm 1: service_payment > threshold
        service_payment = row.get("service_payment", 0)
        high_payment_threshold = config.get("alarm_high_payment", 20000)
        if pd.notna(service_payment) and service_payment != "" and float(service_payment) > high_payment_threshold:
            alarms["high_payment"].append({
                "type": "high_payment",
                "message": f"Сумма оплаты > {high_payment_threshold}: {service_payment}",
                "worker": worker,
                "order": order,
                "section": section,
                "row_info": row_info
            })
        
        # Alarm 2: non-standard percent (configurable)
        percent = parse_percent(row.get("percent", 0))
        standard_percents = config.get("standard_percents", [30, 50, 100])
        if percent > 0 and round(percent, 0) not in standard_percents:
            specialist_fee = float(row.get("specialist_fee", 0)) if pd.notna(row.get("specialist_fee")) and row.get("specialist_fee") != "" else 0
            revenue_total = float(row.get("revenue_total", 0)) if pd.notna(row.get("revenue_total")) and row.get("revenue_total") != "" else 0
            total = float(row.get("total", 0)) if pd.notna(row.get("total")) and row.get("total") != "" else 0
            
            # Check if specialist_fee >= 50% of revenue_total
            should_skip = False
            if revenue_total > 0 and specialist_fee >= (revenue_total * 0.5):
                if total <= revenue_total:
                    should_skip = True
            
            if not should_skip:
                alarms["non_standard_percent"].append({
                    "type": "non_standard_percent",
                    "message": f"Нестандартный процент: {percent:.1f}%",
                    "worker": worker,
                    "order": order,
                    "section": section,
                    "row_info": row_info
                })
        
        # Alarm 3: specialist_fee > threshold
        specialist_fee = row.get("specialist_fee", 0)
        high_specialist_threshold = config.get("alarm_high_specialist", 3500)
        if pd.notna(specialist_fee) and specialist_fee != "" and float(specialist_fee) > high_specialist_threshold:
            alarms["high_specialist_fee"].append({
                "type": "high_specialist_fee",
                "message": f"Выручка (выезд) > {high_specialist_threshold}: {specialist_fee}",
                "worker": worker,
                "order": order,
                "section": section,
                "row_info": row_info
            })
        
        # Alarm 4: fuel_payment > warning threshold
        fuel_payment = row.get("fuel_payment", 0)
        if pd.notna(fuel_payment) and fuel_payment != "" and float(fuel_payment) > config.get("fuel_warning", 2000):
            alarms["high_fuel"].append({
                "type": "high_fuel",
                "message": f"Оплата бензина > {config.get('fuel_warning', 2000)}: {fuel_payment}",
                "worker": worker,
                "order": order,
                "section": section,
                "row_info": row_info
            })
    
    return alarms
