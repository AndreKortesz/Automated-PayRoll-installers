# 🔌 API Reference — Полный справочник

## Содержание
1. [Общая информация](#общая-информация)
2. [Аутентификация](#аутентификация)
3. [Периоды](#периоды)
4. [Загрузки](#загрузки)
5. [Заказы и расчёты](#заказы-и-расчёты)
6. [Поиск](#поиск)
7. [Отчёты](#отчёты)
8. [Статусы](#статусы)
9. [Коды ошибок](#коды-ошибок)

---

## Общая информация

### Base URL
```
Production: https://salary.mos-gsm.ru
Local:      http://localhost:8000
```

### Формат ответов
Все API endpoints возвращают JSON:

```json
// Успешный ответ
{
    "success": true,
    "data": { ... }
}

// Ошибка
{
    "success": false,
    "error": "Описание ошибки"
}
```

### Заголовки
```http
Content-Type: application/json
X-CSRF-Token: <csrf_token>   # Для POST/PUT/DELETE
Cookie: salary_session=<session_id>
```

---

## Аутентификация

### Начать OAuth авторизацию
```http
GET /auth/login
```

**Response:** Redirect на Bitrix24 OAuth

---

### OAuth Callback
```http
GET /auth/callback?code=<authorization_code>
```

**Response:** Redirect на `/` с установкой cookie сессии

---

### Выход
```http
GET /auth/logout
POST /auth/logout
```

**Response:** Redirect на `/login`

---

### Текущий пользователь
```http
GET /api/me
```

**Response:**
```json
{
    "success": true,
    "user": {
        "id": 1,
        "name": "Иванов Иван Иванович",
        "email": "ivanov@company.ru",
        "role": "admin",
        "bitrix_id": "123"
    }
}
```

---

## Периоды

### Список периодов
```http
GET /api/periods
```

**Query параметры:**
| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `status` | string | - | Фильтр по статусу: DRAFT, SENT, PAID |
| `year` | int | - | Фильтр по году |
| `month` | int | - | Фильтр по месяцу |
| `limit` | int | 50 | Максимум записей |
| `offset` | int | 0 | Смещение |

**Response:**
```json
{
    "success": true,
    "periods": [
        {
            "id": 15,
            "name": "16-31.12.25",
            "month": 12,
            "year": 2025,
            "status": "DRAFT",
            "upload_id": 69,
            "version": 3,
            "workers_count": 12,
            "orders_count": 156,
            "total": 1250000,
            "created_at": "2025-12-16T10:30:00"
        }
    ],
    "total_count": 25
}
```

---

### Детали периода
```http
GET /api/period/{period_id}
```

**Response:**
```json
{
    "success": true,
    "period": {
        "id": 15,
        "name": "16-31.12.25",
        "status": "DRAFT",
        "uploads": [
            {
                "id": 69,
                "version": 3,
                "created_at": "2025-12-20T14:00:00",
                "created_by": "Иванов И.И."
            },
            {
                "id": 65,
                "version": 2,
                "created_at": "2025-12-18T10:00:00",
                "created_by": "Петров П.П."
            }
        ],
        "current_upload": {
            "id": 69,
            "workers_count": 12,
            "orders_count": 156,
            "total": 1250000
        }
    }
}
```

---

### Удалить период
```http
DELETE /api/period/{period_id}
```

**Требуется:** роль `admin`

**Response:**
```json
{
    "success": true,
    "message": "Период удалён"
}
```

---

## Загрузки

### Загрузить файлы
```http
POST /upload
Content-Type: multipart/form-data
```

**Body:**
```
files[]: revenue.xlsx
files[]: diagnostic.xlsx
files[]: yandex_fuel.xlsx (опционально)
```

**Response:**
```json
{
    "success": true,
    "redirect": "/review?session=abc123"
}
```

---

### Данные для review
```http
GET /api/review/{session_id}
```

**Response:**
```json
{
    "success": true,
    "period": "16-31.12.25",
    "changes": {
        "new": [
            {
                "worker": "Иванов Иван",
                "order_code": "КАУТ-001500",
                "revenue_services": 50000
            }
        ],
        "deleted": [...],
        "modified": [...],
        "manual_edits": [...]
    },
    "has_previous": true
}
```

---

### Применить изменения
```http
POST /api/apply-review
Content-Type: application/json
```

**Body:**
```json
{
    "session_id": "abc123",
    "restore_manual_edits": [1, 2, 5]
}
```

**Response:**
```json
{
    "success": true,
    "period_id": 15,
    "upload_id": 69,
    "redirect": "/upload/69"
}
```

---

### Детали загрузки
```http
GET /api/upload/{upload_id}
```

**Response:**
```json
{
    "success": true,
    "upload": {
        "id": 69,
        "period_id": 15,
        "period_name": "16-31.12.25",
        "version": 3,
        "status": "DRAFT",
        "created_at": "2025-12-20T14:00:00",
        "workers": [
            {
                "name": "Иванов Иван Иванович",
                "orders_count": 15,
                "company_total": 45000,
                "client_total": 5000,
                "fuel": 3200,
                "transport": 2000,
                "yandex_fuel": 9000,
                "grand_total": 46200
            }
        ],
        "totals": {
            "orders_count": 156,
            "grand_total": 1250000
        }
    }
}
```

---

## Заказы и расчёты

### Заказы монтажника
```http
GET /api/upload/{upload_id}/worker/{worker_name}
```

**Response:**
```json
{
    "success": true,
    "worker": "Иванов Иван Иванович",
    "orders": [
        {
            "id": 1234,
            "order_code": "КАУТ-001405",
            "order_date": "2025-12-20",
            "address": "г. Москва, ул. Ленина, 1",
            "revenue_total": 50000,
            "revenue_services": 40000,
            "service_payment": 12000,
            "percent": "30%",
            "is_client_payment": false,
            "calculation": {
                "id": 5678,
                "fuel_payment": 300,
                "transport": 1000,
                "diagnostic_50": 0,
                "total": 13300
            }
        }
    ],
    "totals": {
        "company_orders_count": 12,
        "client_orders_count": 3,
        "company_total": 45000,
        "client_total": 5000,
        "fuel": 3200,
        "transport": 2000,
        "yandex_fuel": 9000,
        "grand_total": 46200
    }
}
```

---

### Обновить расчёт
```http
POST /api/calculation/{calc_id}/update
Content-Type: application/json
```

**Body:**
```json
{
    "field": "fuel_payment",
    "value": 500
}
```

**Поля:**
- `fuel_payment` — Бензин
- `transport` — Транспортные
- `total` — Итого

**Response:**
```json
{
    "success": true,
    "calculation": {
        "id": 5678,
        "fuel_payment": 500,
        "transport": 1000,
        "total": 13500
    },
    "worker_totals": {
        "grand_total": 46400
    }
}
```

---

### Добавить строку
```http
POST /api/upload/{upload_id}/worker/{worker_name}/add-row
Content-Type: application/json
```

**Body:**
```json
{
    "description": "Доплата за Кардан",
    "amount": 5000
}
```

**Response:**
```json
{
    "success": true,
    "order": {
        "id": 1500,
        "order_code": "-",
        "address": "Доплата за Кардан",
        "is_extra_row": true
    },
    "calculation": {
        "id": 6000,
        "total": 5000
    }
}
```

---

### Удалить заказ
```http
DELETE /api/order/{order_id}
```

**Требуется:** роль `admin` или `manager`, статус `DRAFT`

**Response:**
```json
{
    "success": true,
    "message": "Заказ удалён",
    "worker_totals": {
        "grand_total": 41200
    }
}
```

---

## Поиск

### Глобальный поиск
```http
GET /api/search?q={query}&limit={limit}
```

**Query параметры:**
| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `q` | string | - | Поисковый запрос (мин. 2 символа) |
| `limit` | int | 10 | Максимум результатов (1-100) |

**Поиск по:**
- Номер заказа (КАУТ-001234)
- Адрес (частичное совпадение, fuzzy)
- ФИО монтажника

**Особенности:**
- Fuzzy search через PostgreSQL `pg_trgm`
- Автозамена ё↔е
- Только последние версии периодов

**Response:**
```json
{
    "success": true,
    "query": "озерная",
    "results": [
        {
            "order_id": 1234,
            "order_code": "КАУТ-001854",
            "order_date": "25.12.25",
            "worker": "Романюк Алексей",
            "address": "КП Агаларов, ул. Озерная, 14",
            "total": 24220,
            "upload_id": 69,
            "period_name": "16-31.12.25",
            "type": "Компания"
        }
    ],
    "count": 4
}
```

---

## Отчёты

### Скачать архив отчётов
```http
GET /api/period/{period_id}/download/{archive_type}
```

**archive_type:**
| Значение | Описание |
|----------|----------|
| `all` | Все отчёты в ZIP |
| `accounting` | Только бухгалтерский отчёт |
| `individual` | Только индивидуальные отчёты |

**Response:** Файл Excel или ZIP

---

### Отчёт по монтажнику
```http
GET /api/upload/{upload_id}/worker/{worker_name}/report
```

**Response:** Excel файл

---

## Статусы

### Изменить статус периода
```http
POST /api/period/{period_id}/status
Content-Type: application/json
```

**Body:**
```json
{
    "status": "SENT"
}
```

**Разрешённые переходы:**
| Из | В | Роли |
|----|---|------|
| DRAFT | SENT | admin, manager |
| SENT | PAID | admin |
| PAID | SENT | admin |
| SENT | DRAFT | admin |

**Response:**
```json
{
    "success": true,
    "period": {
        "id": 15,
        "status": "SENT",
        "sent_at": "2025-12-25T10:00:00"
    }
}
```

---

## Коды ошибок

| Код | HTTP | Описание |
|-----|------|----------|
| `UNAUTHORIZED` | 401 | Требуется авторизация |
| `FORBIDDEN` | 403 | Недостаточно прав |
| `NOT_FOUND` | 404 | Ресурс не найден |
| `VALIDATION_ERROR` | 400 | Ошибка валидации |
| `PERIOD_LOCKED` | 403 | Период заблокирован (не DRAFT) |
| `FILE_PARSE_ERROR` | 400 | Ошибка парсинга файла |
| `GEOCODING_ERROR` | 500 | Ошибка геокодирования |

---

## Примеры

### cURL
```bash
# Поиск
curl "https://salary.mos-gsm.ru/api/search?q=озерная&limit=10" \
  -H "Cookie: salary_session=xxx"

# Обновить расчёт  
curl -X POST "https://salary.mos-gsm.ru/api/calculation/123/update" \
  -H "Cookie: salary_session=xxx" \
  -H "X-CSRF-Token: xxx" \
  -H "Content-Type: application/json" \
  -d '{"field": "fuel_payment", "value": 500}'
```

### JavaScript
```javascript
const result = await Security.fetch('/api/calculation/123/update', {
    method: 'POST',
    body: JSON.stringify({ field: 'fuel_payment', value: 500 })
});
```
