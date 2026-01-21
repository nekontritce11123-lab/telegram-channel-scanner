# Findings: v52.0 Complete Metrics + Compact Header

## User Requirements (Screenshot Analysis)
1. **Score Card** (54 SCORE / 0.85 TRUST) - слишком большой, уменьшить
2. **Flags** (Верификация, Комментарии, Реакции) - можно компактнее
3. **Stats Row** (ЦЕНА, ПОДПИСЧИКИ, ER) - слишком большой
4. **Trust Penalties** - ПОКАЗАТЬ ВСЕ (сейчас скрыты)

## Current CSS Values (App.module.css)

### Score Card
```css
.scoreValue { font-size: 36px; }
.scoreLabel { font-size: 12px; }
.scoreBadge { font-size: 12px; padding: 4px 12px; }
.scoreBlock { padding: 16px; }
.scoreCard { gap: 8px; }
```

### Flags
```css
.flagItem { padding: 8px 4px; font-size: 12px; }
.flagsGrid { gap: 8px; }
svg { width: 16px; height: 16px; }
```

### Stats Row
```css
.statCard { padding defined by card-bg }
.statValue { font-size from design system }
.statsRow { gap: 8px; }
```

## Trust Penalties Data Structure

From scorer.py calculate_trust_factor() returns:
```python
trust_details = {
    'id_clustering': {'multiplier': 0.5, 'reason': '...', 'neighbor_ratio': 0.2},
    'geo_dc': {'multiplier': 0.2, 'reason': '...'},
    'hollow_views': {'multiplier': 0.6, 'reason': '...'},
    # etc
}
```

Backend server.py should convert this to:
```python
trust_penalties = [
    {'name': 'Hollow Views', 'multiplier': 0.6, 'reason': 'Reach 350% > 300%...'},
    {'name': 'Hidden Comments', 'multiplier': 0.85, 'reason': 'Комментарии скрыты'},
]
```

## Current State (v45.0)

### RAW_WEIGHTS in scorer.py (lines 69-92)
```python
RAW_WEIGHTS = {
    'quality': {
        'cv_views': 15,
        'reach': 7,          # v45.0: -3
        'views_decay': 5,    # v45.0: -3 → TO BE REMOVED
        'forward_rate': 13,  # v45.0: +6
    },
    'engagement': {
        'comments': 15,
        'reaction_rate': 15, # → reduce to 8
        'er_variation': 5,   # → TO BE REMOVED
        'stability': 5,
    },
    'reputation': {
        'verified': 0,       # disabled in v38.4
        'age': 7,
        'premium': 7,
        'source': 6,
    },
}

CATEGORY_TOTALS = {
    'quality': 40,      # → 42
    'engagement': 40,   # → 38
    'reputation': 20,   # unchanged
}
```

### er_trend_data Structure (from calculate_er_trend in metrics.py)
```python
{
    'er_trend': float,  # ratio of recent ER / old ER
    'recent_er': float,
    'old_er': float,
    'status': str,      # 'growing' | 'stable' | 'declining' | 'dying' | 'insufficient'
    'posts_analyzed': int
}
```
- Already calculated in scorer.py line 1259
- Currently stored in breakdown as info metric only

### regularity Structure (from calculate_post_regularity in metrics.py)
- Returns CV% of posting intervals
- Higher CV = irregular posting
- Currently stored in breakdown['regularity'] as info only (line 1355)

### posting_data Structure (from calculate_posts_per_day)
```python
{
    'posts_per_day': float,
    'posting_status': str,  # 'normal' | 'active' | 'heavy' | 'spam'
    'trust_multiplier': float
}
```
- This is for TRUST penalty, not scoring
- regularity_to_points should use posts_per_day directly

## Key Insight: regularity vs posts_per_day

Two related but different metrics:
1. `regularity_cv` from `calculate_post_regularity()` - measures consistency (CV of intervals)
2. `posts_per_day` from `calculate_posts_per_day()` - measures frequency

For scoring, we want FREQUENCY (posts_per_day):
- Ideal: 1-5 posts/day = maximum points
- Too rare: <0.5 posts/day = channel is "sleeping"
- Too frequent: >20 posts/day = spam, ad will be buried

## Floating Weights Impact

Current (40 engagement = 15 comments + 15 reactions + 10 redistributable):
```
All on:    15 comments + 15 reactions + 13 forward = 43
No comm:   0  comments + 22 reactions + 21 forward = 43
No react:  22 comments + 0  reactions + 21 forward = 43
Both off:  0  comments + 0  reactions + 43 forward = 43
```

New (38 engagement = 15 comments + 8 reactions + 15 redistributable):
```
All on:    15 comments + 8 reactions + 15 forward = 38
No comm:   0  comments + 15 reactions + 23 forward = 38
No react:  22 comments + 0  reactions + 16 forward = 38
Both off:  0  comments + 0  reactions + 38 forward = 38
```

Wait - need to recalculate. The floating weights affect comments, reactions, and forward_rate.
Total of these three: 15 + 8 + 15 = 38 in new system.

## Trust Factor Penalties Preserved

These stay in calculate_trust_factor():
- `bot_wall` (decay 0.98-1.02): ×0.6
- `budget_cliff` (decay <0.2): ×0.7
- `dying_engagement` (er_trend <0.7 + stable views): ×0.6

## Files to Modify

1. **scanner/scorer.py**
   - RAW_WEIGHTS dict (lines 69-92)
   - CATEGORY_TOTALS dict (lines 94-99)
   - calculate_floating_weights() (lines 459-502)
   - calculate_final_score() - quality and engagement sections
   - New functions: regularity_to_points(), er_trend_to_points()

2. **mini-app/backend/server.py**
   - METRIC_CONFIG mapping
   - format_breakdown_for_ui()
