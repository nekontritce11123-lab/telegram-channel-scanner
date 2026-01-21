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
