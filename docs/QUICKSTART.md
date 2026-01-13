# 🚀 Быстрый старт для разработчика

## Содержание
1. [Требования](#требования)
2. [Локальная установка](#локальная-установка)
3. [Структура проекта](#структура-проекта)
4. [Первый запуск](#первый-запуск)
5. [Тестовые данные](#тестовые-данные)
6. [Типичные задачи](#типичные-задачи)

---

## Требования

### Минимальные
- Python 3.11+
- PostgreSQL 14+
- Git

### Для полной функциональности
- Аккаунт Bitrix24 (OAuth)
- API ключ Yandex Geocoder

---

## Локальная установка

### 1. Клонирование репозитория

```bash
git clone https://github.com/mos-gsm/salary-service.git
cd salary-service
```

### 2. Создание виртуального окружения

```bash
# Linux/Mac
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка PostgreSQL

```bash
# Создать базу данных
createdb salary_service

# Или через psql
psql -U postgres
CREATE DATABASE salary_service;
\q
```

### 5. Переменные окружения

Создайте файл `.env` в корне проекта:

```env
# Database
DATABASE_URL=postgresql://postgres:password@localhost:5432/salary_service

# Auth (можно пропустить для локальной разработки)
BITRIX_CLIENT_ID=local.xxxxx
BITRIX_CLIENT_SECRET=xxxxx
BITRIX_DOMAIN=svyaz.bitrix24.ru

# Geocoding (можно пропустить, будет fallback на Nominatim)
YANDEX_GEOCODER_API_KEY=xxxxx

# Security
SECRET_KEY=dev-secret-key-change-in-production
```

### 6. Запуск

```bash
cd backend
uvicorn app:app --reload --port 8000
```

Приложение будет доступно по адресу: http://localhost:8000

---

## Структура проекта

```
salary-service/
│
├── backend/                    # Python backend
│   ├── app.py                 # 🎯 ГЛАВНЫЙ ФАЙЛ (3800+ строк)
│   │                          # Все endpoints, основная логика
│   │
│   ├── database.py            # Модели БД, CRUD операции
│   ├── auth.py                # OAuth2 Bitrix24
│   ├── permissions.py         # Роли и права доступа
│   ├── config.py              # Конфигурация
│   ├── csrf_middleware.py     # CSRF защита
│   ├── api_status.py          # API статусов периодов
│   │
│   ├── services/              # Бизнес-логика
│   │   ├── excel_parser.py    # Парсинг файлов 1С
│   │   ├── excel_report.py    # Генерация Excel отчётов
│   │   ├── calculation.py     # Расчёт зарплат
│   │   ├── geocoding.py       # Yandex Geocoder
│   │   └── yandex_fuel_parser.py  # Парсинг Яндекс Заправки
│   │
│   └── utils/                 # Утилиты
│       ├── helpers.py         # Вспомогательные функции
│       └── workers.py         # Нормализация имён
│
├── frontend/
│   ├── templates/             # Jinja2 HTML шаблоны
│   │   ├── index.html         # Главная страница
│   │   ├── history.html       # История периодов
│   │   ├── upload.html        # Детали загрузки
│   │   ├── comparison.html    # Сравнение версий
│   │   ├── search.html        # Страница поиска
│   │   └── login.html         # Страница входа
│   │
│   └── static/
│       ├── style.css          # Стили
│       └── security.js        # CSRF, fetch wrapper
│
├── docs/                      # Документация
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Первый запуск

### Без авторизации (режим разработки)

Для локальной разработки можно отключить OAuth:

```python
# В auth.py временно добавить:
def get_current_user(request):
    return {
        "id": 1,
        "name": "Dev User",
        "role": "admin",
        "bitrix_id": "1"
    }
```

### С авторизацией Bitrix24

1. Создайте приложение в Bitrix24:
   - Маркет → Разработчикам → Создать приложение
   - Тип: Серверное
   - Права: user
   - Redirect URI: `http://localhost:8000/auth/callback`

2. Скопируйте Client ID и Secret в `.env`

3. Перейдите на http://localhost:8000 и авторизуйтесь

---

## Тестовые данные

### Создание тестового файла выручки

Создайте Excel файл с такой структурой:

| Отбор | | | | | | | | | |
|-------|--|--|--|--|--|--|--|--|--|
| Заказ 16-30.11.25 от контрагента | | | | | | | | | |
| | | | | | | | | | |
| Монтажник | Заказ | Адрес | Выручка итого | Выручка от услуг | Диагностика | Выезд | Доп.расходы | Оплата услуг | % |
| Иванов Иван | КАУТ-001234 | г. Москва, ул. Ленина, 1 | 50000 | 40000 | 5000 | 0 | 0 | 12000 | 30% |

### Минимальный тест через API

```bash
# Загрузка файлов
curl -X POST http://localhost:8000/upload \
  -F "files=@revenue.xlsx" \
  -F "files=@diagnostic.xlsx"

# Получение периодов
curl http://localhost:8000/api/periods
```

---

## Типичные задачи

### Добавить новый endpoint

```python
# В app.py добавить:

@app.get("/api/my-endpoint")
async def my_endpoint(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    # Логика
    return JSONResponse({"success": True, "data": ...})
```

### Добавить новое поле в БД

```python
# 1. В database.py добавить колонку в модель:
orders = Table(
    "orders", metadata,
    # ... существующие колонки
    Column("new_field", String(100)),  # Новая колонка
)

# 2. Добавить миграцию:
async def run_migrations():
    # ... существующие миграции
    try:
        await database.execute(
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS new_field VARCHAR(100)"
        )
    except:
        pass
```

### Изменить формулу расчёта

```python
# В services/calculation.py найти нужную функцию:

def calculate_fuel(distance_km: float) -> float:
    """Расчёт бензина по расстоянию"""
    for max_dist, payment in FUEL_TARIFFS:
        if distance_km <= max_dist:
            return payment
    return FUEL_TARIFFS[-1][1]
```

### Добавить новый отчёт

```python
# В services/excel_report.py:

def generate_custom_report(data: List[dict]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Custom Report"
    
    # Заголовки
    headers = ["Колонка 1", "Колонка 2"]
    for col, header in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=header)
    
    # Данные
    for row_idx, item in enumerate(data, 2):
        ws.cell(row=row_idx, column=1, value=item["field1"])
        ws.cell(row=row_idx, column=2, value=item["field2"])
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
```

---

## Отладка

### Включить подробные логи

```python
# В app.py в начале добавить:
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Посмотреть SQL запросы

```python
# В database.py:
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

### Тестирование геокодинга

```python
# Запустить в Python REPL:
import asyncio
from services.geocoding import geocode_address_yandex

async def test():
    coords = await geocode_address_yandex("Москва, ул. Ленина, 1")
    print(coords)

asyncio.run(test())
```

---

## Следующие шаги

1. Изучи [ARCHITECTURE.md](./ARCHITECTURE.md) — детальная архитектура
2. Прочитай [BUSINESS_LOGIC.md](./BUSINESS_LOGIC.md) — бизнес-правила
3. Посмотри [API_REFERENCE.md](./API_REFERENCE.md) — все endpoints
