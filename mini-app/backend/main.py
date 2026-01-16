"""
Reklamshik API - FastAPI backend для Mini App.
Использует существующий scanner для анализа каналов.
"""

import os
import sys
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

# Добавляем путь к scanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

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


class ScanRequest(BaseModel):
    channel: str


class ScanResponse(BaseModel):
    channel: str
    score: int
    verdict: str
    trust_factor: float
    members: int
    category: Optional[str] = None
    categories: dict
    breakdown: dict


# Глобальные переменные
db = None
pyrogram_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запуск и остановка приложения."""
    global db, pyrogram_client

    # Импортируем scanner модули
    from scanner.database import CrawlerDB

    # Инициализация БД
    db_path = os.getenv("DATABASE_PATH", "crawler.db")
    db = CrawlerDB(db_path)
    print(f"База данных подключена: {db_path}")

    # Pyrogram клиент - только если есть credentials
    api_id = os.getenv("API_ID", "")
    if api_id and api_id != "your_api_id":
        try:
            from scanner.client import get_client
            pyrogram_client = get_client()
            print("Pyrogram клиент инициализирован (live scan доступен)")
        except Exception as e:
            print(f"Pyrogram клиент не доступен: {e}")
            pyrogram_client = None
    else:
        print("Pyrogram клиент не настроен (только чтение из базы)")
        pyrogram_client = None

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

# CORS для Mini App (allow all origins for Telegram WebView)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# v13.0: Многоуровневые мультипликаторы на основе ВСЕХ метрик
# =============================================================================

def get_size_mult(size_k: float) -> float:
    """Нелинейный коэффициент размера канала."""
    if size_k <= 1:
        return 1.2   # Микро-каналы: премиум за эксклюзивность
    elif size_k <= 5:
        return 1.0   # Малые: стандарт
    elif size_k <= 20:
        return 0.85  # Средние: небольшая скидка
    elif size_k <= 50:
        return 0.7   # Большие: скидка за объём
    elif size_k <= 100:
        return 0.55  # Крупные: значительная скидка
    else:
        return 0.4   # Огромные: максимальная скидка


def calculate_quality_mult(breakdown: dict) -> float:
    """
    v13.0: Мультипликатор качества на основе breakdown.quality.
    Использует реальные метрики вместо просто score.

    Калибровка v13.1: уменьшены коэффициенты для реалистичных цен.
    Returns:
        float: 0.7 - 1.5+ (с бонусами до ~1.8)
    """
    if not breakdown:
        return 1.0

    quality = breakdown.get('quality', {})
    q_total = quality.get('total', 20)
    q_max = quality.get('max', 40)

    if q_max == 0:
        return 1.0

    q_pct = q_total / q_max  # 0.0 - 1.0

    # Базовый множитель: 0.7x - 1.5x (откалибровано)
    quality_mult = 0.7 + q_pct * 0.8

    # БОНУСЫ за отдельные метрики (уменьшены)
    items = quality.get('items', {})

    # CV Views: стабильные просмотры = +5%
    cv = items.get('cv_views', {})
    if cv.get('max', 0) > 0 and cv.get('score', 0) >= cv.get('max', 15) * 0.8:
        quality_mult *= 1.05

    # Reach: высокий охват = +7%
    reach = items.get('reach', {})
    if reach.get('max', 0) > 0 and reach.get('score', 0) >= reach.get('max', 10) * 0.8:
        quality_mult *= 1.07

    # Forward Rate: виральность = +8%
    forward = items.get('forward_rate', {})
    if forward.get('max', 0) > 0 and forward.get('score', 0) >= forward.get('max', 5) * 0.8:
        quality_mult *= 1.08

    # v20.0: Posting: хорошая частота постинга = +5%
    posting = items.get('posting', {})
    if posting.get('max', 0) > 0 and posting.get('score', 0) >= posting.get('max', 5) * 0.8:
        quality_mult *= 1.05

    return round(quality_mult, 3)


def calculate_engagement_mult(breakdown: dict) -> float:
    """
    v13.0: Мультипликатор вовлечённости на основе breakdown.engagement.
    Вовлечённость = главный показатель для рекламодателей.

    Калибровка v13.1: уменьшены коэффициенты для реалистичных цен.
    Returns:
        float: 0.7 - 1.5+ (с бонусами до ~1.8)
    """
    if not breakdown:
        return 1.0

    engagement = breakdown.get('engagement', {})
    e_total = engagement.get('total', 20)
    e_max = engagement.get('max', 40)

    if e_max == 0:
        return 1.0

    e_pct = e_total / e_max  # 0.0 - 1.0

    # Базовый множитель: 0.7x - 1.5x (откалибровано)
    engagement_mult = 0.7 + e_pct * 0.8

    items = engagement.get('items', {})

    # Комментарии активны = +10%
    comments = items.get('comments', {})
    if comments.get('max', 0) > 0 and comments.get('score', 0) >= comments.get('max', 15) * 0.6:
        engagement_mult *= 1.10

    # Высокий reaction rate = +7%
    reactions = items.get('reaction_rate', {})
    if reactions.get('max', 0) > 0 and reactions.get('score', 0) >= reactions.get('max', 15) * 0.7:
        engagement_mult *= 1.07

    # Разнообразие ER (не ботовый паттерн) = +5%
    variation = items.get('er_variation', {})
    if variation.get('max', 0) > 0 and variation.get('score', 0) >= variation.get('max', 5) * 0.8:
        engagement_mult *= 1.05

    return round(engagement_mult, 3)


def calculate_reputation_mult(breakdown: dict) -> float:
    """
    v13.0: Мультипликатор репутации на основе breakdown.reputation.
    Верификация, возраст, премиумы = доверие рекламодателей.

    Калибровка v13.1: уменьшены коэффициенты для реалистичных цен.
    Returns:
        float: 0.9 - 1.3+ (с бонусами до ~1.6)
    """
    if not breakdown:
        return 1.0

    reputation = breakdown.get('reputation', {})
    r_total = reputation.get('total', 10)
    r_max = reputation.get('max', 20)

    if r_max == 0:
        return 1.0

    r_pct = r_total / r_max  # 0.0 - 1.0

    # Базовый множитель: 0.9x - 1.3x (откалибровано)
    reputation_mult = 0.9 + r_pct * 0.4

    items = reputation.get('items', {})

    # ВЕРИФИКАЦИЯ = +20% премиум (откалибровано с +50%)
    verified = items.get('verified', {})
    if verified.get('max', 0) > 0 and verified.get('score', 0) == verified.get('max', 4):
        reputation_mult *= 1.20

    # Возраст >2 лет = +8%
    age = items.get('age', {})
    if age.get('score', 0) >= 4:  # established/veteran
        reputation_mult *= 1.08

    # Premium users >5% = +5%
    premium = items.get('premium', {})
    if premium.get('score', 0) >= 4:
        reputation_mult *= 1.05

    # Оригинальный контент = +5%
    source = items.get('source', {})
    if source.get('max', 0) > 0 and source.get('score', 0) >= source.get('max', 4) * 0.8:
        reputation_mult *= 1.05

    # v20.0: Чистые связи (нет SCAM, мало приватных) = +5%
    links = items.get('links', {})
    if links.get('max', 0) > 0 and links.get('score', 0) >= links.get('max', 4) * 0.8:
        reputation_mult *= 1.05

    return round(reputation_mult, 3)


def calculate_trust_mult(trust_factor: float, trust_penalties: list = None) -> float:
    """
    v13.0: Детализированный мультипликатор доверия.
    Некоторые нарушения критичнее для цены чем другие.

    Returns:
        float: 0.1 - 1.0
    """
    trust_mult = trust_factor  # Базовый 0.0-1.0

    # Дополнительные штрафы по типу нарушения
    if trust_penalties:
        for penalty in trust_penalties:
            name = penalty.get('name', '').lower()

            # Критические нарушения - дополнительный штраф
            if 'накрутка' in name or 'боты' in name or 'критический' in name:
                trust_mult *= 0.7  # Дополнительно -30%
            elif 'спам' in name or 'реклама' in name:
                trust_mult *= 0.8  # Дополнительно -20%

    return max(0.1, round(trust_mult, 3))  # Минимум 10%


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
    trust_penalties: list = None
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

    # Оцениваем средние просмотры
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
    trust_penalties: list = None
) -> dict:
    """
    v15.0: CPM-based расчёт с деталями для UI.
    ВСЕГДА возвращает dict (никогда None).
    """
    # Нормализуем категорию
    category = normalize_category(category)
    rates = CPM_RATES[category]

    # Оцениваем средние просмотры
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
    v22.1: Оценивает детальный breakdown метрик на основе итогового score.

    Используется как fallback когда нет breakdown_json в БД.
    Ключи должны совпадать с METRIC_CONFIG в format_breakdown_for_ui().

    - Quality (35 max): cv_views, reach, views_decay, forward_rate
    - Engagement (40 max): comments, reaction_rate, er_variation, reaction_stability
    - Reputation (16 max): verified, age, premium, source_diversity
    """
    # Raw score до trust factor
    raw_score = score / trust_factor if trust_factor > 0 else score
    raw_score = min(100, raw_score)

    # Процент от максимума (приблизительно)
    pct = raw_score / 100

    # v22.1: Ключи совпадают с METRIC_CONFIG и scorer.py
    weights = {
        'quality': {
            'cv_views': {'max': 13, 'label': 'CV просмотров'},
            'reach': {'max': 10, 'label': 'Охват'},
            'views_decay': {'max': 7, 'label': 'Стабильность'},
            'forward_rate': {'max': 5, 'label': 'Репосты'},
        },
        'engagement': {
            'comments': {'max': 15, 'label': 'Комментарии'},
            'reaction_rate': {'max': 15, 'label': 'Реакции'},
            'er_variation': {'max': 5, 'label': 'Разнообразие'},
            'reaction_stability': {'max': 5, 'label': 'Стабильность ER'},
        },
        'reputation': {
            'verified': {'max': 4, 'label': 'Верификация'},
            'age': {'max': 4, 'label': 'Возраст'},
            'premium': {'max': 4, 'label': 'Премиумы'},
            'source_diversity': {'max': 4, 'label': 'Оригинальность'},
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


def format_breakdown_for_ui(breakdown_data: dict) -> dict:
    """
    v23.0: Преобразует реальный breakdown из scorer.py в формат для UI.

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
    """
    breakdown = breakdown_data.get('breakdown', {})
    categories = breakdown_data.get('categories', {})

    # v23.0: KEY_MAPPING для совместимости со старыми данными
    KEY_MAPPING = {
        'stability': 'reaction_stability',
        'source': 'source_diversity',
    }

    # v23.0: Маппинг метрик в категории с labels (Score Metrics - имеют points/max)
    METRIC_CONFIG = {
        'quality': {
            'cv_views': 'CV просмотров',
            'reach': 'Охват',
            'views_decay': 'Стабильность',
            'forward_rate': 'Репосты',
        },
        'engagement': {
            'comments': 'Комментарии',
            'reaction_rate': 'Реакции',
            'er_variation': 'Разнообразие',
            'reaction_stability': 'Стабильность ER',
        },
        'reputation': {
            'verified': 'Верификация',
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
            # v23.0: Применяем KEY_MAPPING для совместимости
            source_key = metric_key
            for old_key, new_key in KEY_MAPPING.items():
                if new_key == metric_key and old_key in breakdown:
                    source_key = old_key
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
                elif isinstance(raw_value, float):
                    value = f"{raw_value:.1f}%"

            item_data = {
                'score': score_val,
                'max': max_val,
                'label': label,
            }
            if value:
                item_data['value'] = value

            items[metric_key] = item_data
            calculated_max += max_val  # v22.2: Суммируем max каждого item

        # v23.0: Обрабатываем Info Metrics для этой категории
        info_metrics = {}
        cat_info_config = INFO_METRICS_CONFIG.get(cat_key, {})

        for info_key, config in cat_info_config.items():
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
            'max': calculated_max,  # v22.2: Используем сумму из items, НЕ fallback
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
        quality_pct = (breakdown['quality']['total'] / breakdown['quality']['max']) * 100 if breakdown.get('quality') else 0
        engagement_pct = (breakdown['engagement']['total'] / breakdown['engagement']['max']) * 100 if breakdown.get('engagement') else 0
        reputation_pct = (breakdown['reputation']['total'] / breakdown['reputation']['max']) * 100 if breakdown.get('reputation') else 0

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


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


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

    # Base WHERE clause
    where_clause = """
        WHERE status = 'GOOD'
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

    # Main query
    query = f"""
        SELECT username, score, verdict, trust_factor, members,
               category, category_secondary, scanned_at, photo_url, category_percent
        FROM channels {where_clause}
    """

    # Add sorting and pagination
    query += f" ORDER BY {sort_by} {'DESC' if sort_order == 'desc' else 'ASC'}"
    query += f" LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])

    cursor = db.conn.execute(query, params)
    rows = cursor.fetchall()

    channels = []
    for row in rows:
        score = safe_int(row[1], 0)
        trust_factor = safe_float(row[3], 1.0)
        members = safe_int(row[4], 0)
        category = row[5]

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
        ))

    return ChannelListResponse(
        channels=channels,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@app.get("/api/channels/{username}")
async def get_channel(username: str):
    """
    Получить детали канала по username.
    Если канала нет в базе - вернуть 404.

    v23.0: Читает реальный breakdown_json из БД если доступен,
    иначе использует estimate_breakdown() как fallback.
    Поддержка Info Metrics (ad_load, regularity, posting_frequency, private_links).
    """
    username = username.lower().lstrip("@")

    # v23.0: Читаем breakdown_json из БД (если колонка существует)
    # Используем try/except для совместимости с БД без колонки breakdown_json
    try:
        cursor = db.conn.execute("""
            SELECT username, score, verdict, trust_factor, members,
                   category, category_secondary, scanned_at, status,
                   photo_url, breakdown_json
            FROM channels
            WHERE username = ?
        """, (username,))
    except Exception:
        # Fallback для старых БД без колонки breakdown_json
        cursor = db.conn.execute("""
            SELECT username, score, verdict, trust_factor, members,
                   category, category_secondary, scanned_at, status
            FROM channels
            WHERE username = ?
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
    breakdown_json_str = row[10] if len(row) > 10 else None
    photo_url = row[9] if len(row) > 9 else None

    # Парсим breakdown_json или используем fallback
    real_breakdown_data = None
    if breakdown_json_str:
        try:
            real_breakdown_data = json.loads(breakdown_json_str)
        except (json.JSONDecodeError, TypeError):
            real_breakdown_data = None

    # v23.0: Если есть реальный breakdown - форматируем его для UI
    # Иначе используем estimate_breakdown() как fallback
    if real_breakdown_data and real_breakdown_data.get('breakdown'):
        breakdown = format_breakdown_for_ui(real_breakdown_data)
        breakdown_source = "database"
    else:
        breakdown = estimate_breakdown(score, trust_factor)
        breakdown_source = "estimated"

    # v7.0: Trust penalties (риски)
    trust_penalties = estimate_trust_penalties(trust_factor, score)

    # v13.0: Рассчитываем цену с ВСЕМИ мультипликаторами
    price_min, price_max = calculate_post_price(
        category, members, trust_factor, score,
        breakdown=breakdown,
        trust_penalties=trust_penalties
    )

    # v13.0: Детальная структура price_estimate с ВСЕМИ мультипликаторами
    price_estimate = calculate_post_price_details(
        category, members, trust_factor, score,
        breakdown=breakdown,
        trust_penalties=trust_penalties
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

    return {
        "username": str(row[0]) if row[0] else "",
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
    }


@app.post("/api/channels/{username}/scan", response_model=ScanResponse)
async def scan_channel(username: str):
    """
    Сканировать канал на лету.
    Использует Pyrogram для получения данных и scorer для анализа.
    """
    if pyrogram_client is None:
        raise HTTPException(
            status_code=503,
            detail="Live scan недоступен. Telegram API не настроен."
        )

    username = username.lower().lstrip("@")

    try:
        from scanner.client import smart_scan_safe
        from scanner.scorer import calculate_final_score

        # Запускаем клиент если не запущен
        if not pyrogram_client.is_connected:
            await pyrogram_client.start()

        # Сканируем
        scan_result = await smart_scan_safe(pyrogram_client, username)

        if scan_result.chat is None:
            error_reason = scan_result.channel_health.get("reason", "Канал не найден")
            raise HTTPException(status_code=400, detail=error_reason)

        # Считаем score
        result = calculate_final_score(
            scan_result.chat,
            scan_result.messages,
            scan_result.comments_data,
            scan_result.users,
            scan_result.channel_health
        )

        return ScanResponse(
            channel=username,
            score=result.get("score", 0),
            verdict=result.get("verdict", ""),
            trust_factor=result.get("trust_factor", 1.0),
            members=result.get("members", 0),
            category=result.get("category"),
            categories=result.get("categories", {}),
            breakdown=result.get("breakdown", {}),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3002)
