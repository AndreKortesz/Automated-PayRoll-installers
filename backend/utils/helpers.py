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
    """Parse percent value from string like '30,00 %', '40%', or 'Оплата монтажнику 40%'"""
    if pd.isna(value):
        return 0
    if isinstance(value, (int, float)):
        return float(value) * 100 if value <= 1 else float(value)
    
    text = str(value)
    
    # First try to extract number followed by % (handles "Оплата монтажнику 40%")
    import re
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', text)
    if match:
        try:
            return float(match.group(1).replace(',', '.'))
        except:
            pass
    
    # Fallback: try to parse the whole string as number
    text = text.replace(',', '.').replace('%', '').replace(' ', '')
    try:
        return float(text)
    except:
        # Last resort: extract any number from string
        match = re.search(r'(\d+(?:[.,]\d+)?)', str(value))
        if match:
            try:
                return float(match.group(1).replace(',', '.'))
            except:
                pass
        return 0


def extract_address_from_order(order_text: str) -> str:
    """Extract address from order text, handling multiline addresses"""
    if not order_text or pd.isna(order_text):
        return ""
    
    text = str(order_text)
    
    skip_patterns = ["ОБУЧЕНИЕ", "обучение", "двойная оплата", "В прошлом расчете", 
                     "комплекты интернета", "комплект интернета"]
    for pattern in skip_patterns:
        if pattern in text:
            return ""
    
    # Manager comment patterns - these are NOT addresses
    manager_patterns = [
        r'^оплата монтажник',
        r'^зарплата\s+\d',
        r'^оплатить\s+\d',
    ]
    
    # Comment patterns (second line) - these are NOT part of address, skip them
    comment_patterns = [
        r'^помощник',
        r'^физ\s*лицо',
        r'^\(гараж\)',
        r'^\(этаж',
        r'^В монтажный',
        r'^стяжк',
    ]
    
    def is_manager_comment(line):
        return any(re.match(p, line.strip(), re.IGNORECASE) for p in manager_patterns)
    
    def is_comment_line(line):
        return any(re.match(p, line.strip(), re.IGNORECASE) for p in comment_patterns)
    
    def process_address_lines(lines):
        """Process lines after datetime, return clean address with all parts"""
        if not lines:
            return ""
        
        result_parts = []
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Skip manager comments (like "Оплата монтажнику 40%")
            if is_manager_comment(line):
                continue
            
            # For subsequent lines, skip if it's a technical comment
            if i > 0 and is_comment_line(line):
                continue
                
            result_parts.append(line)
        
        # Join all address parts with comma
        addr = ', '.join(result_parts) if result_parts else ""
        addr = clean_address_for_geocoding(addr)
        return addr.strip()
    
    # Pattern 1: Full datetime format "27.10.2025 0:00:00, address"
    match = re.search(r'\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2},\s*(.+)', text, re.DOTALL)
    if match:
        addr_part = match.group(1).strip()
        lines = addr_part.split('\n')
        return process_address_lines(lines)
    
    # Pattern 2: Short time format "0:00:00, address"
    match = re.search(r'\d:\d{2}:\d{2},\s*(.+)', text, re.DOTALL)
    if match:
        addr_part = match.group(1).strip()
        lines = addr_part.split('\n')
        return process_address_lines(lines)
    
    # Pattern 3: Date only format "27.10.2025, address" (no time)
    match = re.search(r'\d{2}\.\d{2}\.\d{4},\s*(.+)', text, re.DOTALL)
    if match:
        addr_part = match.group(1).strip()
        lines = addr_part.split('\n')
        return process_address_lines(lines)
    
    return ""


def clean_address_for_geocoding(addr: str) -> str:
    """Clean address from garbage that prevents geocoding"""
    if not addr:
        return ""
    
    # Remove OZON/DDX prefixes - they prevent geocoding
    addr = re.sub(r'^OZON\s+', '', addr)
    addr = re.sub(r'^DDX\s*-?\s*', '', addr)
    
    # Remove manager comments that got mixed into address
    manager_patterns = [
        r'^Оплата монтажнику\s*\d*%?\s*,?\s*',  # At start
        r',?\s*Оплата монтажнику\s*\d*%?\s*$',  # At end
        r'^оплатить\s+\d+\s*,?\s*',  # "оплатить 7000"
        r'^зарплата\s+\d+.*?,?\s*',  # "зарплата 3500 (ПС Тимофеев)"
    ]
    for pattern in manager_patterns:
        addr = re.sub(pattern, '', addr, flags=re.IGNORECASE)
    
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
