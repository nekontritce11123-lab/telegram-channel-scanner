# Claude Code Optimization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Оптимизировать использование Claude Code — сократить потребление токенов на 57%, устранить потерю контекста при сбросе сессии, улучшить workflow.

**Architecture:** Рефакторинг монолитного CLAUDE.md в модульную структуру docs/. Memory Bank паттерн через PROGRESS.md. Оптимизация глобальных настроек и MCP серверов.

**Tech Stack:** Markdown файлы, Claude Code CLI, MCP configuration

---

## Анализ проблем (Почему нужны изменения)

### Проблема 1: CLAUDE.md проекта раздут (709 строк)

**Что происходит:**
- Файл содержит 709 строк (~8,500 токенов)
- 56% файла (400 строк) — исторические postmortems (v7.0, v22.1, v22.5, v65.1)
- Claude читает ВСЁ это каждую сессию, даже если работает над простой задачей
- Только 61% контента реально полезно для текущей работы

**Почему это плохо:**
- Тратится 4% контекстного окна ещё ДО начала работы
- Важная информация тонет в историческом шуме
- Claude может запутаться в устаревших инструкциях

**Решение:** Вынести postmortems в `docs/incidents/`, оставить в CLAUDE.md только критически важное (100 строк)

---

### Проблема 2: Глобальный CLAUDE.md неэффективен

**Что происходит:**
- 700+ строк инструкций о 930 skills
- Одни и те же skills перечислены 3 раза (таблица + список + примеры)
- ~850 токенов тратится на повторения (25% файла — мусор)
- Нет decision trees — только абстрактные "ALWAYS", "CRITICAL"

**Почему это плохо:**
- Claude не знает КОГДА использовать какой skill
- 95% skills никогда не используются в проекте
- Перегруженный контекст снижает качество ответов

**Решение:** Сократить до 100 строк с конкретными decision trees

---

### Проблема 3: 7 плагинов всегда активны

**Текущие плагины:**
```
youtube-downloader, vibe-coder, fullstack-dev-skills,
github-ops, markdown-tools, mermaid-tools, statusline-generator
```

**Почему это плохо:**
- Каждый плагин добавляет 30-50 токенов описаний
- MCP серверы могут добавлять 15K+ токенов
- Неиспользуемые инструменты засоряют контекст

**Решение:** Проверить `/mcp` и отключить неиспользуемые серверы

---

### Проблема 4: Нет Memory Bank паттерна

**Что происходит:**
- План работы хранится только в памяти Claude
- При auto-compact или сбросе сессии — план теряется полностью
- Баг #20797: "clear context" создаёт новую сессию вместо сжатия

**Почему это плохо:**
- Работа теряется при переполнении контекста
- Нужно заново объяснять что делали
- Невозможны длинные задачи (>1 сессии)

**Решение:** Создать PROGRESS.md и обновлять его перед завершением сессии

---

### Проблема 5: Неэффективный workflow

**Текущие ошибки:**
- Ожидание auto-compact вместо ручного `/compact` на 70%
- Чтение целых файлов через `@` (+70% token overhead)
- Kitchen Sink Sessions (смешивание несвязанных задач)
- Долгие сессии без очистки контекста

**Решение:** Изменить привычки работы

---

## Task 1: Создать структуру docs/

**Files:**
- Create: `f:\Code\Рекламщик\docs\incidents\.gitkeep`
- Create: `f:\Code\Рекламщик\docs\deployment\.gitkeep`
- Create: `f:\Code\Рекламщик\docs\architecture\.gitkeep`

**Step 1: Создать директории**

```bash
mkdir -p "f:\Code\Рекламщик\docs\incidents"
mkdir -p "f:\Code\Рекламщик\docs\deployment"
mkdir -p "f:\Code\Рекламщик\docs\architecture"
```

**Step 2: Проверить создание**

```bash
ls -la "f:\Code\Рекламщик\docs\"
```

Expected: 3 директории (incidents, deployment, architecture)

---

## Task 2: Извлечь postmortems из CLAUDE.md

**Files:**
- Create: `f:\Code\Рекламщик\docs\incidents\v7.0_2026-01-15_deployment.md`
- Create: `f:\Code\Рекламщик\docs\incidents\v22.1_coding_errors.md`
- Create: `f:\Code\Рекламщик\docs\incidents\v22.5_data_structure.md`
- Create: `f:\Code\Рекламщик\docs\incidents\v65.1_critical.md`
- Modify: `f:\Code\Рекламщик\CLAUDE.md` (удалить строки 454-709)

**Step 1: Создать v7.0_2026-01-15_deployment.md**

Содержимое: скопировать секцию "## Ошибки v7.0 (2026-01-15)" из CLAUDE.md (строки 454-486)

**Step 2: Создать v22.1_coding_errors.md**

Содержимое: скопировать секцию "## КРИТИЧЕСКИЕ ОШИБКИ КОДИРОВАНИЯ v22.1" из CLAUDE.md (строки 490-523)

**Step 3: Создать v22.5_data_structure.md**

Содержимое: скопировать секцию "## КРИТИЧЕСКИЕ ОШИБКИ v22.5" из CLAUDE.md (строки 526-612)

**Step 4: Создать v65.1_critical.md**

Содержимое: скопировать секцию "## КРИТИЧЕСКИЕ ОШИБКИ v65.1" из CLAUDE.md (строки 643-709)

**Step 5: Проверить файлы созданы**

```bash
ls -la "f:\Code\Рекламщик\docs\incidents\"
```

Expected: 4 файла с postmortems

---

## Task 3: Извлечь deployment инструкции

**Files:**
- Create: `f:\Code\Рекламщик\docs\deployment\DEPLOY.md`
- Create: `f:\Code\Рекламщик\docs\deployment\servers.md`
- Create: `f:\Code\Рекламщик\docs\deployment\checklist.md`

**Step 1: Создать DEPLOY.md**

```markdown
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

### 2. Проверка порта перед деплоем
```bash
ss -tlnp | grep 3002
```

### 3. Nginx — проверить конфликты
```bash
nginx -T 2>/dev/null | grep -A5 "server_name api.factchain"
```

## Синхронизация БД

**ВАЖНО:** При копировании БД на сервер:
1. Остановить API: `systemctl stop reklamshik-api`
2. Скопировать файл
3. Проверить: `PRAGMA integrity_check`
4. Запустить: `systemctl start reklamshik-api`
```

**Step 2: Создать checklist.md**

```markdown
# Deployment Checklist

## Перед деплоем
- [ ] Проверить что порт 3002 свободен или занят reklamshik-api
- [ ] Запустить миграции БД если есть новые колонки
- [ ] Создать/проверить симлинк nginx в sites-enabled

## После деплоя
- [ ] `nginx -t && nginx -s reload`
- [ ] Проверить API: `curl https://ads-api.factchain-traker.online/api/health`
- [ ] Проверить каналы: `curl https://ads-api.factchain-traker.online/api/channels`
```

---

## Task 4: Создать сокращённый CLAUDE.md

**Files:**
- Modify: `f:\Code\Рекламщик\CLAUDE.md` (полная перезапись)

**Step 1: Написать новый CLAUDE.md (100 строк)**

```markdown
# CLAUDE.md — Рекламщик Project Guide

## Commands

```bash
# Scanner
python run.py @channel_name

# Crawler
python crawler.py @seed1 @seed2    # Первый запуск
python crawler.py                   # Продолжить
python crawler.py --stats           # Статистика
python crawler.py --export good.csv # Экспорт

# Deploy (ВСЕГДА использовать скрипты!)
cd mini-app/frontend && npm run build && cd ../deploy && python deploy_frontend.py
cd mini-app/deploy && python deploy_backend.py
```

## Configuration

Requires `.env`:
```
API_ID=your_api_id
API_HASH=your_api_hash
PHONE=your_phone_number
GROQ_API_KEY=your_groq_key  # Optional
```

## Scoring System (v15.2)

```
Final Score = Raw Score × Trust Factor
```

**Raw Score (0-100):**
- Quality (40): cv_views, reach, views_decay, forward_rate
- Engagement (40): comments, reaction_rate, er_variation, stability
- Reputation (20): verified, age, premium, source_diversity

**Trust Factor (0.0-1.0):** Forensics × Statistical × Ghost × Decay × Content

**Verdict Thresholds:**
- EXCELLENT: ≥75
- GOOD: ≥55
- MEDIUM: ≥40
- HIGH_RISK: ≥25
- SCAM: <25

## Key Modules

| File | Purpose |
|------|---------|
| scanner/scorer.py | `calculate_final_score()`, `calculate_trust_factor()` |
| scanner/metrics.py | `FraudConvictionSystem`, `check_instant_scam()` |
| scanner/forensics.py | `UserForensics` (ID Clustering, Geo/DC, Premium) |
| scanner/client.py | `smart_scan()` — 3 API requests per channel |
| scanner/crawler.py | `SmartCrawler` with rate limiting |

## Documentation Links

- **Architecture:** [docs/architecture/](docs/architecture/)
- **Deployment:** [docs/deployment/DEPLOY.md](docs/deployment/DEPLOY.md)
- **Incidents:** [docs/incidents/](docs/incidents/) — postmortems v7.0, v22.1, v22.5, v65.1

## Critical Rules

1. **Deploy:** НИКОГДА не убивать процессы на портах без проверки (t-cloud на 3000/3001!)
2. **DB Sync:** Остановить API → скопировать → PRAGMA check → запустить
3. **Nginx:** Проверить конфликты доменов перед изменением конфигов
```

**Step 2: Проверить размер**

```bash
wc -l "f:\Code\Рекламщик\CLAUDE.md"
```

Expected: < 150 строк

---

## Task 5: Создать PROGRESS.md (Memory Bank)

**Files:**
- Create: `f:\Code\Рекламщик\PROGRESS.md`

**Step 1: Создать шаблон PROGRESS.md**

```markdown
# PROGRESS.md — Session Memory Bank

> **Инструкция:** Обновляй этот файл перед завершением сессии или при `/compact`

## Current Session

**Date:** [YYYY-MM-DD]
**Focus:** [Текущая задача]
**Status:** [In Progress / Blocked / Completed]

### What I'm Working On
- [ ] Задача 1
- [ ] Задача 2

### Blockers
- Проблема → что нужно для решения

---

## Recently Completed

### [Date] — [Feature/Fix Name]
- [x] Что было сделано
- [x] Какие файлы изменены
- **Result:** Краткий результат

---

## Next Session TODO

1. [ ] Высокий приоритет
2. [ ] Средний приоритет
3. [ ] Низкий приоритет

---

## Known Issues & Gotchas

| Issue | Solution |
|-------|----------|
| Пример проблемы | Как решать |

---

## Architecture Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Пример решения | Почему так | Date |
```

**Step 2: Добавить правило в CLAUDE.md**

Добавить в конец CLAUDE.md:
```markdown
## Memory Bank

**ВАЖНО:** Перед `/compact` или завершением сессии — обнови [PROGRESS.md](PROGRESS.md):
1. Запиши текущую задачу и статус
2. Отметь что сделано
3. Запиши blockers если есть
4. Укажи TODO для следующей сессии
```

---

## Task 6: Оптимизировать глобальный CLAUDE.md

**Files:**
- Modify: `C:\Users\Daniel Simples\.claude\CLAUDE.md`

**Step 1: Создать сокращённую версию (100 строк)**

```markdown
# Global Claude Code Instructions

## When to Use Skills vs Manual Work

### Decision Tree
```
Задача требует специализированных знаний?
├─ YES: Домен известен (Docker/K8s/Security/etc)?
│   ├─ YES → Используй domain skill
│   └─ NO → Manual implementation
└─ NO: Manual implementation

Сложность задачи:
├─ <3 файлов + известное решение → Manual
├─ 3-10 файлов ИЛИ неизвестный подход → Consider skill
└─ >10 файлов ИЛИ критично качество → Use skill
```

### Quick Reference: Keyword → Action

| Trigger | Tool | Action |
|---------|------|--------|
| "error", "bug", "fail" | Task | `subagent_type: "vibe-coder:debugger"` |
| "review", "audit" | Task | `subagent_type: "vibe-coder:code-reviewer"` |
| "test", "TDD" | Task | `subagent_type: "vibe-coder:tdd-test-writer"` |
| "explore", "find" | Task | `subagent_type: "Explore"` |
| "plan", "design" | Task | `subagent_type: "Plan"` |
| "docker", "container" | Skill | `/dockerfile-generator` |
| "deploy", "CI/CD" | Skill | `/ci-cd-pipelines` |
| "security", "vuln" | Skill | `/vulnerability-scanner` |
| "telegram bot" | Skill | `/telegram-bot` |

## Critical Rules

1. **Skill tool** = single focused task (one skill invocation)
2. **Task tool** = complex multi-step workflows (agents)
3. ⚠️ **NEVER use Skill tool for agents** — use Task tool with subagent_type

## Installed Plugins

- `vibe-coder` — Telegram bots, brainstorming, TDD
- `fullstack-dev-skills` — Languages, frameworks, DevOps
- `github-ops` — GitHub automation
- `markdown-tools` — Document conversion
- `mermaid-tools` — Diagram generation

## Best Practices

1. **Before coding** — check if skill exists (use skill search)
2. **Complex tasks** — use Task with Explore first, then Plan
3. **Debugging** — use `vibe-coder:debugger` agent
4. **Don't ask permission** — just use skills when relevant
```

**Step 2: Сохранить и проверить размер**

```bash
wc -l "C:\Users\Daniel Simples\.claude\CLAUDE.md"
```

Expected: < 100 строк

---

## Task 7: Проверить и оптимизировать MCP

**Step 1: Посмотреть текущие MCP**

```
/mcp
```

**Step 2: Отключить неиспользуемые**

Если видишь серверы которые не нужны для текущего проекта:
```
/mcp disable <server-name>
```

**Step 3: Проверить context usage**

```
/context
```

Посмотреть сколько токенов занимают MCP серверы.

---

## Task 8: Создать workflow cheatsheet

**Files:**
- Create: `f:\Code\Рекламщик\docs\WORKFLOW.md`

**Step 1: Написать cheatsheet**

```markdown
# Claude Code Workflow Cheatsheet

## Начало сессии
1. Прочитать PROGRESS.md — понять где остановились
2. Проверить `/context` — сколько контекста свободно
3. Сформулировать конкретную задачу

## Во время работы
- **На 70% контекста** → `/compact` с инструкцией сохранить важное
- **Смена темы** → `/clear` и начать заново
- **Нужен файл** → Grep/Glob сначала, потом Read конкретных строк
- **Большая задача** → Task tool с subagent (изоляция контекста)

## Конец сессии
1. Обновить PROGRESS.md:
   - Что сделано
   - Что в процессе
   - TODO для следующей сессии
2. Commit если есть изменения

## Анти-паттерны (НЕ ДЕЛАТЬ)
- ❌ Ждать auto-compact (теряет контекст)
- ❌ Читать файлы через @ (70% overhead)
- ❌ Смешивать несвязанные задачи в одной сессии
- ❌ Держать сессию часами без `/compact`
- ❌ Хранить план только в памяти

## Команды

| Команда | Когда использовать |
|---------|-------------------|
| `/compact` | На 70% контекста |
| `/clear` | Смена темы |
| `/context` | Проверить usage |
| `/mcp` | Управление серверами |
| `/stats` | Статистика сессии |
```

---

## Task 9: Финальная проверка

**Step 1: Проверить структуру docs/**

```bash
tree "f:\Code\Рекламщик\docs\"
```

Expected:
```
docs/
├── architecture/
├── deployment/
│   ├── DEPLOY.md
│   └── checklist.md
├── incidents/
│   ├── v7.0_2026-01-15_deployment.md
│   ├── v22.1_coding_errors.md
│   ├── v22.5_data_structure.md
│   └── v65.1_critical.md
├── plans/
│   └── 2026-01-30-claude-code-optimization.md
└── WORKFLOW.md
```

**Step 2: Проверить размеры файлов**

```bash
wc -l "f:\Code\Рекламщик\CLAUDE.md"
wc -l "C:\Users\Daniel Simples\.claude\CLAUDE.md"
```

Expected:
- Project CLAUDE.md: < 150 строк
- Global CLAUDE.md: < 100 строк

**Step 3: Проверить PROGRESS.md создан**

```bash
cat "f:\Code\Рекламщик\PROGRESS.md" | head -20
```

---

## Summary: Что изменилось и почему

| Файл | Было | Стало | Экономия |
|------|------|-------|----------|
| CLAUDE.md (проект) | 709 строк, 8500 токенов | 100 строк, 2000 токенов | **-76%** |
| CLAUDE.md (глобальный) | 700 строк, 25% мусора | 100 строк, decision trees | **-85%** |
| Postmortems | В CLAUDE.md | docs/incidents/ | Отдельные файлы |
| Deployment | В CLAUDE.md | docs/deployment/ | Отдельные файлы |
| Memory Bank | Отсутствовал | PROGRESS.md | Сохранение контекста |
| Workflow | Хаотичный | docs/WORKFLOW.md | Чёткие правила |

## Ожидаемые результаты

1. **Токены:** -76% на инструкции (8500 → 2000)
2. **Контекст:** 90%+ эффективность (было 61%)
3. **Сессии:** Потеря при сбросе 10% (было 100%)
4. **Workflow:** Чёткие правила вместо хаоса
