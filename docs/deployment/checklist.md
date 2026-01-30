# Deployment Checklist

## Перед деплоем

- [ ] Проверить что порт 3002 свободен или занят reklamshik-api
  ```bash
  ss -tlnp | grep 3002
  ```

- [ ] Запустить миграции БД если есть новые колонки
  ```bash
  python -c "import sqlite3; ..."
  ```

- [ ] Создать/проверить симлинк nginx в sites-enabled
  ```bash
  ls -la /etc/nginx/sites-enabled/ | grep reklamshik
  ```

- [ ] Убедиться что нет конфликта доменов с другими конфигами
  ```bash
  nginx -T 2>/dev/null | grep -A5 "server_name ads-api"
  ```

## Деплой

- [ ] Frontend: `cd mini-app/deploy && python deploy_frontend.py`
- [ ] Backend: `cd mini-app/deploy && python deploy_backend.py`

## После деплоя

- [ ] `nginx -t && nginx -s reload`

- [ ] Проверить API health:
  ```bash
  curl https://ads-api.factchain-traker.online/api/health
  ```

- [ ] Проверить каналы:
  ```bash
  curl https://ads-api.factchain-traker.online/api/channels | head -50
  ```

## При синхронизации БД

- [ ] Остановить API: `systemctl stop reklamshik-api`
- [ ] Скопировать файл: `scp ./crawler.db root@217.60.3.122:/root/reklamshik/`
- [ ] Проверить integrity: `PRAGMA integrity_check`
- [ ] Запустить API: `systemctl start reklamshik-api`

## Troubleshooting

### API 502 после рестарта
Подождать 30 секунд — uvicorn запускается.

### БД повреждена
```bash
# Восстановить из локальной копии
scp ./crawler.db root@217.60.3.122:/root/reklamshik/crawler.db.new
ssh root@217.60.3.122 "mv /root/reklamshik/crawler.db /root/reklamshik/crawler.db.bak && mv /root/reklamshik/crawler.db.new /root/reklamshik/crawler.db && systemctl restart reklamshik-api"
```
