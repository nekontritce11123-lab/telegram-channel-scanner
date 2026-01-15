# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram Channel Quality Scanner ("Рекламщик") - анализатор качества Telegram каналов для оценки рекламного потенциала. Использует Pyrogram MTProto API для сканирования с минимальным количеством запросов (3 на канал).

## Commands

```bash
# Run scanner on a channel
python run.py @channel_name
python -m scanner.cli @channel_name

# Crawler - автоматический сбор базы каналов
python crawler.py @seed1 @seed2    # Первый запуск с seed каналами
python crawler.py                   # Продолжить сбор
python crawler.py --stats           # Общая статистика
python crawler.py --category-stats  # Статистика по категориям
python crawler.py --export good.csv # Экспорт GOOD каналов
python crawler.py --export ai.csv --category AI_ML  # Экспорт с фильтром
python crawler.py --classify        # Классифицировать существующие GOOD

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Requires `.env` file with Telegram API credentials:
```
API_ID=your_api_id
API_HASH=your_api_hash
PHONE=your_phone_number
GROQ_API_KEY=your_groq_key  # Опционально, для AI классификации
```

Get Telegram credentials at https://my.telegram.org/apps
Get Groq API key at https://console.groq.com/keys

## Architecture

### Scoring System (v15.2 Trust Multiplier)

```
Final Score = Raw Score × Trust Factor
```

**Raw Score (0-100)** - "витрина":
- Quality (40): cv_views, reach, views_decay, forward_rate
- Engagement (40): comments, reaction_rate, er_variation, stability
- Reputation (20): verified, age, premium, source_diversity

**Trust Factor (0.0-1.0)** - мультипликатор доверия:
- Forensics: ID Clustering, Geo/DC Check, Premium Density
- Statistical: Hollow Views, Zombie Engagement, Satellite (only if comments dead)
- Ghost Protocol: Ghost Channel, Zombie Audience, Member Discrepancy
- Decay Trust: Bot Wall, Budget Cliff
- Content: Ad Load, Hidden Comments, Conviction Score

### Core Modules

**scanner/scorer.py** - Main scoring logic
- `calculate_final_score()` - Entry point for scoring
- `calculate_trust_factor()` - Trust multiplier calculation
- `calculate_floating_weights()` - Redistribute points when comments/reactions disabled
- `*_to_points()` functions - Convert metrics to points

**scanner/metrics.py** - Metric calculations
- `FraudConvictionSystem` - Fraud detection with 13 factors (F1-F13)
- `check_instant_scam()` - Quick SCAM detection
- `calculate_ad_load()` - Ad post detection with keyword/link analysis

**scanner/forensics.py** - User analysis
- `UserForensics` class with 4 detection methods:
  - ID Clustering (FATALITY if >30% neighbor IDs)
  - Geo/DC Check (foreign datacenter detection)
  - Premium Density (0% premium = suspicious)
  - Hidden Flags (scam/fake users)

**scanner/client.py** - Telegram API
- `smart_scan()` - 3-request scan (GetHistory, LinkedChat/Reactions, GetFullChannel)
- `RawMessageWrapper`, `RawUserWrapper` - MTProto response wrappers
- Returns `ScanResult` dataclass with channel_health for Ghost Protocol

**scanner/cli.py** - CLI interface
- `scan_channel()` - Async scan entry point
- `print_result()` - Colored terminal output with markers ([FLOAT], [VIRAL], [BOT_WALL], etc.)
- Results saved to `output/{channel}.json`

**scanner/crawler.py** - Smart Crawler (v18.0)
- `SmartCrawler` - автоматический сбор каналов с rate limiting
- Пороги: GOOD_THRESHOLD=60, COLLECT_THRESHOLD=66
- FloodWait: всегда ждать указанное время, никогда не пропускать

**scanner/classifier.py** - AI Classifier (v18.0)
- Groq API + Llama 3.3 70B для классификации
- 17 категорий + multi-label поддержка (CAT+CAT2)
- FALLBACK_KEYWORDS для offline режима без API

**scanner/database.py** - SQLite storage
- Статусы: WAITING, PROCESSING, GOOD, BAD, ERROR
- Поля: category + category_secondary (multi-label)

### AI Categories (v18.0)

```
Премиальные (CPM 2000-7000₽): CRYPTO, FINANCE, REAL_ESTATE, BUSINESS
Технологии (CPM 1000-2000₽):  TECH, AI_ML
Образование (CPM 700-1200₽):  EDUCATION, BEAUTY, HEALTH, TRAVEL
Коммерция (CPM 500-1000₽):    RETAIL
Контент (CPM 100-500₽):       ENTERTAINMENT, NEWS, LIFESTYLE
Риск:                         GAMBLING, ADULT
Fallback:                     OTHER
```

### Key Thresholds

```python
# Verdict thresholds
EXCELLENT: score >= 75
GOOD: score >= 55
MEDIUM: score >= 40
HIGH_RISK: score >= 25
SCAM: score < 25

# Trust Factor penalties
ID Clustering FATALITY: ×0.0 (>30% neighbor IDs)
ID Clustering Suspicious: ×0.5 (>15%)
Geo/DC Mismatch: ×0.2 (>75% foreign DC)
Ghost Channel: ×0.5 (>20k members, <0.1% online)
Zombie Audience: ×0.7 (>5k members, <0.3% online)
Bot Wall: ×0.6 (decay 0.98-1.02, suspiciously flat views)
Budget Cliff: ×0.6 (decay <0.2, views dropped dramatically)
Hollow Views: ×0.6 (adaptive by size: micro 400%, small 300%, medium 225%, large 200%)
Zombie Engagement: ×0.7 (Reach >50% + Reaction <0.1%)
Satellite: ×0.8 (Source share >50% AND avg_comments <1)
Ad Load Spam: ×0.4 (>50% ads)
Hidden Comments: ×0.85 (not for verified channels)

# Conviction SCAM thresholds
conviction >= 50 AND factors >= 2 → SCAM
conviction >= 70 AND factors >= 1 → SCAM
conviction >= 80 → SCAM
```

### Floating Weights System (v15.2)

When features are disabled, engagement points redistribute:
```
Normal:           15 comments + 15 reactions + 7 forward = 37
Comments off:     0 comments + 22 reactions + 15 forward = 37
Reactions off:    22 comments + 0 reactions + 15 forward = 37
Both off:         0 comments + 0 reactions + 37 forward = 37
```

### Data Flow

1. `cli.scan_channel()` → `client.smart_scan()` (3 API requests)
2. Returns: chat info, 50 messages, comments data, users for forensics, channel_health
3. `scorer.calculate_final_score()`:
   - Runs `check_instant_scam()` (SCAM check first)
   - Runs `UserForensics.analyze()` (FATALITY check)
   - Calculates Raw Score (quality + engagement + reputation)
   - Calculates Trust Factor (forensics + statistical + ghost + decay + content)
   - Returns final verdict

### Language

Code comments and documentation are in Russian. User-facing output is in Russian.
