"""
AI Классификатор тем Telegram каналов.
v28.0: СТРОГАЯ КЛАССИФИКАЦИЯ - только нейросеть!

Архитектура:
  - 17 категорий на основе анализа рынка рекламы
  - Single-label: возвращаем ОДНУ категорию
  - Формат ответа: просто "CATEGORY"
  - Groq API + Llama 3.3 70B
  - Кэширование результатов на 7 дней
  - RETRY механизм: 3 попытки с задержками 5/15/30 сек
  - БЕЗ FALLBACK: если AI не ответил - категория не определяется
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
MAX_POSTS_FOR_AI = 20      # v27.0: увеличено с 10 для лучшего контекста
MAX_CHARS_PER_POST = 800   # v27.0: увеличено с 500

# DEBUG режим - включить для отладки классификации (False в production!)
DEBUG_CLASSIFIER = False


# === СИСТЕМНЫЙ ПРОМПТ v27.0 (с русским сленгом) ===

SYSTEM_PROMPT = """You are a Telegram channel classifier.
Analyze the channel and return EXACTLY ONE category.

OUTPUT FORMAT: Just the category name, nothing else.
Example: CRYPTO

CATEGORIES (pick ONE):
- CRYPTO: Bitcoin, Ethereum, DeFi, NFT, Web3, trading signals, blockchain, airdrops
- FINANCE: stocks, forex, banks, investing, economics (NOT crypto!)
- REAL_ESTATE: property, apartments, mortgages, real estate
- BUSINESS: B2B, SaaS, startups, consulting, entrepreneurs
- TECH: programming, IT, DevOps, gadgets, software development
- AI_ML: ChatGPT, neural networks, ML, LLM, Data Science, prompts
- EDUCATION: courses, tutorials, learning, online schools
- BEAUTY: cosmetics, makeup, skincare, beauty salons
- HEALTH: fitness, medicine, wellness, diet, sports
- TRAVEL: tourism, hotels, flights, travel guides
- RETAIL: shops, e-commerce, products, delivery, marketplaces
- ENTERTAINMENT: games, movies, music, memes, humor, TON games, P2E, streaming
- NEWS: news, politics, current events, war, world events
- LIFESTYLE: personal blogs, diary, thoughts, motivation
- GAMBLING: betting, casinos, poker, sports betting
- ADULT: 18+ content, dating, escorts
- OTHER: does not fit any category

RUSSIAN TRADING/CRYPTO SLANG (CRITICAL - many channels are in Russian):
- "бинанс", "binance", "байбит", "bybit", "окекс", "okx" → crypto EXCHANGE → CRYPTO
- "позиция", "лонг", "шорт", "стоп-лосс", "тейк-профит" → trading terms → CRYPTO/FINANCE
- "краснянка", "зеленянка" → loss/profit slang → CRYPTO/FINANCE
- "скальп", "скальпинг", "scalp" → scalping (short-term trading) → CRYPTO/FINANCE
- "пампы", "дампы", "памп", "дамп" → pump and dump → CRYPTO
- "альты", "альткоины", "альта" → altcoins → CRYPTO
- "ликвидация", "маржа", "плечо", "леверидж" → margin trading → CRYPTO/FINANCE
- "стакан", "ордера", "заявки" → order book → CRYPTO/FINANCE
- "сетка", "грид", "grid" → grid trading → CRYPTO
- "фьючерсы", "фьючи", "спот" → futures/spot → CRYPTO/FINANCE

DECISION RULES (IMPORTANT):
1. Memes about crypto → ENTERTAINMENT (humor is primary, not topic)
2. TON games, P2E, play-to-earn → ENTERTAINMENT (it's gaming)
3. News about crypto/tech/politics → NEWS (news format is primary)
4. Tech news channel → NEWS (not TECH)
5. Trading education/courses → EDUCATION (teaching is primary)
6. Beauty/fitness blogger → LIFESTYLE (personal blog format)
7. Crypto trading signals → CRYPTO (trading is the service)
8. AI tools reviews → AI_ML (tools are primary)
9. Startup news → BUSINESS (business focus)
10. Product reviews → RETAIL (commerce focus)
11. Russian trading slang in posts → CRYPTO or FINANCE (NOT BEAUTY/LIFESTYLE!)

Pick the DOMINANT theme based on content FORMAT, not just topic.
Return ONE word only."""


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
        parts.append("Recent posts:\n" + "\n".join(posts_text[:MAX_POSTS_FOR_AI]))

    return "\n\n".join(parts)


# === ПАРСИНГ ОТВЕТА LLM v15.0 (ОДНА КАТЕГОРИЯ) ===

def parse_category_response(response: str) -> str:
    """
    Парсит ответ LLM - одна категория.
    Input: "CRYPTO" или "ENTERTAINMENT" или любой текст с категорией
    Output: "CRYPTO" или "OTHER"
    """
    response = response.strip().upper()

    # Убираем возможные артефакты (кавычки, точки, двоеточия с процентами)
    response = re.sub(r'["\'\.\:\d\+\%]', '', response).strip()

    # Прямое совпадение
    if response in CATEGORIES:
        return response

    # Ищем категорию в ответе (AI иногда добавляет пояснения)
    for cat in CATEGORIES:
        if cat in response:
            return cat

    return "OTHER"


# === RETRY КОНФИГУРАЦИЯ (v28.0) ===

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]  # Задержки между попытками в секундах


# === GROQ API ===

async def _call_groq_api_once(context: str, api_key: str) -> tuple[Optional[str], bool]:
    """
    Один запрос к Groq API.
    Возвращает (category, should_retry):
    - (category, False) - успех
    - (None, True) - retry (rate limit, timeout)
    - (None, False) - фатальная ошибка (не retry)
    """
    if not HTTPX_AVAILABLE:
        return None, False

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
                if DEBUG_CLASSIFIER:
                    print("CLASSIFIER DEBUG: Rate limit (429) - will retry")
                return None, True  # Retry

            response.raise_for_status()
            data = response.json()

            answer = data["choices"][0]["message"]["content"].strip()

            if DEBUG_CLASSIFIER:
                print(f"CLASSIFIER DEBUG - LLM raw response: '{answer}'")

            category = parse_category_response(answer)

            if DEBUG_CLASSIFIER:
                print(f"CLASSIFIER DEBUG - Parsed category: {category}")

            return category, False

    except httpx.TimeoutException:
        if DEBUG_CLASSIFIER:
            print("CLASSIFIER DEBUG: Timeout - will retry")
        return None, True  # Retry
    except Exception as e:
        if DEBUG_CLASSIFIER:
            print(f"CLASSIFIER DEBUG: Error - {e}")
        return None, True  # Retry на любую ошибку


async def _call_groq_api(context: str, api_key: str) -> Optional[str]:
    """
    v28.0: Запрос к Groq API с retry.
    ТОЛЬКО нейросеть определяет категорию. Без fallback на OTHER.
    """
    if not HTTPX_AVAILABLE:
        print("CLASSIFIER: httpx не установлен, классификация невозможна")
        return None

    # DEBUG: показать что отправляем в LLM
    if DEBUG_CLASSIFIER:
        print(f"\n{'='*60}")
        print(f"CLASSIFIER DEBUG - Context ({len(context)} chars):")
        print(f"{'='*60}")
        print(context[:2000] + ("..." if len(context) > 2000 else ""))
        print(f"{'='*60}\n")

    for attempt in range(MAX_RETRIES):
        category, should_retry = await _call_groq_api_once(context, api_key)

        if category is not None:
            return category

        if not should_retry:
            break

        if attempt < MAX_RETRIES - 1:
            delay = RETRY_DELAYS[attempt]
            print(f"CLASSIFIER: Попытка {attempt + 1}/{MAX_RETRIES} не удалась, жду {delay} сек...")
            await asyncio.sleep(delay)

    print(f"CLASSIFIER: Все {MAX_RETRIES} попыток исчерпаны, категория не определена")
    return None  # НЕ возвращаем OTHER - нейросеть не ответила


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

            try:
                # Проверяем кэш
                cached = _get_cached(channel_id, self.cache)
                if cached:
                    self.results[channel_id] = cached
                    if task.get("callback"):
                        try:
                            task["callback"](channel_id, cached)
                        except Exception as e:
                            print(f"Classifier callback error (cached): {e}")
                    continue

                # Классифицируем
                category = await self._classify_task(task)

                # v28.0: Если AI не смог определить категорию - НЕ сохраняем
                if category is None:
                    print(f"CLASSIFIER: Канал {channel_id} не классифицирован (AI не ответил)")
                    continue

                # Сохраняем ТОЛЬКО если категория определена
                self.results[channel_id] = category
                _set_cached(channel_id, category, self.cache)

                if task.get("callback"):
                    try:
                        task["callback"](channel_id, category)
                    except Exception as e:
                        print(f"Classifier callback error: {e}")

            except Exception as e:
                print(f"Classifier worker error for channel {channel_id}: {e}")

            # Небольшая пауза между запросами к API
            if self.api_key:
                await asyncio.sleep(2)  # 30 req/min = 1 req/2sec

    async def _classify_task(self, task: dict) -> Optional[str]:
        """
        Классифицирует один канал.
        v28.0: Возвращает None если AI не смог классифицировать.
        ТОЛЬКО нейросеть определяет категорию - без fallback!
        """
        if not self.api_key:
            print("CLASSIFIER: GROQ_API_KEY не установлен, классификация невозможна")
            return None

        context = _prepare_context(
            task.get("title", ""),
            task.get("description", ""),
            task.get("messages", [])
        )

        # ТОЛЬКО AI - никакого fallback
        result = await _call_groq_api(context, self.api_key)
        return result  # None если AI не ответил

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

    async def classify_sync(
        self,
        channel_id: int,
        title: str,
        description: str,
        messages: list
    ) -> Optional[str]:
        """
        Синхронная классификация (ждёт результат).
        v28.0: Возвращает None если AI не смог классифицировать.
        ТОЛЬКО нейросеть определяет категорию - без fallback!
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

        # v28.0: Сохраняем в кэш ТОЛЬКО если категория определена
        if category is not None:
            _set_cached(channel_id, category, self.cache)
            self.results[channel_id] = category

        return category  # None если AI не ответил

    def save_cache(self):
        """Сохраняет кэш на диск."""
        _save_cache(self.cache)


# === ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ===

_classifier: Optional[ChannelClassifier] = None


def get_classifier() -> ChannelClassifier:
    """Возвращает глобальный экземпляр классификатора."""
    global _classifier
    if _classifier is None:
        _classifier = ChannelClassifier()
    return _classifier
