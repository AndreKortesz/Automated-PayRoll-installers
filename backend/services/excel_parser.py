"""
Excel file parsing from 1C exports
"""

import pandas as pd
from io import BytesIO

from utils.workers import (
    build_worker_name_map,
    normalize_worker_name,
    is_valid_worker_name,
)


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
