"""
Salary Calculation Service for Montazhniki
FastAPI backend for processing Excel files and calculating salaries
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from contextlib import asynccontextmanager
from urllib.parse import quote
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

# Database imports
from database import (
    database, create_tables, connect_db, disconnect_db,
    get_or_create_period, create_upload, save_order, save_calculation,
    save_worker_total, save_change, get_previous_upload, compare_uploads,
    get_orders_by_upload, get_all_periods, get_period_details,
    get_upload_details, get_worker_orders, get_months_summary
)

# Lifespan for database connection
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_tables()
    await connect_db()
    yield
    # Shutdown
    await disconnect_db()

app = FastAPI(
    title="Salary Calculator", 
    description="Расчёт зарплаты монтажников",
    lifespan=lifespan
)

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
    "alarm_high_payment": 20000,
    "alarm_high_specialist": 3500,
    "standard_percents": [30, 50, 100],
    "yandex_api_key": "9c140935-e689-4e9f-ab3a-46473474918e"
}

# Global storage for session data
session_data = {}

# Distance cache to avoid repeated API calls
distance_cache = {}

# Worker name normalization - built dynamically from actual data
def build_worker_name_map(all_names: set) -> dict:
    """
    Build normalization map automatically.
    If we have 'Иванов Иван' and 'Иванов Иван Иванович', 
    the shorter one maps to the longer (more complete) one.
    """
    name_map = {}
    # Clean names (remove оплата клиентом suffix)
    clean_names = set()
    for name in all_names:
        clean = name.replace(" (оплата клиентом)", "").strip()
        if clean:
            clean_names.add(clean)
    
    # Sort by length descending - longer names are "more complete"
    sorted_names = sorted(clean_names, key=len, reverse=True)
    
    for i, short_name in enumerate(sorted_names):
        # Skip if already mapped
        if short_name in name_map:
            continue
        
        # Look for a longer name that starts with this name
        for long_name in sorted_names[:i]:  # Only check longer names
            # Check if long_name starts with short_name + space (to avoid partial matches)
            if long_name.startswith(short_name + " "):
                name_map[short_name] = long_name
                break
    
    return name_map


def normalize_worker_name(name: str, name_map: dict = None) -> str:
    """Normalize worker name using the provided map"""
    if not name:
        return name
    if name_map is None:
        name_map = {}
    clean_name = name.replace(" (оплата клиентом)", "").strip()
    normalized = name_map.get(clean_name, clean_name)
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
            print(f"  🔍 Yandex запрос: {address[:50]}...")
            response = await client.get(url, params=params, timeout=10)
            print(f"  🔍 Yandex ответ: HTTP {response.status_code}")
            if response.status_code != 200:
                print(f"  ❌ Yandex ошибка: {response.text[:200]}")
                return None, None
            data = response.json()
            
            pos = data["response"]["GeoObjectCollection"]["featureMember"]
            if pos:
                coords = pos[0]["GeoObject"]["Point"]["pos"].split()
                return float(coords[1]), float(coords[0])  # lat, lon
            print(f"  ⚠️ Yandex: нет результатов для {address[:40]}")
    except Exception as e:
        print(f"  ❌ Yandex exception: {e}")
    return None, None


async def geocode_address_nominatim(address: str) -> tuple:
    """Get coordinates from Nominatim (OpenStreetMap) - free"""
    try:
        await asyncio.sleep(1)  # Rate limiting
        async with httpx.AsyncClient() as client:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": address,
                "format": "json",
                "limit": 1
            }
            headers = {"User-Agent": "SalaryCalculator/1.0"}
            print(f"  🔍 Nominatim запрос: {address[:50]}...")
            response = await client.get(url, params=params, headers=headers, timeout=10)
            print(f"  🔍 Nominatim ответ: HTTP {response.status_code}")
            if response.status_code != 200:
                print(f"  ❌ Nominatim ошибка: {response.text[:200]}")
                return None, None
            data = response.json()
            
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
            print(f"  ⚠️ Nominatim: нет результатов для {address[:40]}")
    except Exception as e:
        print(f"  ❌ Nominatim exception: {e}")
    return None, None


async def geocode_address(address: str, api_key: str) -> tuple:
    """Get coordinates - try Yandex first, fallback to Nominatim"""
    cache_key = f"geo_{address}"
    if cache_key in distance_cache:
        return distance_cache[cache_key]
    
    lat, lon = await geocode_address_yandex(address, api_key)
    if lat and lon:
        print(f"  📍 Yandex OK: {address[:40]}... -> ({lat:.4f}, {lon:.4f})")
        distance_cache[cache_key] = (lat, lon)
        return lat, lon
    
    lat, lon = await geocode_address_nominatim(address)
    if lat and lon:
        print(f"  📍 Nominatim OK: {address[:40]}... -> ({lat:.4f}, {lon:.4f})")
        distance_cache[cache_key] = (lat, lon)
        return lat, lon
    
    print(f"  ❌ Геокодинг FAILED: {address[:50]}")
    return None, None


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
    """Check if address is in Moscow or Moscow Oblast
    
    Logic: Consider address as Moscow/MO unless it explicitly mentions another region.
    This is because most orders are in Moscow area and addresses often don't include city name.
    """
    if not address:
        return False
    
    addr_lower = address.lower()
    
    # Explicit Moscow markers - if found, definitely Moscow
    moscow_markers = [
        "москва", "московская обл", "московской обл", "мо,", "мо ", "м.о.",
        "московский", "подмосков"
    ]
    if any(marker in addr_lower for marker in moscow_markers):
        return True
    
    # Moscow street patterns that might be confused with other cities
    # (e.g. "Севастопольский проспект" is in Moscow, not Sevastopol)
    moscow_streets = [
        "севастопольский", "крымский", "симферопольск", "ялтинск",
        "одесская", "киевское шоссе", "калининградск"
    ]
    if any(street in addr_lower for street in moscow_streets):
        return True
    
    # Explicit non-Moscow regions - if found, return False
    # But check full city names to avoid false matches with street names
    non_moscow_patterns = [
        "санкт-петербург", " спб,", " спб ", "г.спб", "г. спб",
        "ленинградская обл", "петербург",
        "краснодар", "г.сочи", "г. сочи", "новосибирск", "екатеринбург", 
        "г.казань", "г. казань", "нижний новгород", "челябинск", "самара",
        "омск", "ростов-на-дону", "г.уфа", "г. уфа", "красноярск", "пермь",
        "воронеж", "волгоград", "саратов", "тюмень", "тольятти",
        "республика крым", "г.севастополь", "г. севастополь", 
        "калининградская обл"
    ]
    
    if any(pattern in addr_lower for pattern in non_moscow_patterns):
        return False
    
    # If no explicit non-Moscow region, assume it's Moscow/MO area
    return True


async def calculate_fuel_cost(address: str, config: dict, days: int = 1) -> int:
    """Calculate fuel cost for round trip - only for Moscow and MO"""
    if not address or pd.isna(address):
        print(f"⛽ Бензин: пропуск (нет адреса)")
        return 0
    
    # Only calculate for Moscow and Moscow Oblast
    if not is_moscow_region(address):
        print(f"⛽ Бензин: пропуск (не Москва/МО): {address[:50]}")
        return 0
    
    # Add "Москва" or "Московская область" if not present for better geocoding
    addr_for_geocode = address
    if "москва" not in address.lower() and "московская" not in address.lower():
        addr_for_geocode = f"Москва, {address}"
    
    base_lat, base_lon = await geocode_address(config["base_address"], config["yandex_api_key"])
    if not base_lat:
        print(f"⛽ Бензин: не удалось геокодировать базовый адрес")
        return 0
    
    dest_lat, dest_lon = await geocode_address(addr_for_geocode, config["yandex_api_key"])
    if not dest_lat:
        print(f"⛽ Бензин: не удалось геокодировать адрес: {addr_for_geocode[:60]}")
        return 0
    
    distance = await get_distance_osrm(base_lat, base_lon, dest_lat, dest_lon)
    if distance == 0:
        print(f"⛽ Бензин: не удалось рассчитать расстояние для {address[:50]}")
        return 0
    
    cost = distance * 2 * config["fuel_coefficient"] * days
    import math
    cost = math.ceil(cost / 100) * 100
    
    result = min(cost, config["fuel_max"])
    print(f"⛽ Бензин: {address[:40]}... -> {distance:.1f} км -> {result} руб")
    return result


def extract_address_from_order(order_text: str) -> str:
    """Extract address from order text"""
    if not order_text or pd.isna(order_text):
        return ""
    
    text = str(order_text)
    
    skip_patterns = ["ОБУЧЕНИЕ", "обучение", "двойная оплата", "В прошлом расчете", 
                     "комплекты интернета", "комплект интернета"]
    for pattern in skip_patterns:
        if pattern in text:
            return ""
    
    # Pattern 1: Full datetime format "27.10.2025 0:00:00, address"
    match = re.search(r'\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2},\s*(.+?)(?:\n|$)', text)
    if match:
        addr = match.group(1).strip()
        addr = re.sub(r'\\n.*', '', addr)
        addr = re.sub(r'\|.*', '', addr)
        addr = clean_address_for_geocoding(addr)
        return addr.strip()
    
    # Pattern 2: Short time format "0:00:00, address"
    match = re.search(r'\d:\d{2}:\d{2},\s*(.+?)(?:\n|$)', text)
    if match:
        addr = match.group(1).strip()
        addr = re.sub(r'\\n.*', '', addr)
        addr = re.sub(r'\|.*', '', addr)
        addr = clean_address_for_geocoding(addr)
        return addr.strip()
    
    # Pattern 3: Date only format "27.10.2025, address" (no time)
    match = re.search(r'\d{2}\.\d{2}\.\d{4},\s*(.+?)(?:\n|$)', text)
    if match:
        addr = match.group(1).strip()
        addr = re.sub(r'\\n.*', '', addr)
        addr = re.sub(r'\|.*', '', addr)
        addr = clean_address_for_geocoding(addr)
        return addr.strip()
    
    return ""


def clean_address_for_geocoding(addr: str) -> str:
    """Clean address from garbage that prevents geocoding"""
    if not addr:
        return ""
    
    # Remove OZON/DDX prefixes - they prevent geocoding
    addr = re.sub(r'^OZON\s+', '', addr)
    addr = re.sub(r'^DDX\s*-?\s*', '', addr)
    
    # Remove garbage suffixes (comments after address)
    garbage_patterns = [
        r',?\s*зарплата\s+монтажник.*$',
        r',?\s*диагностика\s+.*$', 
        r',?\s*тест\s+делаем.*$',
        r'\s+диагностика\s+\w+$',
        r'\s*\(эатж.*\)$',  # typo "эатж" = "этаж"
        r'\s*\(этаж.*\)$',
    ]
    for pattern in garbage_patterns:
        addr = re.sub(pattern, '', addr, flags=re.IGNORECASE)
    
    return addr.strip()


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


# Groups to exclude from salary calculation (not real workers)
EXCLUDED_GROUPS = {
    "доставка",
    "доставка лестницы",
    "осмотр без оплаты (оплачен ранее)",
    "осмотр без оплаты",
    "помощник",
    "итого",
    "параметры:",
    "отбор:",
    "монтажник",
    "заказ, комментарий",
}


def is_valid_worker_name(name: str) -> bool:
    """Check if name looks like a real person name (ФИО)
    
    Valid: "Ветренко Дмитрий", "Романюк Алексей Юрьевич"
    Invalid: "Доставка", "Помощник", "Итого"
    """
    # Remove "(оплата клиентом)" suffix for checking
    clean_name = name.replace(" (оплата клиентом)", "").strip().lower()
    
    # Check against blacklist
    if clean_name in EXCLUDED_GROUPS:
        return False
    
    # Check if starts with any excluded word
    for excluded in EXCLUDED_GROUPS:
        if clean_name.startswith(excluded):
            return False
    
    # Additional check: real name should have at least 2 words (Фамилия Имя)
    # and each word should start with uppercase letter in original
    original_clean = name.replace(" (оплата клиентом)", "").strip()
    words = original_clean.split()
    
    if len(words) < 2:
        return False
    
    # Check that first word looks like a surname (starts with uppercase, mostly letters)
    first_word = words[0]
    if not first_word[0].isupper():
        return False
    
    # Check that it contains mostly Cyrillic or Latin letters
    letter_count = sum(1 for c in first_word if c.isalpha())
    if letter_count < len(first_word) * 0.8:
        return False
    
    return True


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


def parse_excel_file(file_bytes: bytes, is_over_10k: bool, name_map: dict = None) -> tuple:
    """Parse Excel file from 1C and extract data.
    Returns (DataFrame, set of worker names found)
    """
    df = pd.read_excel(BytesIO(file_bytes), header=None)
    
    header_row = None
    for i in range(min(10, len(df))):
        first_val = str(df.iloc[i].iloc[0]) if pd.notna(df.iloc[i].iloc[0]) else ""
        if first_val.strip() == "Монтажник":
            header_row = i
            break
    
    if header_row is None:
        raise ValueError("Не найден заголовок с 'Монтажник'")
    
    # First pass: collect all worker names
    all_worker_names = set()
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
        
        if not is_order and is_valid_worker_name(first_col_str):
            all_worker_names.add(first_col_str)
    
    # If no external map provided, just return names for first pass
    if name_map is None:
        return None, all_worker_names
    
    # Second pass: extract records with normalized names
    records = []
    current_worker = None
    is_client_payment_section = False
    is_valid_worker = False  # Track if current group is a valid worker
    
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
            # This is a group header (worker name or service category)
            is_client_payment_section = "(оплата клиентом)" in first_col_str
            worker_name = first_col_str.replace(" (оплата клиентом)", "").strip()
            
            if worker_name == "Монтажник":
                continue
            
            # Check if this is a valid worker (not a service category like "Доставка")
            is_valid_worker = is_valid_worker_name(first_col_str)
            
            if is_valid_worker:
                # Normalize worker name
                worker_name = normalize_worker_name(worker_name, name_map)
                current_worker = worker_name
            else:
                # Skip this group - it's not a real worker
                current_worker = None
            
            # "(оплата клиентом)" строка - это заголовок секции, не записываем её как данные
            continue
        else:
            # This is an order row - only add if current worker is valid
            if current_worker and is_valid_worker:
                records.append({
                    "worker": normalize_worker_name(current_worker, name_map),
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
    
    return pd.DataFrame(records), all_worker_names


def parse_both_excel_files(content_under: bytes, content_over: bytes) -> tuple:
    """Parse both Excel files and return combined DataFrame with normalized worker names.
    Returns (combined_df, name_map)
    """
    # First pass: collect all worker names from both files
    _, names_under = parse_excel_file(content_under, is_over_10k=False, name_map=None)
    _, names_over = parse_excel_file(content_over, is_over_10k=True, name_map=None)
    
    all_names = names_under | names_over
    
    # Build normalization map from all names
    name_map = build_worker_name_map(all_names)
    if name_map:
        print(f"📋 Нормализация имён: {name_map}")
    
    # Second pass: parse with normalization
    df_under, _ = parse_excel_file(content_under, is_over_10k=False, name_map=name_map)
    df_over, _ = parse_excel_file(content_over, is_over_10k=True, name_map=name_map)
    
    combined = pd.concat([df_over, df_under], ignore_index=True)
    
    return combined, name_map


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
            # Use the actual total value from data (can be edited in history)
            total_val = to_int(record.get("total", 0))
            c = ws.cell(row=current_row, column=12, value=total_val if total_val else None)
            c.font = data_font
            c.border = thin_border
            
            # Diagnostic -50% column M (13)
            c = ws.cell(row=current_row, column=13)
            c.border = thin_border
            
            current_row += 1
        
        regular_end = current_row - 1
        
        # Calculate sums for worker total row (fuel J, transport K) - use actual values instead of formulas
        if regular_end >= regular_start:
            # Sum fuel and transport from regular rows
            fuel_sum = sum(to_int(r.get("fuel_payment", 0)) or 0 for r in regular_rows if not r.get("is_worker_total"))
            transport_sum = sum(to_int(r.get("transport", 0)) or 0 for r in regular_rows if not r.get("is_worker_total"))
            
            c = ws.cell(row=worker_name_row, column=10, value=fuel_sum if fuel_sum else None)
            c.font = worker_font
            c = ws.cell(row=worker_name_row, column=11, value=transport_sum if transport_sum else None)
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
                
                # Итого - use actual value from data
                total_val = to_int(record.get("total", 0))
                c = ws.cell(row=current_row, column=12, value=total_val if total_val else None)
                c.font = data_font
                c.border = thin_border
                
                diag_50 = to_int(record.get("diagnostic_50", 0))
                c = ws.cell(row=current_row, column=13, value=diag_50 if diag_50 else None)
                c.font = data_font
                c.border = thin_border
                
                current_row += 1
            
            client_end = current_row - 1
            
            # Client section totals - use actual values instead of formulas
            if client_end >= client_start:
                client_total_sum = sum(to_int(r.get("total", 0)) or 0 for r in client_rows if not r.get("is_worker_total"))
                client_diag50_sum = sum(to_int(r.get("diagnostic_50", 0)) or 0 for r in client_rows if not r.get("is_worker_total"))
                
                c = ws.cell(row=client_name_row, column=12, value=client_total_sum if client_total_sum else None)
                c.font = worker_font
                c = ws.cell(row=client_name_row, column=13, value=client_diag50_sum if client_diag50_sum else None)
                c.font = worker_font
        
        # Main worker row Итого - use actual values instead of formulas
        # Sum of regular totals minus diagnostic -50% from client section
        regular_total_sum = sum(to_int(r.get("total", 0)) or 0 for r in regular_rows if not r.get("is_worker_total"))
        client_diag50_sum_for_main = sum(to_int(r.get("diagnostic_50", 0)) or 0 for r in client_rows if not r.get("is_worker_total")) if client_rows else 0
        
        if regular_end >= regular_start:
            if client_name_row:
                # Has client section - subtract diagnostic -50%
                main_total = regular_total_sum - client_diag50_sum_for_main
            else:
                main_total = regular_total_sum
            c = ws.cell(row=worker_name_row, column=12, value=main_total if main_total else None)
            c.font = worker_font
            c.fill = yellow_fill
            c.border = thin_border
        else:
            if client_name_row:
                main_total = -client_diag50_sum_for_main
                c = ws.cell(row=worker_name_row, column=12, value=main_total if main_total else None)
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


@app.post("/api/detect-file-type")
async def detect_file_type(file: UploadFile = File(...)):
    """
    Detect if uploaded Excel file contains orders under 10k or over 10k.
    Looks for the filter condition in "Отбор" row that specifies:
    - "Меньше или равно" -> under 10k
    - "Больше или равно" -> over 10k
    Also extracts period name from "Период:" row.
    """
    try:
        content = await file.read()
        
        # Parse Excel file
        df = pd.read_excel(BytesIO(content), header=None)
        
        file_type = "unknown"
        period_name = None
        
        # Search through first 20 rows for filter info and period
        for idx in range(min(20, len(df))):
            for col_idx in range(min(10, len(df.columns))):
                cell = df.iloc[idx, col_idx]
                if pd.isna(cell):
                    continue
                cell_str = str(cell).strip()
                
                # Look for filter condition (Отбор row)
                # The filter text contains "Выручка от услуг Меньше или равно" or "Больше или равно"
                if "выручка от услуг" in cell_str.lower():
                    if "меньше или равно" in cell_str.lower():
                        file_type = "under"
                    elif "больше или равно" in cell_str.lower():
                        file_type = "over"
                
                # Look for period info
                if "период:" in cell_str.lower():
                    # Extract period like "16.11.2025 - 30.11.2025" and normalize to "16-30.11.25"
                    match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})', cell_str)
                    if match:
                        d1, m1, y1, d2, m2, y2 = match.groups()
                        period_name = f"{d1}-{d2}.{m1}.{y2[2:]}"
        
        return JSONResponse({
            "success": True, 
            "type": file_type,
            "period": period_name,
            "filename": file.filename
        })
        
    except Exception as e:
        return JSONResponse({
            "success": True,
            "type": "unknown",
            "error": str(e)
        })


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
        
        # Parse both files with automatic name normalization
        combined, name_map = parse_both_excel_files(content_under, content_over)
        
        period_df = pd.read_excel(BytesIO(content_under), header=None)
        period = extract_period(period_df)
        
        workers = list(set([w.replace(" (оплата клиентом)", "") 
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
            
            # Check if transport will be applied (revenue > 10k and percent between 20% and 40%)
            percent_min = DEFAULT_CONFIG["transport_percent_min"]
            percent_max = DEFAULT_CONFIG["transport_percent_max"]
            has_transport = revenue_services > DEFAULT_CONFIG["transport_min_revenue"] and percent_min <= percent <= percent_max
            
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
            "workers": workers,
            "name_map": name_map  # Save for later use
        }
        
        # ===== CHECK FOR CHANGES FROM PREVIOUS UPLOAD =====
        changes_summary = {
            "has_previous": False,
            "added": [],
            "deleted": [],
            "modified": []
        }
        
        try:
            if database and database.is_connected:
                from database import get_or_create_period, get_period_details, get_orders_by_upload
                
                # Check if this period exists
                period_id = await get_or_create_period(period)
                period_details = await get_period_details(period_id)
                
                if period_details and period_details.get("uploads"):
                    uploads = period_details["uploads"]
                    if len(uploads) > 0:
                        # Get orders from latest upload
                        latest_upload_id = uploads[0]["id"]
                        old_orders = await get_orders_by_upload(latest_upload_id)
                        
                        # Also get extra rows (manual additions) from previous upload
                        from database import get_upload_details
                        prev_upload_details = await get_upload_details(latest_upload_id)
                        extra_rows_from_prev = []
                        manual_edits_from_prev = []
                        
                        if prev_upload_details:
                            # Get extra rows (is_extra_row=True)
                            for o in old_orders:
                                if o.get("is_extra_row", False):
                                    extra_rows_from_prev.append(o)
                            
                            # Get manual edits
                            manual_edits_from_prev = prev_upload_details.get("manual_edits", [])
                        
                        if old_orders:
                            changes_summary["has_previous"] = True
                            changes_summary["previous_version"] = uploads[0]["version"]
                            changes_summary["previous_date"] = str(uploads[0].get("created_at", ""))
                            changes_summary["previous_upload_id"] = latest_upload_id
                            
                            # Build maps for comparison
                            old_map = {}
                            for o in old_orders:
                                # Skip extra rows for normal comparison
                                if o.get("is_extra_row", False):
                                    continue
                                key = (o.get("order_code", ""), o.get("worker", ""))
                                old_map[key] = o
                            
                            print(f"📊 Comparison: {len(old_map)} orders in DB")
                            
                            new_map = {}
                            for _, row in combined.iterrows():
                                # Skip worker total rows
                                if row.get("is_worker_total", False):
                                    continue
                                    
                                order_text = str(row.get("order", ""))
                                order_code_match = re.search(r'(КАУТ|ИБУТ|ТДУТ)-\d+', order_text)
                                order_code = order_code_match.group(0) if order_code_match else ""
                                
                                # Skip rows without order code (they are totals or headers)
                                if not order_code:
                                    continue
                                    
                                worker = normalize_worker_name(str(row.get("worker", ""))).replace(" (оплата клиентом)", "")
                                
                                # Extract address from order text
                                address = ""
                                if ", " in order_text:
                                    parts = order_text.split(", ", 1)
                                    if len(parts) > 1:
                                        address = parts[1].split("\n")[0][:80]  # First 80 chars of address
                                
                                key = (order_code, worker)
                                
                                # Collect all numeric fields - with safe parsing
                                def safe_float(val):
                                    if val is None or val == "" or pd.isna(val):
                                        return 0.0
                                    try:
                                        if isinstance(val, str):
                                            val = val.replace(" ", "").replace(",", ".").replace("%", "")
                                        return float(val)
                                    except:
                                        return 0.0
                                
                                revenue_total = safe_float(row.get("revenue_total", 0))
                                revenue_services = safe_float(row.get("revenue_services", 0))
                                diagnostic = safe_float(row.get("diagnostic", 0))
                                specialist_fee = safe_float(row.get("specialist_fee", 0))
                                additional_expenses = safe_float(row.get("additional_expenses", 0))
                                service_payment = safe_float(row.get("service_payment", 0))
                                percent_val = parse_percent(row.get("percent", 0))
                                
                                new_map[key] = {
                                    "order_code": order_code,
                                    "order_full": order_text,
                                    "address": address,
                                    "worker": worker,
                                    "revenue_total": revenue_total,
                                    "revenue_services": revenue_services,
                                    "diagnostic": diagnostic,
                                    "specialist_fee": specialist_fee,
                                    "additional_expenses": additional_expenses,
                                    "service_payment": service_payment,
                                    "percent": percent_val,
                                }
                            
                            print(f"📊 Comparison: {len(new_map)} orders in new files")
                            
                            # Find added - include all details
                            for key, order in new_map.items():
                                if key[0] and key not in old_map:  # Has order_code and not in old
                                    # Build details dict with non-zero values
                                    details = {}
                                    if order["revenue_total"] > 0:
                                        details["Выручка итого"] = f"{order['revenue_total']:,.0f}".replace(",", " ")
                                    if order["revenue_services"] != 0:
                                        details["Выручка от услуг"] = f"{order['revenue_services']:,.0f}".replace(",", " ")
                                    if order["diagnostic"] > 0:
                                        details["Диагностика"] = f"{order['diagnostic']:,.0f}".replace(",", " ")
                                    if order["specialist_fee"] > 0:
                                        details["Выезд специалиста"] = f"{order['specialist_fee']:,.0f}".replace(",", " ")
                                    if order["additional_expenses"] != 0:
                                        details["Доп. расходы"] = f"{order['additional_expenses']:,.0f}".replace(",", " ")
                                    if order["service_payment"] != 0:
                                        details["Оплата услуг"] = f"{order['service_payment']:,.0f}".replace(",", " ")
                                    if order["percent"] > 0:
                                        details["Процент"] = f"{order['percent']:.0f}%"
                                    
                                    changes_summary["added"].append({
                                        "order_code": order["order_code"],
                                        "worker": order["worker"],
                                        "address": order["address"],
                                        "details": details
                                    })
                            
                            # Find deleted - include address from old data
                            for key, order in old_map.items():
                                if key[0] and key not in new_map:  # Has order_code and not in new
                                    # Build details from old order
                                    details = {}
                                    if float(order.get("revenue_total", 0) or 0) > 0:
                                        details["Выручка итого"] = f"{float(order.get('revenue_total', 0)):,.0f}".replace(",", " ")
                                    if float(order.get("revenue_services", 0) or 0) != 0:
                                        details["Выручка от услуг"] = f"{float(order.get('revenue_services', 0)):,.0f}".replace(",", " ")
                                    if float(order.get("service_payment", 0) or 0) != 0:
                                        details["Оплата услуг"] = f"{float(order.get('service_payment', 0)):,.0f}".replace(",", " ")
                                    if float(order.get("percent", 0) or 0) > 0:
                                        details["Процент"] = f"{float(order.get('percent', 0)):.0f}%"
                                    
                                    changes_summary["deleted"].append({
                                        "order_code": order.get("order_code", ""),
                                        "worker": order.get("worker", ""),
                                        "address": order.get("address", ""),
                                        "details": details
                                    })
                            
                            # Find modified - compare all fields
                            compare_fields = [
                                ("revenue_total", "Выручка итого"),
                                ("revenue_services", "Выручка от услуг"),
                                ("diagnostic", "Диагностика"),
                                ("specialist_fee", "Выезд специалиста"),
                                ("additional_expenses", "Доп. расходы"),
                                ("service_payment", "Оплата услуг"),
                                ("percent", "Процент"),
                            ]
                            
                            # Debug: show some keys from both maps
                            print(f"📊 Sample old_map keys: {list(old_map.keys())[:5]}")
                            print(f"📊 Sample new_map keys: {list(new_map.keys())[:5]}")
                            
                            for key in new_map:
                                if key[0] and key in old_map:  # Both exist
                                    old_order = old_map[key]
                                    new_order = new_map[key]
                                    
                                    field_changes = []
                                    for field_key, field_name in compare_fields:
                                        old_val = float(old_order.get(field_key, 0) or 0)
                                        new_val = float(new_order.get(field_key, 0) or 0)
                                        
                                        if abs(old_val - new_val) > 0.01:  # Compare with tolerance
                                            if field_key == "percent":
                                                field_changes.append({
                                                    "field": field_name,
                                                    "old": f"{old_val:.0f}%",
                                                    "new": f"{new_val:.0f}%"
                                                })
                                            else:
                                                field_changes.append({
                                                    "field": field_name,
                                                    "old": f"{old_val:,.0f}".replace(",", " "),
                                                    "new": f"{new_val:,.0f}".replace(",", " ")
                                                })
                                    
                                    if field_changes:
                                        print(f"📊 Modified found: {key} - {field_changes}")
                                        changes_summary["modified"].append({
                                            "order_code": new_order["order_code"],
                                            "worker": new_order["worker"],
                                            "address": new_order["address"],
                                            "changes": field_changes
                                        })
                            
                            print(f"📊 Comparison result: {len(changes_summary['added'])} added, {len(changes_summary['deleted'])} deleted, {len(changes_summary['modified'])} modified")
                            
                            # Add extra rows (manual additions) from previous version to deleted list
                            # These are rows that were manually added and won't be in new 1C files
                            changes_summary["extra_rows"] = []  # Store for later restoration
                            for extra in extra_rows_from_prev:
                                order_text = extra.get("order_full", "") or extra.get("order_code", "")
                                worker = extra.get("worker", "")
                                
                                # Get calculation data for this extra row
                                calc = extra.get("calculation", {})
                                total = calc.get("total", 0) if calc else 0
                                
                                changes_summary["extra_rows"].append({
                                    "id": extra.get("id"),
                                    "order_code": extra.get("order_code", "") or order_text[:50],
                                    "order_full": order_text,
                                    "worker": worker,
                                    "address": extra.get("address", ""),
                                    "total": total,
                                    "type": "extra_row"
                                })
                                
                                # Add to deleted list for UI
                                changes_summary["deleted"].append({
                                    "order_code": order_text[:50] if not extra.get("order_code") else extra.get("order_code"),
                                    "worker": worker,
                                    "address": extra.get("address", "") or order_text,
                                    "details": {
                                        "Итого": f"{total:,.0f}".replace(",", " ") if total else "—"
                                    },
                                    "type": "extra_row",
                                    "original_id": extra.get("id")
                                })
                            
                            # Also add manual_edits info for potential restoration
                            changes_summary["manual_edits_prev"] = manual_edits_from_prev
                            
        except Exception as e:
            print(f"⚠️ Changes comparison error (non-critical): {e}")
            import traceback
            traceback.print_exc()
        
        # Store changes_summary in session for review page
        session_data[session_id]["changes_summary"] = changes_summary
        
        # Check if there are changes to review
        has_changes = (
            changes_summary.get("has_previous", False) and (
                len(changes_summary.get("added", [])) > 0 or
                len(changes_summary.get("deleted", [])) > 0 or
                len(changes_summary.get("modified", [])) > 0
            )
        )
        
        return JSONResponse({
            "success": True,
            "session_id": session_id,
            "period": period,
            "workers": workers,
            "orders": orders,
            "total_records": len(combined),
            "changes": changes_summary,
            "has_changes": has_changes,
            "redirect_to_review": has_changes  # Flag for frontend
        })
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===== REVIEW CHANGES PAGE =====
@app.get("/review")
async def review_page(request: Request):
    """Render the review changes page"""
    return templates.TemplateResponse("review.html", {"request": request})


@app.get("/api/review/{session_id}")
async def get_review_data(session_id: str):
    """Get changes data for review page"""
    try:
        if session_id not in session_data:
            return JSONResponse({"success": False, "error": "Сессия истекла"})
        
        session = session_data[session_id]
        changes = session.get("changes_summary", {})
        
        return JSONResponse({
            "success": True,
            "session_id": session_id,
            "period": session.get("period", ""),
            "previous_version": changes.get("previous_version", 1),
            "changes": {
                "added": changes.get("added", []),
                "deleted": changes.get("deleted", []),
                "modified": changes.get("modified", [])
            }
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/api/apply-review")
async def apply_review_changes(request: Request):
    """Apply selected changes and proceed with calculation"""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        selections = data.get("selections", {})
        
        if session_id not in session_data:
            return JSONResponse({"success": False, "error": "Сессия истекла"})
        
        session = session_data[session_id]
        combined_records = session.get("combined", [])
        changes = session.get("changes_summary", {})
        
        # Convert combined back to list of dicts for modification
        modified_records = list(combined_records)
        
        # Process deleted items that should be restored
        deleted_to_restore = selections.get("deleted", [])
        if deleted_to_restore and changes.get("has_previous"):
            # We need to fetch the old orders from database
            try:
                from database import get_orders_by_upload, get_upload_details
                period_id = await get_or_create_period(session["period"])
                period_details = await get_period_details(period_id)
                
                if period_details and period_details.get("uploads"):
                    latest_upload_id = period_details["uploads"][0]["id"]
                    old_orders = await get_orders_by_upload(latest_upload_id)
                    
                    # Get upload details for extra rows with calculations
                    upload_details = await get_upload_details(latest_upload_id)
                    
                    for old_order in old_orders:
                        order_code = old_order.get("order_code", "")
                        order_full = old_order.get("order_full", "")
                        worker = old_order.get("worker", "")
                        is_extra = old_order.get("is_extra_row", False)
                        
                        # For extra rows, use order_full as key if no order_code
                        if is_extra and not order_code:
                            key = (order_full[:50] if order_full else "EXTRA") + "_" + worker
                        else:
                            key = order_code + "_" + worker
                        
                        if key in deleted_to_restore:
                            # Get calculation data if available
                            calc = old_order.get("calculation", {})
                            
                            # Add this order back to combined records
                            restored_record = {
                                "worker": worker,
                                "order": order_full or order_code,
                                "revenue_total": old_order.get("revenue_total", 0),
                                "revenue_services": old_order.get("revenue_services", 0),
                                "diagnostic": old_order.get("diagnostic", 0),
                                "diagnostic_payment": old_order.get("diagnostic_payment", 0),
                                "specialist_fee": old_order.get("specialist_fee", 0),
                                "additional_expenses": old_order.get("additional_expenses", 0),
                                "service_payment": old_order.get("service_payment", 0),
                                "percent": old_order.get("percent", 0),
                                "is_client_payment": old_order.get("is_client_payment", False),
                                "is_restored": True,  # Mark as restored
                                "is_extra_row": is_extra,
                                # Preserve calculation values for extra rows
                                "fuel_payment": calc.get("fuel_payment", 0) if calc else 0,
                                "transport": calc.get("transport", 0) if calc else 0,
                                "total": calc.get("total", 0) if calc else 0,
                            }
                            modified_records.append(restored_record)
                            print(f"✅ Restored: {key} (extra_row={is_extra})")
            except Exception as e:
                print(f"Error restoring deleted orders: {e}")
                import traceback
                traceback.print_exc()
        
        # Process modified items where user wants to keep old values
        modified_to_revert = selections.get("modified", [])
        if modified_to_revert and changes.get("has_previous"):
            try:
                from database import get_orders_by_upload
                period_id = await get_or_create_period(session["period"])
                period_details = await get_period_details(period_id)
                
                if period_details and period_details.get("uploads"):
                    latest_upload_id = period_details["uploads"][0]["id"]
                    old_orders = await get_orders_by_upload(latest_upload_id)
                    old_orders_map = {}
                    for o in old_orders:
                        old_orders_map[o.get("order_code", "") + "_" + o.get("worker", "")] = o
                    
                    # Update records with old values
                    for i, record in enumerate(modified_records):
                        order_text = str(record.get("order", ""))
                        order_code_match = re.search(r'(КАУТ|ИБУТ|ТДУТ)-\d+', order_text)
                        order_code = order_code_match.group(0) if order_code_match else ""
                        worker = str(record.get("worker", "")).replace(" (оплата клиентом)", "")
                        key = order_code + "_" + worker
                        
                        if key in modified_to_revert and key in old_orders_map:
                            old = old_orders_map[key]
                            # Revert numeric fields to old values
                            modified_records[i]["revenue_total"] = old.get("revenue_total", 0)
                            modified_records[i]["revenue_services"] = old.get("revenue_services", 0)
                            modified_records[i]["diagnostic"] = old.get("diagnostic", 0)
                            modified_records[i]["specialist_fee"] = old.get("specialist_fee", 0)
                            modified_records[i]["additional_expenses"] = old.get("additional_expenses", 0)
                            modified_records[i]["service_payment"] = old.get("service_payment", 0)
                            modified_records[i]["percent"] = old.get("percent", 0)
                            modified_records[i]["is_reverted"] = True
            except Exception as e:
                print(f"Error reverting modified orders: {e}")
        
        # Process added items - remove those not selected
        added_to_skip = set()
        for item in changes.get("added", []):
            key = item["order_code"] + "_" + item["worker"]
            if key not in selections.get("added", []):
                added_to_skip.add(key)
        
        if added_to_skip:
            filtered_records = []
            for record in modified_records:
                order_text = str(record.get("order", ""))
                order_code_match = re.search(r'(КАУТ|ИБУТ|ТДУТ)-\d+', order_text)
                order_code = order_code_match.group(0) if order_code_match else ""
                worker = str(record.get("worker", "")).replace(" (оплата клиентом)", "")
                key = order_code + "_" + worker
                
                if key not in added_to_skip:
                    filtered_records.append(record)
            modified_records = filtered_records
        
        # Update session with modified records
        session["combined"] = modified_records
        session["review_applied"] = True
        session_data[session_id] = session
        
        # Now proceed with calculation (similar to /calculate endpoint)
        # Use default config and calculate
        config = DEFAULT_CONFIG.copy()
        name_map = session.get("name_map", {})
        
        calculated_data = []
        for row in modified_records:
            calc_row = await calculate_row(row, config, {})
            calculated_data.append(calc_row)
        
        calculated_data.sort(key=lambda x: normalize_worker_name(x.get("worker", ""), name_map).replace(" (оплата клиентом)", ""))
        
        # Save to database
        period = session["period"]
        period_id = await get_or_create_period(period)
        upload_id = await create_upload(period_id)
        
        # First pass: save all orders and collect totals
        worker_totals = {}
        
        for row in calculated_data:
            worker = row.get("worker", "")
            if not worker or pd.isna(worker):
                continue
            
            is_worker_total = row.get("is_worker_total", False)
            
            # Skip worker total rows - we'll calculate totals from orders
            if is_worker_total:
                continue
            
            # Save individual order
            order_text = str(row.get("order", ""))
            order_code = ""
            address = ""
            
            match = re.search(r'(КАУТ|ИБУТ|ТДУТ)-\d+', order_text)
            if match:
                order_code = match.group(0)
            
            if ", " in order_text:
                parts = order_text.split(", ", 1)
                if len(parts) > 1:
                    address = parts[1].split("\n")[0][:100]
            
            base_worker = worker.replace(" (оплата клиентом)", "")
            is_client = "(оплата клиентом)" in worker
            
            order_id = await save_order(
                upload_id=upload_id,
                worker=base_worker,
                order_code=order_code,
                order_full=order_text[:500],
                address=address,
                is_client_payment=is_client,
                revenue_total=float(row.get("revenue_total", 0) or 0),
                revenue_services=float(row.get("revenue_services", 0) or 0),
                diagnostic=float(row.get("diagnostic", 0) or 0),
                diagnostic_payment=float(row.get("diagnostic_payment", 0) or 0),
                specialist_fee=float(row.get("specialist_fee", 0) or 0),
                additional_expenses=float(row.get("additional_expenses", 0) or 0),
                service_payment=float(row.get("service_payment", 0) or 0),
                percent=float(str(row.get("percent", "0")).replace("%", "").replace(",", ".") or 0)
            )
            
            # Save calculation for this order
            total_val = float(row.get("total", 0) or 0)
            await save_calculation(
                order_id=order_id,
                fuel_payment=float(row.get("fuel_payment", 0) or 0),
                transport=float(row.get("transport", 0) or 0),
                diagnostic_50=float(row.get("diagnostic_50", 0) or 0),
                total=total_val
            )
            
            # Accumulate totals per worker
            if base_worker not in worker_totals:
                worker_totals[base_worker] = {"company": 0, "client": 0}
            
            if is_client:
                worker_totals[base_worker]["client"] += total_val
            else:
                worker_totals[base_worker]["company"] += total_val
        
        # Save worker totals
        for worker, totals in worker_totals.items():
            await save_worker_total(
                upload_id=upload_id,
                worker=worker,
                company_amount=totals["company"],
                client_amount=totals["client"]
            )
        
        # Compare with previous upload and save changes
        prev_upload_id = await get_previous_upload(period_id, upload_id)
        if prev_upload_id:
            changes_list = await compare_uploads(prev_upload_id, upload_id)
            for change in changes_list:
                if change["type"] == "added":
                    await save_change(upload_id, change["order_code"], change["worker"], "added")
                elif change["type"] == "deleted":
                    await save_change(upload_id, change["order_code"], change["worker"], "deleted")
                else:
                    for field_change in change.get("changes", []):
                        await save_change(
                            upload_id, change["order_code"], change["worker"], 
                            "modified", field_change["field"],
                            str(field_change["old"]), str(field_change["new"])
                        )
        
        # Cleanup session
        del session_data[session_id]
        
        return JSONResponse({
            "success": True,
            "period_id": period_id,
            "upload_id": upload_id
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/api/process-first-upload")
async def process_first_upload(request: Request):
    """Process first upload for a period (no previous version to compare)"""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        
        if session_id not in session_data:
            return JSONResponse({"success": False, "error": "Сессия истекла"})
        
        session = session_data[session_id]
        combined_records = session.get("combined", [])
        
        # Use default config
        config = DEFAULT_CONFIG.copy()
        name_map = session.get("name_map", {})
        
        calculated_data = []
        for row in combined_records:
            calc_row = await calculate_row(row, config, {})
            calculated_data.append(calc_row)
        
        calculated_data.sort(key=lambda x: normalize_worker_name(x.get("worker", ""), name_map).replace(" (оплата клиентом)", ""))
        
        # Save to database
        period = session["period"]
        period_id = await get_or_create_period(period)
        upload_id = await create_upload(period_id)
        
        # First pass: save all orders and collect totals
        worker_totals = {}
        
        for row in calculated_data:
            worker = row.get("worker", "")
            if not worker or pd.isna(worker):
                continue
            
            is_worker_total = row.get("is_worker_total", False)
            
            # Skip worker total rows - we'll calculate totals from orders
            if is_worker_total:
                continue
            
            # Save individual order
            order_text = str(row.get("order", ""))
            order_code = ""
            address = ""
            
            match = re.search(r'(КАУТ|ИБУТ|ТДУТ)-\d+', order_text)
            if match:
                order_code = match.group(0)
            
            if ", " in order_text:
                parts = order_text.split(", ", 1)
                if len(parts) > 1:
                    address = parts[1].split("\n")[0][:100]
            
            base_worker = worker.replace(" (оплата клиентом)", "")
            is_client = "(оплата клиентом)" in worker
            
            order_id = await save_order(
                upload_id=upload_id,
                worker=base_worker,
                order_code=order_code,
                order_full=order_text[:500],
                address=address,
                is_client_payment=is_client,
                revenue_total=float(row.get("revenue_total", 0) or 0),
                revenue_services=float(row.get("revenue_services", 0) or 0),
                diagnostic=float(row.get("diagnostic", 0) or 0),
                diagnostic_payment=float(row.get("diagnostic_payment", 0) or 0),
                specialist_fee=float(row.get("specialist_fee", 0) or 0),
                additional_expenses=float(row.get("additional_expenses", 0) or 0),
                service_payment=float(row.get("service_payment", 0) or 0),
                percent=float(str(row.get("percent", "0")).replace("%", "").replace(",", ".") or 0)
            )
            
            # Save calculation for this order
            total_val = float(row.get("total", 0) or 0)
            await save_calculation(
                order_id=order_id,
                fuel_payment=float(row.get("fuel_payment", 0) or 0),
                transport=float(row.get("transport", 0) or 0),
                diagnostic_50=float(row.get("diagnostic_50", 0) or 0),
                total=total_val
            )
            
            # Accumulate totals per worker
            if base_worker not in worker_totals:
                worker_totals[base_worker] = {"company": 0, "client": 0}
            
            if is_client:
                worker_totals[base_worker]["client"] += total_val
            else:
                worker_totals[base_worker]["company"] += total_val
        
        # Save worker totals
        for worker, totals in worker_totals.items():
            await save_worker_total(
                upload_id=upload_id,
                worker=worker,
                company_amount=totals["company"],
                client_amount=totals["client"]
            )
        
        # Cleanup session
        del session_data[session_id]
        
        return JSONResponse({
            "success": True,
            "period_id": period_id,
            "upload_id": upload_id
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/preview")
async def preview_calculation(
    session_id: str = Form(...),
    config_json: str = Form(...),
    days_json: str = Form(...),
    extra_rows_json: str = Form(...)
):
    """Preview calculation without saving to database"""
    try:
        if session_id not in session_data:
            raise HTTPException(status_code=400, detail="Session expired")
        
        session = session_data[session_id]
        config = json.loads(config_json)
        days_map = json.loads(days_json)
        extra_rows = json.loads(extra_rows_json)
        
        full_config = {**DEFAULT_CONFIG, **config}
        name_map = session.get("name_map", {})
        
        calculated_data = []
        for row in session["combined"]:
            calc_row = await calculate_row(row, full_config, days_map)
            calculated_data.append(calc_row)
        
        for worker, rows in extra_rows.items():
            for extra in rows:
                calculated_data.append({
                    "worker": normalize_worker_name(worker, name_map),
                    "order": extra.get("description", ""),
                    "order_id": f"extra_{worker}_{extra.get('description', '')[:20]}",
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
                    "is_extra_row": True,
                    "fuel_payment": "",
                    "transport": "",
                    "diagnostic_50": "",
                    "total": float(extra.get("amount", 0))
                })
        
        calculated_data.sort(key=lambda x: normalize_worker_name(x.get("worker", ""), name_map).replace(" (оплата клиентом)", ""))
        
        # Generate unique IDs for each row for deletion
        preview_rows = []
        for idx, row in enumerate(calculated_data):
            order_code = ""
            order_text = row.get("order", "")
            match = re.search(r'((?:КАУТ|ИБУТ|ТДУТ)-\d+)', order_text)
            if match:
                order_code = match.group(1)
            
            # Extract address
            address = extract_address_from_order(order_text)
            if not address:
                address = order_text[:50] + "..." if len(order_text) > 50 else order_text
            
            preview_rows.append({
                "id": idx,
                "worker": row.get("worker", "").replace(" (оплата клиентом)", ""),
                "order_code": order_code,
                "address": address,
                "revenue_total": row.get("revenue_total", ""),
                "revenue_services": row.get("revenue_services", ""),
                "service_payment": row.get("service_payment", ""),
                "percent": row.get("percent", ""),
                "fuel_payment": row.get("fuel_payment", ""),
                "transport": row.get("transport", ""),
                "total": row.get("total", 0),
                "is_client_payment": row.get("is_client_payment", False),
                "is_over_10k": row.get("is_over_10k", False),
                "is_extra_row": row.get("is_extra_row", False)
            })
        
        # Store calculated data in session for later finalization
        session["calculated_data"] = calculated_data
        session["config"] = full_config
        
        # Group by worker for summary
        workers_summary = {}
        for row in preview_rows:
            worker = row["worker"]
            if worker not in workers_summary:
                workers_summary[worker] = {
                    "total": 0,
                    "count": 0,
                    "fuel": 0,
                    "transport": 0
                }
            total = row.get("total", 0)
            if isinstance(total, (int, float)):
                workers_summary[worker]["total"] += total
            workers_summary[worker]["count"] += 1
            fuel = row.get("fuel_payment", 0)
            if isinstance(fuel, (int, float)):
                workers_summary[worker]["fuel"] += fuel
            transport = row.get("transport", 0)
            if isinstance(transport, (int, float)):
                workers_summary[worker]["transport"] += transport
        
        alarms = generate_alarms(calculated_data, full_config)
        
        return JSONResponse({
            "success": True,
            "rows": preview_rows,
            "workers_summary": workers_summary,
            "alarms": alarms,
            "period": session["period"]
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/calculate")
async def calculate_salaries(
    session_id: str = Form(...),
    config_json: str = Form(...),
    days_json: str = Form(...),
    extra_rows_json: str = Form(...),
    deleted_rows_json: str = Form("[]")
):
    """Calculate all salaries and generate files"""
    try:
        if session_id not in session_data:
            raise HTTPException(status_code=400, detail="Session expired")
        
        session = session_data[session_id]
        deleted_rows_raw = json.loads(deleted_rows_json)
        deleted_rows = set(int(x) for x in deleted_rows_raw)
        
        if deleted_rows:
            print(f"🗑️ Удаляем строки с ID: {sorted(deleted_rows)}")
        
        # Use pre-calculated data from preview if available
        if "calculated_data" in session:
            all_calculated = session["calculated_data"]
            full_config = session.get("config", DEFAULT_CONFIG)
            
            # Filter out deleted rows
            calculated_data = []
            for idx, row in enumerate(all_calculated):
                if idx in deleted_rows:
                    order_info = row.get("order", "")[:50]
                    worker = row.get("worker", "")
                    print(f"  ❌ Удаляем: {worker} - {order_info}")
                    continue
                calculated_data.append(row)
        else:
            # Fallback: recalculate (shouldn't normally happen)
            config = json.loads(config_json)
            days_map = json.loads(days_json)
            extra_rows = json.loads(extra_rows_json)
            
            full_config = {**DEFAULT_CONFIG, **config}
            name_map = session.get("name_map", {})
            
            calculated_data = []
            for idx, row in enumerate(session["combined"]):
                calc_row = await calculate_row(row, full_config, days_map)
                calculated_data.append(calc_row)
            
            for worker, rows in extra_rows.items():
                for extra in rows:
                    calculated_data.append({
                        "worker": normalize_worker_name(worker, name_map),
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
                        "is_extra_row": True,
                        "fuel_payment": "",
                        "transport": "",
                        "diagnostic_50": "",
                        "total": float(extra.get("amount", 0))
                    })
            
            # Sort same as preview
            name_map = session.get("name_map", {})
            calculated_data.sort(key=lambda x: normalize_worker_name(x.get("worker", ""), name_map).replace(" (оплата клиентом)", ""))
            
            # Now filter deleted
            calculated_data = [row for idx, row in enumerate(calculated_data) if idx not in deleted_rows]
        
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
        
        # ===== SAVE TO DATABASE =====
        try:
            if database:
                # 1. Get or create period
                period_id = await get_or_create_period(period)
                
                # 2. Create upload
                upload_id = await create_upload(period_id, full_config)
                
                # 3. Check for previous upload and compare
                prev_upload_id = await get_previous_upload(period_id, 
                    (await get_period_details(period_id))["uploads"][0]["version"] if (await get_period_details(period_id))["uploads"] else 1
                )
                
                # 4. Save orders and calculations - ONLY for valid workers
                order_id_map = {}  # To map order to its DB id
                for row in calculated_data:
                    # Skip non-worker groups (Доставка, Помощник, etc.)
                    worker = normalize_worker_name(row.get("worker", "").replace(" (оплата клиентом)", ""))
                    if not is_valid_worker_name(worker):
                        continue
                    
                    is_extra = row.get("is_extra_row", False)
                    
                    # Extract order code from order text (for regular rows)
                    order_text = row.get("order", "")
                    order_code_match = re.search(r'(КАУТ|ИБУТ|ТДУТ)-\d+', order_text)
                    order_code = order_code_match.group(0) if order_code_match else ""
                    
                    # For extra rows, use description as order text
                    if is_extra:
                        order_code = "ДОПЛАТА"  # Special code for extra rows
                    
                    # Save order
                    order_data = {
                        "worker": row.get("worker", ""),
                        "order_code": order_code,
                        "order": order_text,
                        "address": extract_address_from_order(order_text) if not is_extra else order_text,
                        "revenue_total": row.get("revenue_total", 0) if not is_extra else 0,
                        "revenue_services": row.get("revenue_services", 0) if not is_extra else 0,
                        "diagnostic": row.get("diagnostic", 0) if not is_extra else 0,
                        "diagnostic_payment": row.get("diagnostic_payment", 0) if not is_extra else 0,
                        "specialist_fee": row.get("specialist_fee", 0) if not is_extra else 0,
                        "additional_expenses": row.get("additional_expenses", 0) if not is_extra else 0,
                        "service_payment": row.get("service_payment", 0) if not is_extra else 0,
                        "percent": row.get("percent", "") if not is_extra else "",
                        "is_client_payment": row.get("is_client_payment", False),
                        "is_over_10k": row.get("is_over_10k", False),
                        "is_extra_row": is_extra,
                    }
                    order_id = await save_order(upload_id, order_data)
                    order_id_map[order_text] = order_id
                    
                    # Save calculation
                    calc_data = {
                        "worker": row.get("worker", ""),
                        "fuel_payment": row.get("fuel_payment", 0) if not is_extra else 0,
                        "transport": row.get("transport", 0) if not is_extra else 0,
                        "diagnostic_50": row.get("diagnostic_50", 0) if not is_extra else 0,
                        "total": row.get("total", 0),
                    }
                    await save_calculation(upload_id, order_id, calc_data)
                
                # 5. Calculate and save worker totals - ONLY for valid workers
                worker_totals_dict = {}
                for row in calculated_data:
                    worker = normalize_worker_name(row.get("worker", "").replace(" (оплата клиентом)", ""))
                    
                    # Skip non-worker groups (Доставка, Помощник, etc.)
                    if not is_valid_worker_name(worker):
                        continue
                    
                    if worker not in worker_totals_dict:
                        worker_totals_dict[worker] = {
                            "total": 0,
                            "company_total": 0,
                            "client_total": 0,
                            "count": 0,
                            "company_count": 0,
                            "client_count": 0,
                            "fuel": 0,
                            "transport": 0
                        }
                    
                    total = row.get("total", 0)
                    is_client = row.get("is_client_payment", False)
                    
                    if isinstance(total, (int, float)):
                        worker_totals_dict[worker]["total"] += total
                        if is_client:
                            worker_totals_dict[worker]["client_total"] += total
                            worker_totals_dict[worker]["client_count"] += 1
                        else:
                            worker_totals_dict[worker]["company_total"] += total
                            worker_totals_dict[worker]["company_count"] += 1
                    
                    worker_totals_dict[worker]["count"] += 1
                    
                    fuel = row.get("fuel_payment", 0)
                    if isinstance(fuel, (int, float)):
                        worker_totals_dict[worker]["fuel"] += fuel
                    
                    transport = row.get("transport", 0)
                    if isinstance(transport, (int, float)):
                        worker_totals_dict[worker]["transport"] += transport
                
                for worker, totals in worker_totals_dict.items():
                    await save_worker_total(
                        upload_id, 
                        worker, 
                        totals["total"],
                        totals["count"],
                        totals["fuel"],
                        totals["transport"],
                        totals["company_total"],
                        totals["client_total"],
                        totals["company_count"],
                        totals["client_count"]
                    )
                
                # 6. Compare with previous upload if exists
                if prev_upload_id:
                    changes_list = await compare_uploads(prev_upload_id, upload_id)
                    for change in changes_list:
                        if change["type"] == "added":
                            await save_change(upload_id, change["order_code"], change["worker"], "added")
                        elif change["type"] == "deleted":
                            await save_change(upload_id, change["order_code"], change["worker"], "deleted")
                        elif change["type"] == "modified":
                            for field_change in change.get("changes", []):
                                await save_change(
                                    upload_id, 
                                    change["order_code"], 
                                    change["worker"], 
                                    "modified",
                                    field_change["field"],
                                    str(field_change["old"]),
                                    str(field_change["new"])
                                )
                
                print(f"✅ Saved to database: period={period}, upload_id={upload_id}")
        except Exception as db_error:
            print(f"⚠️ Database save error (non-critical): {db_error}")
            # Don't fail the request if DB save fails
        
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


# ============== HISTORY API ENDPOINTS ==============

@app.get("/history")
async def history_page(request: Request):
    """History page - view all periods by month"""
    response = templates.TemplateResponse("history.html", {"request": request})
    # Prevent browser caching so back button shows fresh data
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/periods")
async def api_get_periods():
    """Get all periods grouped by month"""
    try:
        periods = await get_all_periods()
        
        # Enrich periods with total_amount and latest_upload_id
        enriched_periods = []
        for p in periods:
            period_details = await get_period_details(p["id"])
            total_amount = 0
            company_amount = 0
            client_amount = 0
            latest_upload_id = None
            
            if period_details and period_details.get("uploads"):
                latest_upload = period_details["uploads"][0]
                latest_upload_id = latest_upload["id"]
                
                upload_details = await get_upload_details(latest_upload_id)
                if upload_details:
                    worker_totals = upload_details.get("worker_totals", [])
                    for wt in worker_totals:
                        company_amount += wt.get("company_amount", 0) or 0
                        client_amount += wt.get("client_amount", 0) or 0
                    total_amount = company_amount + client_amount
            
            enriched_periods.append({
                **p,
                "total_amount": total_amount,
                "company_amount": company_amount,
                "client_amount": client_amount,
                "latest_upload_id": latest_upload_id
            })
        
        # Group by month
        months = {}
        for p in enriched_periods:
            month_key = p["month"]
            if month_key not in months:
                months[month_key] = {
                    "month": month_key,
                    "year": p["year"],
                    "periods": []
                }
            months[month_key]["periods"].append(p)
        
        return JSONResponse({
            "success": True,
            "months": list(months.values())
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/period/{period_id}")
async def api_get_period(period_id: int):
    """Get period details with uploads"""
    try:
        details = await get_period_details(period_id)
        if not details:
            raise HTTPException(status_code=404, detail="Period not found")
        
        return JSONResponse({
            "success": True,
            "data": details
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/upload/{upload_id}")
async def api_get_upload(upload_id: int):
    """Get upload details with worker totals"""
    try:
        details = await get_upload_details(upload_id)
        if not details:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        return JSONResponse({
            "success": True,
            "data": details
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/upload/{upload_id}/worker/{worker}")
async def api_get_worker_orders(upload_id: int, worker: str):
    """Get all orders for a worker"""
    try:
        from urllib.parse import unquote
        worker_decoded = unquote(worker)
        
        # Get orders for this worker (both regular and client payment)
        orders = await get_worker_orders(upload_id, worker_decoded)
        orders_client = await get_worker_orders(upload_id, f"{worker_decoded} (оплата клиентом)")
        
        # Get worker totals
        upload_details = await get_upload_details(upload_id)
        worker_totals = upload_details.get("worker_totals", []) if upload_details else []
        
        worker_total = None
        for wt in worker_totals:
            if wt.get("worker") == worker_decoded:
                worker_total = wt
                break
        
        return JSONResponse({
            "success": True,
            "data": {
                "worker": worker_decoded,
                "orders": orders + orders_client,
                "worker_total": worker_total
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/worker-report/{upload_id}/{worker}")
async def api_worker_report(upload_id: int, worker: str):
    """Download Excel report for a specific worker"""
    try:
        from urllib.parse import unquote
        worker_decoded = unquote(worker)
        
        # Get upload details
        upload_details = await get_upload_details(upload_id)
        if not upload_details:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        # Get period info
        upload = upload_details.get("upload", {})
        period_id = upload.get("period_id")
        
        period_details = await get_period_details(period_id)
        period_name = period_details.get("period", {}).get("name", "") if period_details else ""
        
        # Get ALL orders for this upload (needed for proper report generation)
        worker_totals_list = upload_details.get("worker_totals", [])
        
        all_orders = []
        for wt in worker_totals_list:
            worker_orders = await get_worker_orders(upload_id, wt["worker"])
            all_orders.extend(worker_orders)
            worker_orders_client = await get_worker_orders(upload_id, f"{wt['worker']} (оплата клиентом)")
            all_orders.extend(worker_orders_client)
        
        # Build calculated_data structure (same as archive generation)
        calculated_data = []
        for order in all_orders:
            calc = order.get("calculation", {})
            row = {
                "worker": order["worker"],
                "order": order.get("order_full", "") or order.get("address", ""),
                "order_code": order.get("order_code", ""),
                "address": order.get("address", ""),
                "revenue_total": order.get("revenue_total", 0),
                "revenue_services": order.get("revenue_services", 0),
                "diagnostic": order.get("diagnostic", 0),
                "diagnostic_payment": order.get("diagnostic_payment", 0),
                "specialist_fee": order.get("specialist_fee", 0),
                "additional_expenses": order.get("additional_expenses", 0),
                "service_payment": order.get("service_payment", 0),
                "percent": order.get("percent", ""),
                "is_client_payment": order.get("is_client_payment", False),
                "is_over_10k": order.get("is_over_10k", False),
                "is_extra_row": order.get("is_extra_row", False),
                "fuel_payment": calc.get("fuel_payment", 0),
                "transport": calc.get("transport", 0),
                "diagnostic_50": calc.get("diagnostic_50", 0),
                "total": calc.get("total", 0),
            }
            calculated_data.append(row)
        
        # Generate worker report using same function as archive
        report_bytes = create_worker_report(calculated_data, worker_decoded, period_name, DEFAULT_CONFIG, for_workers=True)
        
        # Create safe filename
        worker_surname = worker_decoded.split()[0] if worker_decoded else "worker"
        filename = f"{worker_surname}_{period_name.replace('.', '_')}.xlsx"
        
        return Response(
            content=report_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/months-summary")
async def api_months_summary():
    """Get summary by months for dashboard"""
    try:
        summary = await get_months_summary()
        return JSONResponse({
            "success": True,
            "summary": summary
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/comparison")
async def api_comparison():
    """Get comparison data for all periods and workers"""
    try:
        periods = await get_all_periods()
        
        # Get all unique workers and worker totals for each period
        all_workers = set()
        periods_with_totals = []
        
        for period in periods:
            period_details = await get_period_details(period["id"])
            if period_details and period_details.get("uploads"):
                latest_upload = period_details["uploads"][0]
                upload_details = await get_upload_details(latest_upload["id"])
                
                worker_totals = upload_details.get("worker_totals", [])
                for wt in worker_totals:
                    all_workers.add(wt["worker"])
                
                periods_with_totals.append({
                    "id": period["id"],
                    "name": period["name"],
                    "month": period["month"],
                    "worker_totals": worker_totals
                })
        
        # Group by months
        months_map = {}
        for p in periods_with_totals:
            month = p["month"]
            if month not in months_map:
                months_map[month] = {
                    "month": month,
                    "worker_totals": []
                }
            # Aggregate worker totals by month
            for wt in p["worker_totals"]:
                existing = next((w for w in months_map[month]["worker_totals"] if w["worker"] == wt["worker"]), None)
                if existing:
                    existing["total_amount"] = existing.get("total_amount", 0) + wt.get("total_amount", 0)
                    existing["company_amount"] = existing.get("company_amount", 0) + wt.get("company_amount", 0)
                    existing["client_amount"] = existing.get("client_amount", 0) + wt.get("client_amount", 0)
                else:
                    months_map[month]["worker_totals"].append({
                        "worker": wt["worker"],
                        "total_amount": wt.get("total_amount", 0),
                        "company_amount": wt.get("company_amount", 0),
                        "client_amount": wt.get("client_amount", 0)
                    })
        
        months_list = sorted(months_map.values(), key=lambda x: x["month"], reverse=True)
        
        return JSONResponse({
            "success": True,
            "data": {
                "periods": periods_with_totals,
                "months": months_list,
                "workers": sorted(list(all_workers))
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/comparison/export")
async def api_comparison_export():
    """Export comparison table to Excel"""
    try:
        # Get comparison data
        periods = await get_all_periods()
        
        all_workers = set()
        periods_with_totals = []
        
        for period in periods:
            period_details = await get_period_details(period["id"])
            if period_details and period_details.get("uploads"):
                latest_upload = period_details["uploads"][0]
                upload_details = await get_upload_details(latest_upload["id"])
                
                worker_totals = upload_details.get("worker_totals", [])
                for wt in worker_totals:
                    all_workers.add(wt["worker"])
                
                periods_with_totals.append({
                    "id": period["id"],
                    "name": period["name"],
                    "month": period["month"],
                    "worker_totals": worker_totals
                })
        
        workers = sorted(list(all_workers))
        
        # Create Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Сравнение по периодам"
        
        # Header style
        header_fill = PatternFill(start_color="667eea", end_color="667eea", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        
        # Headers
        ws.cell(row=1, column=1, value="Монтажник").fill = header_fill
        ws.cell(row=1, column=1).font = header_font
        
        for col, period in enumerate(periods_with_totals, start=2):
            cell = ws.cell(row=1, column=col, value=period["name"])
            cell.fill = header_fill
            cell.font = header_font
        
        total_col = len(periods_with_totals) + 2
        ws.cell(row=1, column=total_col, value="Всего").fill = header_fill
        ws.cell(row=1, column=total_col).font = header_font
        
        # Data rows
        for row, worker in enumerate(workers, start=2):
            ws.cell(row=row, column=1, value=worker)
            worker_total = 0
            
            for col, period in enumerate(periods_with_totals, start=2):
                wt = next((w for w in period["worker_totals"] if w["worker"] == worker), None)
                value = wt.get("total_amount", 0) if wt else 0
                worker_total += value
                ws.cell(row=row, column=col, value=round(value))
            
            ws.cell(row=row, column=total_col, value=round(worker_total))
        
        # Total row
        total_row = len(workers) + 2
        ws.cell(row=total_row, column=1, value="ИТОГО").font = Font(bold=True)
        
        for col, period in enumerate(periods_with_totals, start=2):
            period_total = sum(w.get("total_amount", 0) for w in period["worker_totals"])
            ws.cell(row=total_row, column=col, value=round(period_total)).font = Font(bold=True)
        
        grand_total = sum(
            sum(w.get("total_amount", 0) for w in p["worker_totals"])
            for p in periods_with_totals
        )
        ws.cell(row=total_row, column=total_col, value=round(grand_total)).font = Font(bold=True)
        
        # Auto-width
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            ws.column_dimensions[column].width = max_length + 2
        
        # Save to bytes
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=comparison.xlsx"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/period/{period_id}/download/{archive_type}")
async def download_period_archive(period_id: int, archive_type: str):
    """Download archive for a specific period - generates full archive like step 4"""
    try:
        period_details = await get_period_details(period_id)
        if not period_details or not period_details.get("uploads"):
            raise HTTPException(status_code=404, detail="Period not found")
        
        latest_upload = period_details["uploads"][0]
        upload_details = await get_upload_details(latest_upload["id"])
        
        # Get worker totals
        worker_totals_list = upload_details.get("worker_totals", [])
        workers = [wt["worker"] for wt in worker_totals_list]
        
        # Get all orders for this upload with FRESH calculation data
        all_orders = []
        for wt in worker_totals_list:
            worker_orders = await get_worker_orders(latest_upload["id"], wt["worker"])
            all_orders.extend(worker_orders)
            # Also get client payment orders
            worker_orders_client = await get_worker_orders(latest_upload["id"], f"{wt['worker']} (оплата клиентом)")
            all_orders.extend(worker_orders_client)
        
        # Reconstruct data structure from current DB values (calculations table!)
        calculated_data = []
        for order in all_orders:
            calc = order.get("calculation", {})
            row = {
                "worker": order["worker"],
                "order": order.get("order_full", "") or order.get("address", ""),
                "order_code": order.get("order_code", ""),
                "address": order.get("address", ""),
                "revenue_total": order.get("revenue_total", 0),
                "revenue_services": order.get("revenue_services", 0),
                "diagnostic": order.get("diagnostic", 0),
                "diagnostic_payment": order.get("diagnostic_payment", 0),
                "specialist_fee": order.get("specialist_fee", 0),
                "additional_expenses": order.get("additional_expenses", 0),
                "service_payment": order.get("service_payment", 0),
                "percent": order.get("percent", ""),
                "is_client_payment": order.get("is_client_payment", False),
                "is_over_10k": order.get("is_over_10k", False),
                "is_extra_row": order.get("is_extra_row", False),
                # CRITICAL: Take values from calculations table (can be edited!)
                "fuel_payment": calc.get("fuel_payment", 0),
                "transport": calc.get("transport", 0),
                "diagnostic_50": calc.get("diagnostic_50", 0),
                "total": calc.get("total", 0),
            }
            calculated_data.append(row)
        
        print(f"📊 Generating archive from {len(calculated_data)} orders")
        # Debug: show some totals
        for wt in worker_totals_list[:3]:
            worker_data = [r for r in calculated_data if r["worker"].replace(" (оплата клиентом)", "") == wt["worker"]]
            calc_total = sum(r.get("total", 0) for r in worker_data)
            print(f"   {wt['worker']}: {len(worker_data)} orders, calc_total={calc_total}")
        
        period_name = period_details["period"]["name"]
        for_workers = (archive_type == "workers")
        
        # Generate FULL archive with all worker files (like step 4)
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Main report
            main_report = create_excel_report(calculated_data, period_name, DEFAULT_CONFIG, for_workers=for_workers)
            main_filename = f"Для_монтажников_{period_name.replace('.', '_')}.xlsx" if for_workers else f"Общий_отчет_{period_name.replace('.', '_')}.xlsx"
            zf.writestr(main_filename, main_report)
            
            # Individual worker reports
            for worker in workers:
                worker_surname = worker.split()[0] if worker else "Unknown"
                worker_report = create_worker_report(calculated_data, worker, period_name, DEFAULT_CONFIG, for_workers=for_workers)
                zf.writestr(f"{worker_surname}_{period_name.replace('.', '_')}.xlsx", worker_report)
        
        zip_buffer.seek(0)
        
        from fastapi.responses import StreamingResponse
        from urllib.parse import quote
        
        # Use ASCII-safe filename and add UTF-8 encoded filename for modern browsers
        archive_name = f"{'Для_монтажников' if for_workers else 'Полный_отчет'}_{period_name.replace('.', '_')}.zip"
        ascii_name = f"{'workers' if for_workers else 'full'}_{period_name.replace('.', '_')}.zip"
        
        # RFC 5987 encoding for non-ASCII filenames
        encoded_name = quote(archive_name)
        
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/comparison")
async def comparison_page(request: Request):
    """Comparison table page"""
    return templates.TemplateResponse("comparison.html", {"request": request})


@app.post("/api/calculation/{calc_id}/update")
async def update_calculation(calc_id: int, request: Request):
    """Update calculation values (fuel, transport, total)"""
    try:
        if not database:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        data = await request.json()
        fuel_payment = data.get("fuel_payment")
        transport = data.get("transport")
        total = data.get("total")
        
        # Build update query
        from sqlalchemy import update
        from database import calculations, orders, save_manual_edit
        
        # First, get current values to record the change
        calc_query = calculations.select().where(calculations.c.id == calc_id)
        calc_row = await database.fetch_one(calc_query)
        
        if not calc_row:
            raise HTTPException(status_code=404, detail="Calculation not found")
        
        # Get order info for logging
        order_query = orders.select().where(orders.c.id == calc_row["order_id"])
        order_row = await database.fetch_one(order_query)
        
        update_values = {}
        edits_to_save = []
        
        # Prepare updates and track changes
        field_names = {
            "fuel_payment": "Бензин",
            "transport": "Транспортные", 
            "total": "Итого"
        }
        
        for field, new_val in [("fuel_payment", fuel_payment), ("transport", transport), ("total", total)]:
            if new_val is not None:
                old_val = calc_row[field] or 0
                new_val_float = float(new_val)
                if old_val != new_val_float:
                    update_values[field] = new_val_float
                    edits_to_save.append({
                        "field": field,
                        "old_value": old_val,
                        "new_value": new_val_float
                    })
        
        if not update_values:
            return JSONResponse({"success": True, "updated": {}, "message": "No changes"})
        
        # Update calculation
        query = update(calculations).where(calculations.c.id == calc_id).values(**update_values)
        await database.execute(query)
        
        # Save manual edits to history
        upload_id = calc_row["upload_id"]
        order_code = order_row["order_code"] if order_row else ""
        worker = calc_row["worker"]
        # For extra_rows, address is stored in order_full
        address = order_row["address"] if order_row and order_row["address"] else ""
        if not address and order_row and order_row.get("order_full"):
            address = order_row["order_full"][:200]  # Use order_full as address for extra rows
        
        for edit in edits_to_save:
            await save_manual_edit(
                upload_id=upload_id,
                order_id=calc_row["order_id"],
                calculation_id=calc_id,
                order_code=order_code,
                worker=worker,
                address=address,
                field_name=edit["field"],
                old_value=edit["old_value"],
                new_value=edit["new_value"]
            )
            print(f"📝 Manual edit saved: {order_code} {worker} - {edit['field']}: {edit['old_value']} → {edit['new_value']}")
        
        # Update worker_totals
        full_worker = calc_row["worker"]
        base_worker = full_worker.replace(" (оплата клиентом)", "")
        
        from database import worker_totals
        from sqlalchemy import and_, text
        
        # Get all orders and calculations for this worker using JOIN
        # This correctly uses orders.is_client_payment flag
        query = text("""
            SELECT c.total, c.fuel_payment, c.transport, o.is_client_payment
            FROM calculations c
            JOIN orders o ON c.order_id = o.id
            WHERE c.upload_id = :upload_id
            AND (o.worker = :worker OR o.worker = :worker_client)
        """).bindparams(
            upload_id=upload_id,
            worker=base_worker,
            worker_client=f"{base_worker} (оплата клиентом)"
        )
        
        all_calcs = await database.fetch_all(query)
        
        company_amount = sum(c["total"] or 0 for c in all_calcs if not c["is_client_payment"])
        client_amount = sum(c["total"] or 0 for c in all_calcs if c["is_client_payment"])
        total_amount = company_amount + client_amount
        
        new_fuel = sum(c["fuel_payment"] or 0 for c in all_calcs)
        new_transport = sum(c["transport"] or 0 for c in all_calcs)
        
        # Update worker_totals
        update_wt = update(worker_totals).where(
            and_(
                worker_totals.c.upload_id == upload_id,
                worker_totals.c.worker == base_worker
            )
        ).values(
            total_amount=total_amount,
            company_amount=company_amount,
            client_amount=client_amount,
            fuel_total=new_fuel,
            transport_total=new_transport
        )
        await database.execute(update_wt)
        
        print(f"✅ Updated calculation {calc_id}: {update_values}")
        print(f"   Worker {base_worker}: company={company_amount}, client={client_amount}, total={total_amount}")
        
        return JSONResponse({
            "success": True,
            "updated": update_values
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/order/{order_id}")
async def delete_order(order_id: int):
    """Delete an order and its calculation from the database"""
    try:
        if not database:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        from sqlalchemy import delete, and_, update, text
        from database import orders, calculations, worker_totals, manual_edits
        
        # First, get order info for updating worker_totals
        order_query = orders.select().where(orders.c.id == order_id)
        order = await database.fetch_one(order_query)
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        upload_id = order["upload_id"]
        full_worker = order["worker"]
        base_worker = full_worker.replace(" (оплата клиентом)", "")
        
        # Get calculation info for logging
        calc_query = calculations.select().where(calculations.c.order_id == order_id)
        calc = await database.fetch_one(calc_query)
        
        deleted_total = calc["total"] if calc else 0
        calc_id = calc["id"] if calc else None
        
        # Delete manual_edits first (they reference calculation)
        if calc_id:
            del_edits = delete(manual_edits).where(manual_edits.c.calculation_id == calc_id)
            await database.execute(del_edits)
        
        # Also delete manual_edits by order_id
        del_edits_order = delete(manual_edits).where(manual_edits.c.order_id == order_id)
        await database.execute(del_edits_order)
        
        # Delete calculation (foreign key to orders)
        del_calc = delete(calculations).where(calculations.c.order_id == order_id)
        await database.execute(del_calc)
        
        # Delete order
        del_order = delete(orders).where(orders.c.id == order_id)
        await database.execute(del_order)
        
        # FULL RECALCULATION of worker_totals (same logic as update_calculation)
        # This is more reliable than incremental subtraction
        query = text("""
            SELECT c.total, c.fuel_payment, c.transport, o.is_client_payment
            FROM calculations c
            JOIN orders o ON c.order_id = o.id
            WHERE c.upload_id = :upload_id
            AND (o.worker = :worker OR o.worker = :worker_client)
        """).bindparams(
            upload_id=upload_id,
            worker=base_worker,
            worker_client=f"{base_worker} (оплата клиентом)"
        )
        
        all_calcs = await database.fetch_all(query)
        
        company_amount = sum(c["total"] or 0 for c in all_calcs if not c["is_client_payment"])
        client_amount = sum(c["total"] or 0 for c in all_calcs if c["is_client_payment"])
        total_amount = company_amount + client_amount
        
        new_fuel = sum(c["fuel_payment"] or 0 for c in all_calcs)
        new_transport = sum(c["transport"] or 0 for c in all_calcs)
        
        # Count orders
        company_count = sum(1 for c in all_calcs if not c["is_client_payment"])
        client_count = sum(1 for c in all_calcs if c["is_client_payment"])
        
        # Update worker_totals
        update_wt = update(worker_totals).where(
            and_(
                worker_totals.c.upload_id == upload_id,
                worker_totals.c.worker == base_worker
            )
        ).values(
            total_amount=total_amount,
            company_amount=company_amount,
            client_amount=client_amount,
            fuel_total=new_fuel,
            transport_total=new_transport,
            orders_count=company_count + client_count,
            company_orders_count=company_count,
            client_orders_count=client_count
        )
        await database.execute(update_wt)
        
        print(f"🗑️ Deleted order {order_id} (worker: {base_worker}, deleted_total: {deleted_total})")
        print(f"   Recalculated: company={company_amount}, client={client_amount}, total={total_amount}")
        
        return JSONResponse({
            "success": True,
            "deleted_order_id": order_id,
            "deleted_total": deleted_total
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload/{upload_id}/worker/{worker}/add-row")
async def add_order_row(upload_id: int, worker: str, request: Request):
    """Add a new order row for a worker"""
    try:
        if not database:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        from urllib.parse import unquote
        from sqlalchemy import and_, update
        from database import orders, calculations, worker_totals
        
        worker_decoded = unquote(worker)
        data = await request.json()
        
        order_code = data.get("order_code", "")
        address = data.get("address", "")
        fuel_payment = float(data.get("fuel_payment", 0) or 0)
        transport = float(data.get("transport", 0) or 0)
        total = float(data.get("total", 0) or 0)
        
        # Determine if client payment
        is_client_payment = "(оплата клиентом)" in worker_decoded
        base_worker = worker_decoded.replace(" (оплата клиентом)", "")
        
        # Create order text
        order_text = f"{order_code}, {address}" if order_code and address else (order_code or address or "Ручная запись")
        
        # Insert new order
        order_insert = orders.insert().values(
            upload_id=upload_id,
            worker=worker_decoded,
            order_code=order_code,
            order_full=order_text,
            address=address,
            revenue_total=0,
            revenue_services=0,
            diagnostic=0,
            diagnostic_payment=0,
            specialist_fee=0,
            additional_expenses=0,
            service_payment=0,
            percent="",
            is_client_payment=is_client_payment,
            is_over_10k=False,
            is_extra_row=True  # Mark as manual/extra row
        )
        order_id = await database.execute(order_insert)
        
        # Insert calculation
        calc_insert = calculations.insert().values(
            upload_id=upload_id,
            order_id=order_id,
            worker=worker_decoded,
            fuel_payment=fuel_payment,
            transport=transport,
            diagnostic_50=0,
            total=total
        )
        calc_id = await database.execute(calc_insert)
        
        # FULL RECALCULATION of worker_totals (same logic as update_calculation)
        from sqlalchemy import text
        
        query = text("""
            SELECT c.total, c.fuel_payment, c.transport, o.is_client_payment
            FROM calculations c
            JOIN orders o ON c.order_id = o.id
            WHERE c.upload_id = :upload_id
            AND (o.worker = :worker OR o.worker = :worker_client)
        """).bindparams(
            upload_id=upload_id,
            worker=base_worker,
            worker_client=f"{base_worker} (оплата клиентом)"
        )
        
        all_calcs = await database.fetch_all(query)
        
        company_amount = sum(c["total"] or 0 for c in all_calcs if not c["is_client_payment"])
        client_amount = sum(c["total"] or 0 for c in all_calcs if c["is_client_payment"])
        total_amount = company_amount + client_amount
        
        new_fuel = sum(c["fuel_payment"] or 0 for c in all_calcs)
        new_transport = sum(c["transport"] or 0 for c in all_calcs)
        
        # Count orders
        company_count = sum(1 for c in all_calcs if not c["is_client_payment"])
        client_count = sum(1 for c in all_calcs if c["is_client_payment"])
        
        # Update worker_totals
        update_wt = update(worker_totals).where(
            and_(
                worker_totals.c.upload_id == upload_id,
                worker_totals.c.worker == base_worker
            )
        ).values(
            total_amount=total_amount,
            company_amount=company_amount,
            client_amount=client_amount,
            fuel_total=new_fuel,
            transport_total=new_transport,
            orders_count=company_count + client_count,
            company_orders_count=company_count,
            client_orders_count=client_count
        )
        await database.execute(update_wt)
        
        print(f"➕ Added new row for {worker_decoded}: order_code={order_code}, total={total}")
        print(f"   Recalculated: company={company_amount}, client={client_amount}, total={total_amount}")
        
        # Return the new order data
        return JSONResponse({
            "success": True,
            "order": {
                "id": order_id,
                "order_code": order_code,
                "address": address,
                "order_full": order_text,
                "worker": worker_decoded,
                "revenue_services": 0,
                "service_payment": 0,
                "percent": "",
                "is_client_payment": is_client_payment,
                "is_over_10k": False,
                "is_extra_row": True,
                "calculation": {
                    "id": calc_id,
                    "fuel_payment": fuel_payment,
                    "transport": transport,
                    "total": total
                }
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/order/{order_id}/update")
async def update_order_info(order_id: int, request: Request):
    """Update order info (order_code, address) - for manually added rows"""
    try:
        if not database:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        from sqlalchemy import update
        from database import orders
        
        data = await request.json()
        
        update_values = {}
        if "order_code" in data:
            update_values["order_code"] = data["order_code"]
        if "address" in data:
            update_values["address"] = data["address"]
        
        if update_values:
            # Also update order_full
            order_query = orders.select().where(orders.c.id == order_id)
            order = await database.fetch_one(order_query)
            
            if order:
                new_order_code = data.get("order_code", order["order_code"] or "")
                new_address = data.get("address", order["address"] or "")
                order_text = f"{new_order_code}, {new_address}" if new_order_code and new_address else (new_order_code or new_address or "Ручная запись")
                update_values["order_full"] = order_text
        
        if not update_values:
            return JSONResponse({"success": True, "message": "No changes"})
        
        query = update(orders).where(orders.c.id == order_id).values(**update_values)
        await database.execute(query)
        
        print(f"📝 Updated order {order_id}: {update_values}")
        
        return JSONResponse({
            "success": True,
            "updated": update_values
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/period/{period_id}")
async def period_page(request: Request, period_id: int):
    """Period details page"""
    response = templates.TemplateResponse("period.html", {"request": request, "period_id": period_id})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/upload/{upload_id}")
async def upload_page(request: Request, upload_id: int, worker: str = ""):
    """Upload details page"""
    # Get worker from query parameter
    worker_name = worker or request.query_params.get("worker", "")
    response = templates.TemplateResponse("upload.html", {
        "request": request, 
        "upload_id": upload_id,
        "worker_name": worker_name
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ============================================================================
# 1C INTEGRATION
# ============================================================================

# 1C Configuration - UPDATE THESE VALUES
ONEС_CONFIG = {
    "enabled": False,  # Set to True when 1C HTTP service is ready
    "base_url": "http://your-1c-server/your-database/hs/salary",  # Update with your 1C server URL
    "username": "api_user",  # 1C username for API access
    "password": "api_password",  # 1C password
    "timeout": 10,  # Request timeout in seconds
}


@app.get("/api/1c/order/{order_code}")
async def get_1c_order_info(order_code: str):
    """
    Get order information from 1C.
    This endpoint proxies requests to the 1C HTTP service.
    """
    import httpx
    from urllib.parse import quote
    
    # Check if 1C integration is enabled
    if not ONEС_CONFIG["enabled"]:
        return JSONResponse({
            "success": False,
            "error": "Интеграция с 1С не настроена",
            "hint": "Необходимо настроить HTTP-сервис в 1С и обновить конфигурацию"
        })
    
    try:
        # Build 1C API URL
        url = f"{ONEС_CONFIG['base_url']}/orders/{quote(order_code)}"
        
        # Make request to 1C with basic auth
        auth = (ONEС_CONFIG["username"], ONEС_CONFIG["password"])
        
        async with httpx.AsyncClient(timeout=ONEС_CONFIG["timeout"]) as client:
            response = await client.get(url, auth=auth)
            
            if response.status_code == 200:
                data = response.json()
                return JSONResponse(data)
            elif response.status_code == 401:
                return JSONResponse({
                    "success": False,
                    "error": "Ошибка авторизации в 1С"
                })
            elif response.status_code == 404:
                return JSONResponse({
                    "success": False,
                    "error": f"Заказ {order_code} не найден в 1С"
                })
            else:
                return JSONResponse({
                    "success": False,
                    "error": f"Ошибка 1С: {response.status_code}"
                })
                
    except httpx.TimeoutException:
        return JSONResponse({
            "success": False,
            "error": "Превышено время ожидания ответа от 1С"
        })
    except httpx.ConnectError:
        return JSONResponse({
            "success": False,
            "error": "Не удалось подключиться к серверу 1С"
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": f"Ошибка: {str(e)}"
        })


@app.get("/api/1c/status")
async def get_1c_status():
    """Check 1C integration status"""
    return JSONResponse({
        "enabled": ONEС_CONFIG["enabled"],
        "base_url": ONEС_CONFIG["base_url"] if ONEС_CONFIG["enabled"] else None,
        "message": "Интеграция с 1С активна" if ONEС_CONFIG["enabled"] else "Интеграция с 1С не настроена"
    })


@app.post("/api/upload/{upload_id}/recalculate")
async def recalculate_worker_totals(upload_id: int):
    """
    Force recalculation of all worker_totals for an upload.
    Use this to fix any inconsistencies in the data.
    """
    try:
        if not database:
            raise HTTPException(status_code=500, detail="Database not connected")
        
        from sqlalchemy import and_, update, text
        from database import worker_totals
        
        # Get all workers for this upload
        wt_query = worker_totals.select().where(worker_totals.c.upload_id == upload_id)
        all_wt = await database.fetch_all(wt_query)
        
        recalculated = []
        
        for wt in all_wt:
            base_worker = wt["worker"]
            
            # Full recalculation using JOIN
            query = text("""
                SELECT c.total, c.fuel_payment, c.transport, o.is_client_payment
                FROM calculations c
                JOIN orders o ON c.order_id = o.id
                WHERE c.upload_id = :upload_id
                AND (o.worker = :worker OR o.worker = :worker_client)
            """).bindparams(
                upload_id=upload_id,
                worker=base_worker,
                worker_client=f"{base_worker} (оплата клиентом)"
            )
            
            all_calcs = await database.fetch_all(query)
            
            company_amount = sum(c["total"] or 0 for c in all_calcs if not c["is_client_payment"])
            client_amount = sum(c["total"] or 0 for c in all_calcs if c["is_client_payment"])
            total_amount = company_amount + client_amount
            
            new_fuel = sum(c["fuel_payment"] or 0 for c in all_calcs)
            new_transport = sum(c["transport"] or 0 for c in all_calcs)
            
            company_count = sum(1 for c in all_calcs if not c["is_client_payment"])
            client_count = sum(1 for c in all_calcs if c["is_client_payment"])
            
            # Update worker_totals
            update_wt = update(worker_totals).where(
                and_(
                    worker_totals.c.upload_id == upload_id,
                    worker_totals.c.worker == base_worker
                )
            ).values(
                total_amount=total_amount,
                company_amount=company_amount,
                client_amount=client_amount,
                fuel_total=new_fuel,
                transport_total=new_transport,
                orders_count=company_count + client_count,
                company_orders_count=company_count,
                client_orders_count=client_count
            )
            await database.execute(update_wt)
            
            recalculated.append({
                "worker": base_worker,
                "company_amount": company_amount,
                "client_amount": client_amount,
                "total_amount": total_amount
            })
            
            print(f"🔄 Recalculated {base_worker}: company={company_amount}, client={client_amount}, total={total_amount}")
        
        return JSONResponse({
            "success": True,
            "recalculated_count": len(recalculated),
            "workers": recalculated
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recalculate-all-totals")
async def recalculate_all_totals():
    """Recalculate worker_totals for ALL uploads based on actual order calculations"""
    try:
        from sqlalchemy import text
        
        # Get all uploads
        query = text("SELECT DISTINCT upload_id FROM orders")
        uploads = await database.fetch_all(query)
        
        recalculated_uploads = []
        
        for upload_row in uploads:
            upload_id = upload_row["upload_id"]
            
            # Get all orders with calculations for this upload
            query = text("""
                SELECT o.worker, o.is_client_payment, c.total
                FROM orders o
                JOIN calculations c ON c.order_id = o.id
                WHERE o.upload_id = :upload_id
            """).bindparams(upload_id=upload_id)
            
            order_calcs = await database.fetch_all(query)
            
            # Aggregate by worker
            worker_sums = {}
            for oc in order_calcs:
                worker = oc["worker"]
                if worker not in worker_sums:
                    worker_sums[worker] = {"company": 0, "client": 0}
                
                total = oc["total"] or 0
                if oc["is_client_payment"]:
                    worker_sums[worker]["client"] += total
                else:
                    worker_sums[worker]["company"] += total
            
            # Update worker_totals
            for worker, sums in worker_sums.items():
                # Check if worker_total exists
                check_query = text("""
                    SELECT id FROM worker_totals WHERE upload_id = :upload_id AND worker = :worker
                """).bindparams(upload_id=upload_id, worker=worker)
                existing = await database.fetch_one(check_query)
                
                if existing:
                    update_query = text("""
                        UPDATE worker_totals 
                        SET company_amount = :company, client_amount = :client, total_amount = :total
                        WHERE upload_id = :upload_id AND worker = :worker
                    """).bindparams(
                        company=sums["company"],
                        client=sums["client"],
                        total=sums["company"] + sums["client"],
                        upload_id=upload_id,
                        worker=worker
                    )
                    await database.execute(update_query)
                else:
                    insert_query = text("""
                        INSERT INTO worker_totals (upload_id, worker, company_amount, client_amount, total_amount)
                        VALUES (:upload_id, :worker, :company, :client, :total)
                    """).bindparams(
                        upload_id=upload_id,
                        worker=worker,
                        company=sums["company"],
                        client=sums["client"],
                        total=sums["company"] + sums["client"]
                    )
                    await database.execute(insert_query)
            
            recalculated_uploads.append({
                "upload_id": upload_id,
                "workers_count": len(worker_sums)
            })
            print(f"✅ Recalculated upload {upload_id}: {len(worker_sums)} workers")
        
        return JSONResponse({
            "success": True,
            "recalculated_uploads": len(recalculated_uploads),
            "details": recalculated_uploads
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
