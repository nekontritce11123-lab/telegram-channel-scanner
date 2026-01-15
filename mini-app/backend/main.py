"""
Reklamshik API - FastAPI backend для Mini App.
Использует существующий scanner для анализа каналов.
"""

import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

# Добавляем путь к scanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

# v7.0: Цена за 1000 подписчиков (калибровка по реальным данным)
# Пример: канал 950 subs, score 82, крипто = ~3000₽ ($30)
# Формула: BASE_PER_1K * size_k * size_mult * quality_mult * trust_factor
BASE_PER_1K = {
    "CRYPTO": {"min": 800, "max": 1500},       # Крипто - премиум
    "FINANCE": {"min": 600, "max": 1200},      # Финансы
    "REAL_ESTATE": {"min": 500, "max": 1000},  # Недвижимость
    "BUSINESS": {"min": 500, "max": 1000},     # Бизнес
    "TECH": {"min": 700, "max": 1400},         # Технологии
    "AI_ML": {"min": 600, "max": 1200},        # ИИ/ML
    "EDUCATION": {"min": 300, "max": 600},     # Образование
    "BEAUTY": {"min": 250, "max": 500},        # Красота
    "HEALTH": {"min": 200, "max": 400},        # Здоровье
    "TRAVEL": {"min": 200, "max": 400},        # Путешествия
    "RETAIL": {"min": 150, "max": 300},        # Ритейл
    "ENTERTAINMENT": {"min": 50, "max": 100},  # Развлечения
    "NEWS": {"min": 100, "max": 200},          # Новости
    "LIFESTYLE": {"min": 150, "max": 300},     # Лайфстайл
    "GAMBLING": {"min": 400, "max": 800},      # Азартные игры
    "ADULT": {"min": 300, "max": 600},         # Взрослый контент
    "OTHER": {"min": 100, "max": 200},         # Другое
}

# Legacy POST_PRICES для обратной совместимости (get_cpm_range)
POST_PRICES = {
    "CRYPTO": {"min": 5000, "max": 12000},
    "FINANCE": {"min": 3000, "max": 8000},
    "REAL_ESTATE": {"min": 4000, "max": 7000},
    "BUSINESS": {"min": 3000, "max": 8000},
    "TECH": {"min": 10000, "max": 16200},
    "AI_ML": {"min": 8000, "max": 15000},
    "EDUCATION": {"min": 1500, "max": 3000},
    "BEAUTY": {"min": 1500, "max": 2500},
    "HEALTH": {"min": 1000, "max": 2000},
    "TRAVEL": {"min": 800, "max": 1500},
    "RETAIL": {"min": 500, "max": 1200},
    "ENTERTAINMENT": {"min": 100, "max": 300},
    "NEWS": {"min": 200, "max": 400},
    "LIFESTYLE": {"min": 500, "max": 1500},
    "GAMBLING": {"min": 3000, "max": 10000},
    "ADULT": {"min": 2000, "max": 5000},
    "OTHER": {"min": 300, "max": 1000},
}


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


def calculate_post_price(
    category: Optional[str],
    members: int,
    trust_factor: float = 1.0,
    score: int = 50
) -> tuple:
    """
    v7.0: Рассчитывает реальную цену за пост.
    Калибровка: 950 subs, score 82, крипто = ~3000₽ ($30)

    Формула: BASE_PER_1K * size_k * size_mult * quality_mult * trust_factor

    size_mult - нелинейный коэффициент:
      - Микро-каналы (<1K): премиум за эксклюзивность
      - Малые (1-5K): высокий engagement
      - Средние (5-50K): стандарт
      - Большие (50K+): скидка за объём

    quality_mult - экспоненциальный рост от качества:
      - Score 50 = 1.0x
      - Score 80 = 2.5x
      - Score 100 = 4.0x
    """
    if not category or category not in BASE_PER_1K:
        return None, None

    base = BASE_PER_1K[category]
    base_min, base_max = base["min"], base["max"]

    # Размер канала в тысячах
    size_k = members / 1000

    # Нелинейный коэффициент размера
    if size_k <= 1:
        size_mult = 1.2   # Микро-каналы: небольшой премиум
    elif size_k <= 5:
        size_mult = 1.0   # Малые: стандарт
    elif size_k <= 20:
        size_mult = 0.85  # Средние: небольшая скидка
    elif size_k <= 50:
        size_mult = 0.7   # Большие: скидка за объём
    elif size_k <= 100:
        size_mult = 0.55  # Крупные: значительная скидка
    else:
        size_mult = 0.4   # Огромные: максимальная скидка

    # Коэффициент качества (экспоненциальный рост)
    # Score 50 = 1.0, Score 80 = 2.5, Score 100 = 4.0
    score_normalized = score / 100
    quality_mult = 0.5 + (score_normalized ** 1.5) * 3.5

    # Итоговая цена
    price_min = int(base_min * size_k * size_mult * quality_mult * trust_factor)
    price_max = int(base_max * size_k * size_mult * quality_mult * trust_factor)

    # Минимальная цена 300₽
    price_min = max(300, price_min)
    price_max = max(500, price_max)

    return price_min, price_max


def get_cpm_range(category: Optional[str]) -> tuple:
    """Возвращает базовый диапазон цен для категории (для обратной совместимости)."""
    if not category or category not in POST_PRICES:
        return None, None
    r = POST_PRICES[category]
    return r["min"], r["max"]


def estimate_breakdown(score: int, trust_factor: float = 1.0) -> dict:
    """
    v7.0: Оценивает детальный breakdown метрик на основе итогового score.

    Поскольку детальные метрики не хранятся в БД, делаем обоснованную оценку:
    - Quality (40 max): 40% от total
    - Engagement (40 max): 40% от total
    - Reputation (20 max): 20% от total

    Внутри категорий распределяем пропорционально весам.
    """
    # Raw score до trust factor
    raw_score = score / trust_factor if trust_factor > 0 else score
    raw_score = min(100, raw_score)

    # Процент от максимума (приблизительно)
    pct = raw_score / 100

    # Детальные веса из scorer.py
    weights = {
        'quality': {
            'cv_views': {'max': 15, 'label': 'CV просмотров'},
            'reach': {'max': 10, 'label': 'Охват'},
            'views_decay': {'max': 8, 'label': 'Стабильность'},
            'forward_rate': {'max': 7, 'label': 'Репосты'},
        },
        'engagement': {
            'comments': {'max': 15, 'label': 'Комментарии'},
            'reaction_rate': {'max': 15, 'label': 'Реакции'},
            'er_variation': {'max': 5, 'label': 'Разнообразие'},
            'stability': {'max': 5, 'label': 'Стабильность ER'},
        },
        'reputation': {
            'verified': {'max': 5, 'label': 'Верификация'},
            'age': {'max': 5, 'label': 'Возраст'},
            'premium': {'max': 5, 'label': 'Премиумы'},
            'source': {'max': 5, 'label': 'Оригинальность'},
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

    # 1. Ценовая рекомендация с контекстом
    if cpm_min and cpm_max:
        category_name = {
            "CRYPTO": "Крипто", "FINANCE": "Финансы", "TECH": "Tech",
            "AI_ML": "AI/ML", "BUSINESS": "Бизнес", "NEWS": "Новости",
            "ENTERTAINMENT": "Развлечения", "EDUCATION": "Образование"
        }.get(category, category or "")

        members_str = f"{members // 1000}K" if members >= 1000 else str(members)
        recs.append(Recommendation(
            type="cpm",
            icon="💰",
            text=f"Цена за пост: {cpm_min:,}-{cpm_max:,}₽ • {category_name} • {members_str} подп."
        ))

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
               category, category_secondary, scanned_at, photo_url
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

        # Рассчитываем реальную цену за пост
        price_min, price_max = calculate_post_price(category, members, trust_factor, score)

        channels.append(ChannelSummary(
            username=str(row[0]) if row[0] else "",
            score=score,
            verdict=str(row[2]) if row[2] else "",
            trust_factor=trust_factor,
            members=members,
            category=category,
            category_secondary=row[6],
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
    """
    username = username.lower().lstrip("@")

    cursor = db.conn.execute("""
        SELECT username, score, verdict, trust_factor, members,
               category, category_secondary, scanned_at, status, photo_url
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

    # Рассчитываем реальную цену за пост
    price_min, price_max = calculate_post_price(category, members, trust_factor, score)

    # v7.0: Детальный breakdown метрик
    breakdown = estimate_breakdown(score, trust_factor)

    # v7.0: Trust penalties (риски)
    trust_penalties = estimate_trust_penalties(trust_factor, score)

    # v7.0: Структура price_estimate
    size_k = members / 1000
    if size_k <= 1:
        size_mult = 1.2
    elif size_k <= 5:
        size_mult = 1.0
    elif size_k <= 20:
        size_mult = 0.85
    elif size_k <= 50:
        size_mult = 0.7
    elif size_k <= 100:
        size_mult = 0.55
    else:
        size_mult = 0.4

    score_normalized = score / 100
    quality_mult = 0.5 + (score_normalized ** 1.5) * 3.5

    price_estimate = {
        "min": price_min,
        "max": price_max,
        "base_price": BASE_PER_1K.get(category, {"min": 100})["min"] if category else 100,
        "size_mult": round(size_mult, 2),
        "quality_mult": round(quality_mult, 2),
        "trust_mult": round(trust_factor, 2),
    }

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
        "category_secondary": row[6],
        "scanned_at": str(row[7]) if row[7] else None,
        "status": row[8],
        "photo_url": str(row[9]) if row[9] else None,
        "cpm_min": price_min,
        "cpm_max": price_max,
        "recommendations": [r.dict() for r in recommendations],
        "source": "database",
        # v7.0: Новые поля
        "breakdown": breakdown,
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
        cpm = POST_PRICES.get(cat, {"min": 0, "max": 0})
        categories.append(CategoryStat(
            category=cat,
            count=count,
            cpm_min=cpm["min"],
            cpm_max=cpm["max"],
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
