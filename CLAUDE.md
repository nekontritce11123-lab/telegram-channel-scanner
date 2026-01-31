# CLAUDE.md — Рекламщик Project Guide

Telegram Channel Quality Scanner для оценки рекламного потенциала. Pyrogram MTProto API, 3 запроса на канал.

## Commands

```bash
# Scanner
python crawler.py scan @channel_name

# Crawler
python crawler.py @seed1 @seed2    # Первый запуск
python crawler.py                   # Продолжить
python crawler.py --stats           # Статистика
python crawler.py --export good.csv # Экспорт

# Deploy (v81.0 Unified CLI)
cd mini-app && python -m deploy deploy all       # Frontend + Backend параллельно
cd mini-app && python -m deploy deploy frontend  # Только фронт
cd mini-app && python -m deploy deploy backend   # Только бэк
cd mini-app && python -m deploy --dry-run deploy all  # Превью
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
| Verdict | Score |
|---------|-------|
| EXCELLENT | ≥75 |
| GOOD | ≥55 |
| MEDIUM | ≥40 |
| HIGH_RISK | ≥25 |
| SCAM | <25 |

## Key Modules

| File | Purpose |
|------|---------|
| scanner/scorer.py | `calculate_final_score()`, `calculate_trust_factor()` |
| scanner/metrics.py | `FraudConvictionSystem`, `check_instant_scam()` |
| scanner/forensics.py | `UserForensics` (ID Clustering, Geo/DC, Premium) |
| scanner/client.py | `smart_scan()` — 3 API requests per channel |
| scanner/crawler.py | `SmartCrawler` with rate limiting |

## Critical Trust Penalties

| Penalty | Multiplier | Trigger |
|---------|------------|---------|
| ID Clustering FATALITY | ×0.0 | >30% neighbor IDs |
| Geo/DC Mismatch | ×0.2 | >75% foreign DC |
| Ghost Channel | ×0.5 | >20k members, <0.1% online |
| Bot Wall | ×0.6 | decay 0.98-1.02 |
| Hollow Views | ×0.6 | views/members ratio too high |

## Documentation

- **Deployment:** [docs/deployment/DEPLOY.md](docs/deployment/DEPLOY.md)
- **Incidents:** [docs/incidents/](docs/incidents/) — postmortems v7.0, v22.1, v22.5, v65.1
- **Plans:** [docs/plans/](docs/plans/)

## Critical Rules

1. **Deploy:** НИКОГДА не убивать процессы на портах без проверки (t-cloud на 3000/3001!)
2. **DB Sync:** Остановить API → скопировать → PRAGMA check → запустить
3. **Nginx:** Проверить конфликты доменов перед изменением конфигов
4. **Crawler:** Остановить перед изменением scorer.py

## Memory Bank

**ВАЖНО:** Обновляй [PROGRESS.md](PROGRESS.md) перед `/compact` или завершением сессии:
1. Запиши текущую задачу и статус
2. Отметь что сделано
3. Укажи TODO для следующей сессии
