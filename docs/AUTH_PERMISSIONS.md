# 🔐 Авторизация и права доступа

## Содержание
1. [OAuth2 через Bitrix24](#oauth2-через-bitrix24)
2. [Роли пользователей](#роли-пользователей)
3. [Матрица прав доступа](#матрица-прав-доступа)
4. [Проверка прав в коде](#проверка-прав-в-коде)
5. [Сессии и токены](#сессии-и-токены)
6. [Настройка Bitrix24](#настройка-bitrix24)
7. [CSRF защита](#csrf-защита)
8. [Аудит действий](#аудит-действий)

---

## OAuth2 через Bitrix24

### Схема авторизации

```
┌─────────┐     1. Нажать "Войти"      ┌─────────────┐
│  User   │ ──────────────────────────► │ Salary Svc  │
│         │                             │  /login     │
└─────────┘                             └──────┬──────┘
                                               │
                2. Redirect                    │
     ┌─────────────────────────────────────────┘
     │
     ▼
┌─────────────┐     3. Логин/пароль     ┌─────────────┐
│  Bitrix24   │ ◄────────────────────── │    User     │
│  OAuth      │                         │             │
└──────┬──────┘                         └─────────────┘
       │
       │ 4. Authorization code
       ▼
┌─────────────┐     5. Exchange code    ┌─────────────┐
│ Salary Svc  │ ──────────────────────► │  Bitrix24   │
│ /callback   │                         │  /token     │
└──────┬──────┘                         └──────┬──────┘
       │                                       │
       │ 7. Create session                     │ 6. Access token
       │ ◄─────────────────────────────────────┘
       │
       ▼
┌─────────────┐     8. Redirect to /    ┌─────────────┐
│  Session    │ ──────────────────────► │    User     │
│  Created    │                         │  Logged in  │
└─────────────┘                         └─────────────┘
```

### Endpoints авторизации

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/auth/login` | GET | Начало OAuth flow |
| `/auth/callback` | GET | Callback от Bitrix24 |
| `/auth/logout` | GET/POST | Выход из системы |
| `/api/me` | GET | Информация о текущем пользователе |

### Код авторизации

#### Начало авторизации

```python
@app.get("/auth/login")
async def auth_login(request: Request):
    """Редирект на страницу авторизации Bitrix24"""
    auth_url = get_auth_url()
    return RedirectResponse(url=auth_url)

def get_auth_url() -> str:
    """Формирует URL для OAuth авторизации"""
    params = {
        "client_id": BITRIX_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
    }
    return f"https://{BITRIX_DOMAIN}/oauth/authorize/?" + urlencode(params)
```

#### Обработка callback

```python
@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Обработка callback от Bitrix24"""
    code = request.query_params.get("code")
    
    if not code:
        return RedirectResponse(url="/login?error=no_code")
    
    try:
        # Обмен кода на токен
        token_data = await exchange_code_for_token(code)
        
        # Получение информации о пользователе
        user_info = await get_bitrix_user(token_data["access_token"])
        
        # Создание/обновление пользователя в БД
        user = await create_or_update_user(
            bitrix_id=user_info["ID"],
            name=f"{user_info['LAST_NAME']} {user_info['NAME']}",
            email=user_info.get("EMAIL"),
            role=determine_role(user_info)
        )
        
        # Создание сессии
        session_id = create_session(user, token_data)
        
        response = RedirectResponse(url="/")
        response.set_cookie(
            SESSION_COOKIE, 
            session_id, 
            httponly=True,
            secure=True,  # Только HTTPS
            samesite="lax"
        )
        return response
        
    except Exception as e:
        return RedirectResponse(url=f"/login?error={str(e)}")
```

#### Обмен кода на токен

```python
async def exchange_code_for_token(code: str) -> dict:
    """Обмен authorization code на access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{BITRIX_DOMAIN}/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "client_id": BITRIX_CLIENT_ID,
                "client_secret": BITRIX_CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            }
        )
    
    if response.status_code != 200:
        raise Exception(f"Token exchange failed: {response.text}")
    
    return response.json()
    # Returns: {
    #     "access_token": "...",
    #     "refresh_token": "...",
    #     "expires_in": 3600,
    #     "user_id": "123"
    # }
```

---

## Роли пользователей

### Описание ролей

| Роль | Код | Описание |
|------|-----|----------|
| **Администратор** | `admin` | Полный доступ ко всем функциям |
| **Менеджер** | `manager` | Загрузка файлов, редактирование черновиков |
| **Просмотр** | `viewer` | Только просмотр данных |

### Определение роли

```python
# Администраторы по Bitrix ID
ADMIN_BITRIX_IDS = ["1", "123", "456"]

# Менеджеры по Bitrix ID  
MANAGER_BITRIX_IDS = ["789", "1011"]

def determine_role(user_info: dict) -> str:
    """
    Определяет роль пользователя по данным из Bitrix24.
    """
    bitrix_id = str(user_info.get("ID"))
    
    if bitrix_id in ADMIN_BITRIX_IDS:
        return "admin"
    
    if bitrix_id in MANAGER_BITRIX_IDS:
        return "manager"
    
    # По умолчанию — только просмотр
    return "viewer"
```

### Структура пользователя

```python
# В БД (таблица users)
{
    "id": 1,
    "bitrix_id": "123",
    "name": "Иванов Иван Иванович",
    "email": "ivanov@company.ru",
    "role": "admin",
    "created_at": "2024-01-01T00:00:00"
}

# В сессии
{
    "user_id": 1,
    "bitrix_id": "123",
    "name": "Иванов Иван Иванович",
    "role": "admin",
    "access_token": "...",
    "refresh_token": "..."
}
```

---

## Матрица прав доступа

### Права по ролям

| Действие | Admin | Manager | Viewer |
|----------|:-----:|:-------:|:------:|
| **Просмотр периодов** | ✅ | ✅ | ✅ |
| **Просмотр деталей** | ✅ | ✅ | ✅ |
| **Скачивание отчётов** | ✅ | ✅ | ✅ |
| **Загрузка файлов** | ✅ | ✅ | ❌ |
| **Редактирование данных** | ✅ | ✅* | ❌ |
| **Добавление строк** | ✅ | ✅* | ❌ |
| **Удаление строк** | ✅ | ✅* | ❌ |
| **Изменение статуса** | ✅ | ✅** | ❌ |
| **Удаление периодов** | ✅ | ❌ | ❌ |
| **Управление пользователями** | ✅ | ❌ | ❌ |

*только в статусе DRAFT  
**только DRAFT → SENT

### Права по статусам периода

| Действие | DRAFT | SENT | PAID |
|----------|:-----:|:----:|:----:|
| Редактирование | ✅ | ❌ | ❌ |
| Добавление строк | ✅ | ❌ | ❌ |
| Удаление строк | ✅ | ❌ | ❌ |
| Загрузка новых файлов | ✅ | ❌ | ❌ |
| Скачивание отчётов | ✅ | ✅ | ✅ |

---

## Проверка прав в коде

### Функции проверки

```python
# permissions.py

def check_edit_permission(user: dict, period_status: str) -> bool:
    """
    Проверяет право на редактирование.
    """
    if not user:
        return False
    
    role = user.get("role")
    
    # Admin может всё
    if role == "admin":
        return True
    
    # Manager может только в DRAFT
    if role == "manager":
        return period_status == "DRAFT"
    
    # Viewer не может редактировать
    return False


def check_upload_permission(user: dict) -> bool:
    """
    Проверяет право на загрузку файлов.
    """
    if not user:
        return False
    
    return user.get("role") in ["admin", "manager"]


def check_delete_period_permission(user: dict) -> bool:
    """
    Проверяет право на удаление периода.
    """
    if not user:
        return False
    
    return user.get("role") == "admin"


def check_status_change_permission(
    user: dict, 
    current_status: str, 
    new_status: str
) -> bool:
    """
    Проверяет право на изменение статуса.
    """
    if not user:
        return False
    
    role = user.get("role")
    
    # Admin может менять любой статус
    if role == "admin":
        return True
    
    # Manager может только DRAFT → SENT
    if role == "manager":
        return current_status == "DRAFT" and new_status == "SENT"
    
    return False
```

### Использование в endpoints

```python
@app.post("/api/calculation/{calc_id}/update")
async def update_calculation(calc_id: int, request: Request):
    # Получаем текущего пользователя
    user = get_current_user(request)
    if not user:
        return JSONResponse(
            {"success": False, "error": "Unauthorized"}, 
            status_code=401
        )
    
    # Получаем статус периода
    period_status = await get_period_status_by_calc(calc_id)
    
    # Проверяем права
    if not check_edit_permission(user, period_status):
        return JSONResponse(
            {"success": False, "error": "Permission denied"}, 
            status_code=403
        )
    
    # Выполняем обновление
    # ...
```

### Декораторы доступа

```python
from functools import wraps

def require_auth(func):
    """Декоратор: требует авторизации"""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return JSONResponse(
                {"error": "Unauthorized"}, 
                status_code=401
            )
        return await func(request, *args, **kwargs)
    return wrapper


def require_admin(func):
    """Декоратор: требует роль admin"""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = get_current_user(request)
        if not user or user.get("role") != "admin":
            return JSONResponse(
                {"error": "Admin required"}, 
                status_code=403
            )
        return await func(request, *args, **kwargs)
    return wrapper


def require_role(*roles):
    """Декоратор: требует одну из указанных ролей"""
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user = get_current_user(request)
            if not user or user.get("role") not in roles:
                return JSONResponse(
                    {"error": f"Role {roles} required"}, 
                    status_code=403
                )
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator


# Использование
@app.delete("/api/period/{period_id}")
@require_admin
async def delete_period(period_id: int, request: Request):
    # Только admin может удалять периоды
    ...

@app.post("/upload")
@require_role("admin", "manager")
async def upload_files(request: Request):
    # Admin и manager могут загружать
    ...
```

---

## Сессии и токены

### Хранение сессий

```python
# In-memory хранилище сессий
sessions = {}

SESSION_COOKIE = "salary_session"
SESSION_EXPIRY = 24 * 60 * 60  # 24 часа

def create_session(user: dict, token_data: dict) -> str:
    """Создаёт новую сессию"""
    import secrets
    
    session_id = secrets.token_urlsafe(32)
    
    sessions[session_id] = {
        "user_id": user["id"],
        "bitrix_id": user["bitrix_id"],
        "name": user["name"],
        "role": user["role"],
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(seconds=SESSION_EXPIRY)
    }
    
    return session_id


def get_session(session_id: str) -> dict:
    """Получает данные сессии"""
    if not session_id:
        return None
    
    session = sessions.get(session_id)
    
    if not session:
        return None
    
    # Проверка истечения
    if datetime.now() > session["expires_at"]:
        delete_session(session_id)
        return None
    
    return session


def delete_session(session_id: str):
    """Удаляет сессию"""
    sessions.pop(session_id, None)


def get_current_user(request: Request) -> dict:
    """Получает текущего пользователя из request"""
    session_id = request.cookies.get(SESSION_COOKIE)
    return get_session(session_id)
```

### Refresh токенов

```python
async def refresh_access_token(session_id: str) -> bool:
    """Обновляет access token используя refresh token"""
    session = sessions.get(session_id)
    if not session or not session.get("refresh_token"):
        return False
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://{BITRIX_DOMAIN}/oauth/token/",
                data={
                    "grant_type": "refresh_token",
                    "client_id": BITRIX_CLIENT_ID,
                    "client_secret": BITRIX_CLIENT_SECRET,
                    "refresh_token": session["refresh_token"],
                }
            )
        
        if response.status_code != 200:
            return False
        
        token_data = response.json()
        
        # Обновляем токены в сессии
        session["access_token"] = token_data["access_token"]
        session["refresh_token"] = token_data.get("refresh_token", session["refresh_token"])
        
        return True
        
    except Exception:
        return False
```

---

## Настройка Bitrix24

### Создание приложения

1. **Войти в Bitrix24** как администратор
2. **Маркет** → **Разработчикам** → **Добавить приложение**
3. **Тип**: Серверное приложение
4. **Права**: 
   - `user` — информация о пользователях
   - `im` — для отправки сообщений (опционально)

### Параметры приложения

```
Название: Salary Service
Описание: Расчёт зарплат монтажников
Тип: Серверное приложение

URL приложения: https://salary.mos-gsm.ru
Redirect URI: https://salary.mos-gsm.ru/auth/callback

Права доступа:
☑️ user - Пользователи
☑️ im - Сообщения (для уведомлений)
```

### Получение credentials

После создания приложения:
- **Client ID**: `local.xxxxxxxxxxxxx.xxxxxxxx`
- **Client Secret**: `xxxxxxxxxxxxxxxxxxxxxxxx`

Сохраните их в переменные окружения.

### Переменные окружения

```env
# Bitrix24 OAuth
BITRIX_CLIENT_ID=local.xxxxxxxxxxxxx.xxxxxxxx
BITRIX_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
BITRIX_DOMAIN=svyaz.bitrix24.ru

# Redirect URI (должен совпадать с настройками приложения)
REDIRECT_URI=https://salary.mos-gsm.ru/auth/callback
```

---

## CSRF защита

### Middleware

```python
# csrf_middleware.py

from starlette.middleware.base import BaseHTTPMiddleware
import secrets

class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF защита для POST/PUT/DELETE запросов"""
    
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    CSRF_HEADER = "X-CSRF-Token"
    CSRF_COOKIE = "csrf_token"
    
    async def dispatch(self, request, call_next):
        # Для безопасных методов — пропускаем
        if request.method in self.SAFE_METHODS:
            response = await call_next(request)
            
            # Устанавливаем CSRF токен если нет
            if self.CSRF_COOKIE not in request.cookies:
                token = secrets.token_urlsafe(32)
                response.set_cookie(
                    self.CSRF_COOKIE, 
                    token,
                    httponly=False,  # JS должен читать
                    samesite="strict"
                )
            
            return response
        
        # Для опасных методов — проверяем токен
        cookie_token = request.cookies.get(self.CSRF_COOKIE)
        header_token = request.headers.get(self.CSRF_HEADER)
        
        if not cookie_token or cookie_token != header_token:
            return JSONResponse(
                {"error": "CSRF token mismatch"},
                status_code=403
            )
        
        return await call_next(request)
```

### JavaScript на клиенте

```javascript
// security.js

// Получение CSRF токена из cookie
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

// Обёртка над fetch с CSRF
async function secureFetch(url, options = {}) {
    const csrfToken = getCSRFToken();
    
    options.headers = {
        ...options.headers,
        'X-CSRF-Token': csrfToken,
    };
    
    return fetch(url, options);
}

// Экспорт для использования
window.Security = {
    fetch: secureFetch,
    getCSRFToken: getCSRFToken,
};
```

---

## Аудит действий

### Логирование

```python
# Таблица audit_log
audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("action", String(50)),      # "edit", "delete", "upload", etc.
    Column("entity_type", String(50)), # "order", "calculation", "period"
    Column("entity_id", Integer),
    Column("period_id", Integer),
    Column("details", JSON),           # Дополнительные данные
    Column("ip_address", String(50)),
    Column("created_at", DateTime, default=datetime.utcnow),
)

async def log_action(
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    period_id: int = None,
    details: dict = None,
    ip_address: str = None
):
    """Записывает действие в аудит лог"""
    query = audit_log.insert().values(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        period_id=period_id,
        details=details,
        ip_address=ip_address,
    )
    await database.execute(query)
```

### Пример использования

```python
@app.post("/api/calculation/{calc_id}/update")
async def update_calculation(calc_id: int, request: Request):
    user = get_current_user(request)
    
    # ... выполняем обновление ...
    
    # Логируем действие
    await log_action(
        user_id=user["id"],
        action="edit",
        entity_type="calculation",
        entity_id=calc_id,
        period_id=period_id,
        details={
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        },
        ip_address=get_client_ip(request)
    )
```

### Получение IP клиента

```python
def get_client_ip(request: Request) -> str:
    """Получает реальный IP клиента"""
    # Проверяем proxy headers
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    return request.client.host
```

### Просмотр аудита

```python
@app.get("/api/audit")
@require_admin
async def get_audit_log(
    request: Request,
    period_id: int = None,
    user_id: int = None,
    action: str = None,
    limit: int = 100
):
    """Получение записей аудита (только для admin)"""
    query = audit_log.select().order_by(audit_log.c.created_at.desc())
    
    if period_id:
        query = query.where(audit_log.c.period_id == period_id)
    if user_id:
        query = query.where(audit_log.c.user_id == user_id)
    if action:
        query = query.where(audit_log.c.action == action)
    
    query = query.limit(limit)
    
    results = await database.fetch_all(query)
    return JSONResponse({"success": True, "audit": [dict(r) for r in results]})
```
