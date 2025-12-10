# API Reference - Salary Service

## Базовый URL
```
https://automated-payroll-installers-production.up.railway.app
```

---

## 📋 Периоды и загрузки

### GET /api/periods
Получить список всех периодов с группировкой по месяцам.

**Response:**
```json
{
  "months": {
    "2025-11": {
      "periods": [
        {
          "id": 4,
          "name": "16-30.11.25",
          "uploads_count": 11,
          "latest_upload": {...}
        }
      ]
    }
  }
}
```

---

### GET /api/period/{period_id}
Получить детали периода со всеми версиями.

**Response:**
```json
{
  "period": {
    "id": 4,
    "name": "16-30.11.25"
  },
  "uploads": [
    {
      "id": 23,
      "version": 11,
      "workers": [
        {
          "worker": "Ветренко Дмитрий",
          "total_amount": 46436,
          "company_amount": 28186,
          "client_amount": 18250,
          "orders_count": 23,
          "company_orders_count": 13,
          "client_orders_count": 10
        }
      ]
    }
  ]
}
```

---

### GET /api/upload/{upload_id}
Получить детали конкретной загрузки.

**Response:**
```json
{
  "upload": {
    "id": 23,
    "period_id": 4,
    "version": 11
  },
  "workers": [...],
  "totals": {
    "company": 460990,
    "client": 36250,
    "total": 497240
  }
}
```

---

### GET /api/upload/{upload_id}/worker/{worker}
Получить все заказы работника.

**URL encode** имя работника: `%D0%92%D0%B5%D1%82%D1%80%D0%B5%D0%BD%D0%BA%D0%BE%20%D0%94%D0%BC%D0%B8%D1%82%D1%80%D0%B8%D0%B9`

**Response:**
```json
{
  "worker": "Ветренко Дмитрий",
  "totals": {
    "orders_count": 23,
    "revenue": 27065,
    "service_payment": 45136,
    "fuel": 300,
    "transport": 1000,
    "total": 46436
  },
  "orders": [
    {
      "id": 1920,
      "order_code": "КАУТ-001736",
      "address": "Москва, Мосфильмовская улица, 74Б",
      "revenue_services": 27065,
      "service_payment": 8120,
      "percent": "30,00 %",
      "is_client_payment": false,
      "is_extra_row": false,
      "calculation": {
        "id": 1920,
        "fuel_payment": 300,
        "transport": 1000,
        "total": 9420
      }
    }
  ]
}
```

---

## ✏️ Редактирование

### POST /api/calculation/{calc_id}/update
Обновить значения расчёта (бензин, транспортные, итого).

**Request:**
```json
{
  "fuel_payment": 500,
  "transport": 1000,
  "total": 10000
}
```

**Response:**
```json
{
  "success": true,
  "updated": {
    "total": 10000
  }
}
```

**Эффект:** 
- Обновляет `calculations`
- Пересчитывает `worker_totals` через JOIN
- Сохраняет в `manual_edits`

---

### PUT /api/order/{order_id}/update
Обновить данные заказа (код, адрес).

**Request:**
```json
{
  "order_code": "ДОПЛАТА",
  "address": "Отпускные"
}
```

**Response:**
```json
{
  "success": true,
  "updated": {
    "order_code": "ДОПЛАТА",
    "address": "Отпускные",
    "order_full": "ДОПЛАТА, Отпускные"
  }
}
```

---

### POST /api/upload/{upload_id}/worker/{worker}/add-row
Добавить новую строку для работника.

**Request:**
```json
{
  "order_code": "",
  "address": "",
  "fuel_payment": 0,
  "transport": 0,
  "total": 0
}
```

**Response:**
```json
{
  "success": true,
  "order": {
    "id": 1950,
    "order_code": "",
    "address": "",
    "is_extra_row": true,
    "calculation": {
      "id": 1950,
      "total": 0
    }
  }
}
```

**Эффект:**
- Создаёт `order` с `is_extra_row=true`
- Создаёт `calculation`
- Пересчитывает `worker_totals`

---

### DELETE /api/order/{order_id}
Удалить заказ и связанный расчёт.

**Response:**
```json
{
  "success": true,
  "deleted_order_id": 1950,
  "deleted_total": 39493
}
```

**Эффект:**
- Удаляет `manual_edits` (FK constraint!)
- Удаляет `calculation`
- Удаляет `order`
- Пересчитывает `worker_totals`

---

## 📥 Отчёты

### GET /api/period/{period_id}/download/full
Скачать полный Excel отчёт.

**Response:** Excel файл (application/vnd.openxmlformats...)

---

### GET /api/period/{period_id}/download/workers
Скачать Excel для монтажников (упрощённый).

**Response:** Excel файл

---

### GET /api/period/{period_id}/download/archive
Скачать ZIP архив с отдельными файлами для каждого работника.

**Response:** ZIP файл

---

## 🔧 Служебные

### POST /api/upload/{upload_id}/recalculate
Принудительно пересчитать все `worker_totals` для загрузки.

**Использовать когда:** данные рассинхронизировались

**Response:**
```json
{
  "success": true,
  "recalculated_count": 8,
  "workers": [
    {
      "worker": "Ветренко Дмитрий",
      "company_amount": 28186,
      "client_amount": 18250,
      "total_amount": 46436
    }
  ]
}
```

---

### GET /api/1c/status
Проверить статус интеграции с 1С.

**Response:**
```json
{
  "enabled": false,
  "base_url": null,
  "message": "Интеграция с 1С не настроена"
}
```

---

### GET /api/1c/order/{order_code}
Получить информацию о заказе из 1С (когда интеграция включена).

**Response (когда включено):**
```json
{
  "success": true,
  "order": {
    "number": "КАУТ-001770",
    "date": "2024-11-15T10:30:00",
    "status": "Выполнен",
    "client": {
      "name": "ООО Рога и копыта",
      "inn": "7701234567"
    },
    "amounts": {
      "total": 38236,
      "paid": 38236,
      "debt": 0
    },
    "payments": [...]
  }
}
```

---

## 🔄 Сравнение версий

### GET /api/upload/{upload_id}/comparison/{prev_upload_id}
Сравнить две версии загрузки.

**Response:**
```json
{
  "changes": {
    "added": [...],
    "modified": [...],
    "deleted": [...]
  }
}
```

---

## 📝 Примеры использования

### JavaScript (в консоли браузера)

```javascript
// Пересчитать worker_totals для upload_id=23
fetch('/api/upload/23/recalculate', {method: 'POST'})
  .then(r => r.json())
  .then(console.log)

// Обновить итого для calculation_id=1920
fetch('/api/calculation/1920/update', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({total: 10000})
}).then(r => r.json()).then(console.log)

// Добавить строку
fetch('/api/upload/23/worker/Ветренко%20Дмитрий/add-row', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({total: 5000})
}).then(r => r.json()).then(console.log)
```

### cURL

```bash
# Пересчитать
curl -X POST https://...railway.app/api/upload/23/recalculate

# Обновить
curl -X POST https://...railway.app/api/calculation/1920/update \
  -H "Content-Type: application/json" \
  -d '{"total": 10000}'
```
