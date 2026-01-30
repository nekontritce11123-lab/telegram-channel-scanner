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
- **Focus:** Metrics Audit Complete
- **Current Step:** ✅ Все метрики исправлены
- **Blockers:** Нет

## 📋 Roadmap & Tasks

### 🔄 In Progress
- Нет активных задач

### ⏳ Backlog
- [x] Протестировать Memory Bank при новой сессии ✅ (контекст восстановлен)
- [x] Продолжить вынос хардкода в scorer_constants.py ✅ (v76.0)
- [ ] Добавить TypedDict для dict returns в forensics.py
- [ ] Extract score_converters.py из scorer.py

### ✅ Completed (2026-01-30) — Metrics Audit v76.0
**8 агентов параллельно исправили все метрики:**

| Фаза | Файл | Изменения |
|------|------|-----------|
| 1 | scorer.py | +5 safety guards `min(result, max_pts)` |
| 2 | recalculator.py | +floating weights, +cap at 100 |
| 3a | metrics.py | +TrustMultipliers (3 константы) |
| 3b | ad_detection.py | +TrustMultipliers (5 констант) |
| 4 | scorer.py | Удалён race condition (1 вызов вместо 2) |
| 5 | scorer.py | **35 изменений** int() → round() |
| 6 | App.tsx | +tooltip `raw × trust = final` |
| 7 | tests/ | 298 passed, 0 failed |

**Исправленные баги:**
- [x] raw_score > 100 — добавлены safety guards
- [x] recalculator без floating weights — исправлено
- [x] TrustMultipliers orphaned — теперь используются
- [x] int() несправедливое округление → round()
- [x] posting_data race condition — унифицировано

**Верификация:** @durov: 71 raw × 0.85 trust = 60 GOOD ✅

### ✅ Completed (2026-01-30) — Production Deploy
- [x] Frontend: https://ads.factchain-traker.online (200 OK)
- [x] Backend: https://ads-api.factchain-traker.online/api/health (554 channels, 268 GOOD)
- [x] 22 scanner modules deployed
- [x] Systemd service running

### ✅ Completed (2026-01-30) — Post-Audit Verification
**6 агентов параллельно проверили все системы:**

| Компонент | Статус | Детали |
|-----------|--------|--------|
| Database | ✅ OK | 554 channels, PRAGMA integrity_check = ok |
| Crawler | ✅ OK | v51.0, 268 GOOD / 170 BAD / 116 in queue |
| Tests | ✅ OK | 298 passed, 1 skipped, 1 xfail |
| Imports | ✅ OK | conviction.py, ad_detection.py, backward compat |
| Frontend | ✅ OK | Build 1.59s, 109 kB gzip |
| Scanner | ✅ OK | @durov: 53/100, trust=0.77, verdict=MEDIUM |

### ✅ Completed (2026-01-30) — Code Audit
**Коммиты:** `5d74b3ac` → `3978646` → `42f035a`

**Phase 1 — Regression Tests (151 тест):**
- [x] tests/test_scorer_regression.py (59 тестов)
- [x] tests/test_metrics_regression.py (51 тест)
- [x] tests/test_forensics_regression.py (41 тест)

**Phase 2 — Dead Code Removal:**
- [x] cli.py — удалён `import requests`
- [x] ad_detector.py, summarizer.py — удалены test blocks
- [x] BottomNav.tsx, FavoritesPage.tsx — удалены

**Phase 3 — Constants:**
- [x] scanner/scorer_constants.py — создан (20+ классов)
- [x] cache.py — исправлен TTL conflict
- [x] scorer.py — использует VerdictThresholds

**Phase 4 — Metrics Split:**
- [x] scanner/conviction.py — 716 строк (FraudConvictionSystem)
- [x] scanner/ad_detection.py — 83 строки (analyze_private_invites)
- [x] scanner/metrics.py — сокращён с 1,336 до 532 строк (-60%)
- [x] Backward compatibility exports работают

**Phase 5 — Error Handling:**
- [x] client.py — исправлены 4 broad exception handlers
- [x] FloodWait теперь всегда re-raised

**Верификация:**
- [x] 300 тестов проходят (298 passed, 0 failed)
- [x] Качество тестов: A- (91/100)
- [x] Нет circular imports
- [x] Все backward compat импорты работают

### ✅ Completed (2026-01-30) — Claude Code Optimization
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
- *Metrics.py Split (v52.0):* conviction.py + ad_detection.py — single responsibility
- *scorer_constants.py:* Централизация хардкода с version tracking
- *Regression tests before refactoring:* Factory pattern, behavior testing

## 📊 Code Audit Metrics (2026-01-30)

| Метрика | До | После | Δ |
|---------|-----|-------|---|
| metrics.py | 1,336 строк | 532 строки | -60% |
| Модулей scanner/ | 20 | 23 | +3 |
| Тестов | ~145 | 300 | +107% |
| Broad exceptions | 4 | 0 | -100% |
| Test quality | — | A- (91%) | ✓ |

