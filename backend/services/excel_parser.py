"""
Excel file parsing from 1C exports
"""

import pandas as pd
import re
from io import BytesIO

from utils.workers import (
    build_worker_name_map,
    normalize_worker_name,
    is_valid_worker_name,
    is_manager,
)


def parse_manager_comment(comment: str) -> dict:
    """Parse manager comment to extract payment instructions.
    
    Returns dict with:
    - type: 'percent' | 'fixed' | 'info' | None
    - value: numeric value (percent or fixed amount)
    - original: original comment text
    """
    if not comment or pd.isna(comment):
        return None
    
    comment = str(comment).strip()
    if not comment:
        return None
    
    result = {
        "type": None,
        "value": None,
        "original": comment
    }
    
    comment_lower = comment.lower()
    
    # Pattern: "Оплата монтажнику 40%" or "оплатить 40%"
    percent_match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', comment)
    if percent_match and ('оплат' in comment_lower or 'монтажник' in comment_lower):
        result["type"] = "percent"
        result["value"] = float(percent_match.group(1).replace(',', '.'))
        return result
    
    # Pattern: "зарплата 3500" or "оплатить 7000" or "оплата 5000"
    fixed_match = re.search(r'(?:зарплата|оплатить|оплата)\s*(\d+(?:[.,]\d+)?)', comment_lower)
    if fixed_match:
        result["type"] = "fixed"
        result["value"] = float(fixed_match.group(1).replace(',', '.'))
        return result
    
    # Pattern: just a number like "7000" or "3500"
    just_number = re.match(r'^(\d+(?:[.,]\d+)?)\s*(?:руб|₽)?\.?$', comment.strip())
    if just_number:
        result["type"] = "fixed"
        result["value"] = float(just_number.group(1).replace(',', '.'))
        return result
    
    # Informational comment (no action needed)
    result["type"] = "info"
    return result


def parse_excel_file(file_bytes: bytes, is_over_10k: bool, name_map: dict = None) -> tuple:
    """Parse Excel file from 1C and extract data.
    Returns (DataFrame, set of worker names found, list of manager comments, list of warnings)
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
    
    # Detect column layout by checking subheader row
    subheader_row = header_row + 1
    has_manager_column = False
    manager_col_idx = 5  # Default position
    
    if subheader_row < len(df):
        subheader = df.iloc[subheader_row]
        for idx, val in enumerate(subheader.values):
            if pd.notna(val) and 'ЗП от менеджера' in str(val):
                has_manager_column = True
                manager_col_idx = idx
                print(f"📋 Обнаружена колонка 'ЗП от менеджера' в позиции {idx}")
                break
    
    # Define column indices based on layout
    # New format (with manager column): col 5 is manager, data starts at col 6
    # Old format: data starts at col 4
    if has_manager_column:
        col_revenue_total = 6
        col_revenue_services = 7
        col_diagnostic = 8
        col_diagnostic_payment = 9
        col_specialist_fee = 10
        col_additional_expenses = 11
        col_service_payment = 12
        col_percent = 13
    else:
        col_revenue_total = 4
        col_revenue_services = 5
        col_diagnostic = 6
        col_diagnostic_payment = 7
        col_specialist_fee = 8
        col_additional_expenses = 9
        col_service_payment = 10
        col_percent = 11
    
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
        return None, all_worker_names, [], []
    
    # Second pass: extract records with normalized names
    records = []
    manager_comments = []  # Collect orders with manager comments
    warnings = []  # Collect warnings (e.g., managers in data)
    managers_found = set()  # Track unique managers found
    current_worker = None
    is_client_payment_section = False
    is_valid_worker = False
    
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
            
            is_valid_worker = is_valid_worker_name(first_col_str)
            
            if is_valid_worker:
                worker_name = normalize_worker_name(worker_name, name_map)
                current_worker = worker_name
                
                # Check if this is a manager (should not be in calculation)
                if is_manager(worker_name) and worker_name not in managers_found:
                    managers_found.add(worker_name)
                    print(f"⚠️ ПРЕДУПРЕЖДЕНИЕ: В расчёт попал менеджер: {worker_name}")
            else:
                current_worker = None
            
            continue
        else:
            # This is an order row
            if current_worker and is_valid_worker:
                # Extract manager comment if present
                manager_comment_raw = None
                manager_comment_parsed = None
                if has_manager_column:
                    manager_val = row.iloc[manager_col_idx] if manager_col_idx < len(row) else None
                    if pd.notna(manager_val) and str(manager_val).strip():
                        manager_comment_raw = str(manager_val).strip()
                        manager_comment_parsed = parse_manager_comment(manager_comment_raw)
                
                record = {
                    "worker": normalize_worker_name(current_worker, name_map),
                    "order": first_col_str,
                    "revenue_total": row.iloc[col_revenue_total] if col_revenue_total < len(row) and pd.notna(row.iloc[col_revenue_total]) else 0,
                    "revenue_services": row.iloc[col_revenue_services] if col_revenue_services < len(row) and pd.notna(row.iloc[col_revenue_services]) else 0,
                    "diagnostic": row.iloc[col_diagnostic] if col_diagnostic < len(row) and pd.notna(row.iloc[col_diagnostic]) else 0,
                    "diagnostic_payment": row.iloc[col_diagnostic_payment] if col_diagnostic_payment < len(row) and pd.notna(row.iloc[col_diagnostic_payment]) else 0,
                    "specialist_fee": row.iloc[col_specialist_fee] if col_specialist_fee < len(row) and pd.notna(row.iloc[col_specialist_fee]) else 0,
                    "additional_expenses": row.iloc[col_additional_expenses] if col_additional_expenses < len(row) and pd.notna(row.iloc[col_additional_expenses]) else 0,
                    "service_payment": row.iloc[col_service_payment] if col_service_payment < len(row) and pd.notna(row.iloc[col_service_payment]) else 0,
                    "percent": row.iloc[col_percent] if col_percent < len(row) else 0,
                    "is_over_10k": is_over_10k,
                    "is_client_payment": is_client_payment_section,
                    "is_worker_total": False,
                    "manager_comment": manager_comment_raw,
                    "manager_comment_parsed": manager_comment_parsed
                }
                records.append(record)
                
                # Track orders with manager comments (including info for display)
                if manager_comment_parsed and manager_comment_parsed["type"] in ["percent", "fixed", "info"]:
                    manager_comments.append({
                        "worker": record["worker"],
                        "order": first_col_str,
                        "comment": manager_comment_raw,
                        "parsed": manager_comment_parsed,
                        "revenue_services": record["revenue_services"],
                        "current_service_payment": record["service_payment"],
                        "is_over_10k": is_over_10k
                    })
    
    # Add warnings for managers found
    for manager_name in managers_found:
        warnings.append({
            "type": "manager_in_data",
            "message": f"В расчёт попал менеджер: {manager_name}",
            "worker": manager_name,
            "severity": "error"
        })
    
    return pd.DataFrame(records), all_worker_names, manager_comments, warnings


def parse_both_excel_files(content_under: bytes, content_over: bytes) -> tuple:
    """Parse both Excel files and return combined DataFrame with normalized worker names.
    Returns (combined_df, name_map, manager_comments, warnings)
    """
    # First pass: collect all worker names from both files
    _, names_under, _, _ = parse_excel_file(content_under, is_over_10k=False, name_map=None)
    _, names_over, _, _ = parse_excel_file(content_over, is_over_10k=True, name_map=None)
    
    all_names = names_under | names_over
    
    # Build normalization map from all names
    name_map = build_worker_name_map(all_names)
    if name_map:
        print(f"📋 Нормализация имён: {name_map}")
    
    # Second pass: parse with normalization
    df_under, _, comments_under, warnings_under = parse_excel_file(content_under, is_over_10k=False, name_map=name_map)
    df_over, _, comments_over, warnings_over = parse_excel_file(content_over, is_over_10k=True, name_map=name_map)
    
    combined = pd.concat([df_over, df_under], ignore_index=True)
    all_comments = comments_over + comments_under
    all_warnings = warnings_over + warnings_under
    
    # Deduplicate warnings by worker name
    seen_managers = set()
    unique_warnings = []
    for w in all_warnings:
        if w["type"] == "manager_in_data":
            if w["worker"] not in seen_managers:
                seen_managers.add(w["worker"])
                unique_warnings.append(w)
        else:
            unique_warnings.append(w)
    
    if all_comments:
        print(f"📝 Найдено {len(all_comments)} заказов с комментариями менеджера")
    
    if unique_warnings:
        print(f"⚠️ Найдено {len(unique_warnings)} предупреждений")
    
    return combined, name_map, all_comments, unique_warnings
