# Salary Service

Сервис автоматического расчёта зарплаты монтажников.

## Быстрый старт

**URL:** https://automated-payroll-installers-production.up.railway.app

## Основной процесс

1. Загрузка двух Excel файлов (до 10к и свыше 10к)
2. Автоматический расчёт: бензин + транспортные + диагностика
3. Сохранение в PostgreSQL
4. Редактирование в веб-интерфейсе
5. Скачивание отчётов

## Ключевые формулы

```
ИТОГО = Сумма_оплаты + Бензин + Транспортные
Бензин = min(расстояние × 2 × 7, 3000) — если specialist_fee = 0
Транспортные = 1000₽ — если выручка > 10к и процент 20-40%
```

## Структура БД

- `periods` → `uploads` → `orders` → `calculations`
- `worker_totals` — агрегированные итоги
- `manual_edits` — история ручных правок

## Критически важно

**Пересчёт worker_totals** всегда через JOIN с использованием `orders.is_client_payment`:

```sql
SELECT c.total, o.is_client_payment
FROM calculations c
JOIN orders o ON c.order_id = o.id
WHERE ...
```

НЕ определять тип по суффиксу "(оплата клиентом)" в имени!

## Файлы

- `app.py` — основная логика (~2850 строк)
- `database.py` — модели БД
- `index.html` — загрузка файлов
- `period.html` — список работников
- `upload.html` — редактирование заказов

## API для отладки

```bash
# Принудительный пересчёт всех worker_totals
POST /api/upload/{id}/recalculate
```

## Документация

См. `PROJECT_DOCUMENTATION.md` для полного описания.
