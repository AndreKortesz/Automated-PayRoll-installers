# ⚙️ Конфигурация — Все настройки системы

## Содержание
1. [Переменные окружения](#переменные-окружения)
2. [Конфигурация расчётов](#конфигурация-расчётов)
3. [Тарифы на бензин](#тарифы-на-бензин)
4. [Списки сотрудников](#списки-сотрудников)
5. [Настройки безопасности](#настройки-безопасности)
6. [Настройки UI](#настройки-ui)

---

## Переменные окружения

### Обязательные

```env
# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════
DATABASE_URL=postgresql://user:password@host:5432/database
# Формат: postgresql://[user]:[password]@[host]:[port]/[database]
# Пример Railway: postgresql://postgres:xxx@xxx.railway.app:5432/railway

# ═══════════════════════════════════════════════════════════════
# BITRIX24 OAUTH
# ═══════════════════════════════════════════════════════════════
BITRIX_CLIENT_ID=local.xxxxxxxx.xxxxxxxx
# Client ID из настроек приложения Bitrix24

BITRIX_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Client Secret из настроек приложения Bitrix24

BITRIX_DOMAIN=svyaz.bitrix24.ru
# Домен вашего Bitrix24 (без https://)

# ═══════════════════════════════════════════════════════════════
# GEOCODING
# ═══════════════════════════════════════════════════════════════
YANDEX_GEOCODER_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# API ключ Yandex Geocoder
# Получить: https://developer.tech.yandex.ru
```

### Опциональные

```env
# ═══════════════════════════════════════════════════════════════
# SECURITY
# ═══════════════════════════════════════════════════════════════
SECRET_KEY=your-super-secret-key-change-in-production
# Ключ для подписи сессий и CSRF токенов
# По умолчанию: генерируется случайно при запуске

SESSION_EXPIRY=86400
# Время жизни сессии в секундах
# По умолчанию: 86400 (24 часа)

# ═══════════════════════════════════════════════════════════════
# APPLICATION
# ═══════════════════════════════════════════════════════════════
DEBUG=false
# Режим отладки
# true - подробные ошибки, hot reload
# false - production режим

LOG_LEVEL=INFO
# Уровень логирования: DEBUG, INFO, WARNING, ERROR

BASE_URL=https://salary.mos-gsm.ru
# Базовый URL приложения (для редиректов)

# ═══════════════════════════════════════════════════════════════
# HOSTING (Railway)
# ═══════════════════════════════════════════════════════════════
PORT=8000
# Порт приложения (Railway устанавливает автоматически)

RAILWAY_ENVIRONMENT=production
# Окружение Railway (автоматически)
```

### Пример .env файла

```env
# Database
DATABASE_URL=postgresql://postgres:mypassword@localhost:5432/salary_service

# Bitrix24
BITRIX_CLIENT_ID=local.12345678.abcdefgh
BITRIX_CLIENT_SECRET=abcdefghijklmnopqrstuvwxyz123456
BITRIX_DOMAIN=mycompany.bitrix24.ru

# Yandex
YANDEX_GEOCODER_API_KEY=12345678-1234-1234-1234-123456789012

# Security
SECRET_KEY=my-super-secret-key-for-sessions
SESSION_EXPIRY=86400

# App
DEBUG=false
LOG_LEVEL=INFO
```

---

## Конфигурация расчётов

### Основные параметры

```python
# config.py

DEFAULT_CONFIG = {
    # ═══════════════════════════════════════════════════════════
    # ТРАНСПОРТНЫЕ РАСХОДЫ
    # ═══════════════════════════════════════════════════════════
    
    "transport_min_revenue": 10000,
    # Минимальная выручка от услуг для начисления транспортных
    # Если revenue_services <= 10000, транспортные = 0
    
    "transport_percent_min": 20,
    # Минимальный процент монтажника для транспортных
    # Если percent < 20%, транспортные = 0
    
    "transport_percent_max": 40,
    # Максимальный процент монтажника для транспортных
    # Если percent > 40%, транспортные = 0
    
    "transport_amount": 1000,
    # Фиксированная сумма транспортных расходов (в рублях)
    
    # ═══════════════════════════════════════════════════════════
    # ЯНДЕКС ЗАПРАВКИ
    # ═══════════════════════════════════════════════════════════
    
    "yandex_fuel_discount": 0.9,
    # Коэффициент вычета Яндекс Заправок
    # 0.9 = вычитается 90% суммы (скидка 10% для сотрудника)
    
    # ═══════════════════════════════════════════════════════════
    # ДИАГНОСТИКА
    # ═══════════════════════════════════════════════════════════
    
    "diagnostic_client_rate": 0.5,
    # Коэффициент оплаты диагностики для заказов с оплатой клиентом
    # 0.5 = 50% от суммы диагностики
}
```

### Изменение параметров

Параметры можно изменить в файле `config.py` и перезапустить приложение.

Для изменения "на лету" можно добавить админ-панель или API endpoint.

---

## Тарифы на бензин

### Тарифная сетка

```python
# config.py

FUEL_TARIFFS = [
    # (максимальное_расстояние_км, оплата_рублей)
    
    (10, 100),     # 0-10 км → 100 ₽
    (20, 200),     # 10-20 км → 200 ₽
    (30, 300),     # 20-30 км → 300 ₽
    (40, 400),     # 30-40 км → 400 ₽
    (50, 500),     # 40-50 км → 500 ₽
    (60, 600),     # 50-60 км → 600 ₽
    (80, 900),     # 60-80 км → 900 ₽
    (100, 1200),   # 80-100 км → 1 200 ₽
    (150, 1700),   # 100-150 км → 1 700 ₽
    (200, 2200),   # 150-200 км → 2 200 ₽
    (999, 3000),   # 200+ км → 3 000 ₽
]
```

### Визуализация тарифов

```
Расстояние (км)    Оплата (₽)
─────────────────────────────
     0 ─ 10           100
    10 ─ 20           200
    20 ─ 30           300
    30 ─ 40           400
    40 ─ 50           500
    50 ─ 60           600
    60 ─ 80           900
    80 ─ 100        1 200
   100 ─ 150        1 700
   150 ─ 200        2 200
   200+             3 000
```

### Координаты офиса

```python
# config.py

OFFICE_COORDS = (55.8309, 37.4294)
# Широта, Долгота
# Адрес: Москва, Сходненский тупик, 16с4
```

---

## Списки сотрудников

### Монтажники на служебном авто

```python
# config.py

COMPANY_CAR_WORKERS = [
    "Ветренко Дмитрий Андреевич",
    # Добавьте других монтажников на служебном авто
]
```

**Важно:** Монтажники из этого списка НЕ получают транспортные расходы.

### Администраторы по Bitrix ID

```python
# auth.py

ADMIN_BITRIX_IDS = [
    "1",      # ID владельца Bitrix24
    "123",    # Другие админы
]
```

### Менеджеры по Bitrix ID

```python
# auth.py

MANAGER_BITRIX_IDS = [
    "456",
    "789",
]
```

### Исключённые группы

```python
# utils/workers.py

EXCLUDED_GROUPS = [
    "Итого",
    "Всего",
    "ИТОГО",
    "Подытог",
]
```

Строки, содержащие эти слова, игнорируются при парсинге.

---

## Настройки безопасности

### CSRF защита

```python
# csrf_middleware.py

CSRF_CONFIG = {
    "cookie_name": "csrf_token",
    "header_name": "X-CSRF-Token",
    "cookie_secure": True,      # Только HTTPS
    "cookie_httponly": False,   # JS должен читать
    "cookie_samesite": "strict",
}
```

### Сессии

```python
# auth.py

SESSION_CONFIG = {
    "cookie_name": "salary_session",
    "expiry_seconds": 86400,    # 24 часа
    "cookie_secure": True,
    "cookie_httponly": True,
    "cookie_samesite": "lax",
}
```

### CORS (если нужно)

```python
# app.py

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://salary.mos-gsm.ru"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Настройки UI

### Цвета бренда

```css
/* static/style.css */

:root {
    /* Основные цвета Mos-GSM */
    --yellow: #F3C04D;
    --yellow-dark: #D4A843;
    --black: #1A1A1A;
    --orange: #E07B3C;
    
    /* Можно изменить для другого бренда */
}
```

### Шрифты

```css
/* static/style.css */

/* Подключение шрифтов */
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');

/* Использование */
body {
    font-family: 'Roboto', sans-serif;
}

h1, h2, h3 {
    font-family: 'Bebas Neue', sans-serif;
}
```

### Лого

Заменить файл `/frontend/static/logo.svg` или `/frontend/static/logo.png`.

### Favicon

Заменить `/frontend/static/favicon.ico`.

---

## Примеры конфигураций

### Локальная разработка

```env
# .env.local
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/salary_dev
BITRIX_CLIENT_ID=local.dev.xxxxx
BITRIX_CLIENT_SECRET=xxxxx
BITRIX_DOMAIN=test.bitrix24.ru
YANDEX_GEOCODER_API_KEY=xxxxx
DEBUG=true
LOG_LEVEL=DEBUG
```

### Production (Railway)

```env
# Railway Environment Variables
DATABASE_URL=${{Postgres.DATABASE_URL}}
BITRIX_CLIENT_ID=local.prod.xxxxx
BITRIX_CLIENT_SECRET=xxxxx
BITRIX_DOMAIN=svyaz.bitrix24.ru
YANDEX_GEOCODER_API_KEY=xxxxx
DEBUG=false
LOG_LEVEL=INFO
SECRET_KEY=production-secret-key
```

### Тестирование

```env
# .env.test
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/salary_test
DEBUG=true
LOG_LEVEL=DEBUG
# Остальные переменные можно замокать
```
