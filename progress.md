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
- **Focus:** v80.0 Smart Rescan System
- **Current Step:** ✅ Completed
- **Blockers:** Нет

## 📋 Roadmap & Tasks

### 🔄 In Progress
- Нет активных задач

### ✅ Completed (2026-01-30) — v80.0 Smart Rescan System

**Создан модуль `rescan/` с Clean Architecture:**

| Компонент | Описание |
|-----------|----------|
| `rescan/domain/metric_registry.py` | 25 core метрик с MetricSource enum |
| `rescan/domain/metric_checker.py` | Анализ полноты данных по всей БД |
| `rescan/fillers/llm_filler.py` | Заполнение ai_summary, bot%, ad% |
| `rescan/fillers/forensics_filler.py` | Заполнение id_clustering, geo_dc |
| `rescan/fillers/photo_filler.py` | Скачивание аватарок каналов |
| `rescan/cli.py` | CLI интерфейс |

**CLI Usage:**
```bash
python -m rescan --status              # Анализ полноты данных
python -m rescan --fill llm            # Заполнить LLM метрики
python -m rescan --fill forensics      # Заполнить forensics
python -m rescan --metric ai_summary   # Проверить конкретную метрику
python -m rescan --fill llm --dry-run  # Превью без записи
```

**Результаты верификации:**
- 25 метрик в реестре
- 521 канал проанализирован
- 490 каналов без ai_summary (94%)
- Все тесты прошли

### ✅ Completed (2026-01-30) — v79.2 Bug Analysis & Fixes
**Критические исправления после аудита v79.0-v79.1:**

**Найдено и исправлено 8 багов:**

| # | Баг | Severity | Impact |
|---|-----|----------|--------|
| 1 | Missing reaction_stability | HIGH | -5 pts на все каналы |
| 2 | Wrong floating weight keys | MEDIUM | Неправильные веса |
| 3 | comments_enabled extraction | MEDIUM | Floating weights broken |
| 4 | members not passed | HIGH | reach/forward = 0 |
| 5 | llm_analysis: null crash | CRITICAL | 3 канала в WAITING |
| 6 | No data validation | CRITICAL | 104+ false scores |
| 7 | False positive defaults | HIGH | +16 pts garbage data |
| 8 | 63 stuck in WAITING | MEDIUM | 161 канал не обработан |

**Исправления в коде:**

| Файл | Изменения |
|------|-----------|
| `recalc/modes/local.py` | +11 null-safe `.get() or {}`, +validation guard |
| `recalc/domain/score_calculator.py` | +15 null-safe chains, fixed defaults |
| `recalc/infrastructure/db_repository.py` | +WHERE clause для валидных данных |
| `tests/test_recalc_domain.py` | +6 тестов null handling |

**Результаты:**

| Метрика | До | После |
|---------|-----|-------|
| GOOD | 290 | 334 |
| BAD | 67 | 187 |
| WAITING | 195 | 31 |
| Тестов | 359 | 365 |

**Восстановленные каналы:**
- @thefactchain: WAITING → EXCELLENT (78)
- @ssttaannookk: WAITING → MEDIUM (45)
- 161 канал восстановлен из WAITING

**31 оставшийся WAITING** — нет breakdown данных, требуется rescan.

### ✅ Completed (2026-01-30) — v79.1 Score Calculator Bugfixes
**Критические исправления в recalc модуле:**

**1. score_calculator.py:**

| Баг | Исправление |
|-----|-------------|
| Missing import | +`stability_to_points` from scorer |
| ScoreInput incomplete | +`stability_cv`, +`stability_points` fields |
| Wrong weight keys | `comments_max` → `comments`, `reaction_rate_max` → `reaction_rate`, `forward_rate_max` → `forward_rate` |
| Missing 5 points! | +reaction_stability calculation (was entirely missing) |
| Wrong extraction path | `comments_enabled`/`reactions_enabled` now from breakdown root, not metadata |
| Missing parameter | `extract_score_input_from_breakdown()` now accepts `members` param |

**2. local.py:**
- Pass `members` from DB row to `extract_score_input_from_breakdown()`

**Результаты пересчёта:**
```
524 channels recalculated
@levaki: 74 → 91 (correct!)
Distribution: 304 GOOD, 220 BAD
Invalid scores: 0
```

**Файлы изменены:**
- recalc/domain/score_calculator.py
- recalc/modes/local.py

### ✅ Completed (2026-01-30) — v79.0 Unified Recalculation System
**Создан новый модуль `recalc/` с Clean Architecture:**

| Компонент | Описание |
|-----------|----------|
| `recalc/domain/trust_calculator.py` | ЕДИНАЯ функция trust с 20+ множителями |
| `recalc/domain/score_calculator.py` | Пересчёт raw_score из breakdown |
| `recalc/domain/verdict.py` | Verdict thresholds и статусы |
| `recalc/modes/local.py` | --mode local (быстрый, из БД) |
| `recalc/modes/forensics.py` | --mode forensics (заменяет recalc_trust.py) |
| `recalc/infrastructure/db_repository.py` | Batch операции с БД |
| `recalc/infrastructure/batch_processor.py` | Progress bar и параллелизм |
| `recalc/cli.py` | CLI интерфейс |

**CLI Usage:**
```bash
python -m recalc --status              # Статистика БД
python -m recalc --mode local          # Полный пересчёт из breakdown
python -m recalc --mode forensics      # Только trust_factor (20+ множителей)
python -m recalc --mode local --dry-run  # Превью изменений
```

**Критическое улучшение:**
- recalc_trust.py использовал только 3 множителя (bot, ad, premium)
- Новый forensics mode использует 20+ множителей:
  - ID Clustering (FATALITY/suspicious)
  - Geo/DC Mismatch
  - Conviction (critical/high)
  - Hollow Views, Zombie Engagement, Satellite
  - Ghost Protocol (ghost_channel, zombie_audience)
  - Spam Posting (category-aware via SpamPostingTiers)
  - Private Links (100%/80%/60% + combos)
  - Hidden Comments, Dying Engagement

**Тесты:**
- 41 новый тест в tests/test_recalc_domain.py
- 361 тест всего (359 passed, 1 skipped, 1 xpass)

**Файлы:**
- recalc/__init__.py
- recalc/__main__.py
- recalc/cli.py
- recalc/domain/ (3 файла)
- recalc/modes/ (4 файла)
- recalc/infrastructure/ (2 файла)
- tests/test_recalc_domain.py

### ✅ Completed (2026-01-30) — Claude Context Optimization
**8 агентов проанализировали кодовую базу:**

| Агент | Анализ | Найдено |
|-------|--------|---------|
| #1 | .claudeignore research | Нет такого файла! Используется settings.json |
| #2 | Dependencies | node_modules 72MB, __pycache__ 1MB |
| #3 | Build artifacts | dist/ 408KB, .cache/ 566KB |
| #4 | Logs/temp | crawler.db 14MB, *.session 600KB |
| #5 | Media/binary | Нет медиа файлов (чисто!) |
| #6 | IDE configs | .medusa/ 41KB, .pytest_cache/ 35KB |
| #7 | Test data | Fixtures в коде (no external files) |
| #8 | Largest files | Top: crawler.db, node_modules, output/ |

**Созданы файлы:**
- `.claude/settings.json` — deny rules для Claude
- Обновлён `.gitignore` — +.medusa/, +*.map

**Context Savings: ~92 MB excluded**

| Категория | Размер | Статус |
|-----------|--------|--------|
| node_modules | 72 MB | ✅ Excluded |
| crawler.db | 14 MB | ✅ Excluded |
| output/ | 6.6 MB | ✅ Excluded |
| __pycache__ | 1 MB | ✅ Excluded |
| dist/ | 408 KB | ✅ Excluded |
| .cache/ | 566 KB | ✅ Excluded |

### ⏳ Backlog
- [ ] Добавить TypedDict для dict returns в forensics.py
- [ ] Extract score_converters.py из scorer.py
- [ ] Sync БД на production сервер

### ✅ Completed (2026-01-30) — v78.0 Category Spam Thresholds
**Два ключевых изменения:**

**1. Bot Comments Threshold: 30% → 40%**
- Слабая модерация (до 40% ботов) больше не штрафуется
- @elooop: trust 0.99 → 1.0 (16% ботов без штрафа)

**2. Category-Specific Spam Posting Thresholds:**

| Tier | Categories | Thresholds (active/heavy/spam) |
|------|------------|-------------------------------|
| HIGH_FREQUENCY | NEWS, ADULT | 20/40/60 |
| MEDIUM_FREQUENCY | ENTERTAINMENT, AI_ML, FINANCE, EDUCATION | 10/18/30 |
| LOW_FREQUENCY | CRYPTO, LIFESTYLE, BUSINESS, TECH, HEALTH | 6/12/20 |
| MINIMAL | RETAIL, TRAVEL, REAL_ESTATE, BEAUTY, GAMBLING | 4/8/15 |

**Файлы изменены:**
- scanner/llm_analyzer.py — bot threshold 40%
- recalc_trust.py — bot threshold 40%
- scanner/scorer_constants.py — +SpamPostingTiers class
- scanner/metrics.py — category param
- scanner/scorer.py — category= вместо is_news=

**Результаты:**
- 318 тестов passed
- 263 из 457 каналов пересчитаны
- Deploy: API + Frontend ✓

### ✅ Completed (2026-01-30) — Trust Factor Fix v77.0
**Критический баг: trust_factor не применялся при --recalculate-local**

**Проблема:** @elooop показывал score=91, хотя с штрафами должен быть ~67:
- Raw Score: 91
- Trust Penalties: ×0.75 (spam posting) × ×0.99 (bots) = 0.74
- Expected: 91 × 0.74 = **67** ← БЫЛО 91!

**Корневая причина:** `recalculate_local()` читал trust_factor из БД (1.0), не пересчитывая из breakdown.

**8 агентов параллельно исправили:**

| Агент | Задача | Результат |
|-------|--------|-----------|
| #1 | recalculator.py | +`recalculate_trust_from_breakdown()` |
| #2 | tests/ | +20 тестов для новой функции |
| #3 | DB analysis | 182 канала с 5 типами penalty |
| #4 | scorer.py | 20 типов trust multipliers найдено |
| #5 | CLI flow | Подтвердил что CLI корректен |
| #6 | Baseline | 298 тестов passed |
| #7 | database.py | Схема UPDATE проверена |
| #8 | All usages | 13 файлов, всё согласовано |

**Верификация:**
- @elooop: 91 → **67** (trust 0.74) ✅
- 246 каналов получили recalculated trust_factor
- 318 тестов passed (было 298, +20 новых)

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

