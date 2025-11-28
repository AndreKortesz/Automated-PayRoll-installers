"""
Database module for PostgreSQL connection and models
"""
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from databases import Database
from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Float, DateTime, 
    Text, Boolean, ForeignKey, create_engine, JSON
)

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Fix for Railway PostgreSQL URL (postgres:// -> postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# For async operations
if DATABASE_URL:
    ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    ASYNC_DATABASE_URL = ""

# Database instance
database = Database(ASYNC_DATABASE_URL) if ASYNC_DATABASE_URL else None

# Metadata
metadata = MetaData()


# ============== WORKER FILTERING ==============
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
    original_clean = name.replace(" (оплата клиентом)", "").strip()
    words = original_clean.split()
    
    if len(words) < 2:
        return False
    
    # Check that first word looks like a surname (starts with uppercase, mostly letters)
    first_word = words[0]
    if not first_word or not first_word[0].isupper():
        return False
    
    # Check that it contains mostly Cyrillic or Latin letters
    letter_count = sum(1 for c in first_word if c.isalpha())
    if letter_count < len(first_word) * 0.8:
        return False
    
    return True

# ============== TABLES ==============

# Periods table (периоды расчёта: 01-15.11.25, 16-30.11.25)
periods = Table(
    "periods",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(50), nullable=False),  # "01-15.11.25"
    Column("month", String(7), nullable=False),   # "2025-11"
    Column("year", Integer, nullable=False),      # 2025
    Column("created_at", DateTime, default=datetime.utcnow),
)

# Uploads table (каждая загрузка файлов - версия)
uploads = Table(
    "uploads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("period_id", Integer, ForeignKey("periods.id"), nullable=False),
    Column("version", Integer, nullable=False, default=1),  # 1, 2, 3... версия загрузки
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("config_json", JSON),  # Настройки расчёта
)

# Orders table (исходные данные заказов)
orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("upload_id", Integer, ForeignKey("uploads.id"), nullable=False),
    Column("worker", String(100), nullable=False),
    Column("order_code", String(50)),  # КАУТ-001656
    Column("order_full", Text),  # Полный текст заказа
    Column("order_date", DateTime),
    Column("address", Text),
    Column("revenue_total", Float, default=0),
    Column("revenue_services", Float, default=0),
    Column("diagnostic", Float, default=0),
    Column("diagnostic_payment", Float, default=0),
    Column("specialist_fee", Float, default=0),
    Column("additional_expenses", Float, default=0),
    Column("service_payment", Float, default=0),
    Column("percent", String(20)),
    Column("is_client_payment", Boolean, default=False),
    Column("is_over_10k", Boolean, default=False),
)

# Calculations table (результаты расчётов)
calculations = Table(
    "calculations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("upload_id", Integer, ForeignKey("uploads.id"), nullable=False),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("worker", String(100), nullable=False),
    Column("fuel_payment", Float, default=0),
    Column("transport", Float, default=0),
    Column("diagnostic_50", Float, default=0),
    Column("total", Float, default=0),
)

# Worker totals (итоги по монтажникам за период)
worker_totals = Table(
    "worker_totals",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("upload_id", Integer, ForeignKey("uploads.id"), nullable=False),
    Column("worker", String(100), nullable=False),
    Column("total_amount", Float, default=0),
    Column("company_amount", Float, default=0),   # Оплата компанией
    Column("client_amount", Float, default=0),    # Оплата клиентом
    Column("orders_count", Integer, default=0),
    Column("company_orders_count", Integer, default=0),
    Column("client_orders_count", Integer, default=0),
    Column("fuel_total", Float, default=0),
    Column("transport_total", Float, default=0),
)

# Changes table (история изменений между версиями)
changes = Table(
    "changes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("upload_id", Integer, ForeignKey("uploads.id"), nullable=False),
    Column("order_code", String(50)),
    Column("worker", String(100)),
    Column("change_type", String(20)),  # added, modified, deleted
    Column("field_name", String(50)),   # Какое поле изменилось
    Column("old_value", Text),
    Column("new_value", Text),
    Column("created_at", DateTime, default=datetime.utcnow),
)


# ============== DATABASE FUNCTIONS ==============

async def connect_db():
    """Connect to database"""
    if database:
        await database.connect()
        print("✅ Connected to PostgreSQL")

async def disconnect_db():
    """Disconnect from database"""
    if database:
        await database.disconnect()
        print("🔌 Disconnected from PostgreSQL")

def create_tables():
    """Create all tables (sync, for initial setup)"""
    if DATABASE_URL:
        engine = create_engine(DATABASE_URL)
        metadata.create_all(engine)
        print("✅ Tables created")
        
        # Run migrations for new columns
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            # Add new columns if they don't exist
            migrations = [
                "ALTER TABLE worker_totals ADD COLUMN IF NOT EXISTS company_amount FLOAT DEFAULT 0",
                "ALTER TABLE worker_totals ADD COLUMN IF NOT EXISTS client_amount FLOAT DEFAULT 0",
                "ALTER TABLE worker_totals ADD COLUMN IF NOT EXISTS company_orders_count INTEGER DEFAULT 0",
                "ALTER TABLE worker_totals ADD COLUMN IF NOT EXISTS client_orders_count INTEGER DEFAULT 0",
            ]
            
            for migration in migrations:
                try:
                    cur.execute(migration)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"Migration skipped (may already exist): {e}")
            
            cur.close()
            conn.close()
            print("✅ Migrations completed")
        except Exception as e:
            print(f"⚠️ Migration error (non-critical): {e}")

async def get_or_create_period(name: str) -> int:
    """Get existing period or create new one"""
    # Parse period name to extract month and year
    # Format: "01-15.11.25" -> month="2025-11", year=2025
    try:
        parts = name.split(".")
        if len(parts) >= 2:
            month_num = parts[-2].split("-")[-1] if "-" in parts[-2] else parts[-2]
            year_short = parts[-1]
            year = 2000 + int(year_short) if len(year_short) == 2 else int(year_short)
            month = f"{year}-{month_num.zfill(2)}"
        else:
            year = datetime.now().year
            month = datetime.now().strftime("%Y-%m")
    except:
        year = datetime.now().year
        month = datetime.now().strftime("%Y-%m")
    
    # Check if period exists
    query = periods.select().where(periods.c.name == name)
    result = await database.fetch_one(query)
    
    if result:
        return result["id"]
    
    # Create new period
    query = periods.insert().values(name=name, month=month, year=year)
    period_id = await database.execute(query)
    return period_id

async def create_upload(period_id: int, config: dict) -> int:
    """Create new upload version"""
    # Get current max version for this period
    query = uploads.select().where(uploads.c.period_id == period_id)
    existing = await database.fetch_all(query)
    version = len(existing) + 1
    
    # Create upload
    query = uploads.insert().values(
        period_id=period_id,
        version=version,
        config_json=config
    )
    upload_id = await database.execute(query)
    return upload_id

async def save_order(upload_id: int, order_data: dict) -> int:
    """Save order to database"""
    query = orders.insert().values(
        upload_id=upload_id,
        worker=order_data.get("worker", ""),
        order_code=order_data.get("order_code", ""),
        order_full=order_data.get("order", ""),
        address=order_data.get("address", ""),
        revenue_total=order_data.get("revenue_total", 0) or 0,
        revenue_services=order_data.get("revenue_services", 0) or 0,
        diagnostic=order_data.get("diagnostic", 0) or 0,
        diagnostic_payment=order_data.get("diagnostic_payment", 0) or 0,
        specialist_fee=order_data.get("specialist_fee", 0) or 0,
        additional_expenses=order_data.get("additional_expenses", 0) or 0,
        service_payment=order_data.get("service_payment", 0) or 0,
        percent=str(order_data.get("percent", "")),
        is_client_payment=order_data.get("is_client_payment", False),
        is_over_10k=order_data.get("is_over_10k", False),
    )
    return await database.execute(query)

async def save_calculation(upload_id: int, order_id: int, calc_data: dict):
    """Save calculation result"""
    query = calculations.insert().values(
        upload_id=upload_id,
        order_id=order_id,
        worker=calc_data.get("worker", ""),
        fuel_payment=calc_data.get("fuel_payment", 0) or 0,
        transport=calc_data.get("transport", 0) or 0,
        diagnostic_50=calc_data.get("diagnostic_50", 0) or 0,
        total=calc_data.get("total", 0) or 0,
    )
    await database.execute(query)

async def save_worker_total(
    upload_id: int, 
    worker: str, 
    total: float, 
    orders_count: int, 
    fuel: float, 
    transport: float,
    company_amount: float = 0,
    client_amount: float = 0,
    company_orders_count: int = 0,
    client_orders_count: int = 0
):
    """Save worker total with company/client breakdown"""
    query = worker_totals.insert().values(
        upload_id=upload_id,
        worker=worker,
        total_amount=total,
        company_amount=company_amount,
        client_amount=client_amount,
        orders_count=orders_count,
        company_orders_count=company_orders_count,
        client_orders_count=client_orders_count,
        fuel_total=fuel,
        transport_total=transport,
    )
    await database.execute(query)

async def save_change(upload_id: int, order_code: str, worker: str, change_type: str, field: str = None, old_val: str = None, new_val: str = None):
    """Save change record"""
    query = changes.insert().values(
        upload_id=upload_id,
        order_code=order_code,
        worker=worker,
        change_type=change_type,
        field_name=field,
        old_value=old_val,
        new_value=new_val,
    )
    await database.execute(query)

async def get_previous_upload(period_id: int, current_version: int) -> Optional[int]:
    """Get previous upload ID for comparison"""
    if current_version <= 1:
        return None
    
    query = uploads.select().where(
        (uploads.c.period_id == period_id) & 
        (uploads.c.version == current_version - 1)
    )
    result = await database.fetch_one(query)
    return result["id"] if result else None

async def get_orders_by_upload(upload_id: int) -> List[dict]:
    """Get all orders for an upload"""
    query = orders.select().where(orders.c.upload_id == upload_id)
    results = await database.fetch_all(query)
    return [dict(r) for r in results]

async def compare_uploads(old_upload_id: int, new_upload_id: int) -> List[dict]:
    """Compare two uploads and return changes"""
    old_orders = await get_orders_by_upload(old_upload_id)
    new_orders = await get_orders_by_upload(new_upload_id)
    
    # Index by order_code + worker
    old_map = {(o["order_code"], o["worker"]): o for o in old_orders}
    new_map = {(o["order_code"], o["worker"]): o for o in new_orders}
    
    changes_list = []
    
    # Find added orders
    for key, order in new_map.items():
        if key not in old_map:
            changes_list.append({
                "type": "added",
                "order_code": order["order_code"],
                "worker": order["worker"],
                "order": order
            })
    
    # Find deleted orders
    for key, order in old_map.items():
        if key not in new_map:
            changes_list.append({
                "type": "deleted",
                "order_code": order["order_code"],
                "worker": order["worker"],
                "order": order
            })
    
    # Find modified orders
    compare_fields = ["revenue_total", "revenue_services", "service_payment", "percent", 
                      "specialist_fee", "diagnostic", "additional_expenses"]
    
    for key in old_map:
        if key in new_map:
            old_order = old_map[key]
            new_order = new_map[key]
            
            field_changes = []
            for field in compare_fields:
                old_val = old_order.get(field)
                new_val = new_order.get(field)
                if str(old_val) != str(new_val):
                    field_changes.append({
                        "field": field,
                        "old": old_val,
                        "new": new_val
                    })
            
            if field_changes:
                changes_list.append({
                    "type": "modified",
                    "order_code": new_order["order_code"],
                    "worker": new_order["worker"],
                    "changes": field_changes,
                    "old_order": old_order,
                    "new_order": new_order
                })
    
    return changes_list


# ============== QUERY FUNCTIONS ==============

async def get_all_periods() -> List[dict]:
    """Get all periods grouped by month"""
    query = periods.select().order_by(periods.c.year.desc(), periods.c.month.desc(), periods.c.name.desc())
    results = await database.fetch_all(query)
    return [dict(r) for r in results]

async def get_period_details(period_id: int) -> dict:
    """Get period with all uploads"""
    # Get period
    query = periods.select().where(periods.c.id == period_id)
    period = await database.fetch_one(query)
    if not period:
        return None
    
    # Get uploads
    query = uploads.select().where(uploads.c.period_id == period_id).order_by(uploads.c.version.desc())
    upload_list = await database.fetch_all(query)
    
    return {
        "period": dict(period),
        "uploads": [dict(u) for u in upload_list]
    }

async def get_upload_details(upload_id: int) -> dict:
    """Get upload with worker totals and orders"""
    try:
        # Get upload
        query = uploads.select().where(uploads.c.id == upload_id)
        upload = await database.fetch_one(query)
        if not upload:
            return None
        
        # Get worker totals - FILTER out non-workers
        query = worker_totals.select().where(worker_totals.c.upload_id == upload_id).order_by(worker_totals.c.worker)
        totals = await database.fetch_all(query)
        
        # Filter to only valid workers and add default values for new columns
        filtered_totals = []
        for t in totals:
            if not is_valid_worker_name(t["worker"]):
                continue
            t_dict = dict(t)
            # Add defaults for new columns if they don't exist
            if "company_amount" not in t_dict:
                t_dict["company_amount"] = t_dict.get("total_amount", 0)
            if "client_amount" not in t_dict:
                t_dict["client_amount"] = 0
            if "company_orders_count" not in t_dict:
                t_dict["company_orders_count"] = t_dict.get("orders_count", 0)
            if "client_orders_count" not in t_dict:
                t_dict["client_orders_count"] = 0
            filtered_totals.append(t_dict)
        
        # Get changes for this upload - FILTER out non-workers
        query = changes.select().where(changes.c.upload_id == upload_id)
        change_list = await database.fetch_all(query)
        
        # Filter changes to only valid workers and enrich with order details
        filtered_changes = []
        for c in change_list:
            if not is_valid_worker_name(c["worker"]):
                continue
            
            change_dict = dict(c)
            
            # Try to get order details for this change
            try:
                order_query = orders.select().where(
                    (orders.c.upload_id == upload_id) & 
                    (orders.c.order_code == c["order_code"]) &
                    (orders.c.worker.like(f"%{c['worker']}%"))
                )
                order = await database.fetch_one(order_query)
                
                if order:
                    # Add order details to change
                    change_dict["address"] = order["address"] or ""
                    change_dict["revenue_total"] = order["revenue_total"] or 0
                    change_dict["revenue_services"] = order["revenue_services"] or 0
                    change_dict["service_payment"] = order["service_payment"] or 0
                    change_dict["percent"] = order["percent"] or ""
                    change_dict["diagnostic"] = order["diagnostic"] or 0
                    change_dict["specialist_fee"] = order["specialist_fee"] or 0
            except Exception as e:
                print(f"Warning: Could not get order details for change: {e}")
            
            filtered_changes.append(change_dict)
        
        return {
            "upload": dict(upload),
            "worker_totals": filtered_totals,
            "changes": filtered_changes
        }
    except Exception as e:
        print(f"Error in get_upload_details: {e}")
        raise

async def get_worker_orders(upload_id: int, worker: str) -> List[dict]:
    """Get all orders for a worker in an upload"""
    query = orders.select().where(
        (orders.c.upload_id == upload_id) & 
        (orders.c.worker == worker)
    )
    order_list = await database.fetch_all(query)
    
    # Get calculations for these orders
    result = []
    for order in order_list:
        order_dict = dict(order)
        
        # Get calculation
        calc_query = calculations.select().where(calculations.c.order_id == order["id"])
        calc = await database.fetch_one(calc_query)
        if calc:
            order_dict["calculation"] = dict(calc)
        
        result.append(order_dict)
    
    return result

async def get_months_summary() -> List[dict]:
    """Get summary by months for dashboard"""
    query = """
        SELECT 
            p.month,
            p.year,
            COUNT(DISTINCT p.id) as periods_count,
            COUNT(DISTINCT u.id) as uploads_count,
            SUM(wt.total_amount) as total_amount
        FROM periods p
        LEFT JOIN uploads u ON u.period_id = p.id
        LEFT JOIN worker_totals wt ON wt.upload_id = u.id
        GROUP BY p.month, p.year
        ORDER BY p.year DESC, p.month DESC
    """
    results = await database.fetch_all(query)
    return [dict(r) for r in results]
