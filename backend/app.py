"""
Salary Calculation Service for Montazhniki
FastAPI backend for processing Excel files and calculating salaries
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import pandas as pd
import numpy as np
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import httpx
import asyncio
import json
import os
import re
import zipfile
from io import BytesIO
from datetime import datetime
from typing import Optional, Dict, List, Any
import tempfile
import shutil

app = FastAPI(title="Salary Calculator", description="Расчёт зарплаты монтажников")

# Templates and static files
templates = Jinja2Templates(directory="../frontend/templates")

# Create static directory if it doesn't exist (for Railway deployment)
import pathlib
static_dir = pathlib.Path("../frontend/static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="../frontend/static"), name="static")

# Configuration defaults
DEFAULT_CONFIG = {
    "base_address": "Москва, Сходненский тупик 16с4",
    "fuel_coefficient": 7,
    "fuel_max": 3000,
    "fuel_warning": 2000,
    "transport_amount": 1000,
    "transport_min_revenue": 10000,
    "transport_percent_min": 20,
    "transport_percent_max": 50,
    "diagnostic_percent": 50,
    "yandex_api_key": "9c140935-e689-4e9f-ab3a-46473474918e"
}

# Global storage for session data
session_data = {}

# Distance cache to avoid repeated API calls
distance_cache = {}

# Worker name normalization map
WORKER_NAME_MAP = {
    "Романюк Алексей": "Романюк Алексей Юрьевич",
}


def normalize_worker_name(name: str) -> str:
    """Normalize worker name to handle duplicates like 'Романюк Алексей' -> 'Романюк Алексей Юрьевич'"""
    if not name:
        return name
    clean_name = name.replace(" (оплата клиентом)", "").strip()
    normalized = WORKER_NAME_MAP.get(clean_name, clean_name)
    if "(оплата клиентом)" in name:
        return f"{normalized} (оплата клиентом)"
    return normalized


def format_order_short(order_text: str) -> str:
    """Format order text for display: remove 'Заказ клиента' and time, keep code, date and address"""
    if not order_text or pd.isna(order_text):
        return ""
    
    text = str(order_text)
    
    # Skip special rows
    if any(p in text for p in ["ОБУЧЕНИЕ", "В прошлом расчете"]):
        return text
    
    # Pattern: "Заказ клиента КАУТ-001658 от 05.11.2025 23:59:59, адрес"
    # Result: "КАУТ-001658 от 05.11.2025, адрес"
    match = re.search(r'((?:КАУТ|ИБУТ|ТДУТ)-\d+)\s+от\s+(\d{2}\.\d{2}\.\d{4})\s+\d{1,2}:\d{2}:\d{2},?\s*(.*)', text)
    if match:
        code = match.group(1)
        date = match.group(2)
        address = match.group(3).strip()
        # Clean address from \n and other artifacts
        address = re.sub(r'\\n.*', '', address)
        address = re.sub(r'\|.*', '', address)
        return f"{code} от {date}, {address}".strip(', ')
    
    # Fallback: just remove "Заказ клиента" prefix
    text = re.sub(r'^Заказ клиента\s+', '', text)
    return text


def format_order_for_workers(order_text: str) -> str:
    """Format order text for workers: keep code, date, address and comment. Remove 'Заказ клиента' and time"""
    if not order_text or pd.isna(order_text):
        return ""
    
    text = str(order_text)
    
    # Skip special rows
    if any(p in text for p in ["ОБУЧЕНИЕ", "В прошлом расчете"]):
        return text
    
    # Pattern: "Заказ клиента КАУТ-001658 от 05.11.2025 23:59:59, адрес, комментарий"
    # Result: "КАУТ-001658, 05.11.2025, адрес, комментарий"
    match = re.search(r'((?:КАУТ|ИБУТ|ТДУТ)-\d+)\s+от\s+(\d{2}\.\d{2}\.\d{4})\s+\d{1,2}:\d{2}:\d{2},?\s*(.*)', text)
    if match:
        code = match.group(1)
        date = match.group(2)
        address_and_comment = match.group(3).strip()
        # Clean from \n and other artifacts
        address_and_comment = re.sub(r'\\n.*', '', address_and_comment)
        address_and_comment = re.sub(r'\|.*', '', address_and_comment)
        return f"{code}, {date}, {address_and_comment}".strip(', ')
    
    # Fallback: just remove "Заказ клиента" and time
    text = re.sub(r'^Заказ клиента\s+', '', text)
    text = re.sub(r'\s+от\s+', ', ', text)
    # Remove time if present
    text = re.sub(r'\d{1,2}:\d{2}:\d{2},?\s*', '', text)
    return text.strip(', ')


async def geocode_address_yandex(address: str, api_key: str) -> tuple:
    """Get coordinates from Yandex Geocoder API"""
    try:
        async with httpx.AsyncClient() as client:
            url = "https://geocode-maps.yandex.ru/1.x/"
            params = {
                "apikey": api_key,
                "geocode": address,
                "format": "json"
            }
            response = await client.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return None, None
            data = response.json()
            
            pos = data["response"]["GeoObjectCollection"]["featureMember"]
            if pos:
                coords = pos[0]["GeoObject"]["Point"]["pos"].split()
                return float(coords[1]), float(coords[0])  # lat, lon
    except Exception as e:
        pass
    return None, None


async def geocode_address_nominatim(address: str) -> tuple:
    """Get coordinates from Nominatim (OpenStreetMap) - free"""
    try:
        await asyncio.sleep(1)
        async with httpx.AsyncClient() as client:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": address,
                "format": "json",
                "limit": 1
            }
            headers = {"User-Agent": "SalaryCalculator/1.0"}
            response = await client.get(url, params=params, headers=headers, timeout=10)
            if response.status_code != 200:
                return None, None
            data = response.json()
            
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        pass
    return None, None


async def geocode_address(address: str, api_key: str) -> tuple:
    """Get coordinates - try Yandex first, fallback to Nominatim"""
    cache_key = f"geo_{address}"
    if cache_key in distance_cache:
        return distance_cache[cache_key]
    
    lat, lon = await geocode_address_yandex(address, api_key)
    if lat and lon:
        distance_cache[cache_key] = (lat, lon)
        return lat, lon
    
    lat, lon = await geocode_address_nominatim(address)
    if lat and lon:
        distance_cache[cache_key] = (lat, lon)
    return lat, lon


async def get_distance_osrm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Get driving distance in km using OSRM (free)"""
    try:
        async with httpx.AsyncClient() as client:
            url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
            params = {"overview": "false"}
            response = await client.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("code") == "Ok" and data.get("routes"):
                distance_meters = data["routes"][0]["distance"]
                return distance_meters / 1000
    except Exception as e:
        pass
    return 0


def is_moscow_region(address: str) -> bool:
    """Check if address is in Moscow or Moscow Oblast"""
    if not address:
        return False
    addr_lower = address.lower()
    moscow_keywords = [
        "москва", "московская", "мо,", "м.о.", "го ", "г.о.", 
        "мытищи", "химки", "одинцово", "щелково", "люберцы", "балашиха",
        "красногорск", "подольск", "королев", "долгопрудный", "реутов",
        "домодедово", "раменск", "серпухов", "ногинск", "пушкино",
        "коломна", "электросталь", "орехово-зуево", "сергиев посад",
        "наро-фоминск", "дмитров", "клин", "солнечногорск", "истра",
        "волоколамск", "можайск", "руза", "шатура", "егорьевск",
        "воскресенск", "ступино", "кашира", "озеры", "зарайск",
        "коттеджный", "снт", "днп", "кп ", "деревня", "село",
        "поселок", "городской округ", "район"
    ]
    return any(kw in addr_lower for kw in moscow_keywords)


async def calculate_fuel_cost(address: str, config: dict, days: int = 1) -> int:
    """Calculate fuel cost for round trip - only for Moscow and MO"""
    if not address or pd.isna(address):
        return 0
    
    # Only calculate for Moscow and Moscow Oblast
    if not is_moscow_region(address):
        return 0
    
    # Add "Москва" or "Московская область" if not present for better geocoding
    addr_for_geocode = address
    if "москва" not in address.lower() and "московская" not in address.lower():
        addr_for_geocode = f"Московская область, {address}"
    
    base_lat, base_lon = await geocode_address(config["base_address"], config["yandex_api_key"])
    if not base_lat:
        return 0
    
    dest_lat, dest_lon = await geocode_address(addr_for_geocode, config["yandex_api_key"])
    if not dest_lat:
        return 0
    
    distance = await get_distance_osrm(base_lat, base_lon, dest_lat, dest_lon)
    if distance == 0:
        return 0
    
    cost = distance * 2 * config["fuel_coefficient"] * days
    import math
    cost = math.ceil(cost / 100) * 100
    
    return min(cost, config["fuel_max"])


def extract_address_from_order(order_text: str) -> str:
    """Extract address from order text"""
    if not order_text or pd.isna(order_text):
        return ""
    
    text = str(order_text)
    
    skip_patterns = ["ОБУЧЕНИЕ", "обучение", "двойная оплата", "В прошлом расчете"]
    for pattern in skip_patterns:
        if pattern in text:
            return ""
    
    match = re.search(r'\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2},\s*(.+?)(?:\n|$)', text)
    if match:
        addr = match.group(1).strip()
        addr = re.sub(r'\\n.*', '', addr)
        addr = re.sub(r'\|.*', '', addr)
        return addr.strip()
    
    match = re.search(r'\d:\d{2}:\d{2},\s*(.+?)(?:\n|$)', text)
    if match:
        addr = match.group(1).strip()
        addr = re.sub(r'\\n.*', '', addr)
        addr = re.sub(r'\|.*', '', addr)
        return addr.strip()
    
    return ""


def parse_percent(value) -> float:
    """Parse percent value from string like '30,00 %' or number"""
    if pd.isna(value):
        return 0
    if isinstance(value, (int, float)):
        return float(value) * 100 if value <= 1 else float(value)
    
    text = str(value).replace(',', '.').replace('%', '').replace(' ', '')
    try:
        return float(text)
    except:
        return 0


def extract_period(df: pd.DataFrame) -> str:
    """Extract period from dataframe header"""
    for i in range(min(5, len(df))):
        for col in df.columns:
            val = df.iloc[i][col]
            if pd.notna(val) and 'Период:' in str(val):
                match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})', str(val))
                if match:
                    d1, m1, y1, d2, m2, y2 = match.groups()
                    return f"{d1}-{d2}.{m1}.{y2[2:]}"
    return "период"


def parse_excel_file(file_bytes: bytes, is_over_10k: bool) -> pd.DataFrame:
    """Parse Excel file from 1C and extract data"""
    df = pd.read_excel(BytesIO(file_bytes), header=None)
    
    header_row = None
    for i in range(min(10, len(df))):
        first_val = str(df.iloc[i].iloc[0]) if pd.notna(df.iloc[i].iloc[0]) else ""
        if first_val.strip() == "Монтажник":
            header_row = i
            break
    
    if header_row is None:
        raise ValueError("Не найден заголовок с 'Монтажник'")
    
    records = []
    current_worker = None
    is_client_payment_section = False
    
    for i in range(header_row + 2, len(df)):
        row = df.iloc[i]
        first_col = row.iloc[0] if pd.notna(row.iloc[0]) else ""
        first_col_str = str(first_col).strip()
        
        if not first_col_str or first_col_str == "Итого" or first_col_str == "Заказ, Комментарий":
            continue
        
        is_order = (first_col_str.startswith("Заказ") or 
                   "КАУТ-" in first_col_str or 
                   "ИБУТ-" in first_col_str or 
                   "ТДУТ-" in first_col_str or
                   "В прошлом расчете" in first_col_str)
        
        if not is_order:
            is_client_payment_section = "(оплата клиентом)" in first_col_str
            worker_name = first_col_str.replace(" (оплата клиентом)", "").strip()
            
            if worker_name == "Монтажник":
                continue
            
            # Normalize worker name
            worker_name = normalize_worker_name(worker_name)
            current_worker = worker_name
            
            # "(оплата клиентом)" строка - это заголовок секции, не записываем её как данные
            continue
        else:
            if current_worker:
                records.append({
                    "worker": normalize_worker_name(current_worker),
                    "order": first_col_str,
                    "revenue_total": row.iloc[4] if pd.notna(row.iloc[4]) else 0,
                    "revenue_services": row.iloc[5] if pd.notna(row.iloc[5]) else 0,
                    "diagnostic": row.iloc[6] if pd.notna(row.iloc[6]) else 0,
                    "diagnostic_payment": row.iloc[7] if pd.notna(row.iloc[7]) else 0,
                    "specialist_fee": row.iloc[8] if pd.notna(row.iloc[8]) else 0,
                    "additional_expenses": row.iloc[9] if pd.notna(row.iloc[9]) else 0,
                    "service_payment": row.iloc[10] if pd.notna(row.iloc[10]) else 0,
                    "percent": row.iloc[11],
                    "is_over_10k": is_over_10k,
                    "is_client_payment": is_client_payment_section,
                    "is_worker_total": False
                })
    
    return pd.DataFrame(records)


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
        
        # Alarm 1: service_payment > 20000
        service_payment = row.get("service_payment", 0)
        if pd.notna(service_payment) and service_payment != "" and float(service_payment) > 20000:
            alarms["high_payment"].append({
                "type": "high_payment",
                "message": f"Сумма оплаты > 20000: {service_payment}",
                "worker": worker,
                "order": order,
                "section": section,
                "row_info": row_info
            })
        
        # Alarm 2: non-standard percent (not 30, 50, 100)
        percent = parse_percent(row.get("percent", 0))
        if percent > 0 and round(percent, 0) not in [30, 50, 100]:
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
        
        # Alarm 3: specialist_fee > 3500
        specialist_fee = row.get("specialist_fee", 0)
        if pd.notna(specialist_fee) and specialist_fee != "" and float(specialist_fee) > 3500:
            alarms["high_specialist_fee"].append({
                "type": "high_specialist_fee",
                "message": f"Выручка (выезд) > 3500: {specialist_fee}",
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
    
    # 1. Fuel payment - only if specialist_fee is empty and has real address in Moscow/MO
    if specialist_fee == 0 and address:
        days = days_map.get(order, 1)
        result["fuel_payment"] = await calculate_fuel_cost(address, config, days)
    
    # 2. Transport - only for revenue > 10k with percent < 50%
    if revenue_services > config["transport_min_revenue"] and percent < 50:
        result["transport"] = config["transport_amount"]
    
    # 3. Diagnostic -50% - only for "оплата клиентом" rows with diagnostic
    if row.get("is_client_payment") and diagnostic > 0:
        result["diagnostic_50"] = diagnostic * config["diagnostic_percent"] / 100
    
    # 4. Total = service_payment + fuel + transport
    result["total"] = service_payment + result["fuel_payment"] + result["transport"]
    
    return result


def create_excel_report(data: List[dict], period: str, config: dict, for_workers: bool = False) -> bytes:
    """Create Excel report with proper formatting and formulas
    
    Args:
        for_workers: If True, creates simplified version for workers with hidden columns
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист_1"
    
    # Colors
    HEADER_BLUE = "4574A0"
    ROW_LIGHT_BLUE = "C6E2FF"
    DIAGNOSTIC_RED = "FF0000"
    YELLOW_TOTAL = "FFFF00"
    
    # Border style
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Styles - Arial font
    header_font = Font(name='Arial', bold=True, size=9, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=HEADER_BLUE)
    data_font = Font(name='Arial', size=9)
    param_font = Font(name='Arial', size=9)
    worker_font = Font(name='Arial', bold=True, size=9)
    worker_fill = PatternFill("solid", fgColor=ROW_LIGHT_BLUE)
    diagnostic_header_fill = PatternFill("solid", fgColor=DIAGNOSTIC_RED)
    yellow_fill = PatternFill("solid", fgColor=YELLOW_TOTAL)
    
    alignment_wrap = Alignment(horizontal='left', vertical='top', wrap_text=True)
    alignment_center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    
    # Column widths - removed B,C,D columns
    # New mapping: A=Заказ, B=Выручка итого, C=Выручка от услуг, etc.
    column_widths = {
        'A': 55,
        'B': 12, 'C': 13, 'D': 12, 'E': 13,
        'F': 13, 'G': 15, 'H': 15, 'I': 14,
        'J': 12, 'K': 12, 'L': 12, 'M': 14
    }
    
    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width
    
    # Hide columns for workers version: B (Выручка итого), C (Выручка от услуг), G (Доп. расходы), H (Сумма оплаты), I (Процент)
    if for_workers:
        ws.column_dimensions['B'].hidden = True
        ws.column_dimensions['C'].hidden = True
        ws.column_dimensions['G'].hidden = True
        ws.column_dimensions['H'].hidden = True
        ws.column_dimensions['I'].hidden = True
    
    # Parameter rows (1-3)
    ws['A1'] = "Параметры:"
    ws['A1'].font = param_font
    ws['A2'] = f"Период: {period}"
    ws['A2'].font = param_font
    ws['A3'] = f"Процент оплаты диагностики: {config['diagnostic_percent']}%"
    ws['A3'].font = param_font
    
    # Column headers (row 5) - without B,C,D columns
    headers = [
        ("A", "Монтажник"),
        ("B", "Выручка итого"), ("C", "Выручка от услуг"),
        ("D", "Диагностика"), ("E", "Оплата диагностики"),
        ("F", "Выручка (выезд) специалиста"),
        ("G", "Доп. расходы (Оплата услуг помощников)"),
        ("H", "Сумма оплаты от услуг"),
        ("I", "Процент от выручки по услугам"),
        ("J", "Оплата бензина"), ("K", "Транспортные"),
        ("L", "Итого"), ("M", "Диагностика -50%")
    ]
    
    for col_letter, header_text in headers:
        cell = ws[f"{col_letter}5"]
        cell.value = header_text
        cell.font = header_font
        cell.fill = header_fill if col_letter != "M" else diagnostic_header_fill
        cell.alignment = alignment_center
        cell.border = thin_border
    
    ws.row_dimensions[5].height = 45  # Increased height for headers
    
    # Group data by worker
    workers_data = {}
    for record in data:
        worker = record.get("worker", "").replace(" (оплата клиентом)", "")
        if worker not in workers_data:
            workers_data[worker] = {"regular": [], "client_payment": []}
        
        if record.get("is_client_payment"):
            workers_data[worker]["client_payment"].append(record)
        else:
            workers_data[worker]["regular"].append(record)
    
    current_row = 6
    
    def to_int(val):
        """Convert value to integer, return empty string if invalid"""
        if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
            return ""
        try:
            return int(round(float(val)))
        except:
            return ""
    
    # New column mapping (old -> new after removing B,C,D)
    # Old: A=1, E=5, F=6, G=7, H=8, I=9, J=10, K=11, L=12, M=13, N=14, O=15, P=16
    # New: A=1, B=2, C=3, D=4, E=5, F=6, G=7, H=8, I=9, J=10, K=11, L=12, M=13
    
    for worker in sorted(workers_data.keys()):
        if not worker:
            continue
            
        worker_data = workers_data[worker]
        regular_rows = worker_data["regular"]
        client_rows = worker_data["client_payment"]
        
        # Worker name row
        worker_name_row = current_row
        cell = ws.cell(row=current_row, column=1, value=worker)
        cell.font = worker_font
        cell.fill = worker_fill
        cell.alignment = alignment_wrap
        cell.border = thin_border
        
        for col in range(2, 14):
            c = ws.cell(row=current_row, column=col)
            c.fill = worker_fill
            c.border = thin_border
        
        ws.row_dimensions[current_row].height = 18
        current_row += 1
        
        regular_start = current_row
        
        # Regular orders
        for record in regular_rows:
            if record.get("is_worker_total"):
                continue
            
            # Format order text based on mode
            order_text = record.get("order", "")
            if for_workers:
                order_text = format_order_for_workers(order_text)
            
            cell = ws.cell(row=current_row, column=1, value=order_text)
            cell.font = data_font
            cell.alignment = alignment_wrap
            cell.border = thin_border
            
            # Data columns (new positions)
            for col, key in [(2, "revenue_total"), (3, "revenue_services"), (4, "diagnostic"),
                            (5, "diagnostic_payment"), (6, "specialist_fee"), (7, "additional_expenses"),
                            (8, "service_payment")]:
                val = to_int(record.get(key, ""))
                c = ws.cell(row=current_row, column=col, value=val if val != "" else None)
                c.font = data_font
                c.border = thin_border
            
            # Percent - keep as is (not integer) - column I (9)
            c = ws.cell(row=current_row, column=9, value=record.get("percent", ""))
            c.font = data_font
            c.border = thin_border
            
            fuel = to_int(record.get("fuel_payment", 0))
            transport = to_int(record.get("transport", 0))
            
            c = ws.cell(row=current_row, column=10, value=fuel if fuel else None)  # J
            c.font = data_font
            c.border = thin_border
            
            c = ws.cell(row=current_row, column=11, value=transport if transport else None)  # K
            c.font = data_font
            c.border = thin_border
            
            # Итого - column L (12)
            # For extra rows (additional payments), output value directly
            # For regular rows, use formula =H+J+K
            if record.get("is_extra_row"):
                total_val = to_int(record.get("total", 0))
                c = ws.cell(row=current_row, column=12, value=total_val if total_val else None)
            else:
                c = ws.cell(row=current_row, column=12, value=f"=H{current_row}+J{current_row}+K{current_row}")
            c.font = data_font
            c.border = thin_border
            
            # Diagnostic -50% column M (13)
            c = ws.cell(row=current_row, column=13)
            c.border = thin_border
            
            current_row += 1
        
        regular_end = current_row - 1
        
        # Formulas for worker total row (fuel J, transport K sums)
        if regular_end >= regular_start:
            for col in [10, 11]:  # J, K
                col_letter = get_column_letter(col)
                formula = f"=SUM({col_letter}{regular_start}:{col_letter}{regular_end})"
                c = ws.cell(row=worker_name_row, column=col, value=formula)
                c.font = worker_font
        
        # Client payment section
        client_name_row = None
        if client_rows:
            client_name_row = current_row
            cell = ws.cell(row=current_row, column=1, value=f"{worker} (оплата клиентом)")
            cell.font = worker_font
            cell.fill = worker_fill
            cell.alignment = alignment_wrap
            cell.border = thin_border
            
            for col in range(2, 14):
                c = ws.cell(row=current_row, column=col)
                c.fill = worker_fill
                c.border = thin_border
            
            ws.row_dimensions[current_row].height = 18
            current_row += 1
            
            client_start = current_row
            
            for record in client_rows:
                if record.get("is_worker_total"):
                    continue
                
                # Format order text based on mode
                order_text = record.get("order", "")
                if for_workers:
                    order_text = format_order_for_workers(order_text)
                
                cell = ws.cell(row=current_row, column=1, value=order_text)
                cell.font = data_font
                cell.alignment = alignment_wrap
                cell.border = thin_border
                
                for col, key in [(2, "revenue_total"), (3, "revenue_services"), (4, "diagnostic"),
                                (5, "diagnostic_payment"), (6, "specialist_fee"), (7, "additional_expenses"),
                                (8, "service_payment")]:
                    val = to_int(record.get(key, ""))
                    c = ws.cell(row=current_row, column=col, value=val if val != "" else None)
                    c.font = data_font
                    c.border = thin_border
                
                c = ws.cell(row=current_row, column=9, value=record.get("percent", ""))
                c.font = data_font
                c.border = thin_border
                
                # Columns J, K empty for client payment
                for col in [10, 11]:
                    ws.cell(row=current_row, column=col).border = thin_border
                
                # Итого = just service payment (H)
                c = ws.cell(row=current_row, column=12, value=f"=H{current_row}")
                c.font = data_font
                c.border = thin_border
                
                diag_50 = to_int(record.get("diagnostic_50", 0))
                c = ws.cell(row=current_row, column=13, value=diag_50 if diag_50 else None)
                c.font = data_font
                c.border = thin_border
                
                current_row += 1
            
            client_end = current_row - 1
            
            # Client section totals
            if client_end >= client_start:
                ws.cell(row=client_name_row, column=12, value=f"=SUM(L{client_start}:L{client_end})").font = worker_font
                ws.cell(row=client_name_row, column=13, value=f"=SUM(M{client_start}:M{client_end})").font = worker_font
        
        # Main worker row Итого formula - subtract diagnostic -50% from client section
        if regular_end >= regular_start:
            if client_name_row:
                # Has client section - subtract M (diagnostic -50%) from client row
                formula = f"=SUM(L{regular_start}:L{regular_end})-M{client_name_row}"
            else:
                formula = f"=SUM(L{regular_start}:L{regular_end})"
            c = ws.cell(row=worker_name_row, column=12, value=formula)
            c.font = worker_font
            c.fill = yellow_fill
            c.border = thin_border
        else:
            if client_name_row:
                formula = f"=-M{client_name_row}"
                c = ws.cell(row=worker_name_row, column=12, value=formula)
            else:
                c = ws.cell(row=worker_name_row, column=12, value=0)
            c.font = worker_font
            c.fill = yellow_fill
            c.border = thin_border
        
        current_row += 1
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def create_worker_report(data: List[dict], worker: str, period: str, config: dict, for_workers: bool = False) -> bytes:
    """Create individual worker Excel report"""
    worker_normalized = normalize_worker_name(worker.replace(" (оплата клиентом)", ""))
    worker_data = [r for r in data if normalize_worker_name(r.get("worker", "").replace(" (оплата клиентом)", "")) == worker_normalized]
    return create_excel_report(worker_data, period, config, for_workers=for_workers)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "config": DEFAULT_CONFIG})


@app.post("/upload")
async def upload_files(
    request: Request,
    file_under_10k: UploadFile = File(...),
    file_over_10k: UploadFile = File(...)
):
    """Upload and parse Excel files"""
    try:
        content_under = await file_under_10k.read()
        content_over = await file_over_10k.read()
        
        df_under = parse_excel_file(content_under, is_over_10k=False)
        df_over = parse_excel_file(content_over, is_over_10k=True)
        
        period_df = pd.read_excel(BytesIO(content_under), header=None)
        period = extract_period(period_df)
        
        combined = pd.concat([df_over, df_under], ignore_index=True)
        
        workers = list(set([normalize_worker_name(w).replace(" (оплата клиентом)", "") 
                           for w in combined["worker"].unique() if w and not pd.isna(w)]))
        workers = sorted(workers)
        
        orders = []
        for _, row in combined.iterrows():
            order = row.get("order", "")
            worker = row.get("worker", "")
            is_client = row.get("is_client_payment", False)
            
            # Get revenue_services and percent for transport check
            revenue_services = row.get("revenue_services", 0)
            revenue_services = float(revenue_services) if pd.notna(revenue_services) and revenue_services != "" else 0
            
            percent_str = str(row.get("percent", "0%")).replace("%", "").replace(",", ".").strip()
            try:
                percent = float(percent_str) if percent_str else 0
            except:
                percent = 0
            
            # Check if transport will be applied (revenue > 10k and percent < 50%)
            has_transport = revenue_services > DEFAULT_CONFIG["transport_min_revenue"] and percent < 50
            
            if order and not str(order).startswith(("ОБУЧЕНИЕ", "В прошлом")):
                orders.append({
                    "worker": worker.replace(" (оплата клиентом)", ""),
                    "order": order,
                    "order_short": format_order_short(order),
                    "is_client_payment": is_client,
                    "has_transport": has_transport
                })
        
        orders.sort(key=lambda x: x["worker"])
        
        session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        session_data[session_id] = {
            "combined": combined.to_dict("records"),
            "period": period,
            "workers": workers
        }
        
        return JSONResponse({
            "success": True,
            "session_id": session_id,
            "period": period,
            "workers": workers,
            "orders": orders,
            "total_records": len(combined)
        })
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/calculate")
async def calculate_salaries(
    session_id: str = Form(...),
    config_json: str = Form(...),
    days_json: str = Form(...),
    extra_rows_json: str = Form(...)
):
    """Calculate all salaries and generate files"""
    try:
        if session_id not in session_data:
            raise HTTPException(status_code=400, detail="Session expired")
        
        session = session_data[session_id]
        config = json.loads(config_json)
        days_map = json.loads(days_json)
        extra_rows = json.loads(extra_rows_json)
        
        full_config = {**DEFAULT_CONFIG, **config}
        
        calculated_data = []
        for row in session["combined"]:
            calc_row = await calculate_row(row, full_config, days_map)
            calculated_data.append(calc_row)
        
        for worker, rows in extra_rows.items():
            for extra in rows:
                calculated_data.append({
                    "worker": normalize_worker_name(worker),
                    "order": extra.get("description", ""),
                    "revenue_total": "",
                    "revenue_services": "",
                    "diagnostic": "",
                    "diagnostic_payment": "",
                    "specialist_fee": "",
                    "additional_expenses": "",
                    "service_payment": "",
                    "percent": "",
                    "is_over_10k": False,
                    "is_client_payment": False,
                    "is_worker_total": False,
                    "is_extra_row": True,  # Flag for extra rows
                    "fuel_payment": "",
                    "transport": "",
                    "diagnostic_50": "",
                    "total": float(extra.get("amount", 0))
                })
        
        calculated_data.sort(key=lambda x: normalize_worker_name(x.get("worker", "")).replace(" (оплата клиентом)", ""))
        
        alarms = generate_alarms(calculated_data, full_config)
        
        period = session["period"]
        workers = session["workers"]
        
        # Archive 1: Full reports (for accounting)
        zip_full = BytesIO()
        with zipfile.ZipFile(zip_full, "w", zipfile.ZIP_DEFLATED) as zf:
            main_report = create_excel_report(calculated_data, period, full_config, for_workers=False)
            zf.writestr(f"Общий_отчет {period}.xlsx", main_report)
            
            for worker in workers:
                worker_surname = worker.split()[0] if worker else "Unknown"
                worker_report = create_worker_report(calculated_data, worker, period, full_config, for_workers=False)
                zf.writestr(f"{worker_surname} {period}.xlsx", worker_report)
        
        zip_full.seek(0)
        
        # Archive 2: Simplified reports (for workers - hidden columns)
        zip_workers = BytesIO()
        with zipfile.ZipFile(zip_workers, "w", zipfile.ZIP_DEFLATED) as zf:
            main_report = create_excel_report(calculated_data, period, full_config, for_workers=True)
            zf.writestr(f"Общий_отчет {period}.xlsx", main_report)
            
            for worker in workers:
                worker_surname = worker.split()[0] if worker else "Unknown"
                worker_report = create_worker_report(calculated_data, worker, period, full_config, for_workers=True)
                zf.writestr(f"{worker_surname} {period}.xlsx", worker_report)
        
        zip_workers.seek(0)
        
        # Save both archives
        temp_path_full = f"/tmp/salary_report_{session_id}_full.zip"
        temp_path_workers = f"/tmp/salary_report_{session_id}_workers.zip"
        
        with open(temp_path_full, "wb") as f:
            f.write(zip_full.getvalue())
        
        with open(temp_path_workers, "wb") as f:
            f.write(zip_workers.getvalue())
        
        session_data[session_id]["alarms"] = alarms
        
        return JSONResponse({
            "success": True,
            "download_url_full": f"/download/{session_id}/full",
            "download_url_workers": f"/download/{session_id}/workers",
            "alarms": alarms
        })
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/download/{session_id}/{archive_type}")
async def download_report(session_id: str, archive_type: str):
    """Download generated ZIP file
    
    Args:
        archive_type: 'full' for accounting reports, 'workers' for simplified reports
    """
    if archive_type not in ["full", "workers"]:
        raise HTTPException(status_code=400, detail="Invalid archive type")
    
    temp_path = f"/tmp/salary_report_{session_id}_{archive_type}.zip"
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    period = session_data.get(session_id, {}).get("period", "report")
    
    if archive_type == "full":
        filename = f"Зарплата_{period}.zip"
    else:
        filename = f"Для_монтажников_{period}.zip"
    
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=filename
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
