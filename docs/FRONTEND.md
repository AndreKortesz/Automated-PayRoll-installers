# 🎨 Фронтенд — Документация

## Содержание
1. [Обзор](#обзор)
2. [Дизайн-система](#дизайн-система)
3. [Страницы](#страницы)
4. [Компоненты](#компоненты)
5. [JavaScript функции](#javascript-функции)
6. [API взаимодействие](#api-взаимодействие)
7. [Формы и валидация](#формы-и-валидация)
8. [Поиск](#поиск)

---

## Обзор

### Технологии

| Компонент | Технология |
|-----------|------------|
| Шаблоны | Jinja2 |
| Стили | Vanilla CSS |
| JavaScript | Vanilla JS (ES6+) |
| Иконки | Inline SVG |
| Шрифты | Bebas Neue, Roboto |

### Структура файлов

```
frontend/
├── templates/
│   ├── base.html          # Базовый шаблон
│   ├── index.html         # Главная страница
│   ├── history.html       # История периодов
│   ├── upload.html        # Детали загрузки
│   ├── comparison.html    # Сравнение версий
│   ├── search.html        # Страница поиска
│   └── login.html         # Страница входа
│
└── static/
    ├── style.css          # Все стили
    └── security.js        # CSRF, fetch wrapper
```

---

## Дизайн-система

### Цвета (Mos-GSM branding)

```css
:root {
    /* Основные цвета */
    --yellow: #F3C04D;           /* Акцент, кнопки */
    --yellow-dark: #D4A843;      /* Hover состояние */
    --yellow-light: #F9D98A;     /* Светлый акцент */
    
    --black: #1A1A1A;            /* Основной текст */
    --black-light: #333333;      /* Вторичный текст */
    
    --orange: #E07B3C;           /* Ссылки */
    --orange-dark: #C66A2F;      /* Hover ссылок */
    
    /* Фоны */
    --gray-light: #F5F5F5;       /* Фон страницы */
    --gray-medium: #E0E0E0;      /* Границы */
    --white: #FFFFFF;            /* Карточки */
    
    /* Статусы */
    --status-draft: #6B7280;     /* Серый */
    --status-sent: #3B82F6;      /* Синий */
    --status-paid: #10B981;      /* Зелёный */
    
    /* Семантические */
    --success: #10B981;
    --error: #EF4444;
    --warning: #F59E0B;
    --info: #3B82F6;
}
```

### Шрифты

```css
/* Заголовки */
font-family: 'Bebas Neue', sans-serif;
font-weight: 400;
letter-spacing: 0.05em;

/* Основной текст */
font-family: 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif;
font-weight: 400;

/* Подключение */
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
```

### Отступы и размеры

```css
/* Spacing scale */
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;
--space-2xl: 48px;

/* Border radius */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;

/* Shadows */
--shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
--shadow-md: 0 4px 6px rgba(0,0,0,0.1);
--shadow-lg: 0 10px 15px rgba(0,0,0,0.1);
```

### Компоненты стилей

#### Кнопки

```css
/* Primary Button */
.btn-primary {
    background: var(--yellow);
    color: var(--black);
    padding: 12px 24px;
    border: none;
    border-radius: var(--radius-md);
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
}

.btn-primary:hover {
    background: var(--yellow-dark);
}

/* Secondary Button */
.btn-secondary {
    background: transparent;
    color: var(--black);
    padding: 12px 24px;
    border: 2px solid var(--gray-medium);
    border-radius: var(--radius-md);
}

/* Danger Button */
.btn-danger {
    background: var(--error);
    color: white;
}
```

#### Карточки

```css
.card {
    background: var(--white);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    box-shadow: var(--shadow-md);
}

.card-header {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.5rem;
    margin-bottom: var(--space-md);
}
```

#### Таблицы

```css
.table {
    width: 100%;
    border-collapse: collapse;
}

.table th {
    background: var(--gray-light);
    padding: 12px 16px;
    text-align: left;
    font-weight: 500;
}

.table td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--gray-medium);
}

.table tr:hover {
    background: var(--gray-light);
}
```

---

## Страницы

### index.html — Главная страница

**URL:** `/`

**Функции:**
- Статистика по периодам
- Форма загрузки файлов (drag & drop)
- Поиск в header
- Список последних периодов

**Структура:**

```html
{% extends "base.html" %}

{% block content %}
<div class="dashboard">
    <!-- Статистика -->
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{{ periods_count }}</div>
            <div class="stat-label">Периодов</div>
        </div>
        <!-- ... -->
    </div>
    
    <!-- Форма загрузки -->
    <div class="upload-section">
        <form id="upload-form" enctype="multipart/form-data">
            <div class="drop-zone" id="drop-zone">
                <p>Перетащите файлы сюда или нажмите для выбора</p>
                <input type="file" name="files" multiple accept=".xlsx,.xls">
            </div>
            <button type="submit" class="btn-primary">Загрузить</button>
        </form>
    </div>
    
    <!-- Последние периоды -->
    <div class="recent-periods">
        {% for period in periods %}
        <div class="period-card">
            <h3>{{ period.name }}</h3>
            <span class="status status-{{ period.status|lower }}">
                {{ period.status }}
            </span>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
```

### history.html — История периодов

**URL:** `/history`

**Функции:**
- Список всех периодов
- Фильтрация по статусу
- Удаление периодов (admin)
- Пагинация

**Структура:**

```html
<div class="history-page">
    <!-- Фильтры -->
    <div class="filters">
        <select id="status-filter">
            <option value="">Все статусы</option>
            <option value="DRAFT">Черновик</option>
            <option value="SENT">Отправлен</option>
            <option value="PAID">Оплачен</option>
        </select>
    </div>
    
    <!-- Таблица периодов -->
    <table class="table">
        <thead>
            <tr>
                <th>Период</th>
                <th>Статус</th>
                <th>Монтажников</th>
                <th>Итого</th>
                <th>Действия</th>
            </tr>
        </thead>
        <tbody>
            {% for period in periods %}
            <tr>
                <td><a href="/upload/{{ period.upload_id }}">{{ period.name }}</a></td>
                <td><span class="status">{{ period.status }}</span></td>
                <td>{{ period.workers_count }}</td>
                <td>{{ period.total|format_currency }}</td>
                <td>
                    <button class="btn-icon" onclick="downloadPeriod({{ period.id }})">
                        📥
                    </button>
                    {% if user.role == 'admin' %}
                    <button class="btn-icon btn-danger" onclick="deletePeriod({{ period.id }})">
                        🗑️
                    </button>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
```

### upload.html — Детали загрузки

**URL:** `/upload/{id}` или `/upload/{id}?worker=Иванов`

**Функции:**
- Список монтажников (без параметра worker)
- Детали монтажника (с параметром worker)
- Редактирование ячеек inline
- Скачивание отчётов
- Изменение статуса

**Режим списка монтажников:**

```html
<div class="workers-list">
    {% for worker in workers %}
    <div class="worker-card" onclick="location.href='?worker={{ worker.name|urlencode }}'">
        <div class="worker-name">{{ worker.name }}</div>
        <div class="worker-stats">
            <span>Заказов: {{ worker.orders_count }}</span>
            <span>Итого: {{ worker.total|format_currency }}</span>
        </div>
    </div>
    {% endfor %}
</div>
```

**Режим деталей монтажника:**

```html
<div class="worker-details">
    <h2>{{ worker_name }}</h2>
    
    <!-- Таблица заказов -->
    <table class="orders-table">
        <thead>
            <tr>
                <th>Заказ</th>
                <th>Адрес</th>
                <th>Выручка</th>
                <th>Оплата услуг</th>
                <th>Бензин</th>
                <th>Транспорт</th>
                <th>Итого</th>
            </tr>
        </thead>
        <tbody>
            {% for order in orders %}
            <tr data-order-id="{{ order.id }}">
                <td>{{ order.order_code }}</td>
                <td>{{ order.address }}</td>
                <td>{{ order.revenue_services|format_currency }}</td>
                <td>{{ order.service_payment|format_currency }}</td>
                <td class="editable" data-field="fuel_payment">
                    {{ order.fuel_payment|format_currency }}
                </td>
                <td class="editable" data-field="transport">
                    {{ order.transport|format_currency }}
                </td>
                <td>{{ order.total|format_currency }}</td>
            </tr>
            {% endfor %}
        </tbody>
        <tfoot>
            <tr class="totals-row">
                <td colspan="6">ИТОГО</td>
                <td>{{ totals.grand_total|format_currency }}</td>
            </tr>
        </tfoot>
    </table>
</div>
```

### search.html — Страница поиска

**URL:** `/search?q=запрос`

**Функции:**
- Полнотекстовый поиск
- Результаты в таблице
- Переход к заказу

```html
<div class="search-page">
    <div class="search-form">
        <input type="text" 
               id="search-input" 
               value="{{ query }}" 
               placeholder="Поиск по номеру заказа, адресу или ФИО...">
        <button class="btn-primary search-btn">Найти</button>
    </div>
    
    <div class="search-results">
        <table class="table">
            <thead>
                <tr>
                    <th>Заказ</th>
                    <th>Дата</th>
                    <th>Монтажник</th>
                    <th>Адрес</th>
                    <th>Период</th>
                    <th>Итого</th>
                </tr>
            </thead>
            <tbody id="results-body">
                <!-- Заполняется через JS -->
            </tbody>
        </table>
    </div>
</div>
```

---

## Компоненты

### Header с поиском

```html
<header class="header">
    <div class="header-left">
        <a href="/" class="logo">
            <img src="/static/logo.svg" alt="Mos-GSM">
        </a>
        <nav class="nav">
            <a href="/">Главная</a>
            <a href="/history">История</a>
        </nav>
    </div>
    
    <div class="header-center">
        <div class="search-wrapper">
            <input type="text" 
                   id="global-search" 
                   placeholder="Поиск заказов...">
            <div class="search-dropdown" id="search-dropdown">
                <!-- Результаты autocomplete -->
            </div>
        </div>
    </div>
    
    <div class="header-right">
        {% if user %}
        <div class="user-menu">
            <span>{{ user.name }}</span>
            <a href="/auth/logout">Выйти</a>
        </div>
        {% else %}
        <a href="/auth/login" class="btn-primary">Войти</a>
        {% endif %}
    </div>
</header>
```

### Статус badge

```html
<span class="status status-{{ status|lower }}">
    {% if status == 'DRAFT' %}
        📝 Черновик
    {% elif status == 'SENT' %}
        📤 Отправлен
    {% elif status == 'PAID' %}
        ✅ Оплачен
    {% endif %}
</span>
```

```css
.status {
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 0.875rem;
    font-weight: 500;
}

.status-draft {
    background: #E5E7EB;
    color: #374151;
}

.status-sent {
    background: #DBEAFE;
    color: #1D4ED8;
}

.status-paid {
    background: #D1FAE5;
    color: #047857;
}
```

### Drop Zone

```html
<div class="drop-zone" id="drop-zone">
    <div class="drop-zone-content">
        <svg class="drop-icon">...</svg>
        <p>Перетащите файлы Excel сюда</p>
        <p class="drop-hint">или нажмите для выбора</p>
    </div>
    <input type="file" 
           id="file-input" 
           multiple 
           accept=".xlsx,.xls"
           style="display: none">
</div>
```

```css
.drop-zone {
    border: 2px dashed var(--gray-medium);
    border-radius: var(--radius-lg);
    padding: var(--space-2xl);
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
}

.drop-zone:hover,
.drop-zone.dragover {
    border-color: var(--yellow);
    background: rgba(243, 192, 77, 0.1);
}

.drop-zone.has-files {
    border-color: var(--success);
    background: rgba(16, 185, 129, 0.1);
}
```

---

## JavaScript функции

### security.js — CSRF и fetch wrapper

```javascript
// Получение CSRF токена
function getCSRFToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrf_token') {
            return value;
        }
    }
    return null;
}

// Безопасный fetch с CSRF
async function secureFetch(url, options = {}) {
    const csrfToken = getCSRFToken();
    
    options.headers = {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken,
        ...options.headers,
    };
    
    const response = await fetch(url, options);
    
    if (response.status === 401) {
        window.location.href = '/auth/login';
        return;
    }
    
    return response;
}

// Экспорт
window.Security = {
    fetch: secureFetch,
    getCSRFToken,
};
```

### Drag & Drop загрузка

```javascript
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadForm = document.getElementById('upload-form');

// Клик для выбора файлов
dropZone.addEventListener('click', () => fileInput.click());

// Drag events
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    
    const files = e.dataTransfer.files;
    handleFiles(files);
});

// Обработка файлов
function handleFiles(files) {
    if (files.length === 0) return;
    
    // Показать выбранные файлы
    const fileList = Array.from(files).map(f => f.name).join(', ');
    dropZone.querySelector('p').textContent = fileList;
    dropZone.classList.add('has-files');
    
    // Сохранить файлы для отправки
    fileInput.files = files;
}

// Отправка формы
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const formData = new FormData();
    for (let file of fileInput.files) {
        formData.append('files', file);
    }
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData,
        });
        
        if (response.ok) {
            window.location.href = '/review';
        } else {
            const error = await response.json();
            alert(error.detail || 'Ошибка загрузки');
        }
    } catch (err) {
        alert('Ошибка сети');
    }
});
```

### Inline редактирование ячеек

```javascript
// Делаем ячейку редактируемой
function makeEditable(cell) {
    const value = cell.textContent.trim();
    const field = cell.dataset.field;
    const calcId = cell.closest('tr').dataset.calcId;
    
    // Создаём input
    const input = document.createElement('input');
    input.type = 'number';
    input.value = parseFloat(value.replace(/[^\d.-]/g, '')) || 0;
    input.className = 'edit-input';
    
    // Заменяем содержимое
    cell.innerHTML = '';
    cell.appendChild(input);
    input.focus();
    input.select();
    
    // Обработчики
    input.addEventListener('blur', () => saveCell(cell, input, field, calcId));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') input.blur();
        if (e.key === 'Escape') {
            cell.textContent = value;
        }
    });
}

// Сохранение значения
async function saveCell(cell, input, field, calcId) {
    const newValue = parseFloat(input.value) || 0;
    
    try {
        const response = await Security.fetch(`/api/calculation/${calcId}/update`, {
            method: 'POST',
            body: JSON.stringify({ field, value: newValue }),
        });
        
        const result = await response.json();
        
        if (result.success) {
            cell.textContent = formatCurrency(newValue);
            cell.classList.add('edited');
            
            // Обновляем итоги если есть
            if (result.new_total) {
                updateTotals(result);
            }
        } else {
            alert(result.error);
            cell.textContent = cell.dataset.originalValue;
        }
    } catch (err) {
        alert('Ошибка сохранения');
    }
}

// Инициализация
document.querySelectorAll('.editable').forEach(cell => {
    cell.dataset.originalValue = cell.textContent;
    cell.addEventListener('dblclick', () => makeEditable(cell));
});
```

### Форматирование

```javascript
// Форматирование валюты
function formatCurrency(value) {
    return new Intl.NumberFormat('ru-RU', {
        style: 'decimal',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    }).format(value) + ' ₽';
}

// Форматирование даты
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: '2-digit',
    });
}
```

---

## Поиск

### Autocomplete в header

```javascript
const searchInput = document.getElementById('global-search');
const dropdown = document.getElementById('search-dropdown');
let searchTimeout;

searchInput.addEventListener('input', (e) => {
    const query = e.target.value.trim();
    
    // Debounce
    clearTimeout(searchTimeout);
    
    if (query.length < 2) {
        dropdown.style.display = 'none';
        return;
    }
    
    searchTimeout = setTimeout(() => doSearch(query), 300);
});

async function doSearch(query) {
    try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=6`);
        const data = await response.json();
        
        if (data.success && data.results.length > 0) {
            renderDropdown(data.results, query);
            dropdown.style.display = 'block';
        } else {
            dropdown.style.display = 'none';
        }
    } catch (err) {
        console.error('Search error:', err);
    }
}

function renderDropdown(results, query) {
    dropdown.innerHTML = results.map(r => `
        <a href="/upload/${r.upload_id}?worker=${encodeURIComponent(r.worker)}" 
           class="search-result">
            <div class="search-result-order">
                ${highlightMatch(r.order_code, query)}
            </div>
            <div class="search-result-address">
                ${highlightMatch(truncate(r.address, 40), query)}
            </div>
            <div class="search-result-worker">
                ${highlightMatch(r.worker, query)}
            </div>
        </a>
    `).join('');
}

function highlightMatch(text, query) {
    if (!text || !query) return text;
    const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.slice(0, len) + '...' : str;
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Закрытие dropdown при клике вне
document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrapper')) {
        dropdown.style.display = 'none';
    }
});
```

### Стили dropdown

```css
.search-wrapper {
    position: relative;
}

.search-dropdown {
    position: absolute;
    top: 100%;
    left: -100px;
    width: 550px;
    max-height: 400px;
    overflow-y: auto;
    background: white;
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    z-index: 1000;
    display: none;
}

.search-result {
    display: grid;
    grid-template-columns: 120px 1fr 150px;
    gap: 12px;
    padding: 12px 16px;
    text-decoration: none;
    color: inherit;
    border-bottom: 1px solid var(--gray-light);
}

.search-result:hover {
    background: var(--gray-light);
}

.search-result-order {
    font-weight: 500;
    color: var(--orange);
}

.search-result-address {
    color: var(--black-light);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.search-result mark {
    background: var(--yellow-light);
    padding: 0 2px;
}
```
