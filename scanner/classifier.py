"""
AI Классификатор тем Telegram каналов.
v18.0: Расширенные категории + Multi-label поддержка

Архитектура:
  - 17 категорий (вместо 11) на основе анализа рынка рекламы
  - Multi-label: основная + вторичная категория (CAT+CAT2)
  - Groq API + Llama 3.3 70B
  - Fallback на ключевые слова
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


# === СИСТЕМНЫЙ ПРОМПТ ===

SYSTEM_PROMPT = """You are a Telegram channel topic classifier.
Analyze the channel and return the PRIMARY category + optional SECONDARY category.

FORMAT: CATEGORY or CATEGORY+SECONDARY (if clearly fits two)

CATEGORIES:
- CRYPTO: cryptocurrency, DeFi, NFT, Web3, blockchain, Bitcoin, Ethereum, trading signals
- FINANCE: stocks, investing, forex, banks, economics (NOT crypto)
- REAL_ESTATE: property, mortgages, apartments, real estate agents
- BUSINESS: B2B services, SaaS, consulting, startups, entrepreneurs
- TECH: programming, IT, gadgets, DevOps, software development
- AI_ML: neural networks, ML, ChatGPT, LLM, Data Science, Midjourney, Stable Diffusion
- EDUCATION: courses, tutorials, learning, online schools, how-to guides
- BEAUTY: cosmetics, makeup, skincare, perfume, beauty salons
- HEALTH: fitness, medicine, wellness, diet, sports, gym
- TRAVEL: tourism, hotels, flights, vacations, travel guides
- RETAIL: e-commerce, shops, products, delivery, sales
- ENTERTAINMENT: games, movies, music, memes, humor, streaming
- NEWS: news aggregators, politics, current events, breaking news
- LIFESTYLE: personal blogs, lifestyle, diary, thoughts, opinions
- GAMBLING: betting, casinos, sports predictions, poker, slots
- ADULT: 18+ content, dating, explicit material
- OTHER: does not clearly fit any category

RULES:
1. Return ONLY category name(s), no explanations
2. Use + for dual categories: "AI_ML+NEWS" or "TECH+ENTERTAINMENT"
3. Use dual category ONLY when channel clearly fits both (15-20% of cases)
4. If truly unclear, return OTHER"""


# === FALLBACK КЛЮЧЕВЫЕ СЛОВА ===

FALLBACK_KEYWORDS = {
    # Премиальные категории
    "CRYPTO": [
        "bitcoin", "btc", "ethereum", "eth", "крипта", "криптовалют", "трейдинг",
        "сигнал", "defi", "nft", "блокчейн", "токен", "альткоин", "биржа", "binance",
        "bybit", "памп", "дамп", "холд", "стейкинг", "майнинг", "usdt", "tether",
        "web3", "ton", "solana", "криптотрейд"
    ],
    "FINANCE": [
        "инвестиц", "акции", "дивиденд", "брокер", "тинькофф", "сбер",
        "фондовый", "облигаци", "портфель", "пассивный доход", "форекс",
        "биржев", "трейдер", "капитал", "финанс", "банк"
    ],
    "REAL_ESTATE": [
        "недвижимост", "квартир", "ипотек", "застройщик", "новостройк",
        "жилье", "аренда", "риэлтор", "метр", "жк ", "пик", "лср",
        "жилищ", "коммерческ", "офис", "помещени"
    ],
    "BUSINESS": [
        "b2b", "saas", "стартап", "startup", "консалтинг", "бизнес",
        "предприниматель", "ceo", "founder", "инвестор", "венчур",
        "предпринимател", "масштабирован", "франшиз", "бизнес-модел"
    ],

    # Технологии
    "TECH": [
        "программ", "python", "javascript", "разработ", "код", "developer",
        "github", "api", "frontend", "backend", "devops", "linux", "айти",
        "software", "typescript", "react", "vue", "java", "kotlin", "swift"
    ],
    "AI_ML": [
        "нейросет", "chatgpt", "gpt", "llm", "машинное обучение", "data science",
        "deep learning", "nlp", "computer vision", "midjourney", "stable diffusion",
        "claude", "gemini", "anthropic", "openai", "нейронн", "искусственн интеллект",
        "ai", "ml", "модел", "датасет", "обучен модел"
    ],

    # Образование и развитие
    "EDUCATION": [
        "курс", "обучени", "урок", "tutorial", "учи", "образовани",
        "вебинар", "мастер-класс", "гайд", "инструкц", "онлайн-школ",
        "лекци", "преподава", "студент"
    ],
    "BEAUTY": [
        "косметик", "макияж", "makeup", "парфюм", "красот", "уход за",
        "skincare", "ногт", "маникюр", "визаж", "бьют", "beauty",
        "крем", "сыворотк", "маска для лиц"
    ],
    "HEALTH": [
        "фитнес", "тренировк", "спорт", "здоровь", "зож", "диет",
        "похудени", "медицин", "врач", "клиник", "fitness", "gym",
        "спортзал", "питани", "белок", "калори"
    ],
    "TRAVEL": [
        "путешеств", "туризм", "отель", "авиабилет", "тур", "виза",
        "отпуск", "поездк", "страна", "travel", "booking", "airbnb",
        "самолет", "гостиниц", "экскурси"
    ],

    # Коммерция
    "RETAIL": [
        "магазин", "купить", "продаж", "товар", "доставк", "скидк",
        "акция", "распродаж", "shop", "store", "заказ", "ozon",
        "wildberries", "aliexpress", "маркетплейс"
    ],

    # Контент
    "ENTERTAINMENT": [
        "игр", "кино", "фильм", "музык", "мем", "юмор", "смешн",
        "приколы", "развлечени", "стрим", "twitch", "youtube",
        "сериал", "аниме", "gaming", "steam", "playstation", "xbox"
    ],
    "NEWS": [
        "новости", "срочно", "breaking", "политик", "событи", "происшеств",
        "сводка", "дайджест", "главное за", "что случилось", "инфо",
        "пресс", "журналист", "сми", "медиа"
    ],
    "LIFESTYLE": [
        "мысли", "размышлени", "личн", "дневник", "lifestyle", "лайфстайл",
        "моя жизнь", "блог", "заметк", "opinion", "мнени"
    ],

    # Высокий риск
    "GAMBLING": [
        "казино", "ставк", "букмекер", "1xbet", "fonbet", "покер", "слот",
        "рулетк", "betting", "прогноз на матч", "коэффициент", "экспресс"
    ],
    "ADULT": [
        "18+", "xxx", "эротик", "adult", "знакомств", "интим", "секс",
        "onlyfans", "nsfw"
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

            # Поддержка multi-label формата: "CAT1+CAT2"
            if "+" in answer:
                parts = answer.split("+")
                primary = parts[0].strip()
                secondary = parts[1].strip() if len(parts) > 1 else None

                # Валидируем обе категории
                if primary in CATEGORIES:
                    if secondary and secondary in CATEGORIES:
                        return f"{primary}+{secondary}"
                    return primary

            # Обычный single-label
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
