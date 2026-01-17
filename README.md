<p align="center">
  <img src="https://img.shields.io/badge/Telegram-MTProto-blue?style=for-the-badge&logo=telegram" alt="Telegram MTProto"/>
  <img src="https://img.shields.io/badge/Python-3.10+-green?style=for-the-badge&logo=python" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/AI-Groq%20Llama%203.3-purple?style=for-the-badge&logo=meta" alt="AI Classifier"/>
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT License"/>
</p>

<h1 align="center">
  <br>
  <img src="https://raw.githubusercontent.com/edent/SuperTinyIcons/master/images/svg/telegram.svg" width="80" alt="Telegram Scanner"/>
  <br>
  Telegram Channel Scanner
  <br>
</h1>

<h4 align="center">AI-powered quality analyzer for Telegram channels</h4>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#scoring-system">Scoring</a> •
  <a href="#mini-app">Mini App</a>
</p>

---

## Overview

**Telegram Channel Scanner** is a sophisticated tool for analyzing Telegram channel quality to evaluate advertising potential. It uses **only 3 API requests per channel** thanks to smart MTProto optimization, making it extremely efficient for mass scanning.

```
┌─────────────────────────────────────────────────────────────────┐
│  FINAL SCORE = RAW SCORE (0-100) × TRUST FACTOR (0.0-1.0)      │
│                                                                 │
│  📊 Raw Score: Quality metrics of the channel "storefront"      │
│  🛡️ Trust Factor: Fraud detection & authenticity multiplier    │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### Core Scanner
- **3-Request Scan** — Minimized API calls using MTProto raw queries
- **Trust Factor System** — Multi-layer fraud detection (forensics, statistical, ghost protocol)
- **Floating Weights** — Smart point redistribution when features are disabled
- **13 Quality Metrics** — CV views, reach, engagement, reactions, comments, and more
- **Instant SCAM Detection** — Quick check for obvious fraud patterns

### Smart Crawler
- **Automatic Discovery** — Crawls channel network via forwards and mentions
- **Rate Limiting** — Respects Telegram FloodWait, never skips
- **AI Classification** — Groq Llama 3.3 70B categorization (17 categories)
- **SQLite Storage** — Persistent database with status tracking

### Mini App (Web Interface)
- **Telegram Web App** — Native integration with Telegram
- **Channel Browser** — Search, filter, sort by score/category
- **Detailed Breakdown** — Visual representation of all 13 metrics
- **Price Estimation** — Ad post pricing based on quality and category

## How It Works

```
                    ┌──────────────────┐
                    │  Smart Scan (3)  │
                    │  MTProto API     │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌──────────┐  ┌───────────┐  ┌───────────┐
        │ History  │  │ Linked    │  │ Full      │
        │ 50 posts │  │ Chat/Rxns │  │ Channel   │
        └────┬─────┘  └─────┬─────┘  └─────┬─────┘
             │              │              │
             └──────────────┼──────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │  Scorer v15.2   │
                   │                 │
                   │ • Raw Score     │
                   │ • Trust Factor  │
                   │ • Forensics     │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │  Final Verdict  │
                   │                 │
                   │ EXCELLENT ≥75   │
                   │ GOOD ≥55        │
                   │ MEDIUM ≥40      │
                   │ HIGH_RISK ≥25   │
                   │ SCAM <25        │
                   └─────────────────┘
```

## Installation

### Prerequisites
- Python 3.10+
- Telegram API credentials ([my.telegram.org](https://my.telegram.org/apps))
- Groq API key (optional, for AI classification)

### Setup

```bash
# Clone the repository
git clone https://github.com/nekontritce11123-lab/telegram-channel-scanner.git
cd telegram-channel-scanner

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Configuration (.env)

```env
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
PHONE=+1234567890
GROQ_API_KEY=your_groq_key  # Optional
```

## Usage

### Scan a Single Channel

```bash
python run.py @channel_name
# or
python -m scanner.cli @channel_name
```

**Output Example:**
```
═══════════════════════════════════════════════════════════════════
                    @example_channel
═══════════════════════════════════════════════════════════════════
  Score: 72 GOOD
  Trust: 1.0

  Quality (35/40):
    • CV Views: 13/15
    • Reach: 8/10
    • Views Decay: 7/8 [ORGANIC]
    • Forward Rate: 7/7

  Engagement (32/40):
    • Comments: 12/15
    • Reactions: 13/15
    • ER Variation: 4/5
    • Stability: 3/5

  Reputation (17/20):
    • Verified: ✓
    • Age: 4/5 (2.3 years)
    • Premium: 4/5
    • Source: 5/5
═══════════════════════════════════════════════════════════════════
```

### Crawler — Mass Scanning

```bash
# Start with seed channels
python crawler.py @seed1 @seed2 @seed3

# Continue existing crawl
python crawler.py

# View statistics
python crawler.py --stats
python crawler.py --category-stats

# Export results
python crawler.py --export good_channels.csv
python crawler.py --export crypto.csv --category CRYPTO
```

## Scoring System

### Raw Score Components (100 points)

| Category | Points | Metrics |
|----------|--------|---------|
| **Quality** | 40 | CV Views (15), Reach (10), Views Decay (8), Forward Rate (7) |
| **Engagement** | 40 | Comments (15), Reactions (15), ER Variation (5), Stability (5) |
| **Reputation** | 20 | Verified (5), Age (5), Premium (5), Source Diversity (5) |

### Trust Factor Penalties

| Detection | Multiplier | Trigger |
|-----------|------------|---------|
| **ID Clustering FATALITY** | ×0.0 | >30% neighbor user IDs |
| **ID Clustering** | ×0.5 | >15% neighbor IDs |
| **Geo/DC Mismatch** | ×0.2 | >75% foreign datacenter |
| **Ghost Channel** | ×0.5 | >20k subs, <0.1% online |
| **Zombie Audience** | ×0.7 | >5k subs, <0.3% online |
| **Bot Wall** | ×0.6 | Views decay 0.98-1.02 |
| **Hollow Views** | ×0.6 | Reach > threshold, Forward <0.5% |
| **Ad Load Spam** | ×0.4 | >50% ad posts |

### Floating Weights

When features are disabled, points redistribute automatically:

```
Normal:           15 comments + 15 reactions + 7 forward = 37
Comments off:     0 comments + 22 reactions + 15 forward = 37
Reactions off:    22 comments + 0 reactions + 15 forward = 37
Both off:         0 comments + 0 reactions + 37 forward = 37
```

## AI Categories

The scanner classifies channels into 17 categories with CPM ranges:

| Tier | Categories | CPM Range |
|------|------------|-----------|
| **Premium** | CRYPTO, FINANCE, REAL_ESTATE, BUSINESS | 2000-7000₽ |
| **Tech** | TECH, AI_ML | 1000-2000₽ |
| **Education** | EDUCATION, BEAUTY, HEALTH, TRAVEL | 700-1200₽ |
| **Commerce** | RETAIL | 500-1000₽ |
| **Content** | ENTERTAINMENT, NEWS, LIFESTYLE | 100-500₽ |
| **Risk** | GAMBLING, ADULT | Variable |

## Mini App

The project includes a Telegram Mini App for browsing scanned channels:

### Features
- Channel search and filtering
- Category-based navigation
- Detailed quality breakdown (13 metrics)
- Ad post price estimation
- Trust penalty visualization

### Tech Stack
- **Frontend:** React + Vite + Telegram Web App SDK
- **Backend:** FastAPI + SQLite
- **Bot:** Pyrogram

## Project Structure

```
telegram-channel-scanner/
├── scanner/
│   ├── cli.py          # CLI interface
│   ├── client.py       # MTProto API client
│   ├── scorer.py       # Scoring engine
│   ├── metrics.py      # Metric calculations
│   ├── forensics.py    # User analysis & fraud detection
│   ├── crawler.py      # Smart crawler
│   ├── classifier.py   # AI categorization
│   └── database.py     # SQLite storage
├── mini-app/
│   ├── frontend/       # React Telegram Mini App
│   ├── backend/        # FastAPI server
│   └── deploy/         # Deployment scripts
├── run.py              # Quick scan entry point
├── crawler.py          # Crawler entry point
└── requirements.txt
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Disclaimer

This tool is designed for legitimate advertising research and channel quality analysis. Users are responsible for complying with Telegram's Terms of Service and applicable laws. The developers are not responsible for any misuse of this software.

---

<p align="center">
  Made with ❤️ for the Telegram advertising community
</p>
