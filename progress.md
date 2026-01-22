# Progress Log: v52.0 Complete Metrics + Compact Header

## Session 1 - 2026-01-21

### Status: Planning Updated ✅

**User Clarification:**
- "Уточню что я хотел бы чтобы абсолютно все метрики были то есть даже траст фактор"
- "а верхнее меню нужно уменьшить"

**New Scope:**
1. Уменьшить верхние секции (Score Card, Flags, Stats Row)
2. Показать ВСЕ метрики включая Trust Factor penalties

**Key Finding:**
- Line 948 App.tsx: "v51.3: Trust Penalties and Recommendations sections REMOVED per user feedback"
- Нужно ВЕРНУТЬ Trust Penalties секцию

**Actions:**
1. Updated task_plan.md with new phases
2. Updated findings.md with CSS analysis
3. Identified trust_details structure in scorer.py

**Next Steps:**
- Phase 1: Compact Score Card CSS
- Phase 2: Compact Flags CSS
- Phase 3: Compact Stats Row CSS
- Phase 4: Add Trust Penalties section to App.tsx

---

## Files Modified
- [x] task_plan.md - Updated plan for v52.0
- [x] findings.md - Added CSS analysis
- [x] progress.md - This file

---

## Session 2 - Implementation ✅

**Changes Made:**

### CSS Compact (App.module.css)
1. Score Card: scoreValue 36→28px, trustValue 32→26px, padding 14→10px
2. Flags: padding 10→8px, icons 16→14px, font 11→10px
3. Stats Row: padding 12→8px, font 18→16px, gap 8→6px

### Trust Penalties (App.tsx)
- Added new section after metricsGrid
- Shows penalty name, description, and multiplier
- Orange border, red text for multipliers

### CSS for Trust Penalties
- trustPenaltiesSection with orange border
- trustPenaltyItem cards with red background tint
- penaltyMult in bold red

### Deployment
- Version updated to v52.0
- Built and deployed to https://ads.factchain-traker.online

**Note:** Backend currently returns generic trust_penalties based on trust_factor value. For more detailed penalties (Hollow Views, Bot Wall, etc.), would need to update backend to read actual trust_details from database.

---

## Session 3 - v52.1 Implementation ✅

**User Feedback (screenshots):**
- "Удали сверху траст ибо он дублируется"
- "Скор в виде кружка как в главном меню"
- "Штрафы доверия нужно всем показывать а не просто мелкую надпись"

**Design Decisions (via brainstorming skill):**
- Score Ring: Option A - compact 48px, right of channel name
- Trust Penalties: Option A - cards with icons

**Changes Made:**

### App.tsx
1. ScoreRing component: added `medium` prop for 48px size
2. Hero section: moved ScoreRing to the right (after channel info)
3. Removed Score Card section (was showing duplicate Trust block)
4. Trust Penalties: added icons (warning in header, error per penalty)
5. Removed unused `getVerdictText` function

### App.module.css
1. `.heroScoreRing` - wrapper for ScoreRing in Hero (flex-shrink: 0, margin-left: auto)
2. `.trustPenaltiesTitleRow` - flex row with gap for icon + title
3. `.penaltyIcon` - 32px circle with red background for penalty icons
4. Updated `.trustPenaltyItem` - 3 columns (icon, info, multiplier)

### Deployment
- Version: v52.1
- Built and deployed to https://ads.factchain-traker.online

---

## Session 4 - v52.2 Real Trust Penalties ✅

**User Feedback:**
- "Внизу опять же нету таблицы" - backend возвращал generic penalties, не реальные

**Problem:**
- Backend использовал `estimate_trust_penalties()` - generic "Незначительный риск"
- Реальные штрафы (Hollow Views, Hidden Comments и т.д.) из scorer.py не сохранялись в БД

**Changes Made:**

### scanner/crawler.py
- v52.2: Добавлено сохранение `trust_details` в breakdown
  ```python
  trust_details = score_result.get('trust_details', {})
  if trust_details:
      breakdown['trust_details'] = trust_details
  ```

### mini-app/backend/main.py
1. Новая функция `extract_trust_penalties_from_details()`:
   - Конвертирует trust_details из scorer.py в формат для UI
   - Словарь `PENALTY_NAMES` с русскими названиями штрафов
   - Сортировка по серьёзности (multiplier)

2. Обновлён endpoint `/api/channels/{username}`:
   - Сначала пытается использовать реальные trust_details из breakdown_json
   - Fallback на estimate_trust_penalties если нет данных

3. Обновлён endpoint `/api/scan` (live scan):
   - Извлекает trust_details из result
   - Сохраняет в breakdown_json
   - Использует для trust_penalties в ответе

### Deployment
- Version: v52.2
- Frontend: https://ads.factchain-traker.online
- Backend: https://ads-api.factchain-traker.online

**Note:** Существующие каналы в БД не имеют trust_details. Для отображения реальных штрафов нужно пересканировать каналы (или делать live scan).

---

## Session 5 - v59.5 Priority Queue + Case-Sensitivity Fix ✅

### v59.5 Priority Queue
**Задача:** Пользовательские запросы должны быть ближе к началу очереди (~позиция 3), а не в конце.

**Реализация:**
- Добавлена колонка `priority INTEGER DEFAULT 0` в channels
- `add_scan_request()` добавляет канал с priority=1
- `get_next()`, `peek_next()`, `get_next_atomic()` сортируют по `priority DESC, created_at ASC`

**Результат:** Пользовательские запросы обрабатываются первыми.

### v59.5 checkFullyProcessed Fix
**Проблема:** После изменений карточки каналов перестали открываться.

**Причина:** Проверка `score > 0 && status GOOD/BAD` блокировала все клики.

**Решение:** Добавлен параметр `checkFullyProcessed`:
- `scanChannel(username, false)` — для кликов по карточкам (всегда вернуть данные)
- `scanChannel(username, true)` — для поиска (только полностью обработанные)

### v59.5 Case-Sensitivity Duplicate Fix
**Проблема:** thefactchain показывал SCAM с score=0, хотя в БД был score=74.

**Причина:** На сервере было 2 записи с разным регистром:
- `TheFactChain` → WAITING, score=None
- `thefactchain` → GOOD, score=74

API использует `LOWER()` и находил первую (WAITING).

**Исправление:** Удалён дубликат `TheFactChain` на сервере.

**Верификация:**
- thefactchain: score=74, status=GOOD ✓
- durov: score=61, status=GOOD, is_verified=True ✓

---

## Session 6 - v59.9 Reach Collision Bug Fix ✅

### Проблема
Охват (Reach) показывал 0/7 для всех каналов в UI.

### Расследование
1. Локальный output JSON имел ПРАВИЛЬНОЕ значение reach (290.46%)
2. Колонка `reach_percent` в БД имела ПРАВИЛЬНОЕ значение (291.15)
3. НО в `breakdown_json` поле `re` имело значение [1.31, 0] — НЕВЕРНО!

### Причина
**Коллизия ключей в json_compression.py!**

```python
BREAKDOWN_KEYS = {
    'reach': 're',  # reach → 're'
    # 'regularity' НЕ было в маппинге!
}
# Fallback: key[:2]
# 'regularity'[:2] = 're' — COLLISION!
```

При сжатии breakdown оба ключа `reach` и `regularity` мапились на `'re'`.
Python dict итерировался по порядку, `regularity` шёл ПОСЛЕ `reach` и ПЕРЕЗАПИСЫВАЛ его значение!

Результат:
- `reach: {value: 290.46, points: 0}` → `re: [290.46, 0]`
- `regularity: {value: 1.31}` → `re: [1.31, 0]` ← ПЕРЕЗАПИСЬ!

### Исправление
**scanner/json_compression.py:**
```python
BREAKDOWN_KEYS = {
    ...
    # v59.9: Fix collision — regularity[:2] == 're' == reach!
    'regularity': 'rg',
    'er_trend': 'er',
}

BREAKDOWN_KEYS_REV['rg'] = 'regularity'
BREAKDOWN_KEYS_REV['er'] = 'er_trend'
```

### Миграция данных
Сброшены все 28 каналов с испорченными данными:
- status → WAITING
- breakdown_json → NULL
- priority → 1 (обработаются первыми)

### Следующий шаг
Запустить краулер для пересканирования каналов:
```bash
python crawler.py
```

---

## Session 7 - v60.0 Trust Penalties Fix ✅

### Проблема
"Штрафы доверия" перестали показываться в UI. Раньше показывали "Незначительный риск", теперь вообще ничего.

### Root Cause
**JSON Compression теряла trust_details!**

```python
# json_compression.py compress_breakdown()
if key in ('reactions_enabled', 'comments_enabled', 'floating_weights'):
    result[key] = data  # special keys pass through
    continue

# trust_details НЕ в списке → сжимается как 'tr' → не восстанавливается!
```

Data flow:
1. scorer.py → `trust_details = {'hollow_views': {...}, 'bot_wall': {...}}`
2. crawler.py → `breakdown['trust_details'] = trust_details` ✅
3. compress_breakdown() → `'trust_details'` → `'tr'` (first 2 chars) ❌
4. decompress_breakdown() → `'tr'` → `'tr'` (not in reverse mapping) ❌
5. backend → `bd.get('trust_details', {})` → `{}` (not found!) ❌

### Исправления

**scanner/json_compression.py:**
- Добавлен `'trust_details'` в special keys для compress_breakdown()
- Добавлен `'trust_details'` в special keys для decompress_breakdown()

**mini-app/backend/main.py:**
- Добавлены 2 отсутствующих penalty: `spam_posting`, `scam_network`

### Миграция
- Сброшены 6 каналов для пересканирования
- Backend задеплоен

### Верификация
- API работает: `https://ads-api.factchain-traker.online/api/health`
- Текущие каналы имеют trust_factor=1.0 (нет штрафов для тестирования)
- Для полной проверки нужен канал со штрафами (trust_factor < 1.0)

### Следующий шаг
Запустить краулер и найти канал со штрафами для верификации UI.

---

## Session 8 - v60.1 Full Database Sync ✅

### Задача
При запуске краулера синхронизировать не только пользовательские запросы, но и всю БД с сервером.

### Реализация

**mini-app/backend/main.py:**
- Новый endpoint `GET /api/channels/export`
- Возвращает все GOOD/BAD каналы с полными данными
- ВАЖНО: Endpoint размещён ПЕРЕД `/api/channels/{username}` чтобы избежать перехвата

**scanner/crawler.py:**
- Новая функция `_sync_full_db_from_server()`
- Вызывается после `_sync_from_server()` при старте краулера
- Импортирует обработанные каналы в локальную БД
- Не перезаписывает каналы уже обработанные локально

### Результат
```
✓ Полная синхронизация: 6 каналов с сервера
  + 0 импортировано, 5 обновлено
После синхронизации:
  Всего: 199
  GOOD: 4
  BAD: 2
```

Локальная БД теперь получает данные с сервера при запуске краулера.

---

## Session 9 - v60.2 Bidirectional Database Sync ✅

### Задача
Синхронизация с локальной БД НА сервер (было только с сервера).

### Реализация

**mini-app/backend/main.py:**
- Новый endpoint `POST /api/channels/import`
- Принимает список каналов и сохраняет в серверную БД

**scanner/crawler.py:**
- Новая функция `_sync_to_server()`
- Отправляет локальные GOOD/BAD каналы на сервер

**Порядок синхронизации при старте краулера:**
1. `_sync_from_server()` — забираем пользовательские запросы
2. `_sync_to_server()` — отправляем локальные каналы НА сервер
3. `_sync_full_db_from_server()` — получаем обновлённые данные С сервера

### Результат
```
Локальная БД: GOOD: 29, BAD: 5
✓ Синхронизация на сервер: 34 каналов отправлено
  + 0 новых, 34 обновлено

Сервер после синхронизации: good_channels: 30
```

---

## Session 10 - v48.0 Business-Oriented Scoring System ✅

### Цель
Перейти от "лабораторного анализа" к "бизнес-аналитике":
- Убрать технические метрики (`views_decay`, `er_variation`) из баллов
- Добавить бизнес-метрики (`regularity`, `er_trend`)

### Изменения в весах

**QUALITY (40 → 42 балла):**
| Метрика | v45.0 | v48.0 | Изменение |
|---------|-------|-------|-----------|
| forward_rate | 13 | **15** | +2 (виральность = главное) |
| cv_views | 15 | **12** | -3 |
| reach | 7 | **8** | +1 |
| regularity | 0 | **7** | **NEW!** Стабильность постинга |
| views_decay | 5 | **0** | → info_only (для bot_wall) |

**ENGAGEMENT (40 → 38 баллов):**
| Метрика | v45.0 | v48.0 | Изменение |
|---------|-------|-------|-----------|
| comments | 15 | **15** | без изменений |
| er_trend | 0 | **10** | **NEW!** Канал растёт или умирает? |
| reaction_rate | 15 | **8** | -7 (легко накрутить) |
| stability | 5 | **5** | без изменений |
| er_variation | 5 | **0** | УДАЛЕНО (заменено er_trend) |

**REPUTATION (20 баллов) — без изменений**

### Новые функции scorer.py
1. `regularity_to_points()` - баллы за стабильность постинга
   - 1-5 постов/день = max баллов (профессиональный канал)
   - <1/неделю = 0 (мёртвый)
   - >20/день = минимум (спам)

2. `er_trend_to_points()` - баллы за тренд вовлеченности
   - growing (≥1.1) = max баллов
   - stable (0.9-1.1) = 70%
   - declining (0.7-0.9) = 30%
   - dying (<0.7) = 0

3. `calculate_floating_weights()` обновлён:
   - Новый pool: 15 comments + 8 reactions + 15 forward = 38

### Файлы изменены
- `scanner/scorer.py` - RAW_WEIGHTS, новые функции, calculate_final_score()
- `scanner/cli.py` - docstring и engagement_keys
- `mini-app/backend/main.py` - METRIC_CONFIG

### Деплой
- Backend задеплоен
- 34 канала сброшены в WAITING для пересканирования
- API: https://ads-api.factchain-traker.online

### Следующий шаг
Запустить краулер для пересканирования:
```bash
python crawler.py
```

---

## Session 11 - v61.0 Architecture Simplification ✅

### Цель
Упростить архитектуру: убрать сложную двустороннюю HTTP синхронизацию БД.

**БЫЛО (сложно):**
```
Локал ←→ Сервер (HTTP sync, 350+ строк)
├── _sync_from_server()
├── _sync_to_server()
├── _sync_full_db_from_server()
└── 5 API endpoints
```

**СТАЛО (просто):**
```
Локал → Сервер (SCP, ~60 строк)
├── fetch_requests()   # SCP: забираем requests.json
├── push_database()    # SCP: копируем crawler.db
└── Сервер только читает БД
```

### Изменения

**Создан scanner/sync.py (~60 строк):**
- `fetch_requests()` — SCP скачивает requests.json, очищает на сервере
- `push_database()` — SCP копирует crawler.db на сервер
- Использует paramiko для SSH/SFTP

**Рефакторинг scanner/crawler.py (-204 строки):**
- Удалён `import httpx`
- Удалены функции:
  - `_sync_from_server()` (~56 строк)
  - `_sync_full_db_from_server()` (~92 строки)
  - `_sync_to_server()` (~56 строк)
- Добавлен импорт `from .sync import fetch_requests, push_database`
- В `run()`: вызов `fetch_requests()` в начале, `push_database()` в finally

**Рефакторинг mini-app/backend/main.py (-171 строка):**
- Удалены endpoints:
  - `/api/channels/export`
  - `/api/channels/import`
  - `/api/channels/reset`
  - `/api/queue/pending`
  - `/api/queue/sync`
- Переписаны:
  - `POST /api/scan/request` — пишет в requests.json
  - `GET /api/scan/requests` — читает из requests.json

**Рефакторинг scanner/database.py (-15 строк):**
- Убран ORDER BY priority из `get_next()`, `get_next_atomic()`, `peek_next()`
- Упрощён `add_scan_request()`

### E2E Тестирование ✅
```
1. POST /api/scan/request → {"success": true}
2. requests.json на сервере: [{"username": "test_e2e_channel", ...}]
3. fetch_requests() → ['test_e2e_channel']
4. requests.json очищен: []
5. push_database() → True
```

### Итого
- **Удалено:** ~400 строк
- **Добавлено:** ~145 строк
- **Результат:** -255 строк кода, архитектура значительно упрощена
