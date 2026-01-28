"""
Reklamshik API - FastAPI backend для Mini App.
Использует существующий scanner для анализа каналов.
"""

import os
import sys
import json
import re
import hmac
import hashlib
import asyncio
import time
import base64
from pathlib import Path
from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qs

# v48.1: Regex для валидации Telegram username
USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$')
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# v67.0: Изолированный модуль для фото (не ломается при обновлениях)
from photo import get_channel_photo as _get_channel_photo, get_user_photo as _get_user_photo
from typing import Optional, List
from dotenv import load_dotenv
import httpx

# Добавляем путь к scanner (на сервере: /root/reklamshik/)
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)  # mini-app -> project root
sys.path.insert(0, backend_dir)
sys.path.insert(0, project_root)

# v58.0: Импорт декомпрессии для breakdown
try:
    from scanner.json_compression import decompress_breakdown
except ImportError:
    # Fallback если scanner не найден (legacy)
    decompress_breakdown = lambda x: x

load_dotenv()


# ============================================================================
# v62.0: Analytics - Telegram initData verification
# ============================================================================

def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Верифицирует initData от Telegram и извлекает user_id.
    Работает для ВСЕХ пользователей (не только Premium).
    """
    if not init_data or not bot_token:
        return None
    try:
        parsed = parse_qs(init_data)
        received_hash = parsed.get('hash', [''])[0]
        if not received_hash:
            return None

        # Создаём data-check-string
        data_check_parts = []
        for key in sorted(parsed.keys()):
            if key != 'hash':
                data_check_parts.append(f"{key}={parsed[key][0]}")
        data_check_string = '\n'.join(data_check_parts)

        # Проверяем подпись
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash != received_hash:
            return None

        # Извлекаем user
        user_str = parsed.get('user', [''])[0]
        if user_str:
            user = json.loads(user_str)
            return {'user_id': user.get('id'), 'username': user.get('username')}
        return None
    except Exception:
        return None


def get_user_id_from_request(request) -> int | None:
    """Извлекает user_id из X-Telegram-Init-Data header."""
    init_data = request.headers.get('X-Telegram-Init-Data')
    if not init_data:
        return None
    bot_token = os.getenv("BOT_TOKEN")
    user_data = verify_telegram_init_data(init_data, bot_token)
    return user_data.get('user_id') if user_data else None


# v15.0: CPM-based ценообразование (рублей за 1000 ПРОСМОТРОВ)
# Калиброваны по реальным сделкам:
# - Крипто 800 views, score 82 = $30 = 2700₽
# - TECH 2900 views, score 80 = ~$32 = 2900₽
# - AI_ML 2900 views, score 80 = ~$27 = 2465₽
CPM_RATES = {
    # Премиум (крипто самая дорогая!)
    "CRYPTO":       {"low": 800,  "avg": 1500, "high": 3000},
    "FINANCE":      {"low": 650,  "avg": 1000, "high": 1700},
    "REAL_ESTATE":  {"low": 500,  "avg": 850,  "high": 1500},
    "BUSINESS":     {"low": 400,  "avg": 650,  "high": 1200},

    # Технологии (~3x дешевле крипты)
    "TECH":         {"low": 350,  "avg": 600,  "high": 1000},
    "AI_ML":        {"low": 300,  "avg": 500,  "high": 850},

    # Образование/Лайфстайл
    "EDUCATION":    {"low": 200,  "avg": 350,  "high": 600},
    "BEAUTY":       {"low": 130,  "avg": 230,  "high": 400},
    "HEALTH":       {"low": 130,  "avg": 230,  "high": 400},
    "TRAVEL":       {"low": 170,  "avg": 300,  "high": 500},

    # Контент (самые дешёвые)
    "RETAIL":       {"low": 85,   "avg": 150,  "high": 300},
    "NEWS":         {"low": 65,   "avg": 170,  "high": 400},
    "ENTERTAINMENT":{"low": 35,   "avg": 85,   "high": 170},
    "LIFESTYLE":    {"low": 100,  "avg": 200,  "high": 400},

    # Риск (высокий CPM но сложно продать)
    "GAMBLING":     {"low": 650,  "avg": 1150, "high": 1700},
    "ADULT":        {"low": 65,   "avg": 130,  "high": 200},
    "OTHER":        {"low": 65,   "avg": 130,  "high": 270},
}

# v15.0: Коридор цен ±10% от расчётной цены
PRICE_RANGE = 0.10


def normalize_category(category: str) -> str:
    """Нормализует категорию: uppercase + fallback на OTHER."""
    if not category:
        return "OTHER"
    cat = category.upper().replace("/", "_").replace(" ", "_")
    if cat not in CPM_RATES:
        return "OTHER"
    return cat


def get_cpm_by_score(category: str, score: int, trust_factor: float = 1.0) -> int:
    """
    v15.0: Выбирает CPM по score (экспоненциальная зависимость).
    Score 80 vs 60 = разница в 2-3 раза!
    """
    category = normalize_category(category)
    rates = CPM_RATES[category]
    effective_score = score * trust_factor

    if effective_score >= 80:
        return rates["high"]
    elif effective_score >= 70:
        # 70-80: близко к high
        ratio = (effective_score - 70) / 10
        return int(rates["avg"] + (rates["high"] - rates["avg"]) * (0.5 + ratio * 0.5))
    elif effective_score >= 55:
        # 55-70: avg зона
        ratio = (effective_score - 55) / 15
        return int(rates["avg"] * (0.8 + ratio * 0.2))
    elif effective_score >= 40:
        # 40-55: low-avg
        ratio = (effective_score - 40) / 15
        return int(rates["low"] + (rates["avg"] - rates["low"]) * ratio * 0.5)
    else:
        # <40: ниже low
        return int(rates["low"] * max(0.3, effective_score / 40))


# Pydantic models
class Recommendation(BaseModel):
    type: str  # cpm, tip, warning, success
    icon: str  # emoji
    text: str


class ChannelSummary(BaseModel):
    username: str
    title: Optional[str] = None  # v58.2: Название канала
    score: int
    verdict: str
    trust_factor: float
    members: int
    category: Optional[str] = None
    category_secondary: Optional[str] = None
    category_percent: Optional[int] = None  # v20.0: процент основной категории
    scanned_at: Optional[str] = None
    cpm_min: Optional[int] = None
    cpm_max: Optional[int] = None
    photo_url: Optional[str] = None  # v19.0: аватарка канала
    is_verified: bool = False  # v34.0: Telegram верификация


class ChannelListResponse(BaseModel):
    channels: List[ChannelSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class StatsResponse(BaseModel):
    total: int
    good: int
    bad: int
    waiting: int
    error: int


class CategoryStat(BaseModel):
    category: str
    count: int
    cpm_min: int
    cpm_max: int


class CategoryStatsResponse(BaseModel):
    categories: List[CategoryStat]
    total_categorized: int
    uncategorized: int


# v49.0: Live Scan models
class ScanRequest(BaseModel):
    username: str


class ScanResponse(BaseModel):
    success: bool
    channel: Optional[dict] = None
    error: Optional[str] = None


# v68.0: Prefetch model для batch загрузки фото
class PrefetchPhotosRequest(BaseModel):
    usernames: List[str]


# Глобальные переменные
db = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запуск и остановка приложения."""
    global db

    # Импортируем scanner модули
    from scanner.database import CrawlerDB

    # Инициализация БД
    db_path = os.getenv("DATABASE_PATH", "crawler.db")
    db = CrawlerDB(db_path)
    print(f"База данных подключена: {db_path}")

    # v62.0: Analytics table
    db.conn.execute("PRAGMA journal_mode=WAL")
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER DEFAULT NULL,
            session_id TEXT DEFAULT NULL,
            username TEXT DEFAULT NULL,
            score INTEGER DEFAULT NULL,
            verdict TEXT DEFAULT NULL,
            duration_ms INTEGER DEFAULT NULL,
            status TEXT DEFAULT NULL,
            error_message TEXT DEFAULT NULL,
            properties TEXT DEFAULT NULL,
            platform TEXT DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics_events(created_at DESC)")
    db.conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_type ON analytics_events(event_type)")
    db.conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_user ON analytics_events(user_id)")
    db.conn.commit()
    print("v62.0: Analytics table ready")

    yield

    # Cleanup
    if db:
        db.close()
    print("Сервер остановлен")


app = FastAPI(
    title="Reklamshik API",
    description="API для Telegram Mini App анализа каналов",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# v62.0: Analytics - Async logging helper
# ============================================================================

async def log_analytics(
    event_type: str,
    user_id: int = None,
    username: str = None,
    score: int = None,
    verdict: str = None,
    duration_ms: int = None,
    status: str = "success",
    error_message: str = None,
    properties: dict = None,
    platform: str = None
):
    """
    Асинхронно логирует событие. Никогда не ломает endpoint при ошибке.
    """
    try:
        props_json = json.dumps(properties, ensure_ascii=False) if properties else None
        await asyncio.to_thread(
            _sync_log_event,
            event_type, user_id, username, score, verdict,
            duration_ms, status, error_message, props_json, platform
        )
    except Exception:
        pass  # Silent fail


def _sync_log_event(event_type, user_id, username, score, verdict,
                    duration_ms, status, error_message, props_json, platform):
    """Синхронная запись в SQLite."""
    if db is None:
        return
    cursor = db.conn.cursor()
    cursor.execute("""
        INSERT INTO analytics_events
        (event_type, user_id, username, score, verdict, duration_ms, status, error_message, properties, platform)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (event_type, user_id, username, score, verdict, duration_ms, status, error_message, props_json, platform))
    db.conn.commit()


# CORS для Mini App
# Разрешаем конкретные домены + Telegram WebView
ALLOWED_ORIGINS = [
    "https://ads.factchain-traker.online",  # Production frontend
    "http://localhost:5173",                 # Vite dev server
    "http://localhost:3000",                 # Alternative dev
    "https://web.telegram.org",              # Telegram Web
    "https://weba.telegram.org",             # Telegram Web A
    "https://webk.telegram.org",             # Telegram Web K
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def estimate_avg_views(members: int, breakdown: dict = None, score: int = 50) -> int:
    """
    v15.0: Оценка средних просмотров поста.
    Использует reach% из breakdown или оценивает по score.
    """
    if members <= 0:
        return 100  # Минимум

    # Пытаемся получить reach из breakdown
    reach_percent = 10.0  # Default 10%

    if breakdown:
        quality = breakdown.get('quality', {})
        items = quality.get('items', {})
        reach_item = items.get('reach', {})
        # reach value обычно 0-20 (процент) - может быть строкой или числом
        if 'value' in reach_item:
            try:
                val = reach_item['value']
                # Если строка с % - убираем %
                if isinstance(val, str):
                    val = val.replace('%', '').strip()
                reach_percent = max(1, min(50, float(val)))
            except (ValueError, TypeError):
                pass  # Используем default
        elif reach_item.get('score', 0) > 0:
            # Оценка по score: score 10/10 = 20% reach
            reach_percent = (reach_item['score'] / reach_item.get('max', 10)) * 20

    # Корректировка по score (хороший канал = лучший reach)
    score_factor = 0.7 + (score / 100) * 0.6  # 0.7 - 1.3

    avg_views = int(members * (reach_percent / 100) * score_factor)
    return max(100, avg_views)  # Минимум 100 просмотров


def calculate_post_price(
    category: Optional[str],
    members: int,
    trust_factor: float = 1.0,
    score: int = 50,
    breakdown: dict = None,
    trust_penalties: list = None,
    avg_views: int = None  # v59.6: Реальное значение из БД
) -> tuple:
    """
    v15.0: CPM-based ценообразование.

    Формула:
        price = (avg_views / 1000) × CPM
        CPM зависит от категории и score (экспоненциально)

    Returns:
        (price_min, price_max): Диапазон цен за пост в рублях (±10%)
    """
    # Нормализуем категорию (НИКОГДА не возвращаем None!)
    category = normalize_category(category)

    # v59.6: Используем реальное avg_views если есть, иначе оцениваем
    if avg_views is None or avg_views <= 0:
        avg_views = estimate_avg_views(members, breakdown, score)

    # Получаем CPM по категории и score
    cpm = get_cpm_by_score(category, score, trust_factor)

    # v15.0: Простая формула CPM
    price_center = int((avg_views / 1000) * cpm)

    # Коридор ±10%
    price_min = max(100, int(price_center * (1 - PRICE_RANGE)))
    price_max = max(200, int(price_center * (1 + PRICE_RANGE)))

    return price_min, price_max


def calculate_post_price_details(
    category: Optional[str],
    members: int,
    trust_factor: float = 1.0,
    score: int = 50,
    breakdown: dict = None,
    trust_penalties: list = None,
    avg_views: int = None  # v59.6: Реальное значение из БД
) -> dict:
    """
    v15.0: CPM-based расчёт с деталями для UI.
    ВСЕГДА возвращает dict (никогда None).
    """
    # Нормализуем категорию
    category = normalize_category(category)
    rates = CPM_RATES[category]

    # v59.6: Используем реальное avg_views если есть, иначе оцениваем
    if avg_views is None or avg_views <= 0:
        avg_views = estimate_avg_views(members, breakdown, score)

    # Получаем CPM по score
    cpm = get_cpm_by_score(category, score, trust_factor)

    # v15.0: Простая формула
    price_center = int((avg_views / 1000) * cpm)
    price_min = max(100, int(price_center * (1 - PRICE_RANGE)))
    price_max = max(200, int(price_center * (1 + PRICE_RANGE)))

    return {
        "min": price_min,
        "max": price_max,
        "cpm": cpm,
        "cpm_low": rates["low"],
        "cpm_high": rates["high"],
        "avg_views": avg_views,
        "category": category,
        "score": score,
        "trust_factor": round(trust_factor, 2),
    }


def get_cpm_range(category: Optional[str]) -> tuple:
    """Возвращает CPM диапазон для категории."""
    category = normalize_category(category)
    rates = CPM_RATES[category]
    return rates["low"], rates["high"]


def estimate_breakdown(score: int, trust_factor: float = 1.0) -> dict:
    """
    v65.0: Оценивает детальный breakdown метрик на основе итогового score.

    Используется как fallback когда нет breakdown_json в БД.
    Веса синхронизированы с RAW_WEIGHTS в scanner/scorer.py (v48.0).

    - Quality (42 max): forward_rate(15), cv_views(12), reach(8), regularity(7)
    - Engagement (38 max): comments(15), er_trend(10), reaction_rate(8), reaction_stability(5)
    - Reputation (20 max): age(7), premium(7), source_diversity(6)
    """
    # Raw score до trust factor
    raw_score = score / trust_factor if trust_factor > 0 else score
    raw_score = min(100, raw_score)

    # Процент от максимума (приблизительно)
    pct = raw_score / 100

    # v55.0: Веса синхронизированы с RAW_WEIGHTS в scorer.py (v48.0)
    weights = {
        'quality': {
            'forward_rate': {'max': 15, 'label': 'Репосты'},      # v48.0: +8 (виральность)
            'cv_views': {'max': 12, 'label': 'CV просмотров'},    # v48.0: -3
            'reach': {'max': 8, 'label': 'Охват'},                # v48.0: -2
            'regularity': {'max': 7, 'label': 'Регулярность'},    # v48.0: NEW
            # views_decay убран в v48.0 → остался в Trust Factor
        },
        'engagement': {
            'comments': {'max': 15, 'label': 'Комментарии'},
            'er_trend': {'max': 10, 'label': 'Тренд ER'},
            'reaction_rate': {'max': 8, 'label': 'Реакции'},      # v48.0: -7 (легко накрутить)
            'reaction_stability': {'max': 5, 'label': 'Стабильность ER'},  # v65.0: fix key
        },
        'reputation': {
            'age': {'max': 7, 'label': 'Возраст'},
            'premium': {'max': 7, 'label': 'Премиумы'},
            'source_diversity': {'max': 6, 'label': 'Оригинальность'},  # v65.0: fix key
        },
    }

    breakdown = {}

    for category, items in weights.items():
        cat_max = sum(item['max'] for item in items.values())
        cat_score = int(cat_max * pct)

        breakdown[category] = {
            'total': cat_score,
            'max': cat_max,
            'items': {}
        }

        # Распределяем баллы пропорционально весам
        remaining = cat_score
        item_list = list(items.items())

        for i, (key, item) in enumerate(item_list):
            if i == len(item_list) - 1:
                # Последний элемент получает остаток
                item_score = remaining
            else:
                # Пропорционально весу
                item_score = int(item['max'] * pct)
                remaining -= item_score

            breakdown[category]['items'][key] = {
                'score': min(item_score, item['max']),
                'max': item['max'],
                'label': item['label']
            }

    return breakdown


def format_llm_analysis_for_ui(llm_data: dict) -> dict:
    """
    v41.0: Форматирует LLM анализ для UI.

    Поддерживает две структуры:

    1. Плоская (v41.0 crawler):
    {
        'ad_percentage': 15,
        'bot_percentage': 8,
        'trust_score': 65,
        'llm_trust_factor': 0.85,
        'ad_mult': 1.0,
        'bot_mult': 1.0
    }

    v41.0: authenticity УДАЛЕНА (дубликат bot_percentage).

    2. Вложенная (старая):
    {
        'tier': 'STANDARD',
        'posts': {...},
        'comments': {...}
    }
    """
    if not llm_data:
        return None

    result = {
        'tier': llm_data.get('tier', 'STANDARD'),
        'tier_cap': llm_data.get('tier_cap', 100),
        'exclusion_reason': llm_data.get('exclusion_reason'),
        'llm_bonus': round(llm_data.get('llm_bonus', 0), 1),
        'llm_trust_factor': round(llm_data.get('llm_trust_factor', 1.0), 2),
    }

    # v41.0: Проверяем плоскую структуру (от нового crawler)
    has_flat_data = 'ad_percentage' in llm_data or 'bot_percentage' in llm_data

    if has_flat_data:
        # Плоская структура — форматируем как posts/comments
        ad_pct = llm_data.get('ad_percentage')
        if ad_pct is not None:
            result['posts'] = {
                'ad_percentage': {
                    'value': ad_pct,
                    'label': 'Рекламы %',
                    'status': _get_metric_status(ad_pct, good_max=20, warning_max=40)
                }
            }

        # v41.0: authenticity REMOVED
        bot_pct = llm_data.get('bot_percentage')
        trust = llm_data.get('trust_score')

        if bot_pct is not None or trust is not None:
            result['comments'] = {}
            if bot_pct is not None:
                result['comments']['bot_percentage'] = {
                    'value': bot_pct,
                    'label': 'Ботов %',
                    'status': _get_metric_status(bot_pct, good_max=20, warning_max=50)
                }
            if trust is not None:
                result['comments']['trust_score'] = {
                    'value': trust,
                    'label': 'Доверие',
                    'status': _get_reverse_status(trust, good_min=60, warning_min=30)
                }

        return result

    # Старая вложенная структура
    posts = llm_data.get('posts')
    if posts:
        result['posts'] = {
            'brand_safety': {
                'value': posts.get('brand_safety', 0),
                'label': 'Brand Safety',
                'status': _get_brand_safety_status(posts.get('brand_safety', 0))
            },
            'toxicity': {
                'value': posts.get('toxicity', 0),
                'label': 'Токсичность',
                'status': _get_metric_status(posts.get('toxicity', 0), good_max=10, warning_max=40)
            },
            'violence': {
                'value': posts.get('violence', 0),
                'label': 'Насилие',
                'status': _get_metric_status(posts.get('violence', 0), good_max=10, warning_max=30)
            },
            'political_quantity': {
                'value': posts.get('political_quantity', 0),
                'label': 'Политика %',
                'status': _get_metric_status(posts.get('political_quantity', 0), good_max=15, warning_max=40)
            },
            'political_risk': {
                'value': posts.get('political_risk', 0),
                'label': 'Полит. риск',
                'status': _get_metric_status(posts.get('political_risk', 0), good_max=20, warning_max=50)
            },
            'misinformation': {
                'value': posts.get('misinformation', 0),
                'label': 'Дезинформация',
                'status': _get_metric_status(posts.get('misinformation', 0), good_max=10, warning_max=30)
            },
            'ad_percentage': {
                'value': posts.get('ad_percentage', 0),
                'label': 'Рекламы %',
                'status': _get_metric_status(posts.get('ad_percentage', 0), good_max=20, warning_max=40)
            },
            'red_flags': posts.get('red_flags', [])
        }

    comments = llm_data.get('comments')
    if comments:
        # v41.0: authenticity REMOVED
        result['comments'] = {
            'bot_percentage': {
                'value': comments.get('bot_percentage', 0),
                'label': 'Ботов %',
                'status': _get_metric_status(comments.get('bot_percentage', 0), good_max=20, warning_max=50)
            },
            'bot_signals': comments.get('bot_signals', []),
            'trust_score': {
                'value': comments.get('trust_score', 0),
                'label': 'Доверие',
                'status': _get_reverse_status(comments.get('trust_score', 0), good_min=60, warning_min=30)
            },
            'trust_signals': comments.get('trust_signals', [])
        }

    return result


def _get_brand_safety_status(value: int) -> str:
    """Статус для brand_safety (чем выше - тем лучше)."""
    if value >= 80:
        return 'good'
    elif value >= 60:
        return 'warning'
    return 'bad'


def _get_metric_status(value: int, good_max: int, warning_max: int) -> str:
    """Статус для метрик где низкое значение = хорошо (toxicity, violence, etc)."""
    if value <= good_max:
        return 'good'
    elif value <= warning_max:
        return 'warning'
    return 'bad'


def _get_reverse_status(value: int, good_min: int, warning_min: int) -> str:
    """Статус для метрик где высокое значение = хорошо (trust)."""
    if value >= good_min:
        return 'good'
    elif value >= warning_min:
        return 'warning'
    return 'bad'


def format_breakdown_for_ui(breakdown_data: dict, llm_analysis: dict = None) -> dict:
    """
    v23.0: Преобразует реальный breakdown из scorer.py в формат для UI.
    v39.0: Интегрирует LLM данные в существующие метрики (не показывает отдельно).

    scorer.py возвращает:
        {
            'breakdown': {
                'cv_views': {'value': 45.2, 'points': 12, 'max': 13},
                'reach': {'value': 8.5, 'points': 8, 'max': 10},
                'ad_load': {'value': 15.0, 'status': 'normal'},  # INFO METRIC
                'posting_frequency': {'posts_per_day': 2.5, 'status': 'normal'},  # INFO METRIC
                ...
            },
            'categories': {
                'quality': {'score': 30, 'max': 40},
                'engagement': {'score': 33, 'max': 40},
                'reputation': {'score': 15, 'max': 20}
            }
        }

    UI ожидает:
        {
            'quality': {
                'total': 30, 'max': 40,
                'items': {
                    'cv_views': {'score': 12, 'max': 13, 'label': 'CV просмотров'},
                    ...
                },
                'info_metrics': {
                    'ad_load': {'value': '15%', 'label': 'Рекл. нагрузка', 'status': 'good'},
                    ...
                }
            },
            ...
        }

    v39.0: Если llm_analysis передан:
        - ad_percentage из LLM заменяет keyword-based ad_load (более точный)
        - bot_percentage из LLM добавляется в comments.bot_info
    """
    breakdown = breakdown_data.get('breakdown', {})

    # v39.0: Извлекаем LLM данные для интеграции
    llm_ad_percentage = None
    llm_bot_percentage = None
    if llm_analysis:
        llm_ad_percentage = llm_analysis.get('ad_percentage')
        llm_bot_percentage = llm_analysis.get('bot_percentage')

    categories = breakdown_data.get('categories', {})

    # v62.5: KEY_MAPPING — scorer.py key → METRIC_CONFIG key
    # scorer.py produces: reaction_stability, source_diversity
    # METRIC_CONFIG expects: stability, source
    KEY_MAPPING = {
        'reaction_stability': 'stability',
        'source_diversity': 'source',
    }

    # v48.0: Маппинг метрик в категории с labels (Score Metrics - имеют points/max)
    METRIC_CONFIG = {
        'quality': {
            'cv_views': 'CV просмотров',
            'reach': 'Охват',
            'regularity': 'Регулярность',  # v48.0: NEW
            'forward_rate': 'Репосты',
            # views_decay → info_only (points=0, max=0)
        },
        'engagement': {
            'comments': 'Комментарии',
            'er_trend': 'Тренд ER',  # v48.0: NEW (заменил er_variation)
            'reaction_rate': 'Реакции',
            'reaction_stability': 'Стабильность ER',
        },
        'reputation': {
            # v34.0: verified убран - отображается как галочка на ScoreRing
            'age': 'Возраст',
            'premium': 'Премиумы',
            'source_diversity': 'Оригинальность',
        },
    }

    # v23.0: Info Metrics config с thresholds для определения статуса
    # Эти метрики влияют на Trust Factor, но показываются информационно
    INFO_METRICS_CONFIG = {
        'quality': {
            'ad_load': {
                'label': 'Рекл. нагрузка',
                'value_key': 'value',  # Поле в breakdown
                'format': 'percent',
                'thresholds': {
                    'good': (0, 10),      # 0-10% = хорошо
                    'warning': (10, 30),  # 10-30% = предупреждение
                    'bad': (30, 100),     # >30% = плохо
                },
                'invert': False,  # Меньше = лучше
            },
            'activity': {
                'label': 'Активность',
                'source_key': 'posting_frequency',  # v25.0: берём данные из posting_frequency
                'value_key': 'posts_per_day',
                'format': 'posts_day_smart',  # v25.0: умное форматирование
                'thresholds': {
                    # v25.0: Двусторонние пороги - редко плохо, много тоже плохо
                    'bad_low': (0, 0.14),       # < 1/неделя = мёртвый канал
                    'warning_low': (0.14, 0.5), # 1-3/неделя = редко
                    'good': (0.5, 8),           # 0.5-8/день = активный
                    'warning_high': (8, 15),    # 8-15/день = очень активный
                    'bad_high': (15, 1000),     # >15/день = спам
                },
            },
        },
        'reputation': {
            # v25.0: posting_frequency перенесён в quality как 'activity'
            'private_links': {
                'label': 'Приватные',
                'value_key': 'private_ratio',
                'format': 'ratio_percent',  # v23.0: ratio (0.0-1.0) -> percent
                'thresholds': {
                    'good': (0, 0.2),      # 0-20% = нормально
                    'warning': (0.2, 0.5), # 20-50% = много приватных
                    'bad': (0.5, 1.0),     # >50% = подозрительно
                },
                'invert': False,
            },
        },
    }

    def get_info_metric_status(value: float, config: dict) -> str:
        """Определяет статус info metric по thresholds."""
        thresholds = config.get('thresholds', {})

        # v25.0: Двусторонние пороги (bad_low, warning_low, good, warning_high, bad_high)
        if 'bad_low' in thresholds:
            if thresholds['bad_low'][0] <= value < thresholds['bad_low'][1]:
                return 'bad'
            if 'warning_low' in thresholds and thresholds['warning_low'][0] <= value < thresholds['warning_low'][1]:
                return 'warning'
            if thresholds['good'][0] <= value < thresholds['good'][1]:
                return 'good'
            if 'warning_high' in thresholds and thresholds['warning_high'][0] <= value < thresholds['warning_high'][1]:
                return 'warning'
            if 'bad_high' in thresholds and value >= thresholds['bad_high'][0]:
                return 'bad'
            return 'warning'

        # Специальные случаи (например, слишком редкий постинг)
        special = config.get('special', {})
        for status, (min_val, max_val) in special.items():
            if min_val <= value < max_val:
                return status

        for status, (min_val, max_val) in thresholds.items():
            if min_val <= value < max_val:
                return status

        return 'warning'  # Default

    def format_info_value(value: float, fmt: str, config: dict = None) -> str:
        """Форматирует значение info metric для отображения."""
        if fmt == 'percent':
            return f"{value:.0f}%"
        elif fmt == 'ratio_percent':
            # v23.0: Конвертируем ratio (0.0-1.0) в проценты
            return f"{value * 100:.0f}%"
        elif fmt == 'cv':
            return f"CV {value:.0f}%"
        elif fmt == 'posts_day':
            if value < 1:
                return f"{value:.1f}/день"
            else:
                return f"{value:.0f}/день"
        elif fmt == 'posts_day_smart':
            # v25.0: Умное форматирование - показываем в удобных единицах
            if value < 0.14:  # < 1/неделя
                posts_per_month = value * 30
                if posts_per_month < 1:
                    return "< 1/мес"
                return f"{posts_per_month:.0f}/мес"
            elif value < 1:  # < 1/день
                posts_per_week = value * 7
                return f"{posts_per_week:.1f}/нед"
            else:
                return f"{value:.1f}/день"
        return str(value)

    result = {}

    for cat_key, metrics in METRIC_CONFIG.items():
        cat_data = categories.get(cat_key, {})

        items = {}
        calculated_max = 0  # v22.2: Сумма max всех items (учитывает floating weights)

        for metric_key, label in metrics.items():
            # v62.5: KEY_MAPPING maps scorer.py keys → METRIC_CONFIG keys
            source_key = metric_key
            for scorer_key, config_key in KEY_MAPPING.items():
                if config_key == metric_key and scorer_key in breakdown:
                    source_key = scorer_key
                    break

            metric_data = breakdown.get(source_key, breakdown.get(metric_key, {}))

            # Получаем значения (scorer.py использует 'points', UI ожидает 'score')
            score_val = metric_data.get('points', metric_data.get('score', 0))
            max_val = metric_data.get('max', 0)

            # v22.1: Если max=0, значит метрика отключена (floating weights)
            # Например, reaction_rate=0 когда реакции выключены на канале
            if max_val == 0 and metric_key in ('reaction_rate', 'comments'):
                item_data = {
                    'score': 0,
                    'max': 0,
                    'label': label,
                    'value': 'откл.',  # Показываем что метрика отключена
                    'disabled': True,
                }
                items[metric_key] = item_data
                continue

            # Формируем human-readable value если есть
            value = None
            if 'value' in metric_data:
                raw_value = metric_data['value']
                if metric_key == 'verified':
                    value = 'Да' if raw_value else 'Нет'
                elif metric_key == 'age':
                    # Возраст в днях -> человекочитаемый формат
                    days = raw_value if isinstance(raw_value, (int, float)) else 0
                    if days >= 365 * 2:
                        value = f"{int(days / 365)} года"
                    elif days >= 365:
                        value = "1 год"
                    elif days >= 30:
                        value = f"{int(days / 30)} мес."
                    else:
                        value = f"{int(days)} дн."
                elif metric_key == 'reaction_stability':
                    # v58.2: CV (коэф. вариации) - чем ниже, тем стабильнее
                    # Не показываем числовое значение (257.8% вводит в заблуждение)
                    cv = raw_value if isinstance(raw_value, (int, float)) else 0
                    if cv < 0.5:
                        value = 'высокая'
                    elif cv < 1.0:
                        value = 'средняя'
                    else:
                        value = 'низкая'
                elif metric_key == 'premium':
                    # v58.2: premium_ratio показываем как процент аудитории
                    if isinstance(raw_value, (int, float)) and raw_value > 0:
                        value = f"{raw_value:.1f}%"
                    else:
                        value = '0%'
                elif isinstance(raw_value, float):
                    value = f"{raw_value:.1f}%"

            item_data = {
                'score': score_val,
                'max': max_val,
                'label': label,
            }
            if value:
                item_data['value'] = value

            # v39.0: Добавляем bot_percentage в comments если есть LLM данные
            if metric_key == 'comments' and llm_bot_percentage is not None:
                bot_pct = int(llm_bot_percentage)
                # Определяем статус: <20% = good, 20-50% = warning, >50% = bad
                if bot_pct <= 20:
                    bot_status = 'good'
                elif bot_pct <= 50:
                    bot_status = 'warning'
                else:
                    bot_status = 'bad'
                item_data['bot_info'] = {
                    'value': f'{bot_pct}% боты',
                    'status': bot_status,
                    'llm_source': True,
                }

            items[metric_key] = item_data
            calculated_max += max_val  # v22.2: Суммируем max каждого item

        # v23.0: Обрабатываем Info Metrics для этой категории
        info_metrics = {}
        cat_info_config = INFO_METRICS_CONFIG.get(cat_key, {})

        for info_key, config in cat_info_config.items():
            # v39.0: Для ad_load — используем LLM ad_percentage если есть (более точный)
            if info_key == 'ad_load' and llm_ad_percentage is not None:
                float_value = float(llm_ad_percentage)
                status = get_info_metric_status(float_value, config)
                formatted_value = f"{float_value:.0f}%"
                bar_percent = 100 if status == 'good' else 60 if status == 'warning' else 20

                info_metrics[info_key] = {
                    'score': 0,
                    'max': 0,
                    'value': formatted_value,
                    'label': config['label'] + ' (AI)',  # Маркируем как AI
                    'status': status,
                    'bar_percent': bar_percent,
                    'raw_value': float_value,
                    'llm_source': True,  # v39.0: помечаем что данные от LLM
                }
                continue

            # v25.0: source_key позволяет брать данные из другого ключа breakdown
            source_key = config.get('source_key', info_key)
            info_data = breakdown.get(source_key, {})
            if not info_data:
                continue

            value_key = config.get('value_key', 'value')
            raw_value = info_data.get(value_key)

            if raw_value is None:
                continue

            # Конвертируем в float
            try:
                float_value = float(raw_value)
            except (TypeError, ValueError):
                continue

            # Определяем статус
            status = get_info_metric_status(float_value, config)

            # Форматируем значение для отображения
            formatted_value = format_info_value(float_value, config.get('format', 'percent'), config)

            # v24.0: bar_percent для прогресс-бара (good=100%, warning=60%, bad=20%)
            bar_percent = 100 if status == 'good' else 60 if status == 'warning' else 20

            info_metrics[info_key] = {
                'score': 0,
                'max': 0,
                'value': formatted_value,
                'label': config['label'],
                'status': status,
                'bar_percent': bar_percent,  # v24.0: для прогресс-бара
                'raw_value': float_value,
            }

        result[cat_key] = {
            'total': cat_data.get('score', 0),
            'max': cat_data.get('max', calculated_max),  # v55.0: Берём из categories, fallback на сумму items
            'items': items,
        }

        # v23.0: Добавляем info_metrics только если есть данные
        if info_metrics:
            result[cat_key]['info_metrics'] = info_metrics

    return result


def estimate_trust_penalties(trust_factor: float, score: int) -> list:
    """
    v7.0: Оценивает trust penalties на основе trust_factor.

    Если trust_factor < 1.0, значит были применены штрафы.
    Возвращаем наиболее вероятные причины.
    """
    penalties = []

    if trust_factor >= 1.0:
        return penalties

    # Определяем примерные причины по значению trust_factor
    if trust_factor <= 0.3:
        penalties.append({
            'name': 'Критический риск',
            'multiplier': trust_factor,
            'description': 'Обнаружены серьёзные признаки накрутки'
        })
    elif trust_factor <= 0.5:
        penalties.append({
            'name': 'Высокий риск',
            'multiplier': trust_factor,
            'description': 'Подозрительная активность в канале'
        })
    elif trust_factor <= 0.7:
        penalties.append({
            'name': 'Средний риск',
            'multiplier': trust_factor,
            'description': 'Некоторые метрики вызывают сомнения'
        })
    elif trust_factor < 0.9:
        penalties.append({
            'name': 'Незначительный риск',
            'multiplier': trust_factor,
            'description': 'Небольшие отклонения от нормы'
        })
    else:
        penalties.append({
            'name': 'Минимальный риск',
            'multiplier': trust_factor,
            'description': 'Незначительные замечания'
        })

    return penalties


# v52.2: Названия штрафов на русском
PENALTY_NAMES = {
    'id_clustering': 'Кластеризация ID',
    'geo_dc': 'Географическое несоответствие',
    'premium': 'Нет премиумов',
    'hidden_comments': 'Скрытые комментарии',
    'conviction': 'Подозрительные сигналы',
    'hollow_views': 'Пустые просмотры',
    'zombie_engagement': 'Мёртвая вовлечённость',
    'satellite': 'Канал-сателлит',
    'ghost_channel': 'Канал-призрак',
    'zombie_audience': 'Зомби-аудитория',
    'member_discrepancy': 'Несоответствие подписчиков',
    'bot_wall': 'Bot Wall',
    'budget_cliff': 'Обрыв бюджета',
    'dying_engagement': 'Умирающая вовлечённость',
    'posting_frequency': 'Частота постинга',
    'private_links': 'Приватные ссылки',
    'reaction_flatness': 'Плоские реакции',
    # v60.0: Added missing penalties
    'spam_posting': 'Спам-постинг',
    'scam_network': 'Скам-сеть',
}


def extract_trust_penalties_from_details(trust_details: dict) -> list:
    """
    v52.2: Конвертирует trust_details из scorer.py в формат trust_penalties для UI.

    Args:
        trust_details: dict вида {'penalty_key': {'multiplier': X, 'reason': '...'}, ...}

    Returns:
        list of {'name': str, 'multiplier': float, 'description': str}
    """
    if not trust_details:
        return []

    penalties = []
    for key, details in trust_details.items():
        if not isinstance(details, dict):
            continue

        multiplier = details.get('multiplier', 1.0)
        if multiplier >= 1.0:
            continue  # Не штраф

        name = PENALTY_NAMES.get(key, key.replace('_', ' ').title())
        reason = details.get('reason', '')

        penalties.append({
            'name': name,
            'multiplier': multiplier,
            'description': reason
        })

    # Сортируем по multiplier (самые серьёзные первые)
    penalties.sort(key=lambda x: x['multiplier'])

    return penalties


def extract_llm_penalties(llm_analysis: dict) -> list:
    """
    v60.3: Извлекает LLM штрафы (боты, реклама) из llm_analysis.

    Args:
        llm_analysis: dict с полями bot_percentage, ad_percentage, bot_mult, ad_mult

    Returns:
        list of {'name': str, 'multiplier': float, 'description': str}
    """
    if not llm_analysis:
        return []

    penalties = []

    # Bot penalty
    bot_mult = llm_analysis.get('bot_mult', 1.0)
    bot_pct = llm_analysis.get('bot_percentage', 0)
    if bot_mult < 1.0 and bot_pct:
        penalties.append({
            'name': 'Боты в комментариях',
            'multiplier': bot_mult,
            'description': f'{bot_pct}% комментариев от ботов'
        })

    # Ad penalty
    ad_mult = llm_analysis.get('ad_mult', 1.0)
    ad_pct = llm_analysis.get('ad_percentage', 0)
    if ad_mult < 1.0 and ad_pct:
        penalties.append({
            'name': 'Рекламная нагрузка',
            'multiplier': ad_mult,
            'description': f'{ad_pct}% постов — реклама'
        })

    return penalties


def _build_trust_penalties(trust_details: dict, breakdown: dict, trust_factor: float, score: int) -> list:
    """
    v60.3: Собирает все штрафы: forensic (trust_details) + LLM (bot/ad).
    """
    penalties = []

    # 1. Forensic penalties из trust_details
    if trust_details:
        penalties.extend(extract_trust_penalties_from_details(trust_details))

    # 2. LLM penalties из breakdown
    if breakdown:
        llm_data = breakdown.get('ll', breakdown.get('llm_analysis', {}))
        if llm_data:
            penalties.extend(extract_llm_penalties(llm_data))

    # 3. Fallback если нет штрафов но trust < 1.0
    if not penalties and trust_factor < 1.0:
        penalties = estimate_trust_penalties(trust_factor, score)

    # Сортируем по multiplier (самые серьёзные первые)
    if penalties:
        penalties.sort(key=lambda x: x.get('multiplier', 1.0))

    return penalties


def generate_recommendations(
    score: int,
    verdict: str,
    trust_factor: float,
    category: Optional[str],
    members: int,
    cpm_min: Optional[int],
    cpm_max: Optional[int],
    breakdown: Optional[dict] = None
) -> List[Recommendation]:
    """
    v8.0: Умные рекомендации на основе breakdown метрик.
    Не просто "отличный канал", а конкретные инсайты.
    """
    recs = []

    # v10.1: Price recommendation REMOVED - now shown in Hero section inline

    # 2. Анализ breakdown — сильные стороны
    if breakdown:
        # v54.1: Защита от деления на 0
        q = breakdown.get('quality', {})
        e = breakdown.get('engagement', {})
        r = breakdown.get('reputation', {})
        quality_pct = (q['total'] / q['max']) * 100 if q.get('max', 0) > 0 else 0
        engagement_pct = (e['total'] / e['max']) * 100 if e.get('max', 0) > 0 else 0
        reputation_pct = (r['total'] / r['max']) * 100 if r.get('max', 0) > 0 else 0

        strengths = []
        if quality_pct >= 70:
            strengths.append("качество контента")
        if engagement_pct >= 70:
            strengths.append("вовлечённость")
        if reputation_pct >= 80:
            strengths.append("репутация")
        if trust_factor >= 0.9:
            strengths.append("доверие")

        if strengths:
            recs.append(Recommendation(
                type="success",
                icon="💪",
                text=f"Сильные стороны: {', '.join(strengths)}"
            ))

        # 3. Анализ breakdown — что улучшить
        weaknesses = []
        if quality_pct < 50:
            weaknesses.append("качество постов")
        if engagement_pct < 50:
            weaknesses.append("вовлечённость")
        if reputation_pct < 50:
            weaknesses.append("репутация")
        if trust_factor < 0.7:
            weaknesses.append(f"доверие (×{trust_factor:.2f})")

        if weaknesses and verdict not in ["EXCELLENT", "GOOD"]:
            recs.append(Recommendation(
                type="warning",
                icon="⚠️",
                text=f"Слабые стороны: {', '.join(weaknesses)}"
            ))

    # 4. Категорийные инсайты
    if category:
        premium_cats = {"CRYPTO": "крипто", "FINANCE": "финансы", "REAL_ESTATE": "недвижимость", "BUSINESS": "бизнес"}
        tech_cats = {"TECH": "технологии", "AI_ML": "ИИ/ML"}

        if category in premium_cats:
            recs.append(Recommendation(
                type="tip",
                icon="💎",
                text=f"{premium_cats[category].capitalize()} — премиум сегмент с высоким CPM"
            ))
        elif category in tech_cats:
            recs.append(Recommendation(
                type="tip",
                icon="🖥️",
                text=f"{tech_cats[category]} — подходит для IT/SaaS продуктов"
            ))

    # 5. Итоговый вердикт
    if verdict == "EXCELLENT" and trust_factor >= 0.9:
        recs.append(Recommendation(
            type="success",
            icon="✅",
            text="Канал готов к рекламе без оговорок"
        ))
    elif verdict == "GOOD" and trust_factor >= 0.8:
        recs.append(Recommendation(
            type="tip",
            icon="👍",
            text="Хороший выбор для рекламных кампаний"
        ))
    elif verdict in ["HIGH_RISK", "SCAM"]:
        recs.append(Recommendation(
            type="warning",
            icon="🚫",
            text="Высокий риск! Не рекомендуется для рекламы"
        ))

    # 6. Размер канала — полезный контекст
    if members > 100000 and verdict in ["EXCELLENT", "GOOD"]:
        recs.append(Recommendation(
            type="tip",
            icon="📢",
            text="Крупный канал — подходит для масштабных запусков"
        ))
    elif members < 5000 and score >= 70:
        recs.append(Recommendation(
            type="tip",
            icon="🎯",
            text="Микро-канал с высоким score — точечная лояльная аудитория"
        ))

    return recs[:4]  # Максимум 4 рекомендации для читаемости


def safe_int(value, default=0) -> int:
    """Safely convert value to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default=1.0) -> float:
    """Safely convert value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def extract_quick_stats_from_breakdown(breakdown: dict) -> dict:
    """
    v54.0: Извлекает quick_stats из breakdown (сжатый или декомпрессированный формат).

    Сжатый формат (v1):
      re = [reach_value, points]
      rr = [reaction_rate_value, points]
      co = ["enabled (avg X.X)", points]

    Декомпрессированный формат:
      reach = {'value': X, 'points': Y, 'max': Z}
      reaction_rate = {'value': X, 'points': Y, 'max': Z}
      comments = {'value': X, 'points': Y, 'max': Z}
    """
    quick_stats = {'reach': 0, 'err': 0, 'comments_avg': 0}

    if not breakdown:
        return quick_stats

    # Reach - охват в %
    # Сжатый формат: re = [value, points]
    re_data = breakdown.get('re')
    if isinstance(re_data, list) and len(re_data) >= 1:
        quick_stats['reach'] = round(float(re_data[0]), 1)
    # Декомпрессированный формат: reach = {'value': X, ...}
    elif 'reach' in breakdown:
        reach_data = breakdown.get('reach')
        if isinstance(reach_data, dict) and 'value' in reach_data:
            quick_stats['reach'] = round(float(reach_data['value']), 1)
        elif isinstance(reach_data, (int, float)):
            quick_stats['reach'] = round(float(reach_data), 1)

    # ERR / Reaction Rate - engagement rate в %
    # Сжатый формат: rr = [value, points]
    rr = breakdown.get('rr')
    if isinstance(rr, list) and len(rr) >= 1:
        quick_stats['err'] = round(float(rr[0]), 2)
    # Декомпрессированный формат: reaction_rate = {'value': X, ...}
    elif 'reaction_rate' in breakdown:
        rr_data = breakdown.get('reaction_rate')
        if isinstance(rr_data, dict) and 'value' in rr_data:
            quick_stats['err'] = round(float(rr_data['value']), 2)
        elif isinstance(rr_data, (int, float)):
            quick_stats['err'] = round(float(rr_data), 2)

    # Comments avg - среднее кол-во комментариев
    # Сжатый формат: co = ["enabled (avg X.X)", points]
    co = breakdown.get('co')
    if isinstance(co, list) and len(co) >= 1:
        co_value = co[0]
        if isinstance(co_value, str) and 'avg' in co_value:
            match = re.search(r'avg\s+([\d.]+)', co_value)
            if match:
                quick_stats['comments_avg'] = round(float(match.group(1)), 1)
    # Декомпрессированный формат: comments = {'value': X, ...}
    elif 'comments' in breakdown:
        co_data = breakdown.get('comments')
        if isinstance(co_data, dict) and 'value' in co_data:
            val = co_data['value']
            if isinstance(val, str) and 'avg' in val:
                match = re.search(r'avg\s+([\d.]+)', val)
                if match:
                    quick_stats['comments_avg'] = round(float(match.group(1)), 1)
            elif isinstance(val, (int, float)):
                quick_stats['comments_avg'] = round(float(val), 1)

    return quick_stats


# ============================================================================
# v67.0: ФОТО ENDPOINTS (изолированы в photo.py)
# ============================================================================

@app.get("/api/photo/{username}")
async def get_channel_photo(username: str):
    """Загружает аватарку канала. См. photo.py"""
    return await _get_channel_photo(username, db=db)


@app.get("/api/user/photo/{user_id}")
async def get_user_photo(user_id: int):
    """Загружает аватарку пользователя. См. photo.py"""
    return await _get_user_photo(user_id)


@app.post("/api/photos/prefetch")
async def prefetch_photos(request: PrefetchPhotosRequest):
    """
    v68.0: Batch загрузка фото из БД.

    Загружает аватарки нескольких каналов за один запрос.
    Возвращает base64-encoded изображения.

    Args:
        usernames: Список username'ов (max 100)

    Returns:
        {
            "photos": {"username1": "data:image/jpeg;base64,...", ...},
            "failed": ["username2", ...]
        }
    """
    if len(request.usernames) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 usernames per request")

    result = {"photos": {}, "failed": []}

    for username in request.usernames:
        username_clean = username.lower().lstrip('@')

        # Валидация
        if not USERNAME_REGEX.match(username_clean):
            result["failed"].append(username_clean)
            continue

        # Получаем из БД
        channel = db.get_channel(username_clean)

        if channel and getattr(channel, 'photo_blob', None):
            photo_blob = channel.photo_blob
            b64 = base64.b64encode(photo_blob).decode('ascii')
            result["photos"][username_clean] = f"data:image/jpeg;base64,{b64}"
        else:
            result["failed"].append(username_clean)

    return result


@app.get("/api/health")
async def health_check():
    """Health check endpoint с проверкой БД."""
    try:
        # Проверяем подключение к БД
        if db is None:
            return {"status": "error", "error": "Database not initialized", "version": "1.0.0"}

        stats = db.get_stats()
        return {
            "status": "ok",
            "version": "1.0.0",
            "db": {
                "connected": True,
                "total_channels": stats.get("total", 0),
                "good_channels": stats.get("good", 0)
            }
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "version": "1.0.0"}


@app.get("/api/channels", response_model=ChannelListResponse)
async def get_channels(
    category: Optional[str] = Query(None, description="Фильтр по категории"),
    min_score: int = Query(0, ge=0, le=100),
    max_score: int = Query(100, ge=0, le=100),
    min_members: int = Query(0, ge=0),
    max_members: int = Query(10000000, ge=0),
    min_trust: float = Query(0.0, ge=0.0, le=1.0, description="Мин. Trust Factor"),
    verdict: Optional[str] = Query(None, description="good_plus = EXCELLENT+GOOD"),
    sort_by: str = Query("score", regex="^(score|members|scanned_at|trust_factor)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Получить список каналов с фильтрацией и пагинацией.
    Новые фильтры v6.0: min_trust, verdict (good_plus = EXCELLENT + GOOD)
    """
    params = [min_score, max_score, min_members, max_members, min_trust]

    # Base WHERE clause - v33: показываем и GOOD и BAD каналы
    where_clause = """
        WHERE status IN ('GOOD', 'BAD')
          AND score >= ? AND score <= ?
          AND members >= ? AND members <= ?
          AND trust_factor >= ?
    """

    # Verdict filter: good_plus = only EXCELLENT and GOOD
    if verdict == "good_plus":
        where_clause += " AND verdict IN ('EXCELLENT', 'GOOD')"

    if category:
        where_clause += " AND (category = ? OR category_secondary = ?)"
        params.extend([category, category])

    # Count total
    count_query = f"SELECT COUNT(*) FROM channels {where_clause}"
    cursor = db.conn.execute(count_query, params)
    total = safe_int(cursor.fetchone()[0], 0)

    # Main query - v34.0: добавлен breakdown_json для is_verified
    # v58.2: добавлен title для отображения названия канала
    query = f"""
        SELECT username, score, verdict, trust_factor, members,
               category, category_secondary, scanned_at, photo_url, category_percent,
               breakdown_json, title
        FROM channels {where_clause}
    """

    # Add sorting and pagination (whitelist approach to prevent SQL injection)
    ALLOWED_SORT_COLUMNS = {"score", "members", "scanned_at", "trust_factor"}
    safe_sort_by = sort_by if sort_by in ALLOWED_SORT_COLUMNS else "score"
    safe_sort_order = "DESC" if sort_order == "desc" else "ASC"
    query += f" ORDER BY {safe_sort_by} {safe_sort_order}"
    query += " LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])

    cursor = db.conn.execute(query, params)
    rows = cursor.fetchall()

    channels = []
    for row in rows:
        score = safe_int(row[1], 0)
        trust_factor = safe_float(row[3], 1.0)
        members = safe_int(row[4], 0)
        category = row[5]

        # v34.0: Извлекаем is_verified из breakdown_json
        is_verified = False
        if row[10]:  # breakdown_json
            try:
                breakdown_data = json.loads(row[10])
                # Может быть в breakdown.verified.value или в flags.is_verified
                bd = breakdown_data.get('breakdown', breakdown_data)
                if 'verified' in bd and isinstance(bd['verified'], dict):
                    is_verified = bd['verified'].get('value', False)
                # Также проверяем flags
                flags = breakdown_data.get('flags', {})
                if 'is_verified' in flags:
                    is_verified = flags.get('is_verified', False)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # v13.1: Используем breakdown для консистентных цен
        breakdown = estimate_breakdown(score, trust_factor)
        trust_penalties = estimate_trust_penalties(trust_factor, score)
        price_min, price_max = calculate_post_price(
            category, members, trust_factor, score,
            breakdown=breakdown,
            trust_penalties=trust_penalties
        )

        channels.append(ChannelSummary(
            username=str(row[0]) if row[0] else "",
            title=str(row[11]) if row[11] else None,  # v58.2
            score=score,
            verdict=str(row[2]) if row[2] else "",
            trust_factor=trust_factor,
            members=members,
            category=category,
            category_secondary=row[6],
            category_percent=safe_int(row[9], 100) if row[9] else 100,  # v20.0
            scanned_at=str(row[7]) if row[7] else None,
            cpm_min=price_min,
            cpm_max=price_max,
            photo_url=str(row[8]) if row[8] else None,
            is_verified=is_verified,  # v34.0
        ))

    return ChannelListResponse(
        channels=channels,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


# v59.7: Endpoint для подсчёта каналов (для preview в фильтрах)
@app.get("/api/channels/count")
async def get_channels_count(
    category: Optional[str] = Query(None, description="Фильтр по категории"),
    min_score: int = Query(0, ge=0, le=100),
    max_score: int = Query(100, ge=0, le=100),
    min_members: int = Query(0, ge=0),
    max_members: int = Query(10000000, ge=0),
    min_trust: float = Query(0.0, ge=0.0, le=1.0, description="Мин. Trust Factor"),
    verdict: Optional[str] = Query(None, description="good_plus = EXCELLENT+GOOD"),
):
    """
    Получить количество каналов по фильтрам (без пагинации).
    Используется для preview в кнопке "Показать X шт."
    """
    params = [min_score, max_score, min_members, max_members, min_trust]

    where_clause = """
        WHERE status IN ('GOOD', 'BAD')
          AND score >= ? AND score <= ?
          AND members >= ? AND members <= ?
          AND trust_factor >= ?
    """

    if verdict == "good_plus":
        where_clause += " AND verdict IN ('EXCELLENT', 'GOOD')"

    if category:
        where_clause += " AND (category = ? OR category_secondary = ?)"
        params.extend([category, category])

    count_query = f"SELECT COUNT(*) FROM channels {where_clause}"
    cursor = db.conn.execute(count_query, params)
    total = safe_int(cursor.fetchone()[0], 0)

    return {"count": total}


# v61.0: Endpoints export/import/reset удалены
# БД теперь копируется через SCP, синхронизация не нужна


@app.get("/api/channels/{username}")
async def get_channel(username: str, request: Request):
    """
    Получить детали канала по username.
    Если канала нет в базе - вернуть 404.

    v23.0: Читает реальный breakdown_json из БД если доступен,
    иначе использует estimate_breakdown() как fallback.
    Поддержка Info Metrics (ad_load, regularity, posting_frequency, private_links).
    """
    start_time = time.perf_counter()
    user_id = get_user_id_from_request(request)
    platform = request.headers.get('X-Platform', 'unknown')
    username = username.lower().lstrip("@")

    # v48.2: Валидация username (консистентность с get_channel_photo)
    if not USERNAME_REGEX.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format")

    # v23.0: Читаем breakdown_json из БД (если колонка существует)
    # v59.3: Добавлен title
    # v59.4: LOWER() для case-insensitive поиска (в БД могут быть mixed-case)
    # v59.6: Добавлен avg_views для расчёта цены
    # Используем try/except для совместимости с БД без колонки breakdown_json
    try:
        cursor = db.conn.execute("""
            SELECT username, score, verdict, trust_factor, members,
                   category, category_secondary, scanned_at, status,
                   photo_url, breakdown_json, title, avg_views
            FROM channels
            WHERE LOWER(username) = ?
        """, (username,))
    except Exception:
        # Fallback для старых БД без колонки breakdown_json/title/avg_views
        cursor = db.conn.execute("""
            SELECT username, score, verdict, trust_factor, members,
                   category, category_secondary, scanned_at, status
            FROM channels
            WHERE LOWER(username) = ?
        """, (username,))

    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Канал не найден в базе")

    score = safe_int(row[1], 0)
    verdict = str(row[2]) if row[2] else ""
    trust_factor = safe_float(row[3], 1.0)
    members = safe_int(row[4], 0)
    category = row[5]

    # v23.0: Пытаемся получить реальный breakdown из БД
    # v59.3: Добавлен title
    # v59.6: Добавлен avg_views
    breakdown_json_str = row[10] if len(row) > 10 else None
    photo_url = row[9] if len(row) > 9 else None
    title = row[11] if len(row) > 11 else None
    db_avg_views = safe_int(row[12], 0) if len(row) > 12 else None  # v59.6

    # Парсим breakdown_json или используем fallback
    real_breakdown_data = None
    if breakdown_json_str:
        try:
            real_breakdown_data = json.loads(breakdown_json_str)
        except (json.JSONDecodeError, TypeError):
            real_breakdown_data = None

    # v39.0: Извлекаем сырые LLM данные ПЕРЕД format_breakdown_for_ui
    # чтобы можно было интегрировать их в метрики
    # v40.3: Ищем в обоих местах - корень И вложенный breakdown (баг crawler.py)
    raw_llm_analysis = None
    if real_breakdown_data:
        # Приоритет 1: корень (правильная структура)
        if real_breakdown_data.get('llm_analysis'):
            raw_llm_analysis = real_breakdown_data.get('llm_analysis')
        # Приоритет 2: вложенный в breakdown (текущий баг crawler.py)
        elif real_breakdown_data.get('breakdown', {}).get('llm_analysis'):
            raw_llm_analysis = real_breakdown_data.get('breakdown', {}).get('llm_analysis')

    # v54.0: QuickStats из сжатого формата (ДО декомпрессии!)
    quick_stats = {'reach': 0, 'err': 0, 'comments_avg': 0}
    if real_breakdown_data and real_breakdown_data.get('breakdown'):
        # Сохраняем оригинальный сжатый формат для quick_stats
        original_compressed = real_breakdown_data.get('breakdown', {})
        quick_stats = extract_quick_stats_from_breakdown(original_compressed)

    # v23.0: Если есть реальный breakdown - форматируем его для UI
    # v39.0: Передаём LLM данные для интеграции в метрики
    # v58.0: Декомпрессия сжатых ключей (cv -> cv_views, etc.)
    # Иначе используем estimate_breakdown() как fallback
    if real_breakdown_data and real_breakdown_data.get('breakdown'):
        # v58.0: Декомпрессируем сжатый breakdown
        decompressed = decompress_breakdown(real_breakdown_data.get('breakdown', {}))
        real_breakdown_data['breakdown'] = decompressed
        breakdown = format_breakdown_for_ui(real_breakdown_data, raw_llm_analysis)
        breakdown_source = "database"
    else:
        breakdown = estimate_breakdown(score, trust_factor)
        breakdown_source = "estimated"

    # v39.0: llm_analysis теперь НЕ отдаём отдельно — данные интегрированы в breakdown
    # Оставляем только tier/tier_cap для status banner (если нужно)
    llm_analysis = None
    if raw_llm_analysis:
        llm_analysis = {
            'tier': raw_llm_analysis.get('tier', 'STANDARD'),
            'tier_cap': raw_llm_analysis.get('tier_cap', 100),
        }

    # v34.0: Извлекаем is_verified из breakdown_json
    is_verified = False
    if real_breakdown_data:
        bd = real_breakdown_data.get('breakdown', real_breakdown_data)
        if 'verified' in bd and isinstance(bd['verified'], dict):
            is_verified = bd['verified'].get('value', False)
        # Также проверяем flags
        flags = real_breakdown_data.get('flags', {})
        if 'is_verified' in flags:
            is_verified = flags.get('is_verified', False)

    # v60.3: Trust penalties (forensic + LLM)
    trust_details = {}
    breakdown_for_llm = {}
    if real_breakdown_data:
        bd = real_breakdown_data.get('breakdown', real_breakdown_data)
        trust_details = bd.get('trust_details', {})
        breakdown_for_llm = bd

    trust_penalties = _build_trust_penalties(trust_details, breakdown_for_llm, trust_factor, score)

    # v13.0: Рассчитываем цену с ВСЕМИ мультипликаторами
    # v59.6: Передаём реальное avg_views из БД
    price_min, price_max = calculate_post_price(
        category, members, trust_factor, score,
        breakdown=breakdown,
        trust_penalties=trust_penalties,
        avg_views=db_avg_views
    )

    # v13.0: Детальная структура price_estimate с ВСЕМИ мультипликаторами
    # v59.6: Передаём реальное avg_views из БД
    price_estimate = calculate_post_price_details(
        category, members, trust_factor, score,
        breakdown=breakdown,
        trust_penalties=trust_penalties,
        avg_views=db_avg_views
    )

    # v15.0: calculate_post_price_details всегда возвращает dict (fallback не нужен)

    # Генерируем рекомендации (v8.0: с breakdown)
    recommendations = generate_recommendations(
        score=score,
        verdict=verdict,
        trust_factor=trust_factor,
        category=category,
        members=members,
        cpm_min=price_min,
        cpm_max=price_max,
        breakdown=breakdown
    )

    # v62.0: Analytics logging
    asyncio.create_task(log_analytics(
        event_type='channel_view',
        user_id=user_id,
        username=str(row[0]),
        score=score,
        verdict=verdict,
        duration_ms=int((time.perf_counter() - start_time) * 1000),
        platform=platform,
        properties={'members': members, 'category': category}
    ))

    return {
        "username": str(row[0]) if row[0] else "",
        "title": title,  # v59.3: название канала
        "score": score,
        "verdict": verdict,
        "trust_factor": trust_factor,
        "members": members,
        "category": category,
        "category_secondary": row[6] if len(row) > 6 else None,
        "category_percent": 100,  # v15.0: не используем из БД
        "scanned_at": str(row[7]) if len(row) > 7 and row[7] else None,
        "status": row[8] if len(row) > 8 else "GOOD",
        "photo_url": photo_url,  # v23.0: читаем из БД
        "cpm_min": price_min,
        "cpm_max": price_max,
        "recommendations": [r.dict() for r in recommendations],
        "source": "database",
        # v7.0: Новые поля
        "breakdown": breakdown,
        "breakdown_source": breakdown_source,  # v23.0: указываем источник данных
        "trust_penalties": trust_penalties,
        "price_estimate": price_estimate,
        # v38.0: LLM Analysis
        "llm_analysis": llm_analysis,
        # v34.0: Telegram верификация
        "is_verified": is_verified,
        # v54.0: QuickStats (reach, err, comments_avg)
        "quick_stats": quick_stats,
    }


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Общая статистика базы."""
    stats = db.get_stats()
    return StatsResponse(
        total=stats.get("total", 0),
        good=stats.get("good", 0),
        bad=stats.get("bad", 0),
        waiting=stats.get("waiting", 0),
        error=stats.get("error", 0),
    )


@app.get("/api/stats/categories", response_model=CategoryStatsResponse)
async def get_category_stats():
    """Статистика по категориям."""
    cat_stats = db.get_category_stats()

    categories = []
    total_categorized = 0

    for cat, count in sorted(cat_stats.items(), key=lambda x: x[1], reverse=True):
        if cat == "UNCATEGORIZED":
            continue
        cat_normalized = normalize_category(cat)
        rates = CPM_RATES.get(cat_normalized, {"low": 65, "avg": 130, "high": 270})
        categories.append(CategoryStat(
            category=cat,
            count=count,
            cpm_min=rates["low"],
            cpm_max=rates["high"],
        ))
        total_categorized += count

    uncategorized = cat_stats.get("UNCATEGORIZED", 0)

    return CategoryStatsResponse(
        categories=categories,
        total_categorized=total_categorized,
        uncategorized=uncategorized,
    )


# ============================================================================
# v49.0: LIVE SCAN ENDPOINT
# ============================================================================

@app.post("/api/scan", response_model=ScanResponse)
async def live_scan_channel(request: ScanRequest):
    """
    v49.0: Live scan канала через scanner.

    Сканирует канал в реальном времени через Pyrogram.
    Время выполнения: 10-30 секунд.
    """
    username = request.username.lower().lstrip('@')

    # v48.1: Валидация username
    if not USERNAME_REGEX.match(username):
        return ScanResponse(success=False, error="Invalid username format")

    try:
        # Импортируем scanner модуль
        from scanner.client import smart_scan_safe, get_client
        from scanner.scorer import calculate_final_score

        # Получаем Pyrogram клиент
        client = get_client()
        if not client.is_connected:
            await client.start()

        # Сканируем канал
        scan_result = await smart_scan_safe(client, username)

        if scan_result.chat is None:
            error_reason = scan_result.channel_health.get("reason", "Channel not found")
            return ScanResponse(success=False, error=error_reason)

        # Рассчитываем score
        result = calculate_final_score(
            scan_result.chat,
            scan_result.messages,
            scan_result.comments_data,
            scan_result.users,
            scan_result.channel_health
        )

        score = result.get('score', 0)
        verdict = result.get('verdict', 'UNKNOWN')
        trust_factor = result.get('trust_factor', 1.0)
        members = result.get('members', 0)
        categories = result.get('categories', {})
        breakdown = result.get('breakdown', {})
        flags = result.get('flags', {})
        trust_details = result.get('trust_details', {})  # v52.2

        # v52.2: Добавляем trust_details в breakdown
        if trust_details:
            breakdown['trust_details'] = trust_details

        # Формируем breakdown_json
        breakdown_data = {
            'breakdown': breakdown,
            'categories': categories,
            'flags': flags,
        }
        breakdown_json = json.dumps(breakdown_data, ensure_ascii=False)

        # Сохраняем в БД (upsert)
        from datetime import datetime
        db.conn.execute("""
            INSERT OR REPLACE INTO channels
            (username, score, verdict, trust_factor, members,
             status, scanned_at, breakdown_json)
            VALUES (?, ?, ?, ?, ?, 'GOOD', datetime('now'), ?)
        """, (username, score, verdict, trust_factor, members, breakdown_json))
        db.conn.commit()

        # Формируем ответ (как get_channel)
        is_verified = flags.get('is_verified', False)

        # Форматируем breakdown для UI
        ui_breakdown = format_breakdown_for_ui(breakdown_data, None)

        price_min, price_max = calculate_post_price(
            None, members, trust_factor, score,
            breakdown=ui_breakdown
        )

        recommendations = generate_recommendations(
            score=score, verdict=verdict, trust_factor=trust_factor,
            category=None, members=members,
            cpm_min=price_min, cpm_max=price_max,
            breakdown=ui_breakdown
        )

        channel_data = {
            "username": username,
            "score": score,
            "verdict": verdict,
            "trust_factor": trust_factor,
            "members": members,
            "category": None,
            "category_secondary": None,
            "category_percent": 100,
            "scanned_at": datetime.now().isoformat(),
            "cpm_min": price_min,
            "cpm_max": price_max,
            "recommendations": [r.dict() for r in recommendations],
            "breakdown": ui_breakdown,
            # v60.3: Trust penalties с учётом LLM штрафов
            "trust_penalties": _build_trust_penalties(trust_details, breakdown, trust_factor, score),
            "is_verified": is_verified,
            "source": "live_scan",
        }

        return ScanResponse(success=True, channel=channel_data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        # v48.2: Не раскрываем детали ошибки
        return ScanResponse(success=False, error="Scan failed")


# ============================================================================
# v62.0: ANALYTICS ENDPOINTS
# ============================================================================

class EventCreate(BaseModel):
    event_type: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    properties: Optional[dict] = None
    platform: Optional[str] = None


@app.post("/api/events")
async def track_event(event: EventCreate, request: Request):
    """v62.0: Endpoint для frontend event tracking."""
    # Попробовать извлечь user_id из header если не передан
    user_id = event.user_id or get_user_id_from_request(request)

    asyncio.create_task(log_analytics(
        event_type=event.event_type,
        user_id=user_id,
        properties=event.properties,
        platform=event.platform or request.headers.get('X-Platform', 'unknown')
    ))
    return {"success": True}


@app.get("/api/analytics/summary")
async def get_analytics_summary(days: int = 7):
    """v62.0: Сводка аналитики за период."""
    cursor = db.conn.cursor()

    # DAU за каждый день
    cursor.execute("""
        SELECT DATE(created_at) as day, COUNT(DISTINCT user_id) as dau
        FROM analytics_events
        WHERE created_at >= datetime('now', ? || ' days')
          AND user_id IS NOT NULL
        GROUP BY DATE(created_at)
        ORDER BY day DESC
    """, (f"-{days}",))
    dau_by_day = {row[0]: row[1] for row in cursor.fetchall()}

    # События по типам
    cursor.execute("""
        SELECT event_type, COUNT(*) as count, AVG(duration_ms) as avg_ms
        FROM analytics_events
        WHERE created_at >= datetime('now', ? || ' days')
        GROUP BY event_type
    """, (f"-{days}",))
    events = {row[0]: {"count": row[1], "avg_ms": round(row[2], 1) if row[2] else None}
              for row in cursor.fetchall()}

    # Топ каналов
    cursor.execute("""
        SELECT username, COUNT(*) as cnt
        FROM analytics_events
        WHERE event_type IN ('scan_request', 'channel_view')
          AND created_at >= datetime('now', ? || ' days')
          AND username IS NOT NULL
        GROUP BY username ORDER BY cnt DESC LIMIT 10
    """, (f"-{days}",))
    top_channels = [{"username": row[0], "count": row[1]} for row in cursor.fetchall()]

    # Воронка конверсии
    cursor.execute("""
        SELECT
            COUNT(DISTINCT CASE WHEN event_type = 'app_open' THEN user_id END) as opens,
            COUNT(DISTINCT CASE WHEN event_type IN ('search_submit', 'channel_view') THEN user_id END) as browse,
            COUNT(DISTINCT CASE WHEN event_type = 'channel_detail' THEN user_id END) as detail
        FROM analytics_events
        WHERE created_at >= datetime('now', ? || ' days')
    """, (f"-{days}",))
    funnel = cursor.fetchone()

    return {
        "period_days": days,
        "dau_by_day": dau_by_day,
        "events": events,
        "top_channels": top_channels,
        "funnel": {"opens": funnel[0], "browse": funnel[1], "detail": funnel[2]} if funnel else {}
    }


# ============================================================================
# v58.0: SCAN REQUEST QUEUE
# ============================================================================

class ScanRequestCreate(BaseModel):
    username: str


class ScanRequestItem(BaseModel):
    id: int
    username: str
    status: str
    created_at: str
    processed_at: Optional[str] = None
    error: Optional[str] = None


class ScanRequestResponse(BaseModel):
    success: bool
    request_id: Optional[int] = None
    message: str


# v61.0: Путь к файлу запросов
REQUESTS_FILE = Path("/root/reklamshik/requests.json")


def _read_requests() -> list:
    """Читает requests.json."""
    if not REQUESTS_FILE.exists():
        return []
    try:
        return json.loads(REQUESTS_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        return []


def _write_requests(requests: list):
    """Записывает requests.json."""
    REQUESTS_FILE.write_text(json.dumps(requests, indent=2, ensure_ascii=False))


@app.post("/api/scan/request", response_model=ScanRequestResponse)
async def create_scan_request(scan_req: ScanRequestCreate, request: Request):
    """
    v61.0: Добавляет канал в очередь на сканирование.
    Записывает в requests.json для забора локальным краулером через SCP.
    """
    start_time = time.perf_counter()
    user_id = get_user_id_from_request(request)
    platform = request.headers.get('X-Platform', 'unknown')
    username = scan_req.username.lower().lstrip('@')

    # Валидация username
    if not USERNAME_REGEX.match(username):
        asyncio.create_task(log_analytics(
            event_type='scan_request',
            user_id=user_id,
            username=username,
            status='error',
            error_message='Invalid username format',
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            platform=platform
        ))
        return ScanRequestResponse(success=False, message="Invalid username format")

    # Проверяем не отсканирован ли уже канал (с баллами > 0)
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT score, status FROM channels WHERE LOWER(username) = ?",
        (username,)
    )
    existing = cursor.fetchone()
    if existing and existing[0] is not None and existing[0] > 0 and existing[1] in ('GOOD', 'BAD'):
        asyncio.create_task(log_analytics(
            event_type='scan_request',
            user_id=user_id,
            username=username,
            score=existing[0],
            status='already_scanned',
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            platform=platform
        ))
        return ScanRequestResponse(
            success=True,
            request_id=0,
            message=f"Channel already scanned (score: {existing[0]})"
        )

    # Читаем текущие запросы
    requests_list = _read_requests()

    # Проверяем дубликат в очереди
    existing_usernames = [r.get("username", "").lower() for r in requests_list]
    if username in existing_usernames:
        asyncio.create_task(log_analytics(
            event_type='scan_request',
            user_id=user_id,
            username=username,
            status='already_queued',
            duration_ms=int((time.perf_counter() - start_time) * 1000),
            platform=platform,
            properties={'queue_position': existing_usernames.index(username) + 1}
        ))
        return ScanRequestResponse(
            success=True,
            request_id=len(requests_list),
            message="Already in queue"
        )

    # Добавляем в очередь
    requests_list.append({
        "username": username,
        "requested_at": datetime.now().isoformat()
    })
    _write_requests(requests_list)

    asyncio.create_task(log_analytics(
        event_type='scan_request',
        user_id=user_id,
        username=username,
        status='queued',
        duration_ms=int((time.perf_counter() - start_time) * 1000),
        platform=platform,
        properties={'queue_position': len(requests_list)}
    ))

    return ScanRequestResponse(
        success=True,
        request_id=len(requests_list),
        message="Request added to queue"
    )


@app.get("/api/scan/requests")
async def get_scan_requests(limit: int = 10):
    """
    v61.0: Возвращает текущую очередь запросов из requests.json.
    """
    requests_list = _read_requests()

    return {
        "queue": requests_list[-limit:] if limit else requests_list,
        "count": len(requests_list)
    }


# v61.0: QUEUE SYNC удалён - используем requests.json файл


# ============================================================================
# v61.2: REAL-TIME CHANNEL SYNC
# ============================================================================

class ChannelSyncData(BaseModel):
    username: str
    status: str
    score: Optional[int] = None
    verdict: Optional[str] = None
    trust_factor: Optional[float] = None
    members: Optional[int] = None
    category: Optional[str] = None
    category_secondary: Optional[str] = None
    category_percent: Optional[int] = 100
    breakdown_json: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


@app.post("/api/channels/sync")
async def sync_channel(data: ChannelSyncData):
    """
    v61.2: Обновить один канал через API (real-time sync).
    Вызывается краулером после обработки каждого GOOD/BAD канала.

    Upsert: если канал существует — обновляет, иначе создаёт.
    """
    username = data.username.lower().lstrip('@')

    if not USERNAME_REGEX.match(username):
        return {"success": False, "error": "Invalid username format"}

    try:
        cursor = db.conn.cursor()
        cursor.execute("""
            INSERT INTO channels (
                username, status, score, verdict, trust_factor, members,
                category, category_secondary, category_percent,
                breakdown_json, title, description, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(username) DO UPDATE SET
                status = excluded.status,
                score = excluded.score,
                verdict = excluded.verdict,
                trust_factor = excluded.trust_factor,
                members = excluded.members,
                category = excluded.category,
                category_secondary = excluded.category_secondary,
                category_percent = excluded.category_percent,
                breakdown_json = excluded.breakdown_json,
                title = excluded.title,
                description = excluded.description,
                scanned_at = excluded.scanned_at
        """, (
            username,
            data.status,
            data.score,
            data.verdict,
            data.trust_factor,
            data.members,
            data.category,
            data.category_secondary,
            data.category_percent,
            data.breakdown_json,
            data.title,
            data.description
        ))
        db.conn.commit()
        return {"success": True, "username": username}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3002)
