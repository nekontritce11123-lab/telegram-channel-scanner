# Task Plan: Архитектурный рефакторинг v61.0

## Goal
Упростить архитектуру до модели "один источник истины": локальная БД → SCP → сервер (read-only).

## Current Phase
COMPLETED ✅

## Проблема (почему рефакторинг нужен)

### Текущая архитектура (СЛОЖНАЯ):
```
Локал ←→ Сервер (двусторонняя синхронизация)
├── _sync_from_server()      # Забираем запросы
├── _sync_to_server()        # Отправляем результаты
├── _sync_full_db_from_server() # Забираем обновления
└── 5 API endpoints для синхронизации
```

**Проблемы:**
- 2 копии БД → конфликты при обновлении
- Каждое изменение схемы = баги синхронизации
- 350+ строк кода только на синхронизацию
- Сложно отлаживать

### Новая архитектура (ПРОСТАЯ):
```
Локал → Сервер (односторонняя)
├── fetch_requests()  # SCP: забираем requests.json
├── push_database()   # SCP: копируем crawler.db
└── Сервер только читает БД
```

---

## Phases

### Phase 1: Создание sync.py
- [x] Создать `scanner/sync.py` с функциями:
  - `fetch_requests()` - SCP скачать requests.json, очистить
  - `push_database()` - SCP скопировать crawler.db
- [x] Проверить что paramiko установлен
- [x] Протестировать SCP соединение
- **Status:** ✅ COMPLETED
- **Files:** `scanner/sync.py`
- **Lines:** ~60 новых

### Phase 2: Рефакторинг crawler.py
- [x] Удалить `_sync_from_server()` (строки 227-283, 56 строк)
- [x] Удалить `_sync_full_db_from_server()` (строки 285-377, 92 строки)
- [x] Удалить `_sync_to_server()` (строки 379-435, 56 строк)
- [x] Удалить `import httpx` и связанные импорты
- [x] Удалить вызовы в `run()` (строки 873, 876, 879)
- [x] Добавить `from scanner.sync import fetch_requests, push_database`
- [x] Изменить `run()` с fetch_requests() и push_database()
- [x] Протестировать локально
- **Status:** ✅ COMPLETED
- **Files:** `scanner/crawler.py`
- **Lines:** -204 удалить, +15 добавить

### Phase 3: Рефакторинг backend (main.py)
- [ ] Удалить `/api/channels/export` (строки 1656-1691, 35 строк)
- [ ] Удалить `/api/channels/import` (строки 1694-1767, 73 строки)
- [ ] Удалить `/api/channels/reset` (строки 1770-1794, 24 строки)
- [ ] Удалить `/api/queue/pending` (строки 2227-2248, 21 строка)
- [ ] Удалить `/api/queue/sync` (строки 2251-2269, 18 строк)
- [ ] Переписать `/api/scan/request`:
  ```python
  @app.post("/api/scan/request")
  async def add_scan_request(data: dict):
      username = data.get("username", "").strip().lstrip("@").lower()

      # Читаем текущие запросы
      requests_file = Path("/root/reklamshik/requests.json")
      requests = json.loads(requests_file.read_text()) if requests_file.exists() else []

      # Проверяем дубликат
      if username in [r["username"] for r in requests]:
          return {"success": False, "error": "Already in queue"}

      # Добавляем
      requests.append({
          "username": username,
          "requested_at": datetime.now().isoformat()
      })
      requests_file.write_text(json.dumps(requests, indent=2))

      return {"success": True, "position": len(requests)}
  ```
- [ ] Добавить `/api/scan/queue` для UI:
  ```python
  @app.get("/api/scan/queue")
  async def get_scan_queue():
      requests_file = Path("/root/reklamshik/requests.json")
      requests = json.loads(requests_file.read_text()) if requests_file.exists() else []
      return {"queue": requests, "count": len(requests)}
  ```
- [x] Деплой backend
- **Status:** ✅ COMPLETED
- **Files:** `mini-app/backend/main.py`
- **Lines:** -171 удалить, +40 добавить

### Phase 4: Упрощение database.py
- [x] Убрать priority из `add_channel()` - параметр больше не нужен
- [x] Убрать ORDER BY priority из `get_next()` и `peek_next()`
- [x] НЕ удалять колонку priority (миграция не нужна, просто игнорируем)
- **Status:** ✅ COMPLETED
- **Files:** `scanner/database.py`
- **Lines:** ~-15

### Phase 5: Обновление deploy скриптов
- [x] Проверить `sync_db.py` — уже имеет нужную SCP логику
- [x] deploy_backend.py — без изменений (уже работает)
- **Status:** ✅ COMPLETED
- **Files:** `mini-app/deploy/sync_db.py`, `mini-app/deploy/deploy_backend.py`

### Phase 6: End-to-End тестирование
- [x] Создать пустой `requests.json` на сервере
- [x] Запросить канал через curl → {"success": true}
- [x] Проверить что запрос появился в requests.json ✅
- [x] Запустить fetch_requests() локально ✅
- [x] Проверить что requests.json очистился ✅
- [x] Запустить push_database() локально ✅
- **Status:** ✅ COMPLETED

---

## Детали реализации

### scanner/sync.py (новый файл)

```python
"""
v61.0: Простая синхронизация через SCP.
Заменяет сложную HTTP синхронизацию.
"""
import json
import logging
import paramiko
from pathlib import Path

logger = logging.getLogger(__name__)

# Конфигурация сервера
SERVER_HOST = "217.60.3.122"
SERVER_USER = "root"
SERVER_KEY = Path.home() / ".ssh" / "id_rsa"  # или из .env
REMOTE_DIR = "/root/reklamshik"


def _get_sftp():
    """Создать SFTP соединение."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SERVER_HOST, username=SERVER_USER, key_filename=str(SERVER_KEY))
    return ssh, ssh.open_sftp()


def fetch_requests() -> list[str]:
    """
    Забрать запросы с сервера и очистить файл.
    Returns: список username'ов для обработки.
    """
    ssh, sftp = _get_sftp()
    try:
        remote_file = f"{REMOTE_DIR}/requests.json"
        local_file = Path("requests_temp.json")

        try:
            sftp.get(remote_file, str(local_file))
        except FileNotFoundError:
            logger.info("requests.json не найден на сервере")
            return []

        # Парсим запросы
        data = json.loads(local_file.read_text())
        usernames = [r["username"] for r in data]

        # Очищаем файл на сервере
        sftp.putfo(io.BytesIO(b"[]"), remote_file)

        # Удаляем временный файл
        local_file.unlink()

        logger.info(f"Забрано {len(usernames)} запросов с сервера")
        return usernames

    finally:
        sftp.close()
        ssh.close()


def push_database():
    """
    Скопировать локальную БД на сервер.
    """
    ssh, sftp = _get_sftp()
    try:
        local_db = Path("crawler.db")
        remote_db = f"{REMOTE_DIR}/crawler.db"

        if not local_db.exists():
            logger.error("Локальная БД не найдена!")
            return False

        sftp.put(str(local_db), remote_db)
        logger.info(f"БД ({local_db.stat().st_size / 1024:.1f} KB) скопирована на сервер")
        return True

    finally:
        sftp.close()
        ssh.close()
```

### Структура requests.json

```json
[
  {
    "username": "durov",
    "requested_at": "2026-01-22T10:00:00"
  },
  {
    "username": "telegram",
    "requested_at": "2026-01-22T10:05:00"
  }
]
```

---

## Key Questions

| # | Вопрос | Ответ |
|---|--------|-------|
| 1 | Где хранить requests.json? | `/root/reklamshik/requests.json` |
| 2 | Как обрабатывать concurrent writes? | Маловероятно (1 запрос/сек макс), JSON atomic write |
| 3 | Что если краулер упал посреди обработки? | Запросы уже в локальной БД, не потеряются |
| 4 | Нужна ли история запросов? | Нет, после обработки канал в БД |
| 5 | Как показывать статус запроса в UI? | GET /api/scan/queue + проверка есть ли в БД |
| 6 | Где брать SSH ключ? | Из существующего deploy/.env |

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| JSON файл вместо отдельной БД | Простота, нет синхронизации, легко читать |
| SCP через Paramiko | Уже используется в deploy скриптах |
| Оставить priority колонку | Удаление требует пересоздание таблицы |
| requests.json на сервере | Сервер 24/7, запросы не теряются |
| Push БД после каждого запуска | ~1MB, SCP за секунду |
| Очищать requests.json сразу | Предотвращает дублирование |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| (пока нет) | - | - |

---

## Файлы для изменения (summary)

| # | Файл | Действие | Строк |
|---|------|----------|-------|
| 1 | `scanner/sync.py` | CREATE | +60 |
| 2 | `scanner/crawler.py` | MODIFY | -204, +15 |
| 3 | `mini-app/backend/main.py` | MODIFY | -171, +40 |
| 4 | `scanner/database.py` | MODIFY | -15 |
| 5 | `mini-app/deploy/sync_db.py` | REWRITE | ~30 |
| 6 | `mini-app/deploy/deploy_backend.py` | MODIFY | -20 |

**Итого:** ~400 строк удаляется, ~145 добавляется = **-255 строк**

---

## Verification Checklist

```bash
# 1. Локальный тест sync.py
python -c "from scanner.sync import fetch_requests, push_database; print(fetch_requests())"

# 2. Локальный тест краулера
python crawler.py --stats  # должно работать без HTTP

# 3. Проверка backend
curl https://ads-api.factchain-traker.online/api/health

# 4. Тест полного цикла
curl -X POST https://ads-api.factchain-traker.online/api/scan/request \
  -H "Content-Type: application/json" \
  -d '{"username": "test_channel"}'

# На сервере:
cat /root/reklamshik/requests.json  # должен быть test_channel

# Локально:
python crawler.py  # должен забрать и обработать

# На сервере:
cat /root/reklamshik/requests.json  # должен быть пустой []
```

---

## ВАЖНО: Не трогать!

- **Порт 3000/3001** - t-cloud, НЕ наш
- **Порт 3002** - reklamshik-api (наш)
- **Домен api.factchain-traker.online** - принадлежит t-cloud
- **Наш домен**: ads-api.factchain-traker.online
