"""
Worker name normalization and validation functions
"""


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


def is_valid_worker_name(name: str) -> bool:
    """Check if name looks like a real person name (ФИО)
    
    Valid: "Ветренко Дмитрий", "Романюк Алексей Юрьевич"
    Invalid: "Доставка", "Помощник", "Итого"
    """
    if not name:
        return False
        
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
