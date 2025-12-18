# API Reference

## Оглавление

1. [Аутентификация](#аутентификация)
2. [Загрузка файлов](#загрузка-файлов)
3. [Периоды](#периоды)
4. [Расчёты](#расчёты)
5. [Отчёты](#отчёты)
6. [Статусы](#статусы)

---

## Аутентификация

### OAuth2 через Bitrix24

#### Начало авторизации

```http
GET /auth/login
```

Перенаправляет на страницу авторизации Bitrix24.

#### Callback

```http
GET /auth/callback?code={code}&domain={domain}
```

Обрабатывает ответ от Bitrix24, создаёт сессию.

#### Выход

```http
GET /auth/logout
```

Завершает сессию.

---

## Загрузка файлов

### Определение типа файла

```http
POST /api/detect-file-type
Content-Type: multipart/form-data

file: <Excel file>
```

**Response:**
```json
{
    "success": true,
    "file_type": "revenue",  // "revenue" | "diagnostic" | "yandex_fuel" | "unknown"
    "period": "16-30.11.25",
    "workers_count": 5
}
```

### Загрузка файлов

```http
POST /upload
Content-Type: multipart/form-data

file_revenue: <Excel file>       // Обязательный
file_diagnostic: <Excel file>    // Обязательный
file_yandex_fuel: <Excel file>   // Обязательный для периодов 16-30
```

**Response (есть предыдущая версия):**
```json
{
    "success": true,
    "session_id": "20251218103627",
    "redirect_to_review": true,
    "has_changes": true,
    "changes": {
        "added": [...],
        "deleted": [...],
        "modified": [...]
    }
}
```

**Response (первая загрузка):**
```json
{
    "success": true,
    "period_id": 4,
    "upload_id": 48
}
```

---

## Периоды

### Список периодов

```http
GET /api/periods
```

**Response:**
```json
{
    "periods": [
        {
            "id": 4,
            "name": "16-30.11.25",
            "month": 11,
            "year": 2025,
            "status": "DRAFT",
            "uploads_count": 3,
            "latest_upload": {
                "id": 48,
                "version": 3,
                "created_at": "2025-12-18T10:36:27"
            }
        }
    ]
}
```

### Детали периода

```http
GET /api/period/{period_id}
```

**Response:**
```json
{
    "id": 4,
    "name": "16-30.11.25",
    "status": "DRAFT",
    "uploads": [
        {
            "id": 48,
            "version": 3,
            "created_at": "2025-12-18T10:36:27",
            "created_by": "Конторин Андрей"
        }
    ],
    "worker_totals": [
        {
            "worker": "Ветренко Дмитрий",
            "total": 66180,
            "fuel": 300,
            "transport": 1000,
            "orders_count": 15
        }
    ]
}
```

### Права на период

```http
GET /api/period/{period_id}/permissions
```

**Response:**
```json
{
    "can_edit": true,
    "can_upload": true,
    "can_change_status": true,
    "can_delete": false,
    "current_status": "DRAFT",
    "available_statuses": ["SENT"]
}
```

---

## Расчёты

### Preview расчёта

```http
POST /preview
Content-Type: application/x-www-form-urlencoded

session_id=20251218103627
config_json={"diagnostic_percent": 50}
days_json={}
extra_rows_json={"Иванов Иван": [{"description": "Доплата", "amount": 5000}]}
```

**Response:**
```json
{
    "success": true,
    "preview": [
        {
            "worker": "Ветренко Дмитрий",
            "order": "КАУТ-001405, газетный переулок",
            "revenue_total": 70742,
            "service_payment": 21223,
            "fuel_payment": 300,
            "transport": 1000,
            "total": 22523
        }
    ],
    "summary": {
        "total": 350000,
        "workers_count": 5
    },
    "alarms": []
}
```

### Применение изменений из Review

```http
POST /api/apply-review
Content-Type: application/json

{
    "session_id": "20251218103627",
    "selections": {
        "added": ["ИБУТ-000392_Ветренко Дмитрий"],
        "deleted": ["КАУТ-001405_Фадин Сергей"],
        "modified": []
    }
}
```

**Response:**
```json
{
    "success": true,
    "period_id": 4,
    "upload_id": 49
}
```

### Финальный расчёт

```http
POST /calculate
Content-Type: application/x-www-form-urlencoded

session_id=20251218103627
config_json={"diagnostic_percent": 50}
days_json={}
extra_rows_json={}
deleted_rows=[]
```

**Response:**
```json
{
    "success": true,
    "period_id": 4,
    "upload_id": 49,
    "archives": {
        "full": "base64...",
        "workers": "base64..."
    }
}
```

---

## Отчёты

### Скачать архив

```http
GET /api/period/{period_id}/download/{archive_type}
```

**Параметры:**
- `archive_type`: `full` | `workers`

**Response:** ZIP-архив с Excel-файлами

**Содержимое архива (full):**
- `Общий_отчет_16-30_11_25.xlsx` — сводный отчёт
- `Ветренко_16-30_11_25.xlsx` — отчёт монтажника
- ... (файл для каждого монтажника)

**Содержимое архива (workers):**
Те же файлы, но с скрытыми колонками (для выдачи монтажникам).

### Детали загрузки

```http
GET /api/upload/{upload_id}
```

**Response:**
```json
{
    "id": 48,
    "version": 3,
    "period_id": 4,
    "created_at": "2025-12-18T10:36:27",
    "orders": [...],
    "worker_totals": [...],
    "config": {
        "diagnostic_percent": 50,
        "yandex_fuel": {
            "Ветренко Дмитрий": 4898.52
        }
    }
}
```

### Отчёт по монтажнику

```http
GET /upload/{upload_id}?worker={worker_name}
```

Страница с детальным отчётом по монтажнику.

### Скачать отчёт монтажника

```http
GET /api/upload/{upload_id}/worker/{worker_name}/download
```

**Response:** Excel-файл

---

## Статусы

### Изменить статус периода

```http
POST /api/period/{period_id}/status
Content-Type: application/json

{
    "status": "SENT"
}
```

**Response:**
```json
{
    "success": true,
    "period_id": 4,
    "old_status": "DRAFT",
    "new_status": "SENT",
    "sent_at": "2025-12-18T10:45:00"
}
```

### Возможные статусы

| Статус | Описание |
|--------|----------|
| DRAFT | Черновик, можно редактировать |
| SENT | Отправлено, только просмотр |
| PAID | Оплачено, архив |

---

## Коды ошибок

| Код | Описание |
|-----|----------|
| 400 | Неверный запрос (отсутствуют обязательные поля) |
| 401 | Не авторизован |
| 403 | Нет прав доступа |
| 404 | Ресурс не найден |
| 409 | Конфликт (например, статус не позволяет действие) |
| 500 | Внутренняя ошибка сервера |

### Формат ошибки

```json
{
    "success": false,
    "error": "Описание ошибки",
    "detail": "Подробности (опционально)"
}
```
