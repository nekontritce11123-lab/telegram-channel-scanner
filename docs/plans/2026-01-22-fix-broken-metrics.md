# Fix 4 Broken Metrics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 4 metrics that don't display in UI: regularity, er_trend (was er_variation), stability, source.

**Architecture:** 5 bugs across scorer.py, backend/main.py, and App.tsx prevent metrics from reaching UI. Fix each bug sequentially.

**Tech Stack:** Python (scorer.py, FastAPI), TypeScript (React App.tsx)

---

## Verified Root Causes (3 Agents)

| Metric | scorer.py key | Expected key | Bug Location | Issue |
|--------|---------------|--------------|--------------|-------|
| Регулярность | regularity | regularity | scorer.py:1401 | OVERWRITTEN with incomplete data |
| Тренд ER | er_trend | er_trend | main.py:512 | Fallback uses old 'er_variation' |
| Стабильность ER | reaction_stability | stability | main.py:916 | KEY_MAPPING condition wrong |
| Оригинальность | source_diversity | source | main.py:916 | KEY_MAPPING condition wrong |

---

### Task 1: Fix regularity overwrite bug

**Files:**
- Modify: `scanner/scorer.py:1398-1404`

**Context:**
- Line 1226-1231: FIRST assignment (CORRECT) — has `value`, `points`, `max`, `status`
- Line 1401-1404: SECOND assignment (BROKEN) — only `value`, `status`, **MISSING points/max**

**Step 1: Verify bug exists**

```bash
grep -n "breakdown\['regularity'\]" scanner/scorer.py
```

Expected: Two matches at lines ~1226 and ~1401.

**Step 2: Read lines 1398-1404**

```python
    # Дополнительные данные для Trust Factor
    regularity_cv = calculate_post_regularity(messages)

    # v41.0: ad_load больше не в breakdown (теперь LLM ad_percentage)
    breakdown['regularity'] = {
        'value': round(regularity_cv, 2),
        'status': 'info_only'  # v13.0: только информационно
    }
```

**Step 3: Delete lines 1400-1404 (keep line 1398-1399)**

Keep:
```python
    # Дополнительные данные для Trust Factor
    regularity_cv = calculate_post_regularity(messages)
```

Delete completely:
```python
    # v41.0: ad_load больше не в breakdown (теперь LLM ad_percentage)
    breakdown['regularity'] = {
        'value': round(regularity_cv, 2),
        'status': 'info_only'  # v13.0: только информационно
    }
```

**Step 4: Verify fix**

```bash
grep -n "breakdown\['regularity'\]" scanner/scorer.py
```

Expected: Only ONE match at line ~1226.

**Step 5: Commit**

```bash
git add scanner/scorer.py
git commit -m "fix(scorer): remove regularity overwrite that lost points/max

Bug: Line 1401 overwrote breakdown['regularity'] with incomplete data,
destroying points/max fields set correctly at line 1226."
```

---

### Task 2: Fix KEY_MAPPING logic in backend

**Files:**
- Modify: `mini-app/backend/main.py:772-775` and `mini-app/backend/main.py:915-918`

**Problem Analysis:**
- scorer.py produces: `reaction_stability`, `source_diversity`
- METRIC_CONFIG expects: `stability`, `source`
- KEY_MAPPING maps: `stability` → `reaction_stability`, `source` → `source_diversity`
- Loop condition (line 916): `if new_key == metric_key and old_key in breakdown`
- This checks if `'reaction_stability' == 'stability'` — ALWAYS FALSE!

**Step 1: Read current KEY_MAPPING (lines 772-775)**

```python
    # v23.0: KEY_MAPPING для совместимости со старыми данными
    KEY_MAPPING = {
        'stability': 'reaction_stability',
        'source': 'source_diversity',
    }
```

**Step 2: Invert KEY_MAPPING**

Replace with:
```python
    # v62.5: KEY_MAPPING — scorer.py key → METRIC_CONFIG key
    # scorer.py produces: reaction_stability, source_diversity
    # METRIC_CONFIG expects: stability, source
    KEY_MAPPING = {
        'reaction_stability': 'stability',
        'source_diversity': 'source',
    }
```

**Step 3: Read current loop (lines 913-918)**

```python
            source_key = metric_key
            for old_key, new_key in KEY_MAPPING.items():
                if new_key == metric_key and old_key in breakdown:
                    source_key = old_key
                    break
```

**Step 4: Fix loop logic**

Replace with:
```python
            source_key = metric_key
            for scorer_key, config_key in KEY_MAPPING.items():
                if config_key == metric_key and scorer_key in breakdown:
                    source_key = scorer_key
                    break
```

**Step 5: Commit**

```bash
git add mini-app/backend/main.py
git commit -m "fix(api): invert KEY_MAPPING to correctly resolve reaction_stability/source_diversity

Bug: Condition checked if new_key==metric_key which never matched.
Now correctly maps scorer.py keys to METRIC_CONFIG keys."
```

---

### Task 3: Update er_variation → er_trend in estimate_breakdown()

**Files:**
- Modify: `mini-app/backend/main.py:509-514`

**Problem:** estimate_breakdown() fallback uses old key 'er_variation' with max:5, but scorer.py produces 'er_trend' with max:10.

**Step 1: Read current code (lines 509-514)**

```python
        'engagement': {
            'comments': {'max': 15, 'label': 'Комментарии'},
            'reaction_rate': {'max': 15, 'label': 'Реакции'},
            'er_variation': {'max': 5, 'label': 'Разнообразие'},
            'stability': {'max': 5, 'label': 'Стабильность ER'},
        },
```

**Step 2: Update to er_trend with max:10**

Replace with:
```python
        'engagement': {
            'comments': {'max': 15, 'label': 'Комментарии'},
            'reaction_rate': {'max': 15, 'label': 'Реакции'},
            'er_trend': {'max': 10, 'label': 'Тренд ER'},  # v62.5: was er_variation (max:5)
            'stability': {'max': 5, 'label': 'Стабильность ER'},
        },
```

**Step 3: Commit**

```bash
git add mini-app/backend/main.py
git commit -m "fix(api): rename er_variation → er_trend in estimate_breakdown (v48.0 change)"
```

---

### Task 4: Add regularity to METRIC_DESCRIPTIONS

**Files:**
- Modify: `mini-app/frontend/src/App.tsx:232-236`

**Step 1: Find insertion point**

After `forward_rate` (line 232-236):
```typescript
  'forward_rate': {
    title: 'Виральность',
    description: 'Как часто посты репостят.',
    interpretation: 'Вирусный контент постоянно репостят. Мало репостов = слабая виральность.'
  },
```

**Step 2: Add regularity after forward_rate (after line 236)**

Insert:
```typescript
  'regularity': {
    title: 'Регулярность',
    description: 'Как часто выходят посты.',
    interpretation: 'Оптимально 1-5 постов в день. Меньше 1 в неделю = мёртвый канал. Больше 10 = спам.'
  },
```

**Step 3: Commit**

```bash
git add mini-app/frontend/src/App.tsx
git commit -m "feat(ui): add regularity metric description"
```

---

### Task 5: Rename er_variation → er_trend in METRIC_DESCRIPTIONS

**Files:**
- Modify: `mini-app/frontend/src/App.tsx:247-251`

**Step 1: Read current code (lines 247-251)**

```typescript
  'er_variation': {
    title: 'Разнообразие ER',
    description: 'Насколько разные реакции на разные посты.',
    interpretation: 'Естественно когда на разные посты разная реакция. Одинаково везде = накрутка.'
  },
```

**Step 2: Replace with er_trend**

```typescript
  'er_trend': {
    title: 'Тренд ER',
    description: 'Растёт или падает вовлечённость.',
    interpretation: 'Растущий ER = канал набирает аудиторию. Падающий = выгорание.'
  },
```

**Step 3: Commit**

```bash
git add mini-app/frontend/src/App.tsx
git commit -m "fix(ui): rename er_variation → er_trend in descriptions"
```

---

### Task 6: Build and Deploy

**Step 1: Build frontend**

```bash
cd mini-app/frontend && npm run build
```

Expected: Build successful, no TypeScript errors.

**Step 2: Deploy backend**

```bash
cd mini-app/deploy && python deploy_backend.py
```

**Step 3: Deploy frontend**

```bash
cd mini-app/deploy && python deploy_frontend.py
```

**Step 4: Verify API response**

```bash
curl -s "https://ads-api.factchain-traker.online/api/channels/durov" | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('breakdown',{}), indent=2))"
```

Expected in breakdown:
- `regularity`: has `score` and `max` fields
- `er_trend`: has `score` and `max` fields
- `stability`: has `score` and `max` fields
- `source`: has `score` and `max` fields

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: v62.5 fix 4 broken metrics display complete"
```

---

## Verification Checklist

After deployment, verify in Mini App UI:

- [ ] Регулярность (regularity) shows score X/7, NOT 0/0
- [ ] Тренд ER (er_trend) displays with score X/10
- [ ] Стабильность ER (stability) displays with score X/5
- [ ] Оригинальность (source) displays with score X/6
- [ ] All 4 metrics show description popup on click

---

## Optional: Rescan channels

If breakdown data is stale (old er_variation keys, missing regularity), reset and rescan:

```bash
# Reset all channels to WAITING status
curl -X POST "https://ads-api.factchain-traker.online/api/channels/reset"

# Run crawler to rescan
python crawler.py
```
