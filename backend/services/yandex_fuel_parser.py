"""
Parser for Yandex Fuel (Яндекс Заправки) reports
"""

import pandas as pd
from io import BytesIO
from typing import Dict, Optional
from utils.workers import normalize_worker_name


def parse_yandex_fuel_file(file_content: bytes, name_map: dict = None) -> Dict[str, float]:
    """
    Parse Yandex Fuel report and return fuel deductions per worker.
    
    The report has:
    - Header rows at the top (company info, period, etc.)
    - Column headers row with "Имя пользователя" and "Стоимость"
    - Data rows with fuel transactions
    
    Returns dict: {worker_name: deduction_amount}
    where deduction_amount = total_fuel * 0.9 (10% discount for employees)
    """
    if name_map is None:
        name_map = {}
    
    try:
        # Wrap bytes in BytesIO
        file_io = BytesIO(file_content)
        
        # Read Excel file
        df = pd.read_excel(file_io, header=None)
        
        # Find header row (contains "Имя пользователя")
        header_row = None
        for i, row in df.iterrows():
            row_str = ' '.join(str(v) for v in row.values)
            if 'Имя пользователя' in row_str:
                header_row = i
                break
        
        if header_row is None:
            print("⚠️ Yandex Fuel: Could not find header row with 'Имя пользователя'")
            return {}
        
        # Re-read with correct header
        file_io.seek(0)  # Reset file pointer
        df = pd.read_excel(file_io, header=header_row)
        
        # Check required columns exist
        if 'Имя пользователя' not in df.columns or 'Стоимость' not in df.columns:
            print(f"⚠️ Yandex Fuel: Missing required columns. Found: {list(df.columns)}")
            return {}
        
        # Filter only rows with valid numeric Стоимость
        df_clean = df[pd.to_numeric(df['Стоимость'], errors='coerce').notna()].copy()
        
        if df_clean.empty:
            print("⚠️ Yandex Fuel: No valid data rows found")
            return {}
        
        # Group by worker and sum amounts
        totals = df_clean.groupby('Имя пользователя')['Стоимость'].sum()
        
        # Apply 10% discount (multiply by 0.9) and normalize names
        result = {}
        for name, total in totals.items():
            if pd.isna(name) or not name:
                continue
            
            # Normalize worker name to match main payroll names
            normalized_name = normalize_worker_name(str(name), name_map)
            
            # Apply 10% discount (employee benefit)
            deduction = round(total * 0.9, 2)
            
            result[normalized_name] = deduction
            print(f"⛽ Яндекс Заправки: {name} -> {normalized_name}: {total:.2f} руб, вычет: {deduction:.2f} руб")
        
        return result
        
    except Exception as e:
        print(f"❌ Error parsing Yandex Fuel file: {e}")
        import traceback
        traceback.print_exc()
        return {}


def detect_yandex_fuel_file(file_content: bytes) -> bool:
    """
    Detect if file is a Yandex Fuel report.
    
    Looks for specific markers:
    - "Яндекс" or "Заправк" in content
    - Columns like "Имя пользователя", "Стоимость", "АЗС", "Топливо"
    """
    try:
        file_io = BytesIO(file_content)
        df = pd.read_excel(file_io, header=None, nrows=20)
        
        # Convert to string for searching
        content_str = df.to_string().lower()
        
        # Check for Yandex Fuel markers
        markers = [
            'яндекс' in content_str or 'yandex' in content_str,
            'заправк' in content_str or 'fuel' in content_str.lower(),
            'азс' in content_str,
            'топливо' in content_str,
            'стоимость' in content_str,
        ]
        
        # If at least 3 markers match, it's likely a Yandex Fuel report
        if sum(markers) >= 3:
            return True
        
        # Also check for specific column pattern
        for i, row in df.iterrows():
            row_str = ' '.join(str(v) for v in row.values).lower()
            if 'имя пользователя' in row_str and 'стоимость' in row_str:
                return True
        
        return False
        
    except Exception as e:
        print(f"Error detecting Yandex Fuel file: {e}")
        return False


def is_second_half_period(period: str) -> bool:
    """
    Check if period is for second half of month (16-28/29/30/31).
    Yandex Fuel deductions should only apply to second half periods.
    
    Period format examples:
    - "16-30.11.25" (November)
    - "16-31.12.25" (December)
    - "16-28.02.25" (February normal year)
    - "16-29.02.24" (February leap year)
    - "1-15.11.25" (First half - should return False)
    """
    if not period:
        return False
    
    try:
        # Extract start day from period (before first '-')
        parts = period.split('-')
        if len(parts) >= 1:
            # Handle cases like "16-30.11.25" -> start_day = 16
            start_day_str = parts[0].strip()
            start_day = int(start_day_str)
            # Second half of month starts from day 16
            return start_day >= 16
    except (ValueError, IndexError):
        pass
    
    return False
