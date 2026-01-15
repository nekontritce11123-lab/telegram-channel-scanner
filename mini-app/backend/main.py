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

# CPM справочник по категориям
CPM_RANGES = {
    "CRYPTO": {"min": 2000, "max": 7000},
    "FINANCE": {"min": 2000, "max": 5000},
    "REAL_ESTATE": {"min": 2000, "max": 4000},
    "BUSINESS": {"min": 1500, "max": 3500},
    "TECH": {"min": 1000, "max": 2000},
    "AI_ML": {"min": 1000, "max": 2000},
    "EDUCATION": {"min": 700, "max": 1200},
    "BEAUTY": {"min": 700, "max": 1200},
    "HEALTH": {"min": 700, "max": 1200},
    "TRAVEL": {"min": 700, "max": 1200},
    "RETAIL": {"min": 500, "max": 1000},
    "ENTERTAINMENT": {"min": 100, "max": 500},
    "NEWS": {"min": 100, "max": 500},
    "LIFESTYLE": {"min": 100, "max": 500},
    "GAMBLING": {"min": 500, "max": 2000},
    "ADULT": {"min": 300, "max": 1000},
    "OTHER": {"min": 200, "max": 800},
}


# Pydantic models
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


def get_cpm_range(category: Optional[str]) -> tuple:
    """Возвращает CPM диапазон для категории."""
    if not category or category not in CPM_RANGES:
        return None, None
    r = CPM_RANGES[category]
    return r["min"], r["max"]


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
    sort_by: str = Query("score", regex="^(score|members|scanned_at)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Получить список каналов с фильтрацией и пагинацией.
    """
    params = [min_score, max_score, min_members, max_members]

    # Base WHERE clause
    where_clause = """
        WHERE status = 'GOOD'
          AND score >= ? AND score <= ?
          AND members >= ? AND members <= ?
    """

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
               category, category_secondary, scanned_at
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
        cpm_min, cpm_max = get_cpm_range(row[5])
        channels.append(ChannelSummary(
            username=str(row[0]) if row[0] else "",
            score=safe_int(row[1], 0),
            verdict=str(row[2]) if row[2] else "",
            trust_factor=safe_float(row[3], 1.0),
            members=safe_int(row[4], 0),
            category=row[5],
            category_secondary=row[6],
            scanned_at=str(row[7]) if row[7] else None,
            cpm_min=cpm_min,
            cpm_max=cpm_max,
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
               category, category_secondary, scanned_at, status
        FROM channels
        WHERE username = ?
    """, (username,))

    row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Канал не найден в базе")

    cpm_min, cpm_max = get_cpm_range(row[5])

    return {
        "username": str(row[0]) if row[0] else "",
        "score": safe_int(row[1], 0),
        "verdict": str(row[2]) if row[2] else "",
        "trust_factor": safe_float(row[3], 1.0),
        "members": safe_int(row[4], 0),
        "category": row[5],
        "category_secondary": row[6],
        "scanned_at": str(row[7]) if row[7] else None,
        "status": row[8],
        "cpm_min": cpm_min,
        "cpm_max": cpm_max,
        "source": "database",
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
        cpm = CPM_RANGES.get(cat, {"min": 0, "max": 0})
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
    uvicorn.run(app, host="0.0.0.0", port=3001)
