"""
AI Классификатор тем Telegram каналов.
v17.0: Groq API + Llama 3 + Async Background Processing

Архитектура:
  - Асинхронная очередь классификации (не блокирует краулер)
  - Фоновый worker обрабатывает очередь
  - Fallback на ключевые слова если API недоступен
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
    "CRYPTO",      # криптовалюты, трейдинг, DeFi, NFT
    "NEWS",        # новости, политика, события
    "BLOG",        # личные блоги, лайфстайл
    "SHOP",        # магазины, продажи
    "GAMBLING",    # ставки, казино
    "ADULT",       # 18+ контент
    "TECH",        # программирование, IT, гаджеты
    "FINANCE",     # инвестиции, акции (не крипта)
    "EDUCATION",   # курсы, обучение
    "MARKETING",   # реклама, SMM, продвижение
    "OTHER",       # не подходит ни под что
]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama3-8b-8192"
API_TIMEOUT = 10  # секунд
CACHE_TTL_DAYS = 7
MAX_POSTS_FOR_AI = 10
MAX_CHARS_PER_POST = 500


# === СИСТЕМНЫЙ ПРОМПТ ===

SYSTEM_PROMPT = """You are a Telegram channel topic classifier. Your task is to analyze channel data and determine its primary topic category.

RULES:
1. Return ONLY the category name from the list below
2. No explanations, no punctuation, just the category word
3. If channel fits multiple categories, choose the MOST DOMINANT one
4. If truly unclear, return OTHER

CATEGORIES:
- CRYPTO: cryptocurrency trading, DeFi, NFT, Web3, blockchain, Bitcoin, Ethereum, trading signals
- NEWS: news aggregators, current events, politics, breaking news, journalism
- BLOG: personal blogs, lifestyle, opinions, diary-style content, thoughts
- SHOP: online stores, product sales, dropshipping, marketplace, goods
- GAMBLING: betting, casinos, sports predictions, poker, slots
- ADULT: 18+ content, dating, explicit material
- TECH: programming, IT, gadgets, software development, coding, tech reviews
- FINANCE: stocks, investing, economics, banks, forex (NOT crypto)
- EDUCATION: courses, tutorials, learning, academic, how-to guides
- MARKETING: advertising, SMM, promotion, PR, traffic, targeting
- OTHER: does not clearly fit any category above"""


# === FALLBACK КЛЮЧЕВЫЕ СЛОВА ===

FALLBACK_KEYWORDS = {
    "CRYPTO": [
        "bitcoin", "btc", "ethereum", "eth", "крипта", "криптовалют", "трейдинг",
        "сигнал", "defi", "nft", "блокчейн", "токен", "альткоин", "биржа", "binance",
        "bybit", "памп", "дамп", "холд", "стейкинг", "майнинг", "usdt", "tether"
    ],
    "NEWS": [
        "новости", "срочно", "breaking", "политик", "событи", "происшеств",
        "сводка", "дайджест", "главное за", "что случилось", "инфо"
    ],
    "TECH": [
        "программ", "python", "javascript", "разработ", "код", "developer",
        "github", "api", "frontend", "backend", "devops", "linux", "айти",
        "нейросет", "chatgpt", "ai", "машинное обучение", "data science"
    ],
    "MARKETING": [
        "реклама", "продвижен", "smm", "таргет", "трафик", "маркетинг",
        "пиар", "pr", "раскрутк", "подписчик", "охват", "воронк", "лид"
    ],
    "GAMBLING": [
        "казино", "ставк", "букмекер", "1xbet", "fonbet", "покер", "слот",
        "рулетк", "betting", "прогноз на матч", "коэффициент", "экспресс"
    ],
    "ADULT": [
        "18+", "xxx", "эротик", "adult", "знакомств", "интим", "секс"
    ],
    "FINANCE": [
        "инвестиц", "акции", "дивиденд", "брокер", "тинькофф", "сбер",
        "фондовый", "облигаци", "портфель", "пассивный доход", "форекс"
    ],
    "EDUCATION": [
        "курс", "обучени", "урок", "tutorial", "учи", "образовани",
        "вебинар", "мастер-класс", "гайд", "инструкц"
    ],
    "SHOP": [
        "магазин", "купить", "продаж", "товар", "доставк", "скидк",
        "акция", "распродаж", "shop", "store", "заказ"
    ],
    "BLOG": [
        "мысли", "размышлени", "личн", "дневник", "lifestyle", "лайфстайл",
        "моя жизнь", "блог", "заметк"
    ],
}


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


# === FALLBACK КЛАССИФИКАЦИЯ ===

def classify_fallback(title: str, description: str, messages: list) -> str:
    """
    Классификация по ключевым словам (без AI).
    Используется как fallback если API недоступен.
    """
    # Собираем весь текст
    all_text = ""
    if title:
        all_text += " " + title.lower()
    if description:
        all_text += " " + description.lower()

    for msg in messages[:15]:
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text
        if text:
            all_text += " " + text.lower()

    # Считаем совпадения по категориям
    scores = {}
    for category, keywords in FALLBACK_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            count = all_text.count(keyword.lower())
            score += count
        scores[category] = score

    # Выбираем категорию с максимумом
    if not scores or max(scores.values()) == 0:
        return "OTHER"

    best_category = max(scores, key=scores.get)
    return best_category


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

            answer = data["choices"][0]["message"]["content"].strip().upper()

            # Валидируем ответ
            if answer in CATEGORIES:
                return answer

            # Пытаемся извлечь категорию из ответа
            for cat in CATEGORIES:
                if cat in answer:
                    return cat

            return "OTHER"

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
