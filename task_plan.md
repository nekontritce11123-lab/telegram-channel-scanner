# Task Plan: v52.0 Complete Metrics Display + Compact Header

## Goal
1. **Уменьшить верхнее меню** - Score Card, Flags, Stats Row занимают слишком много места
2. **Показать ВСЕ метрики** - включая Trust Factor penalties (сейчас скрыты в v51.3)

## Current State (v51.5)
- Score Card: два крупных блока (Score + Trust)
- Flags: 3 чипа на всю ширину
- Stats Row: 3 карточки (Цена, Подписчики, ER)
- Trust Penalties: **СКРЫТЫ** (line 948: "REMOVED per user feedback")
- Info Metrics: ad_load, regularity, er_trend — показаны как info

## Target State (v52.0)
- Score Card: **компактнее** (меньше padding, меньше шрифты)
- Flags: **в одну строку, меньше**
- Stats Row: **компактнее**
- Trust Penalties: **ПОКАЗАТЬ** новую секцию под метриками
- Все метрики видны

---

## Phases

### Phase 1: Compact Score Card ⬜
**Status:** pending
**File:** App.module.css
**Changes:**
- Уменьшить scoreValue: 36px → 28px
- Уменьшить padding: 16px → 10px
- Уменьшить scoreBadge: 12px → 10px
- Gap между блоками: 8px → 6px

### Phase 2: Compact Flags ⬜
**Status:** pending
**File:** App.module.css
**Changes:**
- Уменьшить flagItem padding: 8px → 6px
- Уменьшить иконки: 16px → 14px
- Уменьшить шрифт: 12px → 11px
- Убрать flagsSectionTitle или сделать меньше

### Phase 3: Compact Stats Row ⬜
**Status:** pending
**File:** App.module.css
**Changes:**
- Уменьшить statCard padding
- Уменьшить шрифты statValue, statLabel
- Gap: 8px → 6px

### Phase 4: Add Trust Penalties Section ⬜
**Status:** pending
**File:** App.tsx
**Changes:**
- Добавить новую секцию после metricsGrid
- Показать selectedChannel.trust_penalties (если есть)
- Формат: список штрафов с множителем и причиной

```tsx
{/* Trust Penalties */}
{selectedChannel.trust_penalties && selectedChannel.trust_penalties.length > 0 && (
  <div className={styles.trustPenaltiesSection}>
    <div className={styles.trustPenaltiesTitle}>Штрафы доверия</div>
    {selectedChannel.trust_penalties.map((penalty, i) => (
      <div key={i} className={styles.trustPenaltyItem}>
        <span className={styles.penaltyName}>{penalty.name}</span>
        <span className={styles.penaltyMult}>×{penalty.multiplier}</span>
      </div>
    ))}
  </div>
)}
```

### Phase 5: CSS for Trust Penalties ⬜
**Status:** pending
**File:** App.module.css
**Changes:**
- trustPenaltiesSection: background, border-radius
- trustPenaltiesTitle: small header
- trustPenaltyItem: flex row, justify-between
- penaltyMult: red/orange color

### Phase 6: Backend - ensure trust_penalties returned ⬜
**Status:** pending
**File:** mini-app/backend/server.py
**Changes:**
- Проверить что trust_penalties передаётся в API response
- Формат: `[{name: str, multiplier: float, reason: str}]`

### Phase 7: Test & Deploy ⬜
**Status:** pending

---

## Trust Penalties List (from scorer.py)

| Penalty | Mult | Condition |
|---------|------|-----------|
| ID Clustering FATALITY | ×0.0 | >30% соседних ID |
| ID Clustering Suspicious | ×0.5 | >15% соседних ID |
| Geo/DC Mismatch | ×0.2 | >75% foreign DC |
| Ghost Channel | ×0.5 | >20K members, <0.1% online |
| Zombie Audience | ×0.7 | >5K members, <0.3% online |
| Hollow Views | ×0.6 | Высокие просмотры без реакций |
| Zombie Engagement | ×0.7 | Reach >50% + Reaction <0.1% |
| Bot Wall | ×0.6 | Decay 0.98-1.02 (плоские просмотры) |
| Budget Cliff | ×0.6 | Decay <0.2 (обрыв просмотров) |
| Satellite | ×0.8 | Source share >50% + avg_comments <1 |
| Ad Load Spam | ×0.4 | >50% рекламы |
| Hidden Comments | ×0.85 | Комментарии скрыты |
| Private Links | ×0.85 | Много приватных ссылок |
| Low Posting | ×0.9 | Редкий постинг |

---

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| - | - | - |
