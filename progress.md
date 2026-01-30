# 🧠 Project Memory & Status

> **AI INSTRUCTION:** Read this first. Update automatically after significant changes.

## 📍 Project Overview
- **Goal:** Telegram Channel Quality Scanner для оценки рекламного потенциала
- **Type:** Python + Pyrogram MTProto API + React Mini App
- **Key Features:**
  - Сканер каналов (3 API запроса на канал)
  - Scoring System v15.2 (Raw Score × Trust Factor)
  - Краулер для массового сбора каналов
  - Mini App для просмотра результатов

## 🛠️ Tech Stack & Rules
- **Language:** Python 3.12
- **Backend:** FastAPI, SQLite, Pyrogram
- **Frontend:** React, Vite, TailwindCSS
- **Style Guide:**
  - Асинхронность везде (`async/await`)
  - Type Hints обязательны
  - Конфиги из `.env`
  - Deploy только через скрипты (`deploy_frontend.py`, `deploy_backend.py`)

## 🛠️ Skills & Tools (Reusable)
- `python run.py @channel` — сканировать один канал
- `python crawler.py` — запустить краулер
- `python crawler.py --stats` — статистика краулера
- `cd mini-app/deploy && python deploy_frontend.py` — деплой фронта
- `cd mini-app/deploy && python deploy_backend.py` — деплой бэка

## 🚧 Current Session Status
- **Focus:** Оптимизация Claude Code workflow
- **Current Step:** ✅ Завершено
- **Blockers:** Нет

## 📋 Roadmap & Tasks

### 🔄 In Progress
- [x] Обновить глобальный CLAUDE.md на v3.2 (Tools-First + Adaptive)

### ⏳ Backlog
- [ ] Протестировать Memory Bank при новой сессии
- [ ] Проверить работу /compact с новым CLAUDE.md
- [ ] Продолжить работу над Рекламщик

### ✅ Completed (2026-01-30)
- [x] Анализ Claude Code 12 агентами
- [x] Создана структура docs/ (incidents, deployment, architecture)
- [x] Извлечены postmortems v7.0, v22.1, v22.5, v23.0, v65.1
- [x] Сокращён CLAUDE.md с 709 до 93 строк (-87%)
- [x] Добавлен Memory Bank паттерн
- [x] Создан WORKFLOW.md cheatsheet
- [x] Обновлён глобальный CLAUDE.md v2.0 → v3.2 (Tools-First)

## 💡 Architecture Decisions
- *Postmortems в docs/incidents/:* Не нужны каждую сессию, экономия токенов
- *Memory Bank через PROGRESS.md:* Сохранение контекста между сессиями
- *CLAUDE.md < 100 строк:* Только критическая информация
- *GLOBAL AI DRIVER v2.0:* Три протокола — Memory, Skills, Agents

