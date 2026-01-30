# Deployment Guide — Рекламщик Mini App

## Серверы

| Сервер | IP | Назначение |
|--------|----|-----------|
| Frontend | 37.140.192.181 | ads.factchain-traker.online |
| Backend | 217.60.3.122 | ads-api.factchain-traker.online (порт 3002) |

**ВАЖНО:** Домен `api.factchain-traker.online` принадлежит t-cloud! Reklamshik использует `ads-api.factchain-traker.online`.

## Quick Deploy

### Frontend
```bash
cd mini-app/frontend && npm run build
cd mini-app/deploy && python deploy_frontend.py
```

### Backend
```bash
cd mini-app/deploy && python deploy_backend.py
```

## Критические ошибки (НЕ ПОВТОРЯТЬ!)

### 1. НИКОГДА не убивать процессы на портах без проверки
На сервере 217.60.3.122 работают НЕСКОЛЬКО приложений:
- **t-cloud** (порт 3000, 3001) - НЕ ТРОГАТЬ
- **subscription-tracker** - НЕ ТРОГАТЬ
- **reklamshik-api** (порт 3002)

```bash
# ЗАПРЕЩЕНО - убьёт чужие приложения!
fuser -k 3001/tcp
```

### 2. Проверка порта перед деплоем
```bash
# Сначала проверь что на порте
ss -tlnp | grep 3002
# Если занят - НЕ УБИВАТЬ, а выбрать другой порт
```

### 3. Nginx — проверить конфликты доменов
```bash
nginx -T 2>/dev/null | grep -A5 "server_name api.factchain"
```

**ВАЖНО:** НЕ создавать nginx конфиг для reklamshik-api с доменом api.factchain-traker.online — этот домен принадлежит t-cloud!

### 4. Симлинки nginx
```bash
# После создания конфига ОБЯЗАТЕЛЬНО создать симлинк
ln -sf /etc/nginx/sites-available/reklamshik-api /etc/nginx/sites-enabled/
nginx -t && nginx -s reload
```

### 5. Миграции БД
Если в коде есть новые колонки, СНАЧАЛА запустить миграцию:
```python
cursor.execute("ALTER TABLE channels ADD COLUMN photo_url TEXT DEFAULT NULL")
```

## Синхронизация БД

**КРИТИЧЕСКИ ВАЖНО:** При копировании БД на сервер:

```bash
# ПРАВИЛЬНЫЙ порядок:
ssh root@217.60.3.122 "systemctl stop reklamshik-api"
scp -C ./crawler.db root@217.60.3.122:/root/reklamshik/crawler.db
ssh root@217.60.3.122 "cd /root/reklamshik && python3 -c 'import sqlite3; c=sqlite3.connect(\"crawler.db\"); print(c.execute(\"PRAGMA integrity_check\").fetchone()[0])'"
ssh root@217.60.3.122 "systemctl start reklamshik-api"
```

**БЕЗ остановки API БД может повредиться!** (`database disk image is malformed`)

## Служебные API endpoints

```bash
# Сброс всех каналов для пересканирования
curl -X POST "https://ads-api.factchain-traker.online/api/channels/reset"

# Экспорт всех GOOD/BAD каналов
curl "https://ads-api.factchain-traker.online/api/channels/export"

# Импорт каналов
curl -X POST "https://ads-api.factchain-traker.online/api/channels/import" \
  -H "Content-Type: application/json" \
  -d '{"channels": [...]}'
```

## После деплоя — Проверка

```bash
# Health check
curl https://ads-api.factchain-traker.online/api/health

# Проверить каналы
curl https://ads-api.factchain-traker.online/api/channels | head -100
```
