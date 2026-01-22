# Findings: v61.0 Архитектурный рефакторинг

## Requirements

**Основная задача:** Упростить архитектуру, убрать двустороннюю синхронизацию БД.

**Требования пользователя:**
- Один источник истины - локальная `crawler.db`
- Сервер только читает готовую БД
- Сервер может отправлять запросы на сканирование (в requests.json)
- Краулер строго локальный
- Минимум зависимостей между компонентами

---

## Research Findings

### Текущий код синхронизации (ДЛЯ УДАЛЕНИЯ)

#### scanner/crawler.py

**Импорты (строка 29):**
```python
import httpx  # ← УДАЛИТЬ
```

**Функция _sync_from_server() (строки 227-283):**
- Делает GET /api/queue/pending
- Получает username'ы с priority > 0
- Добавляет в локальную БД
- Делает POST /api/queue/sync для сброса priority
- **56 строк → УДАЛИТЬ**

**Функция _sync_full_db_from_server() (строки 285-377):**
- Делает GET /api/channels/export
- Получает все GOOD/BAD каналы
- Импортирует в локальную БД если не обработаны
- **92 строки → УДАЛИТЬ**

**Функция _sync_to_server() (строки 379-435):**
- Собирает локальные GOOD/BAD каналы
- Делает POST /api/channels/import
- **56 строк → УДАЛИТЬ**

**Вызовы в run() (строки 873, 876, 879):**
```python
await self._sync_from_server()           # ← УДАЛИТЬ
await self._sync_to_server()             # ← УДАЛИТЬ
await self._sync_full_db_from_server()   # ← УДАЛИТЬ
```

#### mini-app/backend/main.py

**Endpoints для синхронизации:**

| Endpoint | Строки | Описание |
|----------|--------|----------|
| `/api/channels/export` | 1656-1691 | Экспорт GOOD/BAD для краулера |
| `/api/channels/import` | 1694-1767 | Импорт с краулера |
| `/api/channels/reset` | 1770-1794 | Сброс для пересканирования |
| `/api/queue/pending` | 2227-2248 | Список priority > 0 |
| `/api/queue/sync` | 2251-2269 | Сброс priority |

**Итого:** 171 строка → УДАЛИТЬ

### Текущий деплой (mini-app/deploy/)

**deploy_backend.py:**
- Копирует mini-app/backend/* на сервер
- НЕ копирует scanner/* (уже убрано ранее)
- Рестартует systemd сервис reklamshik-api

**sync_db.py:**
- Сложная логика синхронизации
- → ПЕРЕПИСАТЬ на простое SCP копирование

### SSH/SCP credentials

Из существующих deploy скриптов (deploy/.env):
```
SERVER_IP=217.60.3.122
SERVER_USER=root
SSH_KEY_PATH=~/.ssh/id_rsa
```

---

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| requests.json вместо БД | Простота, текстовый файл, легко читать и отлаживать |
| SCP через Paramiko | Уже используется в deploy скриптах, надёжная библиотека |
| Очищать requests.json сразу после чтения | Предотвращает дубликаты, запросы уже в локальной БД |
| Оставить priority колонку в БД | SQLite не поддерживает DROP COLUMN без пересоздания таблицы |
| Push БД целиком | ~1MB файл, SCP копирует за секунду |
| Не удалять scan_requests таблицу | Может пригодиться для истории на сервере |

---

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| SQLite не поддерживает DROP COLUMN | Оставить колонку priority, просто игнорировать |
| Concurrent writes в requests.json | Маловероятно при 1 запрос/сек, JSON atomic write |
| Потеря запросов при падении краулера | Запросы уже в локальной БД после fetch_requests() |

---

## Resources

**Файлы для изменения:**
- `scanner/sync.py` (NEW)
- `scanner/crawler.py` (строки 227-435, 873-879)
- `mini-app/backend/main.py` (строки 1656-1794, 2227-2269)
- `scanner/database.py` (priority логика)
- `mini-app/deploy/sync_db.py`

**API endpoints после рефакторинга:**

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/channels` | GET | Список каналов (пагинация, фильтры) |
| `/api/channels/{username}` | GET | Детали канала |
| `/api/channels/count` | GET | Количество каналов |
| `/api/stats` | GET | Общая статистика |
| `/api/stats/categories` | GET | По категориям |
| `/api/health` | GET | Здоровье сервера |
| `/api/scan/request` | POST | Добавить в requests.json |
| `/api/scan/queue` | GET | Текущая очередь (из requests.json) |

---

## Code Analysis

### Как сейчас работает priority система

**database.py add_channel():**
```python
def add_channel(self, username, priority=0):
    cursor.execute("""
        INSERT OR IGNORE INTO channels (username, status, priority, created_at)
        VALUES (?, 'WAITING', ?, ?)
    """, (username, priority, datetime.now()))
```

**database.py get_next():**
```python
def get_next(self):
    cursor.execute("""
        SELECT username FROM channels
        WHERE status = 'WAITING'
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
    """)
```

**После рефакторинга:**
- `add_channel()` - убрать параметр priority
- `get_next()` - убрать ORDER BY priority (только created_at ASC)

### Структура requests.json

```json
[
  {"username": "durov", "requested_at": "2026-01-22T10:00:00"},
  {"username": "telegram", "requested_at": "2026-01-22T10:05:00"}
]
```

После fetch_requests():
- Файл становится `[]`
- Usernames добавляются в локальную БД как WAITING

---

## Visual/Browser Findings

*(пока нет)*

---

*Update this file after every 2 view/browser/search operations*
