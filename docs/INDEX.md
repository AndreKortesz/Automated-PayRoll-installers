# 📚 Salary Service — Полная база знаний

## 🗂️ Навигация по документации

### Быстрый старт
| Документ | Описание |
|----------|----------|
| [README.md](../README.md) | Обзор системы, быстрый старт |
| [QUICKSTART.md](./QUICKSTART.md) | Пошаговая инструкция для нового разработчика |

### Бизнес-логика
| Документ | Описание |
|----------|----------|
| [BUSINESS_LOGIC.md](./BUSINESS_LOGIC.md) | Формулы расчётов, алгоритмы |
| [CALCULATION_RULES.md](./CALCULATION_RULES.md) | Детальные правила расчёта каждого поля |
| [EXCEL_PARSING.md](./EXCEL_PARSING.md) | Парсинг файлов 1С, форматы, структура |
| [EXCEL_REPORTS.md](./EXCEL_REPORTS.md) | Генерация отчётов, форматы выгрузки |

### Техническая документация
| Документ | Описание |
|----------|----------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Архитектура системы, модули, зависимости |
| [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) | Схема БД, таблицы, связи, миграции |
| [API_REFERENCE.md](./API_REFERENCE.md) | Все API endpoints с примерами |
| [FRONTEND.md](./FRONTEND.md) | Фронтенд, страницы, компоненты, JS |

### Процессы и интеграции
| Документ | Описание |
|----------|----------|
| [WORKFLOW.md](./WORKFLOW.md) | Статусы периодов, переходы, права |
| [AUTH_PERMISSIONS.md](./AUTH_PERMISSIONS.md) | Авторизация Bitrix24, роли, права |
| [INTEGRATIONS.md](./INTEGRATIONS.md) | Внешние API: Yandex, Bitrix24 |

### Эксплуатация
| Документ | Описание |
|----------|----------|
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Развёртывание, Railway, Docker |
| [CONFIGURATION.md](./CONFIGURATION.md) | Все настройки и переменные окружения |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | Частые проблемы и решения |
| [CHANGELOG.md](./CHANGELOG.md) | История изменений |

---

## 🎯 Карта системы

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SALARY SERVICE                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │
│  │   1С Files  │───►│   Parser    │───►│  Database   │              │
│  │ (Excel)     │    │             │    │ (PostgreSQL)│              │
│  └─────────────┘    └─────────────┘    └──────┬──────┘              │
│                                               │                      │
│  ┌─────────────┐    ┌─────────────┐    ┌──────▼──────┐              │
│  │   Yandex    │◄───│ Calculation │◄───│   Orders    │              │
│  │  Geocoder   │    │   Engine    │    │             │              │
│  └─────────────┘    └──────┬──────┘    └─────────────┘              │
│                            │                                         │
│                     ┌──────▼──────┐                                  │
│                     │   Reports   │                                  │
│                     │   (Excel)   │                                  │
│                     └─────────────┘                                  │
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │
│  │  Bitrix24   │───►│    Auth     │───►│    Users    │              │
│  │   OAuth     │    │             │    │   & Roles   │              │
│  └─────────────┘    └─────────────┘    └─────────────┘              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📖 Как пользоваться документацией

### Для нового разработчика
1. Прочитай [README.md](../README.md) — общее понимание
2. Изучи [QUICKSTART.md](./QUICKSTART.md) — настройка окружения
3. Посмотри [ARCHITECTURE.md](./ARCHITECTURE.md) — структура кода
4. Разбери [BUSINESS_LOGIC.md](./BUSINESS_LOGIC.md) — бизнес-правила

### Для добавления новой фичи
1. [ARCHITECTURE.md](./ARCHITECTURE.md) — где писать код
2. [API_REFERENCE.md](./API_REFERENCE.md) — как добавить endpoint
3. [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) — как изменить БД
4. [FRONTEND.md](./FRONTEND.md) — как добавить UI

### Для отладки проблемы
1. [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) — известные проблемы
2. [CALCULATION_RULES.md](./CALCULATION_RULES.md) — правила расчёта
3. [INTEGRATIONS.md](./INTEGRATIONS.md) — внешние API

### Для AI-ассистента (Claude, GPT)
Рекомендуемый порядок чтения для понимания проекта:
1. [INDEX.md](./INDEX.md) (этот файл)
2. [ARCHITECTURE.md](./ARCHITECTURE.md)
3. [BUSINESS_LOGIC.md](./BUSINESS_LOGIC.md)
4. [CALCULATION_RULES.md](./CALCULATION_RULES.md)
5. [API_REFERENCE.md](./API_REFERENCE.md)
6. [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md)

---

## 🔑 Ключевые концепции

### Период (Period)
Временной интервал для расчёта зарплаты: `16-31.12.25`
- Первая половина: 01-15
- Вторая половина: 16-30/31 (требует Яндекс Заправки)

### Загрузка (Upload)  
Версия данных. Каждая загрузка файлов = новая версия периода.

### Заказ (Order)
Одна строка из 1С — выполненная работа монтажником.

### Расчёт (Calculation)
Результат вычислений для заказа: бензин, транспорт, итого.

### Статусы
- **DRAFT** — черновик, можно редактировать
- **SENT** — отправлено, только просмотр
- **PAID** — оплачено, только просмотр

---

## 📞 Контакты

**Mos-GSM** — mos-gsm.ru
