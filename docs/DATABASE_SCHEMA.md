# Схема базы данных

## Оглавление

1. [Диаграмма](#диаграмма)
2. [Таблицы](#таблицы)
3. [Связи](#связи)
4. [Индексы](#индексы)
5. [Миграции](#миграции)

---

## Диаграмма

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   periods   │       │   uploads   │       │   orders    │
├─────────────┤       ├─────────────┤       ├─────────────┤
│ id (PK)     │──────<│ id (PK)     │──────<│ id (PK)     │
│ name        │       │ period_id   │       │ upload_id   │
│ month       │       │ version     │       │ worker      │
│ year        │       │ created_at  │       │ order_code  │
│ status      │       │ created_by  │       │ order_full  │
│ created_at  │       │ config_json │       │ address     │
│ sent_at     │       └─────────────┘       │ revenue_*   │
│ paid_at     │                             │ is_extra_row│
└─────────────┘                             └──────┬──────┘
                                                   │
                                                   v
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   users     │       │worker_totals│       │calculations │
├─────────────┤       ├─────────────┤       ├─────────────┤
│ id (PK)     │       │ id (PK)     │       │ id (PK)     │
│ bitrix_id   │       │ upload_id   │       │ upload_id   │
│ name        │       │ worker      │       │ order_id    │
│ email       │       │ total       │       │ fuel_payment│
│ role        │       │ fuel        │       │ transport   │
│ created_at  │       │ transport   │       │ diagnostic50│
└─────────────┘       │ company_amt │       │ total       │
                      │ client_amt  │       └─────────────┘
                      └─────────────┘

┌─────────────┐       ┌─────────────┐
│manual_edits │       │  audit_log  │
├─────────────┤       ├─────────────┤
│ id (PK)     │       │ id (PK)     │
│ upload_id   │       │ user_id     │
│ order_id    │       │ action      │
│ calc_id     │       │ entity_type │
│ field       │       │ entity_id   │
│ old_value   │       │ period_id   │
│ new_value   │       │ details     │
│ edited_by   │       │ created_at  │
│ edited_at   │       └─────────────┘
└─────────────┘
```

---

## Таблицы

### periods

Хранит информацию о расчётных периодах.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| name | VARCHAR(50) | Название периода ("16-30.11.25") |
| month | INTEGER | Месяц (1-12) |
| year | INTEGER | Год (2024, 2025, ...) |
| status | VARCHAR(20) | Статус: DRAFT, SENT, PAID |
| created_at | DATETIME | Дата создания |
| sent_at | DATETIME | Дата отправки (статус SENT) |
| paid_at | DATETIME | Дата оплаты (статус PAID) |

```sql
CREATE TABLE periods (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'DRAFT',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    paid_at TIMESTAMP
);
```

### uploads

Хранит версии загрузок для каждого периода.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| period_id | INTEGER FK | Ссылка на период |
| version | INTEGER | Номер версии (1, 2, 3, ...) |
| created_at | DATETIME | Дата загрузки |
| created_by | INTEGER FK | Кто загрузил (user_id) |
| config_json | JSON | Конфигурация расчёта |

```sql
CREATE TABLE uploads (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES periods(id) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    config_json JSON
);
```

**Важно**: `config_json` содержит:
- Параметры расчёта (процент диагностики, тарифы)
- Данные Яндекс Заправок (`yandex_fuel: {worker: amount}`)

### orders

Хранит заказы из файлов 1С.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| upload_id | INTEGER FK | Ссылка на загрузку |
| worker | VARCHAR(100) | ФИО монтажника |
| order_code | VARCHAR(50) | Код заказа (КАУТ-001405) |
| order_full | TEXT | Полный текст заказа |
| address | TEXT | Адрес |
| revenue_total | FLOAT | Выручка итого |
| revenue_services | FLOAT | Выручка от услуг |
| diagnostic | FLOAT | Диагностика |
| diagnostic_payment | FLOAT | Оплата диагностики |
| specialist_fee | FLOAT | Выезд специалиста |
| additional_expenses | FLOAT | Доп. расходы |
| service_payment | FLOAT | Оплата услуг |
| percent | VARCHAR(20) | Процент ("30%") |
| is_client_payment | BOOLEAN | Оплата клиентом |
| is_over_10k | BOOLEAN | Выручка > 10000 |
| is_extra_row | BOOLEAN | Ручная корректировка |

```sql
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    upload_id INTEGER REFERENCES uploads(id) NOT NULL,
    worker VARCHAR(100) NOT NULL,
    order_code VARCHAR(50),
    order_full TEXT,
    address TEXT,
    revenue_total FLOAT DEFAULT 0,
    revenue_services FLOAT DEFAULT 0,
    diagnostic FLOAT DEFAULT 0,
    diagnostic_payment FLOAT DEFAULT 0,
    specialist_fee FLOAT DEFAULT 0,
    additional_expenses FLOAT DEFAULT 0,
    service_payment FLOAT DEFAULT 0,
    percent VARCHAR(20),
    is_client_payment BOOLEAN DEFAULT FALSE,
    is_over_10k BOOLEAN DEFAULT FALSE,
    is_extra_row BOOLEAN DEFAULT FALSE
);
```

### calculations

Хранит результаты расчётов для каждого заказа.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| upload_id | INTEGER FK | Ссылка на загрузку |
| order_id | INTEGER FK | Ссылка на заказ |
| worker | VARCHAR(100) | ФИО монтажника |
| fuel_payment | FLOAT | Бензин |
| transport | FLOAT | Транспортные |
| diagnostic_50 | FLOAT | Диагностика -50% |
| total | FLOAT | Итого |

```sql
CREATE TABLE calculations (
    id SERIAL PRIMARY KEY,
    upload_id INTEGER REFERENCES uploads(id) NOT NULL,
    order_id INTEGER REFERENCES orders(id) NOT NULL,
    worker VARCHAR(100) NOT NULL,
    fuel_payment FLOAT DEFAULT 0,
    transport FLOAT DEFAULT 0,
    diagnostic_50 FLOAT DEFAULT 0,
    total FLOAT DEFAULT 0
);
```

### worker_totals

Хранит итоги по монтажникам для быстрого доступа.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| upload_id | INTEGER FK | Ссылка на загрузку |
| worker | VARCHAR(100) | ФИО монтажника |
| total | FLOAT | Общий итого |
| fuel | FLOAT | Сумма бензина |
| transport | FLOAT | Сумма транспортных |
| company_amount | FLOAT | Сумма по заказам компании |
| client_amount | FLOAT | Сумма по заказам с оплатой клиентом |
| company_orders_count | INTEGER | Количество заказов компании |
| client_orders_count | INTEGER | Количество заказов клиента |

```sql
CREATE TABLE worker_totals (
    id SERIAL PRIMARY KEY,
    upload_id INTEGER REFERENCES uploads(id) NOT NULL,
    worker VARCHAR(100) NOT NULL,
    total FLOAT DEFAULT 0,
    fuel FLOAT DEFAULT 0,
    transport FLOAT DEFAULT 0,
    company_amount FLOAT DEFAULT 0,
    client_amount FLOAT DEFAULT 0,
    company_orders_count INTEGER DEFAULT 0,
    client_orders_count INTEGER DEFAULT 0
);
```

### users

Хранит пользователей системы.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| bitrix_id | VARCHAR(50) | ID в Bitrix24 |
| name | VARCHAR(100) | ФИО |
| email | VARCHAR(100) | Email |
| role | VARCHAR(20) | Роль: admin, manager, viewer |
| created_at | DATETIME | Дата создания |

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    bitrix_id VARCHAR(50) UNIQUE,
    name VARCHAR(100),
    email VARCHAR(100),
    role VARCHAR(20) DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### manual_edits

Хранит историю ручных правок.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| upload_id | INTEGER FK | Ссылка на загрузку |
| order_id | INTEGER FK | Ссылка на заказ |
| calculation_id | INTEGER FK | Ссылка на расчёт |
| field | VARCHAR(50) | Изменённое поле |
| old_value | VARCHAR(100) | Старое значение |
| new_value | VARCHAR(100) | Новое значение |
| edited_by | INTEGER FK | Кто изменил |
| edited_at | DATETIME | Когда изменил |

### audit_log

Хранит аудит действий пользователей.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный идентификатор |
| user_id | INTEGER FK | Кто выполнил |
| action | VARCHAR(50) | Действие |
| entity_type | VARCHAR(50) | Тип сущности |
| entity_id | INTEGER | ID сущности |
| period_id | INTEGER | ID периода |
| details | JSON | Детали |
| created_at | DATETIME | Когда |

---

## Связи

### Основные связи

```
periods (1) ─────< (N) uploads
uploads (1) ─────< (N) orders
uploads (1) ─────< (N) calculations
uploads (1) ─────< (N) worker_totals
orders (1) ─────< (1) calculations
users (1) ─────< (N) uploads (created_by)
users (1) ─────< (N) manual_edits (edited_by)
```

### JOIN-запросы

Получение заказов с расчётами:
```sql
SELECT o.*, c.fuel_payment, c.transport, c.diagnostic_50, c.total
FROM orders o
LEFT JOIN calculations c ON o.id = c.order_id
WHERE o.upload_id = :upload_id
ORDER BY o.worker, o.is_client_payment, o.id
```

---

## Индексы

```sql
CREATE INDEX idx_uploads_period ON uploads(period_id);
CREATE INDEX idx_orders_upload ON orders(upload_id);
CREATE INDEX idx_orders_worker ON orders(worker);
CREATE INDEX idx_calculations_upload ON calculations(upload_id);
CREATE INDEX idx_calculations_order ON calculations(order_id);
CREATE INDEX idx_worker_totals_upload ON worker_totals(upload_id);
```

---

## Миграции

### Добавление created_by в uploads

```sql
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id);
```

### Добавление статусов в periods

```sql
ALTER TABLE periods ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'DRAFT';
ALTER TABLE periods ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP;
ALTER TABLE periods ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
```

Миграции выполняются автоматически при старте приложения в функции `run_migrations()`.
