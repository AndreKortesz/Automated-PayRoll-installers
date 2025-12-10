# Database Schema - Salary Service

## Диаграмма связей

```
┌─────────────┐
│   periods   │
├─────────────┤
│ id (PK)     │
│ name        │──────────────────────────────────────┐
│ month       │                                      │
│ year        │                                      │
└─────────────┘                                      │
                                                     │
                                                     ▼
┌─────────────┐     ┌─────────────────────────────────────────┐
│   uploads   │     │              worker_totals              │
├─────────────┤     ├─────────────────────────────────────────┤
│ id (PK)     │◄────┤ upload_id (FK)                          │
│ period_id   │     │ worker          (базовое имя)           │
│ version     │     │ total_amount    = company + client      │
│ config_json │     │ company_amount  (is_client_payment=F)   │
└─────────────┘     │ client_amount   (is_client_payment=T)   │
       │            │ orders_count                            │
       │            │ company_orders_count                    │
       │            │ client_orders_count                     │
       │            │ fuel_total                              │
       │            │ transport_total                         │
       │            └─────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                          orders                               │
├──────────────────────────────────────────────────────────────┤
│ id (PK)                                                       │
│ upload_id (FK)                                                │
│ worker              "Имя Фамилия" или "Имя Фамилия (оплата...│
│ order_code          "КАУТ-001770"                            │
│ order_full          Полный текст заказа                      │
│ address             Извлечённый адрес                        │
│ revenue_total       Выручка итого                            │
│ revenue_services    Выручка от услуг                         │
│ diagnostic          Диагностика                              │
│ diagnostic_payment  Оплата диагностики                       │
│ specialist_fee      Выручка (выезд)                          │
│ additional_expenses Доп. расходы                             │
│ service_payment     Сумма оплаты                             │
│ percent             "30,00 %"                                │
│ is_client_payment   ★ КЛЮЧЕВОЕ ПОЛЕ для разделения ★         │
│ is_over_10k         Выручка > 10к                            │
│ is_extra_row        Ручное добавление                        │
└──────────────────────────────────────────────────────────────┘
       │
       │ order_id (FK)
       ▼
┌──────────────────────────────────────────────────────────────┐
│                       calculations                            │
├──────────────────────────────────────────────────────────────┤
│ id (PK)                                                       │
│ upload_id (FK)                                                │
│ order_id (FK)        ──────────────────────────────────────┐ │
│ worker                                                      │ │
│ fuel_payment         Бензин (0-3000)                        │ │
│ transport            Транспортные (0 или 1000)              │ │
│ diagnostic_50        Диагностика -50%                       │ │
│ total                = service_payment + fuel + transport   │ │
└──────────────────────────────────────────────────────────────┘
       │                                                      │
       │ calculation_id (FK)                                  │
       ▼                                                      │
┌──────────────────────────────────────┐                      │
│          manual_edits                │                      │
├──────────────────────────────────────┤                      │
│ id (PK)                              │                      │
│ upload_id (FK)                       │                      │
│ order_id (FK)        ◄───────────────┼──────────────────────┘
│ calculation_id (FK)  ◄───────────────┘
│ order_code                           │
│ worker                               │
│ address                              │
│ field_name           "total", "fuel_payment", "transport"
│ old_value                            │
│ new_value                            │
│ created_at                           │
└──────────────────────────────────────┘


┌──────────────────────────────────────┐
│            changes                   │
├──────────────────────────────────────┤
│ id (PK)                              │
│ upload_id (FK)                       │
│ order_code                           │
│ worker                               │
│ change_type         "added"/"modified"/"deleted"
│ field_name                           │
│ old_value                            │
│ new_value                            │
│ created_at                           │
└──────────────────────────────────────┘
```

## Ключевые связи

### Порядок удаления (foreign keys)
```
1. manual_edits (ссылается на calculations и orders)
2. calculations (ссылается на orders)
3. orders (ссылается на uploads)
```

### Пересчёт worker_totals

**ПРАВИЛЬНЫЙ способ** — JOIN через orders.is_client_payment:

```sql
SELECT 
    SUM(CASE WHEN o.is_client_payment = FALSE THEN c.total ELSE 0 END) as company_amount,
    SUM(CASE WHEN o.is_client_payment = TRUE THEN c.total ELSE 0 END) as client_amount
FROM calculations c
JOIN orders o ON c.order_id = o.id
WHERE c.upload_id = :upload_id
AND (o.worker = :worker OR o.worker = :worker || ' (оплата клиентом)')
```

**НЕПРАВИЛЬНЫЙ способ** — проверка суффикса в имени:
```python
# НЕ ДЕЛАТЬ ТАК!
is_client = "(оплата клиентом)" in worker_name
```

## Типичные значения

| Поле | Типичные значения |
|------|-------------------|
| order_code | КАУТ-001770, ИБУТ-000387 |
| percent | 30,00 %, 50,00 %, 100,00 % |
| fuel_payment | 0, 300, 900, 1500, 3000 |
| transport | 0, 1000 |
| diagnostic_50 | 0, 500, 1000, 1500 |
| is_client_payment | TRUE/FALSE |
| is_extra_row | TRUE (ручное), FALSE (из Excel) |
