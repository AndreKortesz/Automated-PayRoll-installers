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
    "transport_percent_max": 40,
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
    cost = round(cost / 100) * 100
    
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
            
            if is_client_payment_section and (pd.notna(row.iloc[4]) or pd.notna(row.iloc[10])):
                records.append({
                    "worker": current_worker,
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
                    "is_client_payment": True,
                    "is_worker_total": True
                })
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


def generate_alarms(data: List[dict], config: dict) -> List[Dict]:
    """Generate warning alarms for manual review - AFTER calculation"""
    alarms = []
    
    for row in data:
        worker = row.get("worker", "")
        order = row.get("order", "")
        
        # Full row data for display
        row_info = {
            "Монтажник": worker,
            "Заказ": order[:80] + "..." if len(str(order)) > 80 else order,
            "Выручка итого": row.get("revenue_total", ""),
            "Выручка от услуг": row.get("revenue_services", ""),
            "Диагностика": row.get("diagnostic", ""),
            "Оплата диагностики": row.get("diagnostic_payment", ""),
            "Выручка (выезд)": row.get("specialist_fee", ""),
            "Доп. расходы": row.get("additional_expenses", ""),
            "Сумма оплаты": row.get("service_payment", ""),
            "Процент": row.get("percent", ""),
            "Оплата бензина": row.get("fuel_payment", ""),
            "Транспортные": row.get("transport", ""),
            "Итого": row.get("total", ""),
            "Диагностика -50%": row.get("diagnostic_50", "")
        }
        
        # Alarm 1: service_payment > 20000
        service_payment = row.get("service_payment", 0)
        if pd.notna(service_payment) and service_payment != "" and float(service_payment) > 20000:
            alarms.append({
                "type": "high_payment",
                "message": f"⚠️ Сумма оплаты > 20000: {service_payment}",
                "worker": worker,
                "order": order,
                "row_info": row_info
            })
        
        # Alarm 2: non-standard percent (not 30, 50, 100)
        percent = parse_percent(row.get("percent", 0))
        if percent > 0 and round(percent, 0) not in [30, 50, 100]:
            alarms.append({
                "type": "non_standard_percent",
                "message": f"⚠️ Нестандартный процент: {percent:.1f}%",
                "worker": worker,
                "order": order,
                "row_info": row_info
            })
        
        # Alarm 3: specialist_fee > 3500
        specialist_fee = row.get("specialist_fee", 0)
        if pd.notna(specialist_fee) and specialist_fee != "" and float(specialist_fee) > 3500:
            alarms.append({
                "type": "high_specialist_fee",
                "message": f"⚠️ Выручка (выезд) > 3500: {specialist_fee}",
                "worker": worker,
                "order": order,
                "row_info": row_info
            })
        
        # Alarm 4: fuel_payment > 2000
        fuel_payment = row.get("fuel_payment", 0)
        if pd.notna(fuel_payment) and fuel_payment != "" and float(fuel_payment) > config.get("fuel_warning", 2000):
            alarms.append({
                "type": "high_fuel",
                "message": f"⚠️ Оплата бензина > {config.get('fuel_warning', 2000)}: {fuel_payment}",
                "worker": worker,
                "order": order,
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
    
    # 2. Transport - only for montazh over 10k with 20-40% commission
    if revenue_services > config["transport_min_revenue"] and config["transport_percent_min"] <= percent <= config["transport_percent_max"]:
        result["transport"] = config["transport_amount"]
    
    # 3. Diagnostic -50% - only for "оплата клиентом" rows with diagnostic
    if row.get("is_client_payment") and diagnostic > 0:
        result["diagnostic_50"] = diagnostic * config["diagnostic_percent"] / 100
    
    # 4. Total
    result["total"] = service_payment + result["fuel_payment"] + result["transport"]
    
    return result


def create_excel_report(data: List[dict], period: str, config: dict) -> bytes:
    """Create Excel report with proper formatting and formulas"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист_1"
    
    # Styles matching the original format
    header_font = Font(bold=True, size=10)
    header_fill = PatternFill("solid", fgColor="DAEEF3")
    data_font = Font(size=9)
    worker_font = Font(bold=True, size=10)
    total_font = Font(bold=True, size=10)
    border = Border(
        left=Side(style='thin', color='B8B8B8'),
        right=Side(style='thin', color='B8B8B8'),
        top=Side(style='thin', color='B8B8B8'),
        bottom=Side(style='thin', color='B8B8B8')
    )
    
    # Header rows (matching original file format)
    ws['A1'] = ""
    ws['A2'] = "Параметры:"
    ws['C2'] = f"Период: {period}"
    ws['C3'] = f"Процент оплаты диагностики: 0,{config['diagnostic_percent']}"
    ws['C4'] = "Процент выручки от услуг: 0,3"
    
    # Column headers (row 6)
    headers = [
        ("A", "Монтажник", 80),
        ("B", "", 3),
        ("C", "", 3),
        ("D", "", 3),
        ("E", "Выручка итого", 14),
        ("F", "Выручка от услуг", 16),
        ("G", "Диагностика", 12),
        ("H", "Оплата диагностики", 17),
        ("I", "Выручка (выезд) специалиста", 24),
        ("J", "Доп. расходы (Оплата услуг помощников)", 32),
        ("K", "Сумма оплаты от услуг", 20),
        ("L", "Процент от выручки по услугам", 26),
        ("M", "Оплата бензина", 14),
        ("N", "Транспортные", 12),
        ("O", "Итого", 12),
        ("P", "Диагностика -50%", 16)
    ]
    
    for col_letter, header_text, width in headers:
        cell = ws[f"{col_letter}6"]
        cell.value = header_text
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[col_letter].width = width
    
    ws['A7'] = "Заказ, Комментарий"
    ws['A7'].font = data_font
    
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
    
    current_row = 8
    
    for worker in sorted(workers_data.keys()):
        if not worker:
            continue
            
        worker_data = workers_data[worker]
        regular_rows = worker_data["regular"]
        client_rows = worker_data["client_payment"]
        
        # Worker name row with formulas for totals
        worker_name_row = current_row
        ws.cell(row=current_row, column=1, value=worker).font = worker_font
        current_row += 1
        
        # Track row ranges for formulas
        regular_start = current_row
        
        # Regular orders
        for record in regular_rows:
            if record.get("is_worker_total"):
                continue
            
            ws.cell(row=current_row, column=1, value=record.get("order", "")).font = data_font
            
            for col, key in [(5, "revenue_total"), (6, "revenue_services"), (7, "diagnostic"),
                            (8, "diagnostic_payment"), (9, "specialist_fee"), (10, "additional_expenses"),
                            (11, "service_payment")]:
                val = record.get(key, "")
                if val != "" and val != 0 and pd.notna(val):
                    ws.cell(row=current_row, column=col, value=val).font = data_font
            
            # Percent
            ws.cell(row=current_row, column=12, value=record.get("percent", "")).font = data_font
            
            # Calculated columns
            for col, key in [(13, "fuel_payment"), (14, "transport"), (15, "total"), (16, "diagnostic_50")]:
                val = record.get(key, "")
                if val != "" and val != 0:
                    ws.cell(row=current_row, column=col, value=val).font = data_font
            
            current_row += 1
        
        regular_end = current_row - 1
        
        # Add formulas for worker total row (regular)
        if regular_end >= regular_start:
            for col in [5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16]:
                col_letter = get_column_letter(col)
                formula = f"=SUM({col_letter}{regular_start}:{col_letter}{regular_end})"
                ws.cell(row=worker_name_row, column=col, value=formula).font = worker_font
        
        # Client payment section
        if client_rows:
            client_name_row = current_row
            ws.cell(row=current_row, column=1, value=f"{worker} (оплата клиентом)").font = worker_font
            current_row += 1
            
            client_start = current_row
            
            for record in client_rows:
                if record.get("is_worker_total"):
                    continue
                
                ws.cell(row=current_row, column=1, value=record.get("order", "")).font = data_font
                
                for col, key in [(5, "revenue_total"), (6, "revenue_services"), (7, "diagnostic"),
                                (8, "diagnostic_payment"), (9, "specialist_fee"), (10, "additional_expenses"),
                                (11, "service_payment")]:
                    val = record.get(key, "")
                    if val != "" and val != 0 and pd.notna(val):
                        ws.cell(row=current_row, column=col, value=val).font = data_font
                
                ws.cell(row=current_row, column=12, value=record.get("percent", "")).font = data_font
                
                for col, key in [(13, "fuel_payment"), (14, "transport"), (15, "total"), (16, "diagnostic_50")]:
                    val = record.get(key, "")
                    if val != "" and val != 0:
                        ws.cell(row=current_row, column=col, value=val).font = data_font
                
                current_row += 1
            
            client_end = current_row - 1
            
            # Add formulas for client payment total row
            if client_end >= client_start:
                for col in [5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16]:
                    col_letter = get_column_letter(col)
                    formula = f"=SUM({col_letter}{client_start}:{col_letter}{client_end})"
                    ws.cell(row=client_name_row, column=col, value=formula).font = worker_font
        
        # Empty row between workers
        current_row += 1
    
    # Save to bytes
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def create_worker_report(data: List[dict], worker: str, period: str, config: dict) -> bytes:
    """Create individual worker Excel report"""
    worker_normalized = normalize_worker_name(worker.replace(" (оплата клиентом)", ""))
    worker_data = [r for r in data if normalize_worker_name(r.get("worker", "").replace(" (оплата клиентом)", "")) == worker_normalized]
    return create_excel_report(worker_data, period, config)


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
        
        # Get unique workers (normalized)
        workers = list(set([normalize_worker_name(w) for w in combined["worker"].unique() if w and not pd.isna(w)]))
        workers = sorted(workers)
        
        # Get orders for days input
        orders = combined[["worker", "order"]].to_dict("records")
        orders = [o for o in orders if o.get("order") and not str(o.get("order", "")).startswith(("ОБУЧЕНИЕ", "В прошлом"))]
        
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
        
        # Calculate each row
        calculated_data = []
        for row in session["combined"]:
            calc_row = await calculate_row(row, full_config, days_map)
            calculated_data.append(calc_row)
        
        # Add extra rows
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
                    "fuel_payment": "",
                    "transport": "",
                    "diagnostic_50": "",
                    "total": float(extra.get("amount", 0))
                })
        
        # Sort by worker
        calculated_data.sort(key=lambda x: normalize_worker_name(x.get("worker", "")))
        
        # Generate alarms AFTER calculation
        alarms = generate_alarms(calculated_data, full_config)
        
        period = session["period"]
        workers = session["workers"]
        
        # Create ZIP with all files
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            main_report = create_excel_report(calculated_data, period, full_config)
            zf.writestr(f"Общий_отчет {period}.xlsx", main_report)
            
            for worker in workers:
                worker_surname = worker.split()[0] if worker else "Unknown"
                worker_report = create_worker_report(calculated_data, worker, period, full_config)
                zf.writestr(f"{worker_surname} {period}.xlsx", worker_report)
        
        zip_buffer.seek(0)
        
        temp_path = f"/tmp/salary_report_{session_id}.zip"
        with open(temp_path, "wb") as f:
            f.write(zip_buffer.getvalue())
        
        # Store alarms for response
        session_data[session_id]["alarms"] = alarms
        
        return JSONResponse({
            "success": True,
            "download_url": f"/download/{session_id}",
            "alarms": alarms
        })
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/download/{session_id}")
async def download_report(session_id: str):
    """Download generated ZIP file"""
    temp_path = f"/tmp/salary_report_{session_id}.zip"
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    period = session_data.get(session_id, {}).get("period", "report")
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=f"Зарплата_{period}.zip"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
