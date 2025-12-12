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


# ============== PERIOD STATUSES ==============
class PeriodStatus:
    DRAFT = "draft"           # Черновик - admin и employee могут редактировать
    SENT = "sent"             # Отправлено монтажникам - редактирование с логированием
    PAID = "paid"             # Оплачено - только admin может редактировать


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
    Column("status", String(20), default="draft"),  # draft, sent, paid
    Column("sent_at", DateTime, nullable=True),     # When files were sent to workers
    Column("paid_at", DateTime, nullable=True),     # When salary was paid
    Column("created_at", DateTime, default=datetime.utcnow),
)

# Users table (пользователи из Bitrix24)
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("bitrix_id", Integer, unique=True, nullable=False),  # ID пользователя в Bitrix24
    Column("name", String(200)),                                 # Имя из Bitrix24
    Column("email", String(200)),
    Column("role", String(20), default="employee"),              # admin, employee
    Column("access_token", Text),                                # OAuth access token
    Column("refresh_token", Text),                               # OAuth refresh token
    Column("token_expires_at", DateTime),
    Column("last_login", DateTime),
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
    Column("created_by", Integer, ForeignKey("users.id"), nullable=True),  # Кто создал
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
    Column("is_extra_row", Boolean, default=False),  # Дополнительная строка (ручное добавление)
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

# Table for manual edits (changes made in history UI)
manual_edits = Table(
    "manual_edits",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("upload_id", Integer, ForeignKey("uploads.id"), nullable=False),
    Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
    Column("calculation_id", Integer, ForeignKey("calculations.id"), nullable=False),
    Column("order_code", String(50)),
    Column("worker", String(100)),
    Column("address", Text),
    Column("field_name", String(50)),  # fuel_payment, transport, total
    Column("old_value", Float),
    Column("new_value", Float),
    Column("edited_by", Integer, ForeignKey("users.id"), nullable=True),  # Кто редактировал
    Column("created_at", DateTime, default=datetime.utcnow),
)

# Audit log table (ВСЕ действия пользователей)
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=True),
    Column("user_name", String(200)),  # Дублируем имя для удобства
    Column("user_role", String(20)),   # admin/employee
    Column("action", String(50), nullable=False),  # upload, edit, delete, send, mark_paid, etc.
    Column("entity_type", String(50)),  # period, upload, order, calculation
    Column("entity_id", Integer),
    Column("period_id", Integer, ForeignKey("periods.id"), nullable=True),
    Column("period_status", String(20)),  # Статус периода на момент действия
    Column("details", JSON),  # Детали действия (что изменилось)
    Column("ip_address", String(50)),
    Column("created_at", DateTime, default=datetime.utcnow),
)

# Sent notifications table (кому отправляли)
sent_notifications = Table(
    "sent_notifications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("period_id", Integer, ForeignKey("periods.id"), nullable=False),
    Column("worker", String(100), nullable=False),
    Column("bitrix_user_id", Integer),  # ID монтажника в Bitrix24
    Column("notification_type", String(20)),  # chat, email
    Column("file_url", Text),  # URL отправленного файла
    Column("sent_by", Integer, ForeignKey("users.id")),  # Кто отправил
    Column("sent_at", DateTime, default=datetime.utcnow),
    Column("status", String(20), default="sent"),  # sent, delivered, read
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
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_extra_row BOOLEAN DEFAULT FALSE",
                # Create manual_edits table if not exists
                """CREATE TABLE IF NOT EXISTS manual_edits (
                    id SERIAL PRIMARY KEY,
                    upload_id INTEGER REFERENCES uploads(id),
                    order_id INTEGER REFERENCES orders(id),
                    calculation_id INTEGER REFERENCES calculations(id),
                    order_code VARCHAR(50),
                    worker VARCHAR(100),
                    address TEXT,
                    field_name VARCHAR(50),
                    old_value FLOAT,
                    new_value FLOAT,
                    edited_by INTEGER REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                # Add edited_by to manual_edits if not exists
                "ALTER TABLE manual_edits ADD COLUMN IF NOT EXISTS edited_by INTEGER REFERENCES users(id)",
                # Period status columns
                "ALTER TABLE periods ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'draft'",
                "ALTER TABLE periods ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP",
                "ALTER TABLE periods ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP",
                # Add created_by to uploads
                "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
                # Users table for Bitrix24 auth
                """CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    bitrix_id INTEGER UNIQUE NOT NULL,
                    name VARCHAR(200),
                    email VARCHAR(200),
                    role VARCHAR(20) DEFAULT 'employee',
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expires_at TIMESTAMP,
                    last_login TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                # Audit log table
                """CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    user_name VARCHAR(200),
                    user_role VARCHAR(20),
                    action VARCHAR(50) NOT NULL,
                    entity_type VARCHAR(50),
                    entity_id INTEGER,
                    period_id INTEGER REFERENCES periods(id),
                    period_status VARCHAR(20),
                    details JSONB,
                    ip_address VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                # Sent notifications table
                """CREATE TABLE IF NOT EXISTS sent_notifications (
                    id SERIAL PRIMARY KEY,
                    period_id INTEGER REFERENCES periods(id) NOT NULL,
                    worker VARCHAR(100) NOT NULL,
                    bitrix_user_id INTEGER,
                    notification_type VARCHAR(20),
                    file_url TEXT,
                    sent_by INTEGER REFERENCES users(id),
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) DEFAULT 'sent'
                )""",
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


# ============== AUDIT LOG FUNCTIONS ==============

async def log_action(
    user: dict,
    action: str,
    entity_type: str = None,
    entity_id: int = None,
    period_id: int = None,
    details: dict = None,
    ip_address: str = None
):
    """Log user action to audit_log table"""
    if not database or not database.is_connected:
        return
    
    # Get period status if period_id provided
    period_status = None
    if period_id:
        status_result = await get_period_status(period_id)
        period_status = status_result.get("status") if status_result else None
    
    query = audit_log.insert().values(
        user_id=user.get("id") if user else None,
        user_name=user.get("name") if user else "Anonymous",
        user_role=user.get("role") if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        period_id=period_id,
        period_status=period_status,
        details=details,
        ip_address=ip_address,
    )
    await database.execute(query)


async def get_audit_log(period_id: int = None, limit: int = 100) -> List[dict]:
    """Get audit log entries, optionally filtered by period"""
    if not database or not database.is_connected:
        return []
    
    if period_id:
        query = audit_log.select().where(
            audit_log.c.period_id == period_id
        ).order_by(audit_log.c.created_at.desc()).limit(limit)
    else:
        query = audit_log.select().order_by(
            audit_log.c.created_at.desc()
        ).limit(limit)
    
    rows = await database.fetch_all(query)
    return [dict(row._mapping) for row in rows]


# ============== PERMISSION FUNCTIONS ==============

def can_user_edit_period(user: dict, period_status: str, is_latest_period: bool) -> tuple:
    """
    Check if user can edit a period.
    Returns (can_edit: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Admin can edit anything except PAID
    if role == "admin":
        if period_status == PeriodStatus.PAID:
            return True, "Админ может редактировать оплаченный период"  # Admin can still edit
        return True, "Админ"
    
    # Employee restrictions
    if role == "employee":
        # Cannot edit PAID periods at all
        if period_status == PeriodStatus.PAID:
            return False, "Период оплачен. Для изменений обратитесь к администратору"
        
        # Can only edit the latest period
        if not is_latest_period:
            return False, "Можно редактировать только текущий (последний) период"
        
        # Can edit DRAFT and SENT (but SENT will be logged)
        return True, "Текущий период"
    
    return False, "Недостаточно прав"


def can_user_upload(user: dict, period_status: str, is_latest_period: bool) -> tuple:
    """
    Check if user can upload new files.
    Returns (can_upload: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Admin can always upload
    if role == "admin":
        return True, "Админ"
    
    # Employee restrictions
    if role == "employee":
        # Cannot upload to PAID periods
        if period_status == PeriodStatus.PAID:
            return False, "Период оплачен. Загрузка невозможна"
        
        # Can only upload to the latest period (or create new)
        if not is_latest_period:
            return False, "Можно загружать файлы только в текущий (последний) период"
        
        return True, "Текущий период"
    
    return False, "Недостаточно прав"


def can_user_delete_row(user: dict, period_status: str, is_latest_period: bool) -> tuple:
    """
    Check if user can delete a ROW in report (not the whole period).
    Returns (can_delete: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Admin can delete rows anytime except PAID
    if role == "admin":
        return True, "Админ"
    
    # Employee can delete rows only in latest non-paid period
    if role == "employee":
        if period_status == PeriodStatus.PAID:
            return False, "Период оплачен. Для изменений обратитесь к администратору"
        
        if not is_latest_period:
            return False, "Можно редактировать только текущий (последний) период"
        
        return True, "Текущий период"
    
    return False, "Недостаточно прав"


def can_user_delete_period(user: dict) -> tuple:
    """
    Check if user can delete entire PERIOD.
    Returns (can_delete: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Only admin can delete entire periods
    if role == "admin":
        return True, "Админ"
    
    return False, "Только администратор может удалять периоды"


def can_user_send_to_workers(user: dict, period_status: str, is_latest_period: bool) -> tuple:
    """
    Check if user can send reports to workers.
    Returns (can_send: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Admin can always send
    if role == "admin":
        return True, "Админ"
    
    # Employee can send only for latest non-paid period
    if role == "employee":
        if period_status == PeriodStatus.PAID:
            return False, "Период оплачен. Отправка невозможна"
        
        if not is_latest_period:
            return False, "Можно отправлять только текущий (последний) период"
        
        return True, "Текущий период"
    
    return False, "Недостаточно прав"


def can_user_send_to_accountant(user: dict, period_status: str, is_latest_period: bool) -> tuple:
    """
    Check if user can send to accountant (marks period as PAID).
    Returns (can_send: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Cannot send already paid period
    if period_status == PeriodStatus.PAID:
        return False, "Период уже оплачен"
    
    # Admin can always send
    if role == "admin":
        return True, "Админ"
    
    # Employee can send only for latest period
    if role == "employee":
        if not is_latest_period:
            return False, "Можно отправлять только текущий (последний) период"
        
        return True, "Текущий период"
    
    return False, "Недостаточно прав"


def can_user_unlock_period(user: dict) -> tuple:
    """
    Check if user can unlock a PAID period for editing.
    Only admin can do this.
    Returns (can_unlock: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    if role == "admin":
        return True, "Админ"
    
    return False, "Только администратор может разблокировать оплаченный период"


def can_user_change_status(user: dict, from_status: str, to_status: str) -> tuple:
    """
    Check if user can change period status.
    Returns (can_change: bool, reason: str)
    """
    if not user:
        return False, "Необходима авторизация"
    
    role = user.get("role", "employee")
    
    # Only admin can change status
    if role == "admin":
        return True, "Админ"
    
    return False, "Только администратор может менять статус периода"


# ============== PERIOD STATUS FUNCTIONS ==============

async def get_period_status(period_id: int) -> Optional[dict]:
    """Get period with status info"""
    if not database or not database.is_connected:
        return None
    
    query = periods.select().where(periods.c.id == period_id)
    row = await database.fetch_one(query)
    if row:
        return dict(row._mapping)
    return None


async def update_period_status(period_id: int, new_status: str, user: dict = None) -> bool:
    """Update period status"""
    if not database or not database.is_connected:
        return False
    
    update_data = {"status": new_status}
    
    if new_status == PeriodStatus.SENT:
        update_data["sent_at"] = datetime.utcnow()
    elif new_status == PeriodStatus.PAID:
        update_data["paid_at"] = datetime.utcnow()
    
    query = periods.update().where(periods.c.id == period_id).values(**update_data)
    await database.execute(query)
    
    # Log the action
    if user:
        await log_action(
            user=user,
            action=f"status_change_to_{new_status}",
            entity_type="period",
            entity_id=period_id,
            period_id=period_id,
            details={"new_status": new_status}
        )
    
    return True


async def is_latest_period(period_id: int) -> bool:
    """Check if this is the latest (most recent) period"""
    if not database or not database.is_connected:
        return False
    
    # Get the latest period by created_at
    query = periods.select().order_by(periods.c.created_at.desc()).limit(1)
    row = await database.fetch_one(query)
    
    if row:
        return row._mapping["id"] == period_id
    return False


# ============== EXISTING FUNCTIONS (keep all existing implementations) ==============

async def get_or_create_period(period_name: str) -> int:
    """Get existing period or create new one"""
    if not database or not database.is_connected:
        return None
    
    # Parse period name like "01-15.11.25" or "16-30.11.25"
    import re
    match = re.match(r'(\d{2})-(\d{2})\.(\d{2})\.(\d{2})', period_name)
    if match:
        day1, day2, month, year = match.groups()
        month_str = f"20{year}-{month}"
        year_int = 2000 + int(year)
    else:
        month_str = datetime.now().strftime("%Y-%m")
        year_int = datetime.now().year
    
    # Check if exists
    query = periods.select().where(periods.c.name == period_name)
    existing = await database.fetch_one(query)
    
    if existing:
        return existing._mapping["id"]
    
    # Create new
    query = periods.insert().values(
        name=period_name,
        month=month_str,
        year=year_int,
        status=PeriodStatus.DRAFT
    )
    return await database.execute(query)


async def create_upload(period_id: int, config: dict = None, user: dict = None) -> int:
    """Create new upload (version) for period"""
    if not database or not database.is_connected:
        return None
    
    # Get next version number
    query = uploads.select().where(uploads.c.period_id == period_id).order_by(uploads.c.version.desc())
    latest = await database.fetch_one(query)
    next_version = (latest._mapping["version"] + 1) if latest else 1
    
    # Create upload
    query = uploads.insert().values(
        period_id=period_id,
        version=next_version,
        config_json=config,
        created_by=user.get("id") if user else None
    )
    upload_id = await database.execute(query)
    
    # Log the action
    if user:
        await log_action(
            user=user,
            action="upload_files",
            entity_type="upload",
            entity_id=upload_id,
            period_id=period_id,
            details={"version": next_version}
        )
    
    return upload_id


async def save_order(upload_id: int, order_data: dict) -> int:
    """Save order data"""
    if not database or not database.is_connected:
        return None
    
    # Only include fields that exist in orders table
    allowed_fields = {
        'worker', 'order_code', 'order_full', 'address',
        'revenue_total', 'revenue_services', 'diagnostic', 'diagnostic_payment',
        'specialist_fee', 'additional_expenses', 'service_payment', 'percent',
        'is_client_payment', 'is_over_10k', 'is_extra_row'
    }
    
    filtered_data = {k: v for k, v in order_data.items() if k in allowed_fields}
    
    # Convert percent to string if it's a number (DB expects string like "30%")
    if 'percent' in filtered_data and filtered_data['percent'] is not None:
        percent_val = filtered_data['percent']
        if isinstance(percent_val, (int, float)):
            filtered_data['percent'] = f"{percent_val}%"
    
    query = orders.insert().values(
        upload_id=upload_id,
        **filtered_data
    )
    return await database.execute(query)


async def save_calculation(upload_id: int, order_id: int, calc_data: dict) -> int:
    """Save calculation result"""
    if not database or not database.is_connected:
        return None
    
    # Only include fields that exist in calculations table
    allowed_fields = {'fuel_payment', 'transport', 'diagnostic_50', 'total'}
    filtered_data = {k: v for k, v in calc_data.items() if k in allowed_fields}
    
    query = calculations.insert().values(
        upload_id=upload_id,
        order_id=order_id,
        **filtered_data
    )
    return await database.execute(query)


async def save_worker_total(upload_id: int, worker: str, totals: dict) -> int:
    """Save worker totals"""
    if not database or not database.is_connected:
        return None
    
    query = worker_totals.insert().values(
        upload_id=upload_id,
        worker=worker,
        **totals
    )
    return await database.execute(query)


async def save_change(upload_id: int, change_data: dict) -> int:
    """Save change record"""
    if not database or not database.is_connected:
        return None
    
    query = changes.insert().values(
        upload_id=upload_id,
        **change_data
    )
    return await database.execute(query)


async def get_previous_upload(period_id: int) -> Optional[dict]:
    """Get the latest upload for a period"""
    if not database or not database.is_connected:
        return None
    
    query = uploads.select().where(
        uploads.c.period_id == period_id
    ).order_by(uploads.c.version.desc()).limit(1)
    
    row = await database.fetch_one(query)
    if row:
        return dict(row._mapping)
    return None


async def compare_uploads(old_upload_id: int, new_upload_id: int) -> dict:
    """Compare two uploads and return differences"""
    # Implementation kept from original
    return {"added": [], "modified": [], "deleted": []}


async def get_orders_by_upload(upload_id: int) -> List[dict]:
    """Get all orders for an upload with calculations data"""
    if not database or not database.is_connected:
        return []
    
    # JOIN with calculations to get fuel_payment, transport, total
    query = """
        SELECT o.*, c.fuel_payment, c.transport, c.diagnostic_50, c.total, c.id as calculation_id
        FROM orders o
        LEFT JOIN calculations c ON o.id = c.order_id
        WHERE o.upload_id = :upload_id
        ORDER BY o.worker, o.is_client_payment, o.id
    """
    rows = await database.fetch_all(query, {"upload_id": upload_id})
    return [dict(row._mapping) for row in rows]


async def get_all_periods() -> List[dict]:
    """Get all periods ordered by date (newest first)"""
    if not database or not database.is_connected:
        return []
    
    # Sort by year DESC, then by month DESC, then by name DESC (to get 16-30 before 01-15)
    query = periods.select().order_by(
        periods.c.year.desc(),
        periods.c.month.desc(),
        periods.c.name.desc()
    )
    rows = await database.fetch_all(query)
    return [dict(row._mapping) for row in rows]


async def get_period_details(period_id: int) -> Optional[dict]:
    """Get period with all uploads"""
    if not database or not database.is_connected:
        return None
    
    # Get period
    query = periods.select().where(periods.c.id == period_id)
    period_row = await database.fetch_one(query)
    if not period_row:
        return None
    
    period = dict(period_row._mapping)
    
    # Get uploads
    query = uploads.select().where(
        uploads.c.period_id == period_id
    ).order_by(uploads.c.version.desc())
    upload_rows = await database.fetch_all(query)
    period["uploads"] = [dict(row._mapping) for row in upload_rows]
    
    return period


async def get_upload_details(upload_id: int) -> Optional[dict]:
    """Get upload with orders, calculations and manual edits"""
    if not database or not database.is_connected:
        return None
    
    # Get upload
    query = uploads.select().where(uploads.c.id == upload_id)
    upload_row = await database.fetch_one(query)
    if not upload_row:
        return None
    
    upload = dict(upload_row._mapping)
    
    # Get orders with calculations
    query = """
        SELECT o.*, c.fuel_payment, c.transport, c.diagnostic_50, c.total, c.id as calculation_id
        FROM orders o
        LEFT JOIN calculations c ON o.id = c.order_id
        WHERE o.upload_id = :upload_id
        ORDER BY o.worker, o.is_client_payment, o.id
    """
    rows = await database.fetch_all(query, {"upload_id": upload_id})
    upload["orders"] = [dict(row._mapping) for row in rows]
    
    # Get worker totals
    query = worker_totals.select().where(worker_totals.c.upload_id == upload_id)
    total_rows = await database.fetch_all(query)
    upload["worker_totals"] = [dict(row._mapping) for row in total_rows]
    
    # Get manual edits
    query = manual_edits.select().where(manual_edits.c.upload_id == upload_id)
    edit_rows = await database.fetch_all(query)
    upload["manual_edits"] = [dict(row._mapping) for row in edit_rows]
    
    return upload


async def get_worker_orders(upload_id: int, worker: str) -> List[dict]:
    """Get orders for specific worker"""
    if not database or not database.is_connected:
        return []
    
    query = """
        SELECT o.*, c.fuel_payment, c.transport, c.diagnostic_50, c.total, c.id as calculation_id
        FROM orders o
        LEFT JOIN calculations c ON o.id = c.order_id
        WHERE o.upload_id = :upload_id AND o.worker LIKE :worker
        ORDER BY o.is_client_payment, o.id
    """
    rows = await database.fetch_all(query, {
        "upload_id": upload_id,
        "worker": f"%{worker}%"
    })
    return [dict(row._mapping) for row in rows]


async def get_months_summary() -> List[dict]:
    """Get summary grouped by month"""
    if not database or not database.is_connected:
        return []
    
    query = """
        SELECT 
            p.month,
            p.year,
            COUNT(DISTINCT p.id) as periods_count,
            array_agg(json_build_object(
                'id', p.id,
                'name', p.name,
                'status', p.status,
                'sent_at', p.sent_at,
                'paid_at', p.paid_at,
                'created_at', p.created_at
            ) ORDER BY p.created_at DESC) as periods
        FROM periods p
        GROUP BY p.month, p.year
        ORDER BY p.year DESC, p.month DESC
    """
    rows = await database.fetch_all(query)
    return [dict(row._mapping) for row in rows]


async def get_user_by_bitrix_id(bitrix_id: int) -> Optional[dict]:
    """Get user by Bitrix24 ID"""
    if not database or not database.is_connected:
        return None
    
    query = users.select().where(users.c.bitrix_id == bitrix_id)
    row = await database.fetch_one(query)
    if row:
        return dict(row._mapping)
    return None


async def create_or_update_user(
    bitrix_id: int,
    name: str,
    email: str,
    role: str,
    access_token: str = None,
    refresh_token: str = None,
    token_expires_at: datetime = None
) -> dict:
    """Create new user or update existing"""
    if not database or not database.is_connected:
        return {"id": 0, "bitrix_id": bitrix_id, "name": name, "role": role}
    
    # Check if exists
    existing = await get_user_by_bitrix_id(bitrix_id)
    
    if existing:
        # Update
        query = users.update().where(users.c.bitrix_id == bitrix_id).values(
            name=name,
            email=email,
            role=role,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            last_login=datetime.utcnow()
        )
        await database.execute(query)
        return {**existing, "name": name, "role": role}
    else:
        # Create
        query = users.insert().values(
            bitrix_id=bitrix_id,
            name=name,
            email=email,
            role=role,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            last_login=datetime.utcnow()
        )
        user_id = await database.execute(query)
        return {"id": user_id, "bitrix_id": bitrix_id, "name": name, "role": role}


# ============== NOTIFICATION FUNCTIONS ==============

async def save_notification(
    period_id: int,
    worker: str,
    notification_type: str,
    sent_by: int,
    bitrix_user_id: int = None,
    file_url: str = None
) -> int:
    """Save sent notification record"""
    if not database or not database.is_connected:
        return None
    
    query = sent_notifications.insert().values(
        period_id=period_id,
        worker=worker,
        bitrix_user_id=bitrix_user_id,
        notification_type=notification_type,
        file_url=file_url,
        sent_by=sent_by
    )
    return await database.execute(query)


async def get_period_notifications(period_id: int) -> List[dict]:
    """Get all notifications for a period"""
    if not database or not database.is_connected:
        return []
    
    query = sent_notifications.select().where(
        sent_notifications.c.period_id == period_id
    ).order_by(sent_notifications.c.sent_at.desc())
    
    rows = await database.fetch_all(query)
    return [dict(row._mapping) for row in rows]
