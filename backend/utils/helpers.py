"""
Helper functions for data parsing and formatting
"""

import re
import pandas as pd
from io import BytesIO


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
