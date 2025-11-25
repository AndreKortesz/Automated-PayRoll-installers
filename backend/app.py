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
from openpyxl.utils.dataframe import dataframe_to_rows
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
app.mount("/static", StaticFiles(directory="../frontend/static"), name="static")

# Configuration defaults
DEFAULT_CONFIG = {
    "base_address": "Москва, Сходненский тупик 16с4",
    "fuel_coefficient": 7,
    "fuel_max": 3000,
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
        pass  # Silent fail, will try fallback
    return None, None


async def geocode_address_nominatim(address: str) -> tuple:
    """Get coordinates from Nominatim (OpenStreetMap) - free"""
    try:
        # Add delay to respect rate limits
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
        pass  # Silent fail
    return None, None


async def geocode_address(address: str, api_key: str) -> tuple:
    """Get coordinates - try Yandex first, fallback to Nominatim"""
    # Check cache
    cache_key = f"geo_{address}"
    if cache_key in distance_cache:
        return distance_cache[cache_key]
    
    # Try Yandex first
    lat, lon = await geocode_address_yandex(address, api_key)
    if lat and lon:
        distance_cache[cache_key] = (lat, lon)
        return lat, lon
    
    # Fallback to Nominatim (free)
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
                return distance_meters / 1000  # km
    except Exception as e:
        print(f"OSRM error: {e}")
    return 0


async def calculate_fuel_cost(address: str, config: dict, days: int = 1) -> int:
    """Calculate fuel cost for round trip"""
    if not address or pd.isna(address):
        return 0
    
    base_lat, base_lon = await geocode_address(config["base_address"], config["yandex_api_key"])
    if not base_lat:
        return 0
    
    dest_lat, dest_lon = await geocode_address(address, config["yandex_api_key"])
    if not dest_lat:
        return 0
    
    distance = await get_distance_osrm(base_lat, base_lon, dest_lat, dest_lon)
    if distance == 0:
        return 0
    
    # Round trip * coefficient * days, rounded to 100
    cost = distance * 2 * config["fuel_coefficient"] * days
    cost = round(cost / 100) * 100
    
    # Max limit
    return min(cost, config["fuel_max"])


def extract_address_from_order(order_text: str) -> str:
    """Extract address from order text"""
    if not order_text or pd.isna(order_text):
        return ""
    
    # Pattern: after date/time, before \n or end
    # Example: "Заказ клиента КАУТ-001560 от 27.10.2025 14:17:38, Ростовская набережная 1, магазин Интерьер Маркет"
    
    text = str(order_text)
    
    # Skip non-address entries
    skip_patterns = ["ОБУЧЕНИЕ", "обучение", "двойная оплата", "В прошлом расчете"]
    for pattern in skip_patterns:
        if pattern in text:
            return ""
    
    # Try to extract address after datetime pattern
    match = re.search(r'\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2},\s*(.+?)(?:\n|$)', text)
    if match:
        addr = match.group(1).strip()
        # Clean up address
        addr = re.sub(r'\\n.*', '', addr)  # Remove everything after \n
        addr = re.sub(r'\|.*', '', addr)   # Remove coordinates
        return addr.strip()
    
    # Alternative: after "0:00:00," or similar
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
                # "Период: 01.11.2025 - 15.11.2025"
                match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})', str(val))
                if match:
                    d1, m1, y1, d2, m2, y2 = match.groups()
                    return f"{d1}-{d2}.{m1}.{y2[2:]}"
    return "период"


def parse_excel_file(file_bytes: bytes, is_over_10k: bool) -> pd.DataFrame:
    """Parse Excel file from 1C and extract data"""
    df = pd.read_excel(BytesIO(file_bytes), header=None)
    
    # Find header row (contains "Монтажник" as exact cell value, not "Заказ, Комментарий")
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
    
    for i in range(header_row + 2, len(df)):  # Skip header rows
        row = df.iloc[i]
        first_col = row.iloc[0] if pd.notna(row.iloc[0]) else ""
        first_col_str = str(first_col).strip()
        
        # Skip empty rows, "Итого", and header-like rows
        if not first_col_str or first_col_str == "Итого" or first_col_str == "Заказ, Комментарий":
            continue
        
        # Check if this is a worker name (not an order)
        is_order = (first_col_str.startswith("Заказ") or 
                   "КАУТ-" in first_col_str or 
                   "ИБУТ-" in first_col_str or 
                   "ТДУТ-" in first_col_str or
                   "В прошлом расчете" in first_col_str)
        
        if not is_order:
            # This is a worker name row
            is_client_payment_section = "(оплата клиентом)" in first_col_str
            worker_name = first_col_str.replace(" (оплата клиентом)", "").strip()
            
            # Skip if this is the header row value
            if worker_name == "Монтажник":
                continue
                
            current_worker = worker_name
            
            # If this is "оплата клиентом" section header with totals, add it
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
            # This is an order row or correction row
            if current_worker:
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
                    "is_client_payment": is_client_payment_section,
                    "is_worker_total": False
                })
    
    return pd.DataFrame(records)


def generate_alarms(df: pd.DataFrame) -> List[Dict]:
    """Generate warning alarms for manual review"""
    alarms = []
    
    for idx, row in df.iterrows():
        # Alarm 1: service_payment > 20000
        service_payment = row.get("service_payment", 0)
        if pd.notna(service_payment) and float(service_payment) > 20000:
            alarms.append({
                "type": "high_payment",
                "message": f"⚠️ Сумма оплаты > 20000: {service_payment}",
                "worker": row.get("worker", ""),
                "order": row.get("order", ""),
                "row_data": row.to_dict()
            })
        
        # Alarm 2: non-standard percent (not 30, 50, 100)
        percent = parse_percent(row.get("percent", 0))
        if percent > 0 and percent not in [30, 50, 100]:
            alarms.append({
                "type": "non_standard_percent",
                "message": f"⚠️ Нестандартный процент: {percent}%",
                "worker": row.get("worker", ""),
                "order": row.get("order", ""),
                "row_data": row.to_dict()
            })
        
        # Alarm 3: specialist_fee > 3500
        specialist_fee = row.get("specialist_fee", 0)
        if pd.notna(specialist_fee) and float(specialist_fee) > 3500:
            alarms.append({
                "type": "high_specialist_fee",
                "message": f"⚠️ Выручка (выезд) > 3500: {specialist_fee}",
                "worker": row.get("worker", ""),
                "order": row.get("order", ""),
                "row_data": row.to_dict()
            })
    
    return alarms


async def calculate_row(row: dict, config: dict, days_map: dict) -> dict:
    """Calculate additional columns for a row"""
    result = row.copy()
    
    # Initialize new columns
    result["fuel_payment"] = 0
    result["transport"] = 0
    result["diagnostic_50"] = 0
    result["total"] = 0
    
    # Skip worker total rows and correction rows
    if row.get("is_worker_total") or "В прошлом расчете" in str(row.get("order", "")):
        service_payment = float(row.get("service_payment", 0)) if pd.notna(row.get("service_payment")) else 0
        result["total"] = service_payment
        return result
    
    order = str(row.get("order", ""))
    address = extract_address_from_order(order)
    
    specialist_fee = row.get("specialist_fee", 0)
    specialist_fee = float(specialist_fee) if pd.notna(specialist_fee) else 0
    
    revenue_services = row.get("revenue_services", 0)
    revenue_services = float(revenue_services) if pd.notna(revenue_services) else 0
    
    percent = parse_percent(row.get("percent", 0))
    
    service_payment = row.get("service_payment", 0)
    service_payment = float(service_payment) if pd.notna(service_payment) else 0
    
    diagnostic = row.get("diagnostic", 0)
    diagnostic = float(diagnostic) if pd.notna(diagnostic) else 0
    
    # 1. Fuel payment - only if specialist_fee is empty and has real address
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
    """Create Excel report with all formatting"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист_1"
    
    # Styles
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DAEEF3")
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Header rows
    ws['A1'] = ""
    ws['A2'] = "Параметры:"
    ws['C2'] = f"Период: {period.replace('-', '.').replace('.', '.')} - ..."  # Will be formatted properly
    ws['C3'] = f"Процент оплаты диагностики: 0,{config['diagnostic_percent']}"
    ws['C4'] = "Процент выручки от услуг: 0,3"
    
    # Column headers (row 6)
    headers = [
        "Монтажник", "", "", "", "Выручка итого", "Выручка от услуг", 
        "Диагностика", "Оплата диагностики", "Выручка (выезд) специалиста",
        "Доп. расходы (Оплата услуг помощников)", "Сумма оплаты от услуг",
        "Процент от выручки по услугам", "Оплата бензина", "Транспортные",
        "Итого", "Диагностика -50%"
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
    
    ws.cell(row=7, column=1, value="Заказ, Комментарий")
    
    # Data rows
    current_row = 8
    current_worker = None
    worker_start_row = None
    
    for record in data:
        worker = record.get("worker", "")
        
        # New worker section
        if worker != current_worker:
            if current_worker is not None:
                current_row += 1  # Empty row between workers
            
            current_worker = worker
            worker_start_row = current_row
            
            # Worker name row
            ws.cell(row=current_row, column=1, value=worker)
            ws.cell(row=current_row, column=1).font = Font(bold=True)
            
            # Worker totals will be filled later
            current_row += 1
        
        # Order row
        ws.cell(row=current_row, column=1, value=record.get("order", ""))
        ws.cell(row=current_row, column=5, value=record.get("revenue_total", ""))
        ws.cell(row=current_row, column=6, value=record.get("revenue_services", ""))
        ws.cell(row=current_row, column=7, value=record.get("diagnostic", "") if record.get("diagnostic") else "")
        ws.cell(row=current_row, column=8, value=record.get("diagnostic_payment", "") if record.get("diagnostic_payment") else "")
        ws.cell(row=current_row, column=9, value=record.get("specialist_fee", "") if record.get("specialist_fee") else "")
        ws.cell(row=current_row, column=10, value=record.get("additional_expenses", "") if record.get("additional_expenses") else "")
        ws.cell(row=current_row, column=11, value=record.get("service_payment", ""))
        ws.cell(row=current_row, column=12, value=record.get("percent", ""))
        ws.cell(row=current_row, column=13, value=record.get("fuel_payment", "") if record.get("fuel_payment") else "")
        ws.cell(row=current_row, column=14, value=record.get("transport", "") if record.get("transport") else "")
        ws.cell(row=current_row, column=15, value=record.get("total", ""))
        ws.cell(row=current_row, column=16, value=record.get("diagnostic_50", "") if record.get("diagnostic_50") else "")
        
        current_row += 1
    
    # Column widths
    ws.column_dimensions['A'].width = 80
    ws.column_dimensions['E'].width = 15
    ws.column_dimensions['F'].width = 18
    ws.column_dimensions['G'].width = 12
    ws.column_dimensions['H'].width = 18
    ws.column_dimensions['I'].width = 25
    ws.column_dimensions['J'].width = 35
    ws.column_dimensions['K'].width = 20
    ws.column_dimensions['L'].width = 28
    ws.column_dimensions['M'].width = 15
    ws.column_dimensions['N'].width = 14
    ws.column_dimensions['O'].width = 12
    ws.column_dimensions['P'].width = 18
    
    # Save to bytes
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def create_worker_report(data: List[dict], worker: str, period: str, config: dict) -> bytes:
    """Create individual worker Excel report"""
    worker_data = [r for r in data if r.get("worker", "").replace(" (оплата клиентом)", "") == worker.replace(" (оплата клиентом)", "")]
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
        # Read files
        content_under = await file_under_10k.read()
        content_over = await file_over_10k.read()
        
        # Parse files
        df_under = parse_excel_file(content_under, is_over_10k=False)
        df_over = parse_excel_file(content_over, is_over_10k=True)
        
        # Extract period
        period_df = pd.read_excel(BytesIO(content_under), header=None)
        period = extract_period(period_df)
        
        # Combine data
        combined = pd.concat([df_over, df_under], ignore_index=True)
        
        # Generate alarms
        alarms = generate_alarms(combined)
        
        # Get unique workers
        workers = combined["worker"].unique().tolist()
        workers = [w for w in workers if w and not pd.isna(w)]
        
        # Get orders for days input
        orders = combined[["worker", "order"]].to_dict("records")
        orders = [o for o in orders if o.get("order") and not str(o.get("order", "")).startswith(("ОБУЧЕНИЕ", "В прошлом"))]
        
        # Store in session
        session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        session_data[session_id] = {
            "combined": combined.to_dict("records"),
            "period": period,
            "workers": workers,
            "alarms": alarms
        }
        
        return JSONResponse({
            "success": True,
            "session_id": session_id,
            "period": period,
            "workers": workers,
            "orders": orders,
            "alarms": alarms,
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
        
        # Merge config with defaults
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
                    "worker": worker,
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
        calculated_data.sort(key=lambda x: x.get("worker", ""))
        
        period = session["period"]
        workers = session["workers"]
        
        # Create ZIP with all files
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Main report
            main_report = create_excel_report(calculated_data, period, full_config)
            zf.writestr(f"Общий_отчет {period}.xlsx", main_report)
            
            # Individual reports
            for worker in workers:
                worker_surname = worker.split()[0] if worker else "Unknown"
                worker_report = create_worker_report(calculated_data, worker, period, full_config)
                zf.writestr(f"{worker_surname} {period}.xlsx", worker_report)
        
        zip_buffer.seek(0)
        
        # Save ZIP temporarily
        temp_path = f"/tmp/salary_report_{session_id}.zip"
        with open(temp_path, "wb") as f:
            f.write(zip_buffer.getvalue())
        
        return JSONResponse({
            "success": True,
            "download_url": f"/download/{session_id}"
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
