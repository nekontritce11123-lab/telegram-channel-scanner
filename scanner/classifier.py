"""
AI Классификатор тем Telegram каналов.
v14.0: Процентная классификация без fallback keywords

Архитектура:
  - 17 категорий на основе анализа рынка рекламы
  - Multi-label: основная + вторичная категория с процентами
  - Формат ответа: "CATEGORY:PERCENT" или "CAT1:PCT1+CAT2:PCT2"
  - Groq API + Llama 3.3 70B
  - Без fallback keywords (убраны false positives)
  - Кэширование результатов на 7 дней
"""

import os
import json
import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import deque

# Для HTTP запросов к Groq
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("httpx не установлен. pip install httpx")

from dotenv import load_dotenv


# === КОНФИГУРАЦИЯ ===

CATEGORIES = [
    # Премиальные (CPM 2000-7000₽)
    "CRYPTO",        # криптовалюты, DeFi, NFT, Web3, трейдинг
    "FINANCE",       # акции, инвестиции, форекс, банки (НЕ крипта)
    "REAL_ESTATE",   # недвижимость, ипотека, риэлторы
    "BUSINESS",      # B2B-услуги, SaaS, консалтинг, стартапы

    # Технологии (CPM 1000-2000₽)
    "TECH",          # программирование, IT, гаджеты, DevOps
    "AI_ML",         # нейросети, ML, ChatGPT, Data Science

    # Образование и развитие (CPM 700-1200₽)
    "EDUCATION",     # курсы, обучение, онлайн-школы
    "BEAUTY",        # косметика, парфюмерия, салоны красоты
    "HEALTH",        # фитнес, медицина, ЗОЖ, диетология
    "TRAVEL",        # туризм, авиа, отели, путешествия

    # Коммерция (CPM 500-1000₽)
    "RETAIL",        # магазины, e-commerce, товары

    # Контент (CPM 100-500₽)
    "ENTERTAINMENT", # игры, кино, музыка, мемы, юмор
    "NEWS",          # новости, политика, события
    "LIFESTYLE",     # личные блоги, лайфстайл

    # Высокий риск
    "GAMBLING",      # ставки, казино
    "ADULT",         # 18+ контент

    # Fallback
    "OTHER",         # не подходит ни под что
]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # Updated: old model decommissioned
API_TIMEOUT = 10  # секунд
CACHE_TTL_DAYS = 7
MAX_POSTS_FOR_AI = 10
MAX_CHARS_PER_POST = 500


# === СИСТЕМНЫЙ ПРОМПТ v14.0 ===

SYSTEM_PROMPT = """You are a Telegram channel topic classifier.
Analyze the channel and return categories WITH PERCENTAGES.

FORMAT: CATEGORY:PERCENT or CATEGORY1:PERCENT1+CATEGORY2:PERCENT2
Percentages must sum to 100.

EXAMPLES:
- Pure crypto channel: "CRYPTO:100"
- Crypto memes: "ENTERTAINMENT:70+CRYPTO:30"
- Tech news: "TECH:60+NEWS:40"
- Gaming channel: "ENTERTAINMENT:100"

CATEGORIES:
- CRYPTO: cryptocurrency, DeFi, NFT, Web3, blockchain, Bitcoin, Ethereum, trading signals
- FINANCE: stocks, investing, forex, banks, economics (NOT crypto!)
- REAL_ESTATE: property, mortgages, apartments, real estate agents
- BUSINESS: B2B services, SaaS, consulting, startups, entrepreneurs
- TECH: programming, IT, gadgets, DevOps, software development
- AI_ML: neural networks, ML, ChatGPT, LLM, Data Science
- EDUCATION: courses, tutorials, learning, online schools
- BEAUTY: cosmetics, makeup, skincare, beauty salons
- HEALTH: fitness, medicine, wellness, diet, sports
- TRAVEL: tourism, hotels, flights, travel guides
- RETAIL: e-commerce, shops, products, delivery
- ENTERTAINMENT: games, movies, music, memes, humor, streaming, TON games, P2E
- NEWS: news, politics, current events
- LIFESTYLE: personal blogs, diary, thoughts
- GAMBLING: betting, casinos, poker
- ADULT: 18+ content
- OTHER: does not fit any category

RULES:
1. ALWAYS return percentages (e.g., "TECH:100" not just "TECH")
2. Use + for mixed content: "ENTERTAINMENT:70+CRYPTO:30"
3. Percentages MUST sum to 100
4. Max 2 categories per channel
5. ANALYZE TONE: memes about crypto = ENTERTAINMENT+CRYPTO, not just CRYPTO
6. "TON games", "play to earn", "P2E" = ENTERTAINMENT, not CRYPTO
7. If >80% one topic, use single category: "CRYPTO:100"
8. If truly unclear, return "OTHER:100\""""


# === КЭШИРОВАНИЕ ===

CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_FILE = CACHE_DIR / "classifier_cache.json"


def _load_cache() -> dict:
    """Загружает кэш из файла."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    """Сохраняет кэш в файл."""
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения кэша: {e}")


def _get_cached(channel_id: int, cache: dict) -> Optional[str]:
    """Проверяет кэш на наличие категории."""
    key = str(channel_id)
    if key not in cache:
        return None

    entry = cache[key]
    cached_at = datetime.fromisoformat(entry.get("cached_at", "2000-01-01"))
    if datetime.now() - cached_at > timedelta(days=CACHE_TTL_DAYS):
        return None  # Кэш устарел

    return entry.get("category")


def _set_cached(channel_id: int, category: str, cache: dict):
    """Добавляет категорию в кэш."""
    cache[str(channel_id)] = {
        "category": category,
        "cached_at": datetime.now().isoformat()
    }


# === ПОДГОТОВКА ДАННЫХ ===

def _clean_text(text: str) -> str:
    """Очищает текст от ссылок и лишнего."""
    if not text:
        return ""

    # Убираем ссылки
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r't\.me/\S+', '', text)

    # Убираем множественные emoji (оставляем одиночные)
    text = re.sub(r'[\U0001F600-\U0001F64F]{3,}', '', text)
    text = re.sub(r'[\U0001F300-\U0001F5FF]{3,}', '', text)

    # Убираем множественные переносы строк
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _prepare_context(title: str, description: str, messages: list) -> str:
    """Формирует контекст для LLM."""
    parts = []

    # Название
    if title:
        parts.append(f"Channel name: {title[:256]}")

    # Описание
    if description:
        clean_desc = _clean_text(description)[:1000]
        if clean_desc:
            parts.append(f"Description: {clean_desc}")

    # Посты
    posts_text = []
    for msg in messages[:MAX_POSTS_FOR_AI]:
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text

        if text:
            clean = _clean_text(text)[:MAX_CHARS_PER_POST]
            if clean and len(clean) > 20:  # Игнорируем слишком короткие
                posts_text.append(f"- {clean}")

    if posts_text:
        parts.append("Recent posts:\n" + "\n".join(posts_text[:10]))

    return "\n\n".join(parts)


# === ПАРСИНГ ОТВЕТА LLM v14.0 ===

def parse_category_response(response: str) -> tuple:
    """
    Парсит ответ LLM с процентами.
    Input: "ENTERTAINMENT:70+CRYPTO:30" или "TECH:100"
    Output: ("ENTERTAINMENT", "CRYPTO", 70) или ("TECH", None, 100)
    """
    response = response.strip().upper()

    # Паттерн: CATEGORY:PERCENT+CATEGORY:PERCENT
    pattern = r'([A-Z_]+):(\d+)(?:\+([A-Z_]+):(\d+))?'
    match = re.match(pattern, response)

    if match:
        cat1 = match.group(1)
        pct1 = int(match.group(2))
        cat2 = match.group(3)
        pct2 = int(match.group(4)) if match.group(4) else 0

        if cat1 not in CATEGORIES:
            cat1 = "OTHER"
        if cat2 and cat2 not in CATEGORIES:
            cat2 = None
            pct1 = 100

        return (cat1, cat2, pct1)

    # Legacy: "CAT+CAT" без процентов
    if "+" in response:
        parts = response.split("+")
        cat1 = parts[0].strip()
        cat2 = parts[1].strip() if len(parts) > 1 else None
        if cat1 in CATEGORIES:
            if cat2 and cat2 in CATEGORIES:
                return (cat1, cat2, 50)
            return (cat1, None, 100)

    # Просто категория без процентов
    if response in CATEGORIES:
        return (response, None, 100)

    # Пытаемся найти категорию в ответе
    for cat in CATEGORIES:
        if cat in response:
            return (cat, None, 100)

    return ("OTHER", None, 100)


# === FALLBACK КЛАССИФИКАЦИЯ ===

def classify_fallback(title: str, description: str, messages: list) -> str:
    """
    v14.0: Fallback без ключевых слов.
    Если API недоступен - просто возвращаем OTHER.
    LLM достаточно умный, ключевые слова создают false positives.
    """
    return "OTHER"


# === GROQ API ===

async def _call_groq_api(context: str, api_key: str) -> Optional[str]:
    """Отправляет запрос к Groq API."""
    if not HTTPX_AVAILABLE:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify this channel:\n\n{context}\n\nCategory:"}
        ],
        "temperature": 0,
        "max_tokens": 20
    }

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            response = await client.post(GROQ_API_URL, headers=headers, json=payload)

            if response.status_code == 429:
                return None  # Rate limit

            response.raise_for_status()
            data = response.json()

            answer = data["choices"][0]["message"]["content"].strip()

            # v14.0: Используем новый парсер с процентами
            cat1, cat2, pct1 = parse_category_response(answer)

            # Возвращаем в формате "CAT1+CAT2" или "CAT1"
            if cat2:
                return f"{cat1}+{cat2}"
            return cat1

    except httpx.TimeoutException:
        return None
    except Exception:
        return None


# === ОСНОВНОЙ КЛАССИФИКАТОР ===

class ChannelClassifier:
    """
    Асинхронный классификатор каналов.

    Особенности:
    - Не блокирует основной процесс
    - Очередь задач обрабатывается в фоне
    - Fallback на ключевые слова
    - Кэширование результатов
    """

    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GROQ_API_KEY")
        self.cache = _load_cache()
        self.queue = deque()  # Очередь задач
        self.results = {}  # channel_id -> category
        self.running = False
        self._worker_task = None

        if not self.api_key:
            print("GROQ_API_KEY не найден. Используется только fallback классификация.")

    async def start_worker(self):
        """Запускает фоновый worker для обработки очереди."""
        if self.running:
            return
        self.running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop_worker(self):
        """Останавливает worker и сохраняет кэш."""
        self.running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        _save_cache(self.cache)

    async def _worker_loop(self):
        """Фоновый цикл обработки очереди."""
        while self.running:
            if not self.queue:
                await asyncio.sleep(0.5)
                continue

            task = self.queue.popleft()
            channel_id = task["channel_id"]

            # Проверяем кэш
            cached = _get_cached(channel_id, self.cache)
            if cached:
                self.results[channel_id] = cached
                if task.get("callback"):
                    task["callback"](channel_id, cached)
                continue

            # Классифицируем
            category = await self._classify_task(task)

            # Сохраняем
            self.results[channel_id] = category
            _set_cached(channel_id, category, self.cache)

            if task.get("callback"):
                task["callback"](channel_id, category)

            # Небольшая пауза между запросами к API
            if self.api_key:
                await asyncio.sleep(2)  # 30 req/min = 1 req/2sec

    async def _classify_task(self, task: dict) -> str:
        """Классифицирует один канал."""
        context = _prepare_context(
            task.get("title", ""),
            task.get("description", ""),
            task.get("messages", [])
        )

        # Пробуем AI
        if self.api_key:
            result = await _call_groq_api(context, self.api_key)
            if result:
                return result

        # Fallback
        return classify_fallback(
            task.get("title", ""),
            task.get("description", ""),
            task.get("messages", [])
        )

    def add_to_queue(
        self,
        channel_id: int,
        title: str,
        description: str,
        messages: list,
        callback=None
    ):
        """
        Добавляет канал в очередь классификации.
        Не блокирует - сразу возвращает управление.

        callback(channel_id, category) будет вызван когда классификация завершится.
        """
        # Проверяем кэш сразу
        cached = _get_cached(channel_id, self.cache)
        if cached:
            self.results[channel_id] = cached
            if callback:
                callback(channel_id, cached)
            return

        self.queue.append({
            "channel_id": channel_id,
            "title": title,
            "description": description,
            "messages": messages,
            "callback": callback
        })

    def get_result(self, channel_id: int) -> Optional[str]:
        """Возвращает результат классификации если готов."""
        return self.results.get(channel_id)

    async def classify_sync(
        self,
        channel_id: int,
        title: str,
        description: str,
        messages: list
    ) -> str:
        """
        Синхронная классификация (ждёт результат).
        Используется для режима догоняния.
        """
        # Проверяем кэш
        cached = _get_cached(channel_id, self.cache)
        if cached:
            return cached

        # Классифицируем
        task = {
            "channel_id": channel_id,
            "title": title,
            "description": description,
            "messages": messages
        }
        category = await self._classify_task(task)

        # Сохраняем в кэш
        _set_cached(channel_id, category, self.cache)
        self.results[channel_id] = category

        return category

    def save_cache(self):
        """Сохраняет кэш на диск."""
        _save_cache(self.cache)

    def get_queue_size(self) -> int:
        """Возвращает размер очереди."""
        return len(self.queue)


# === ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ===

_classifier: Optional[ChannelClassifier] = None


def get_classifier() -> ChannelClassifier:
    """Возвращает глобальный экземпляр классификатора."""
    global _classifier
    if _classifier is None:
        _classifier = ChannelClassifier()
    return _classifier
