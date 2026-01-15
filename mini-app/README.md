# Reklamshik Mini App

Telegram Mini App для анализа качества каналов.

## Возможности

- **База каналов** - 1000+ проверенных каналов с фильтрами
- **Проверка канала** - анализ по 13+ факторам накрутки
- **Статистика** - категории и рекомендуемый CPM
- **Telegram интеграция** - нативный Mini App

## Структура

```
mini-app/
├── backend/          # FastAPI + Scanner
│   ├── main.py       # API сервер
│   ├── bot.py        # Telegram бот
│   └── scanner/      # Модули анализа
├── frontend/         # React + Vite
│   └── src/
│       ├── pages/    # DatabasePage, ScanPage, StatsPage
│       └── components/
└── deploy/           # Deploy скрипты
```

## Запуск локально

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt

# Копируйте crawler.db из основного проекта
cp ../crawler.db .

# Запуск API
uvicorn main:app --reload --port 3001

# Запуск бота (в другом терминале)
python bot.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Деплой

1. Настройте DNS:
   - `ads.factchain-traker.online` → 37.140.192.181
   - `api-ads.factchain-traker.online` → 217.60.3.122

2. Деплой backend:
```bash
python deploy/deploy_backend.py
```

3. Билд и деплой frontend:
```bash
cd frontend
npm run build
python ../deploy/deploy_frontend.py
```

4. Настройте бота в BotFather:
   - Menu Button URL: https://ads.factchain-traker.online

## API Endpoints

| Method | Endpoint | Описание |
|--------|----------|----------|
| GET | /api/channels | Список каналов с фильтрами |
| GET | /api/channels/:username | Детали канала |
| POST | /api/channels/:username/scan | Сканировать канал |
| GET | /api/stats | Общая статистика |
| GET | /api/stats/categories | По категориям |

## Бот команды

- `/start` - Открыть Mini App
- `/check @channel` - Проверить канал
- `/stats` - Статистика базы
- `/help` - Справка
