# 🔗 Интеграции — Внешние сервисы

## Содержание
1. [Обзор интеграций](#обзор-интеграций)
2. [Yandex Geocoder](#yandex-geocoder)
3. [Bitrix24 API](#bitrix24-api)
4. [1С через Excel](#1с-через-excel)
5. [Яндекс Заправки](#яндекс-заправки)

---

## Обзор интеграций

```
┌─────────────────────────────────────────────────────────────────┐
│                       SALARY SERVICE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │   Yandex    │    │  Bitrix24   │    │     1С      │          │
│  │  Geocoder   │    │   OAuth     │    │   (Excel)   │          │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘          │
│         │                  │                  │                  │
│         ▼                  ▼                  ▼                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │ Координаты  │    │ Авторизация │    │   Заказы    │          │
│  │ → Бензин    │    │ Уведомления │    │   Данные    │          │
│  └─────────────┘    └─────────────┘    └─────────────┘          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

| Интеграция | Тип | Назначение |
|------------|-----|------------|
| Yandex Geocoder | REST API | Адрес → Координаты → Расстояние |
| Bitrix24 | OAuth2 + REST API | Авторизация, уведомления |
| 1С | Excel файлы | Импорт данных о заказах |
| Яндекс Заправки | Excel файлы | Данные о заправках |

---

## Yandex Geocoder

### Описание

Yandex Geocoder API преобразует текстовые адреса в географические координаты. Используется для расчёта расстояния от офиса до адреса заказа.

### API Details

| Параметр | Значение |
|----------|----------|
| Endpoint | `https://geocode-maps.yandex.ru/1.x/` |
| Метод | GET |
| Формат | JSON |
| Лимит (бесплатно) | 1000 запросов/день |
| Документация | [tech.yandex.ru/maps/geocoder](https://tech.yandex.ru/maps/geocoder/) |

### Получение API ключа

1. Перейти на [developer.tech.yandex.ru](https://developer.tech.yandex.ru)
2. Создать приложение
3. Подключить API "Геокодер"
4. Скопировать API ключ

### Конфигурация

```env
YANDEX_GEOCODER_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### Использование в коде

```python
# services/geocoding.py

import httpx
from config import YANDEX_GEOCODER_API_KEY

GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"

async def geocode_address_yandex(address: str) -> tuple:
    """
    Преобразует адрес в координаты через Yandex Geocoder.
    
    Args:
        address: Текстовый адрес (напр. "Москва, ул. Ленина, 1")
        
    Returns:
        tuple: (latitude, longitude) или None при ошибке
    """
    params = {
        "apikey": YANDEX_GEOCODER_API_KEY,
        "geocode": address,
        "format": "json",
        "results": 1,
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(GEOCODER_URL, params=params)
    
    if response.status_code != 200:
        return None
    
    data = response.json()
    
    try:
        # Извлекаем координаты из ответа
        pos = data["response"]["GeoObjectCollection"]["featureMember"][0]
        pos = pos["GeoObject"]["Point"]["pos"]
        lon, lat = map(float, pos.split())
        return (lat, lon)
    except (KeyError, IndexError):
        return None
```

### Пример запроса/ответа

**Запрос:**
```
GET https://geocode-maps.yandex.ru/1.x/?apikey=xxx&geocode=Москва,+Тверская+1&format=json
```

**Ответ:**
```json
{
  "response": {
    "GeoObjectCollection": {
      "featureMember": [
        {
          "GeoObject": {
            "Point": {
              "pos": "37.611347 55.757660"
            },
            "metaDataProperty": {
              "GeocoderMetaData": {
                "Address": {
                  "formatted": "Россия, Москва, Тверская улица, 1"
                }
              }
            }
          }
        }
      ]
    }
  }
}
```

### Расчёт расстояния

```python
from math import radians, sin, cos, sqrt, atan2

OFFICE_COORDS = (55.8309, 37.4294)  # Сходненский тупик 16с4

def calculate_distance(coords: tuple) -> float:
    """
    Рассчитывает расстояние между двумя точками по формуле Haversine.
    
    Args:
        coords: (latitude, longitude) целевой точки
        
    Returns:
        float: Расстояние в километрах
    """
    lat1, lon1 = OFFICE_COORDS
    lat2, lon2 = coords
    
    R = 6371  # Радиус Земли в км
    
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c
```

### Кэширование

```python
# In-memory кэш для экономии API запросов
distance_cache = {}

async def get_distance_cached(address: str) -> float:
    """Получает расстояние с кэшированием"""
    
    # Нормализуем адрес для ключа кэша
    cache_key = address.lower().strip()
    
    if cache_key in distance_cache:
        return distance_cache[cache_key]
    
    coords = await geocode_address_yandex(address)
    
    if coords is None:
        return 0
    
    distance = calculate_distance(coords)
    distance_cache[cache_key] = distance
    
    return distance
```

### Fallback на Nominatim

Если Yandex API недоступен, используется бесплатный Nominatim:

```python
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

async def geocode_address_nominatim(address: str) -> tuple:
    """Fallback геокодер через OpenStreetMap Nominatim"""
    
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
    }
    
    headers = {
        "User-Agent": "SalaryService/1.0"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            NOMINATIM_URL, 
            params=params, 
            headers=headers
        )
    
    if response.status_code != 200:
        return None
    
    data = response.json()
    
    if not data:
        return None
    
    return (float(data[0]["lat"]), float(data[0]["lon"]))
```

---

## Bitrix24 API

### Описание

Bitrix24 используется для:
1. **OAuth авторизации** — вход в систему
2. **Уведомления** — отправка сообщений монтажникам
3. **Данные пользователей** — получение списка сотрудников

### Настройка приложения

1. **Bitrix24** → **Маркет** → **Разработчикам** → **Добавить приложение**

2. **Параметры:**
   ```
   Название: Salary Service
   Тип: Серверное приложение
   URL: https://salary.mos-gsm.ru
   Redirect URI: https://salary.mos-gsm.ru/auth/callback
   
   Права:
   ☑️ user - Пользователи
   ☑️ im - Сообщения
   ```

3. **Получить credentials:**
   - Client ID: `local.xxxxx.xxxxx`
   - Client Secret: `xxxxxxxx`

### Конфигурация

```env
BITRIX_CLIENT_ID=local.xxxxx.xxxxx
BITRIX_CLIENT_SECRET=xxxxxxxx
BITRIX_DOMAIN=svyaz.bitrix24.ru
```

### OAuth Flow

```python
# auth.py

BITRIX_DOMAIN = os.getenv("BITRIX_DOMAIN")
BITRIX_CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
BITRIX_CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")

def get_auth_url(redirect_uri: str) -> str:
    """Формирует URL для OAuth авторизации"""
    params = {
        "client_id": BITRIX_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    return f"https://{BITRIX_DOMAIN}/oauth/authorize/?" + urlencode(params)


async def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """Обменивает authorization code на access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{BITRIX_DOMAIN}/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "client_id": BITRIX_CLIENT_ID,
                "client_secret": BITRIX_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            }
        )
    return response.json()


async def get_bitrix_user(access_token: str) -> dict:
    """Получает информацию о текущем пользователе"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://{BITRIX_DOMAIN}/rest/user.current",
            params={"auth": access_token}
        )
    return response.json()["result"]
```

### Отправка сообщений

```python
async def send_bitrix_message(
    access_token: str,
    user_id: str,
    message: str
) -> bool:
    """
    Отправляет личное сообщение пользователю Bitrix24.
    
    Args:
        access_token: OAuth токен
        user_id: ID пользователя в Bitrix24
        message: Текст сообщения
        
    Returns:
        bool: Успешность отправки
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{BITRIX_DOMAIN}/rest/im.message.add",
            params={"auth": access_token},
            json={
                "DIALOG_ID": user_id,
                "MESSAGE": message,
            }
        )
    
    return response.status_code == 200
```

### Получение списка сотрудников

```python
async def get_bitrix_users(access_token: str) -> list:
    """Получает список всех пользователей компании"""
    
    users = []
    start = 0
    
    while True:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://{BITRIX_DOMAIN}/rest/user.get",
                params={
                    "auth": access_token,
                    "start": start,
                }
            )
        
        data = response.json()
        users.extend(data.get("result", []))
        
        # Пагинация
        if "next" in data:
            start = data["next"]
        else:
            break
    
    return users
```

---

## 1С через Excel

### Описание

Данные из 1С импортируются через Excel файлы. Система не имеет прямого подключения к 1С — пользователь выгружает файлы вручную.

### Процесс импорта

```
┌─────────┐    Выгрузка     ┌─────────┐    Загрузка    ┌─────────┐
│   1С    │ ─────────────► │  Excel  │ ─────────────► │ Salary  │
│         │    (вручную)    │  файлы  │    (web UI)    │ Service │
└─────────┘                 └─────────┘                └─────────┘
```

### Типы файлов

| Файл | Описание | Обязательный |
|------|----------|--------------|
| Выручка | Основные заказы | ✅ Да |
| Диагностика | Диагностические работы | ✅ Да |
| Яндекс Заправки | Данные о заправках | ⚠️ Для 16-30/31 |

### Формат файла выручки

Строка "Отбор" определяет тип:
```
"Отбор: Тип работы - не равно Диагностика; ..."
```

Колонки:
| Колонка | Описание |
|---------|----------|
| Монтажник | ФИО |
| Заказ | Номер и детали |
| Адрес | Адрес объекта |
| Выручка итого | Общая сумма |
| Выручка от услуг | За работу |
| Диагностика | Сумма диагностики |
| Выезд специалиста | Оплата выезда |
| Оплата услуг | Рассчитанная сумма |
| % | Процент монтажника |

### Парсинг

```python
# services/excel_parser.py

def parse_1c_file(file: BytesIO) -> dict:
    """
    Парсит Excel файл из 1С.
    
    Returns:
        {
            "type": "revenue" | "diagnostic",
            "period": "16-30.11.25",
            "orders": [...]
        }
    """
    df = pd.read_excel(file)
    
    file_type = detect_file_type(df)
    period = extract_period(df)
    orders = parse_orders(df)
    
    return {
        "type": file_type,
        "period": period,
        "orders": orders,
    }
```

---

## Яндекс Заправки

### Описание

Компания оплачивает топливо сотрудникам через Яндекс Заправки. В конце месяца предоставляется отчёт по заправкам.

### Формат файла

| ФИО | Сумма |
|-----|-------|
| Иванов Иван Иванович | 10 000 |
| Петров Пётр Петрович | 8 500 |

### Парсинг

```python
# services/yandex_fuel_parser.py

def parse_yandex_fuel(file: BytesIO) -> dict:
    """
    Парсит файл Яндекс Заправки.
    
    Returns:
        {"Иванов Иван": 10000, "Петров Пётр": 8500, ...}
    """
    df = pd.read_excel(file)
    
    result = {}
    
    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        amount = float(row.iloc[1]) if pd.notna(row.iloc[1]) else 0
        
        if name and amount > 0:
            # Нормализуем имя для сопоставления
            normalized = normalize_worker_name(name)
            result[normalized] = amount
    
    return result
```

### Сопоставление с монтажниками

Имена в файле могут отличаться от имён в заказах:

```python
def match_fuel_to_workers(fuel_data: dict, workers: list) -> dict:
    """
    Сопоставляет данные заправок с монтажниками.
    
    Использует fuzzy matching для неточных совпадений.
    """
    matched = {}
    
    for fuel_name, amount in fuel_data.items():
        # Пробуем точное совпадение
        if fuel_name in workers:
            matched[fuel_name] = amount
            continue
        
        # Пробуем по фамилии + имени
        fuel_short = " ".join(fuel_name.split()[:2])
        
        for worker in workers:
            worker_short = " ".join(worker.split()[:2])
            
            if fuel_short.lower() == worker_short.lower():
                matched[worker] = amount
                break
    
    return matched
```

### Применение вычета

```python
def apply_yandex_fuel(worker_total: float, fuel_amount: float) -> float:
    """
    Применяет вычет Яндекс Заправок.
    
    Вычитается 90% от суммы заправок (скидка 10% для сотрудника).
    """
    deduction = fuel_amount * 0.9
    return worker_total - deduction
```
