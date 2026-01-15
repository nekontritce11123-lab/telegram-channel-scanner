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

# =============================================
# ДЕПЛОЙ MINI APP — ВСЕГДА ИСПОЛЬЗОВАТЬ ЭТИ СКРИПТЫ!
# =============================================
# Frontend (37.140.192.181)
cd mini-app/frontend && npm run build
cd mini-app/deploy && python deploy_frontend.py

# Backend (217.60.3.122 порт 3002)
cd mini-app/deploy && python deploy_backend.py
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

---

## Mini App Deployment

### Серверы

| Сервер | IP | Назначение |
|--------|----|-----------|
| Frontend | 37.140.192.181 | ads.factchain-traker.online |
| Backend | 217.60.3.122 | ads-api.factchain-traker.online (порт 3002) |

**ВАЖНО:** Домен `api.factchain-traker.online` принадлежит t-cloud! Reklamshik использует `ads-api.factchain-traker.online`.

### Критические ошибки при деплое (НЕ ПОВТОРЯТЬ!)

#### 1. НИКОГДА не убивать процессы на портах без проверки
```bash
# ЗАПРЕЩЕНО - убьёт чужие приложения!
fuser -k 3001/tcp
```
На сервере 217.60.3.122 работают НЕСКОЛЬКО приложений:
- **t-cloud** (порт 3000, 3001) - НЕ ТРОГАТЬ
- **subscription-tracker** - НЕ ТРОГАТЬ
- **reklamshik-api** (порт 3002)

#### 2. Перед деплоем backend ПРОВЕРИТЬ свободный порт
```bash
# Сначала проверь что на порте
ss -tlnp | grep 3002
# Если занят - НЕ УБИВАТЬ, а выбрать другой порт
```

#### 3. Nginx конфликты доменов
На сервере несколько nginx конфигов могут иметь ОДИН домен.
Проверка:
```bash
nginx -T 2>/dev/null | grep -A5 "server_name api.factchain"
```
Если несколько блоков с одним server_name — будет конфликт. Первый загруженный выиграет.

**ВАЖНО:** НЕ создавать nginx конфиг для reklamshik-api с доменом api.factchain-traker.online — этот домен принадлежит t-cloud!

#### 4. Не забывать симлинки nginx
```bash
# После создания конфига ОБЯЗАТЕЛЬНО создать симлинк
ln -sf /etc/nginx/sites-available/reklamshik-api /etc/nginx/sites-enabled/
nginx -t && nginx -s reload
```

#### 5. Миграции БД перед деплоем
Если в коде есть новые колонки (например `photo_url`), СНАЧАЛА запустить миграцию:
```python
# На сервере
cursor.execute("ALTER TABLE channels ADD COLUMN photo_url TEXT DEFAULT NULL")
```
Иначе будет `sqlite3.OperationalError: no such column`

#### 6. База данных находится в /root/reklamshik/crawler.db
НЕ в mini-app/backend/! При деплое копируется только код, БД остаётся на месте.

### Чеклист деплоя Mini App

1. [ ] Проверить что порт 3002 свободен или занят reklamshik-api
2. [ ] Запустить миграции БД если есть новые колонки
3. [ ] Создать/проверить симлинк nginx в sites-enabled
4. [ ] Убедиться что нет конфликта доменов с другими конфигами
5. [ ] `nginx -t && nginx -s reload`
6. [ ] Проверить API: `curl https://api.factchain-traker.online/api/health`
7. [ ] Проверить каналы: `curl https://api.factchain-traker.online/api/channels`

### UI ошибки

1. **justify-content: center в flex контейнере** — если контейнер занимает 100% высоты, контент будет висеть посередине с пустым пространством сверху и снизу
2. **margin-left: auto** — создаёт огромный разрыв между элементами в flex row
3. **Увеличивать размеры постепенно** — не делать сразу +50%, проверять на реальном устройстве
4. **Не использовать один зелёный цвет везде** — цены, вердикты, успехи должны иметь разные цвета для визуального различия

---

## Mini App v7.0 (2026-01-15)

### Формула расчёта цен за пост

```python
# v7.0: Цена за 1000 подписчиков
BASE_PER_1K = {
    "CRYPTO": {"min": 800, "max": 1500},
    "TECH": {"min": 700, "max": 1400},
    "FINANCE": {"min": 600, "max": 1200},
    ...
}

def calculate_post_price(category, members, trust_factor, score):
    base = BASE_PER_1K[category]
    size_k = members / 1000

    # Нелинейный коэффициент размера
    if size_k <= 1:     size_mult = 1.2   # Микро: небольшой премиум
    elif size_k <= 5:   size_mult = 1.0   # Малые: стандарт
    elif size_k <= 20:  size_mult = 0.85  # Средние
    elif size_k <= 50:  size_mult = 0.7   # Большие
    elif size_k <= 100: size_mult = 0.55  # Крупные
    else:               size_mult = 0.4   # Огромные

    # Quality mult: экспоненциальный рост
    # Score 50 = 1.0x, Score 80 = 2.5x, Score 100 = 4.0x
    quality_mult = 0.5 + (score/100)**1.5 * 3.5

    price = base * size_k * size_mult * quality_mult * trust_factor
```

**Калибровка:**
- 950 subs, score 82, крипто = 2,800-5,300₽ (пользователь продаёт за 3000₽ ✓)
- 22K subs, score 79, крипто = 36K-68K₽ (было 2K-5K₽ — НЕПРАВИЛЬНО!)

### Детальный Breakdown (13 метрик)

API endpoint `/api/channels/{username}` теперь возвращает:

```json
{
  "breakdown": {
    "quality": {
      "total": 35, "max": 40,
      "items": {
        "cv_views": {"score": 13, "max": 15, "label": "CV просмотров"},
        "reach": {"score": 8, "max": 10, "label": "Охват"},
        "views_decay": {"score": 7, "max": 8, "label": "Стабильность"},
        "forward_rate": {"score": 7, "max": 7, "label": "Репосты"}
      }
    },
    "engagement": {
      "total": 35, "max": 40,
      "items": {
        "comments": {"score": 13, "max": 15, "label": "Комментарии"},
        "reaction_rate": {"score": 13, "max": 15, "label": "Реакции"},
        "er_variation": {"score": 4, "max": 5, "label": "Разнообразие"},
        "stability": {"score": 5, "max": 5, "label": "Стабильность ER"}
      }
    },
    "reputation": {
      "total": 17, "max": 20,
      "items": {
        "verified": {"score": 4, "max": 5, "label": "Верификация"},
        "age": {"score": 4, "max": 5, "label": "Возраст"},
        "premium": {"score": 4, "max": 5, "label": "Премиумы"},
        "source": {"score": 5, "max": 5, "label": "Оригинальность"}
      }
    }
  },
  "price_estimate": {
    "min": 66320, "max": 132640,
    "base_price": 700,
    "size_mult": 0.55,
    "quality_mult": 3.44,
    "trust_mult": 1.0
  },
  "trust_penalties": []
}
```

### CSS v7.0

```css
/* Увеличенные шрифты (+20-30% от v6.0) */
--font-title: clamp(22px, 4vw, 28px);
--font-body: clamp(15px, 2.5vw, 17px);
--font-secondary: clamp(13px, 2vw, 15px);
--font-meta: clamp(12px, 1.5vw, 14px);

/* Увеличенные отступы */
--spacing-sm: 8px;
--spacing-md: 14px;

/* Progress bars 10px высотой */
.breakdownBar { height: 10px; }
```

### Унификация цветов (убрать зелёный хаос)

```css
/* БЫЛО (v6.0) - всё зелёное: */
.priceMain { color: var(--verdict-excellent); }
.noRisks { color: var(--verdict-excellent); }
.verdictOption.active { background: var(--verdict-excellent); }

/* СТАЛО (v7.0) - разные цвета: */
.priceMain { color: var(--text-color); }  /* Белый */
.noRisks { color: var(--accent); }        /* Telegram accent */
.verdictOption.active { background: var(--button-color); }
```

### КРИТИЧЕСКИЕ ОШИБКИ ДЕПЛОЯ — НЕ ПОВТОРЯТЬ!

1. **НИКОГДА не убивать процессы на портах без проверки!**
   - На сервере 217.60.3.122 порт 3001 занят Node.js (t-cloud бот)
   - Reklamshik API должен работать на порту **3002** (см. nginx config)
   - Если видишь "Address already in use" — НЕ УБИВАТЬ процесс, а изменить порт!

2. **Порты на сервере 217.60.3.122:**
   - 3000 — ЗАНЯТ (t-cloud API) — НЕ ТРОГАТЬ!
   - 3001 — ЗАНЯТ — НЕ ТРОГАТЬ!
   - 3002 — reklamshik-api (FastAPI/uvicorn)

3. **Что произошло 2026-01-15:**
   - При деплое reklamshik-api пытался запуститься на порту 3001
   - Claude убил Node.js процесс (PID 689483) думая что это старый reklamshik
   - На самом деле это был t-cloud бот пользователя
   - Правильное решение: изменить порт uvicorn на 3002 (как в nginx config)

4. **Nginx конфликт доменов (ВТОРОЙ СБОЙ 2026-01-15):**
   - На сервере было ДВА nginx конфига для `api.factchain-traker.online`:
     - `t-cloud` → проксирует на порт 3000 (t-cloud backend)
     - `reklamshik-api` → проксирует на порт 3002 (reklamshik)
   - Nginx загружает конфиги в АЛФАВИТНОМ порядке
   - `reklamshik-api` загружался раньше `t-cloud` → перехватывал запросы → "Not Found"
   - После удаления симлинка reklamshik-api и перезапуска — сломался SSL конфиг t-cloud
   - **НИКОГДА не трогать nginx конфиги других сервисов!**
   - **Домен api.factchain-traker.online принадлежит t-cloud, НЕ reklamshik!**

---

## Ошибки v7.0 (2026-01-15)

### 1. API 502 Bad Gateway после деплоя
**Проблема:** После `systemctl restart reklamshik-api` API возвращает 502.
**Причина:** Uvicorn/FastAPI ещё запускается (занимает 10-30 секунд).
**Решение:** Подождать 30 секунд и проверить снова:
```bash
sleep 30 && curl https://ads-api.factchain-traker.online/api/health
```

### 2. Формула цены v6.0 была НЕПРАВИЛЬНОЙ
**Проблема:** 22K крипто канал показывал цену 2K-5K₽, а микро-канал 950 subs продаётся за 3000₽.
**Причина:** Старая формула: `base × (members/50000)^0.7 × quality` — давала слишком низкие цены.
**Решение v7.0:** Новая формула с BASE_PER_1K и нелинейными коэффициентами размера.

### 3. "Зелёный хаос" в UI
**Проблема:** Цены, вердикты, успехи, риски — всё зелёного цвета (--verdict-excellent).
**Причина:** Копипаста CSS без учёта семантики цветов.
**Решение v7.0:**
- `.priceMain` → `var(--text-color)` (белый)
- `.noRisks` → `var(--accent)` (Telegram accent)
- `.verdictOption.active` → `var(--button-color)`

### 4. Слишком мелкий текст на мобильных
**Проблема:** Шрифт 13px нечитаем на iPhone.
**Решение v7.0:** Увеличить на 20-30%:
```css
--font-body: clamp(15px, 2.5vw, 17px);  /* было 13px */
```

### 5. Показывали только 3 метрики из 13
**Проблема:** UI показывал Quality/Engagement/Reputation агрегаты, не детали.
**Решение v7.0:** Добавить breakdown с 13 метриками (cv_views, reach, comments, reactions, etc.)
