"""
AI Классификатор тем Telegram каналов.
V2.0: Chain-of-Thought + Extended Priority Rules

Архитектура:
  - 16 категорий (без OTHER — LLM обязан выбрать)
  - Ollama + Qwen3-8B (think=False для детерминированности)
  - V2.0: Chain-of-Thought — Reasoning: ... перед <category>
  - 30+ Priority Rules для edge cases
  - temperature=0.3, num_predict=300 (для reasoning)
  - Кэширование результатов на 7 дней
"""

import os
import json
import asyncio
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Для HTTP запросов к Ollama
import requests


# === RETRY КОНФИГУРАЦИЯ ===
MAX_RETRIES = 3
RETRY_DELAY = 5  # секунд между попытками


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
]

# === OLLAMA КОНФИГУРАЦИЯ (v32.0) ===

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_TIMEOUT = 60

CACHE_TTL_DAYS = 7
MAX_POSTS_FOR_AI = 50
MAX_CHARS_PER_POST = 800

# DEBUG режим
DEBUG_CLASSIFIER = False


# === СИСТЕМНЫЙ ПРОМПТ v32.0 ===

SYSTEM_PROMPT = """Classify Telegram channel. Pick ONE category from the list.

CATEGORIES:
1. AI_ML - нейросети, ChatGPT, GPT, Claude, Gemini, AI новости, Midjourney
2. CRYPTO - трейдинг, скальпинг, фьючерсы, Binance, Bybit, криптовалюты
3. TECH - программирование, DevOps, VPN, антивирус, cybersecurity, приватность
4. FINANCE - акции, форекс, банки
5. BUSINESS - B2B, маркетинг, бизнес
6. NEWS - новости, политика
7. ENTERTAINMENT - игры, мемы
8. EDUCATION - курсы
9. LIFESTYLE - личный блог
10. HEALTH - фитнес, медицина
11. BEAUTY - косметика
12. TRAVEL - туризм
13. RETAIL - магазины
14. REAL_ESTATE - недвижимость
15. GAMBLING - ставки
16. ADULT - 18+

EXAMPLES:
- Channel about ChatGPT, нейросети, GPT models → AI_ML
- Channel about Binance, трейдинг, фьючерсы → CRYPTO
- Channel about Python, DevOps → TECH
- Channel about VPN, proxy, security, privacy → TECH

Output: <category>EXACT_NAME</category>
IMPORTANT: Use EXACT name like AI_ML, CRYPTO, TECH - not "Technology" or "Artificial Intelligence"."""


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
        return None

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

    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r't\.me/\S+', '', text)
    text = re.sub(r'[\U0001F600-\U0001F64F]{3,}', '', text)
    text = re.sub(r'[\U0001F300-\U0001F5FF]{3,}', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _prepare_context(title: str, description: str, messages: list) -> str:
    """Формирует контекст для LLM."""
    parts = []

    if title:
        parts.append(f"Channel name: {title[:256]}")

    if description:
        clean_desc = _clean_text(description)[:1000]
        if clean_desc:
            parts.append(f"Description: {clean_desc}")

    posts_text = []
    for msg in messages[:MAX_POSTS_FOR_AI]:
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text

        if text:
            clean = _clean_text(text)[:MAX_CHARS_PER_POST]
            if clean and len(clean) > 20:
                posts_text.append(f"- {clean}")

    if posts_text:
        parts.append("Recent posts:\n" + "\n".join(posts_text[:MAX_POSTS_FOR_AI]))

    return "\n\n".join(parts)


# === ПАРСИНГ ОТВЕТА LLM v32.0 ===

def _most_frequent_category(text: str) -> str:
    """Возвращает наиболее часто упомянутую категорию."""
    counts = {}
    for cat in CATEGORIES:
        counts[cat] = text.count(cat)

    counts = {k: v for k, v in counts.items() if v > 0}

    if counts:
        return max(counts, key=counts.get)

    return None  # v33.0: лучше None чем неверная категория с низким CPM


def parse_category_response(response: str) -> str:
    """
    Извлекает категорию из ответа LLM.
    Приоритет: XML tag > CATEGORY: > последнее слово > любое упоминание > частотный
    """
    response_upper = response.upper()

    # 1. XML tag <category>XXX</category>
    match = re.search(r'<CATEGORY>\s*([A-Z_]+)\s*</CATEGORY>', response_upper)
    if match and match.group(1) in CATEGORIES:
        return match.group(1)

    # 2. CATEGORY: XXX или Category: XXX
    match = re.search(r'CATEGORY[:\s]+([A-Z_]+)', response_upper)
    if match and match.group(1) in CATEGORIES:
        return match.group(1)

    # 3. Последнее валидное слово (после reasoning)
    words = re.findall(r'\b([A-Z_]+)\b', response_upper)
    for word in reversed(words):
        if word in CATEGORIES:
            return word

    # 4. Любое упоминание категории
    for cat in CATEGORIES:
        if cat in response_upper:
            return cat

    # 5. Fallback: частотный анализ
    return _most_frequent_category(response_upper)


# === OLLAMA API (v32.0) ===

def _call_ollama_sync(context: str, retry_count: int = 0) -> Optional[str]:
    """
    Синхронный запрос к Ollama v33.0 с retry логикой.
    think=False, temperature=0.3 для детерминированности.
    При таймауте делает до MAX_RETRIES попыток.
    """
    # V2.0: Chain-of-Thought + Extended Priority Rules (30+)
    user_message = f"""CHANNEL CONTENT:
{context[:8000]}

---
TASK: Classify this channel. First explain your reasoning, then give the category.

CATEGORIES (pick ONE):
1. AI_ML - нейросети, ChatGPT, GPT, Claude, Gemini, Midjourney, Stable Diffusion
2. CRYPTO - криптовалюты, трейдинг, скальпинг, фьючерсы, Binance, Bybit, DeFi, NFT
3. TECH - программирование, DevOps, VPN, proxy, security, Python, JavaScript, IT
4. FINANCE - акции, форекс, банки, инвестиции (БЕЗ криптовалют!)
5. BUSINESS - B2B, маркетинг, консалтинг, стартапы, предпринимательство
6. NEWS - новости, политика, события, журналистика
7. ENTERTAINMENT - игры, мемы, кино, музыка, юмор, развлечения
8. EDUCATION - курсы, обучение, онлайн-школы (общие темы)
9. LIFESTYLE - личные блоги, CEO дневники, лайфстайл, мотивация
10. HEALTH - фитнес, медицина, ЗОЖ, диеты, психология
11. BEAUTY - косметика, мода, стиль, парфюмерия
12. TRAVEL - туризм, путешествия, авиа, отели
13. RETAIL - магазины, e-commerce, обзоры товаров, скидки
14. REAL_ESTATE - недвижимость, ипотека, риэлторы
15. GAMBLING - ставки, казино, букмекеры
16. ADULT - 18+ контент

PRIORITY RULES (V2.0 — 30+ rules):

CRYPTO vs FINANCE:
- Binance, Bybit, OKX, криптобиржи → CRYPTO
- BTC, ETH, альткоины, токены → CRYPTO
- Фьючерсы крипты, perpetual → CRYPTO
- Акции, фондовый рынок, MOEX → FINANCE
- Форекс, валютные пары → FINANCE
- Банки, вклады, кредиты → FINANCE

AI_ML vs TECH:
- ChatGPT, Claude, Gemini, LLM → AI_ML
- Midjourney, DALL-E, генерация → AI_ML
- Нейросети, машинное обучение → AI_ML
- Python/JavaScript код (общий) → TECH
- DevOps, Docker, Kubernetes → TECH
- VPN, proxy, privacy tools → TECH
- Cybersecurity, хакинг → TECH

LIFESTYLE (личные блоги):
- CEO блог, founder дневник → LIFESTYLE (НЕ BUSINESS!)
- Личные размышления автора → LIFESTYLE
- Мотивация, продуктивность → LIFESTYLE

RETAIL (товары):
- Обзоры гаджетов для покупки → RETAIL (НЕ TECH!)
- Скидки, промокоды → RETAIL
- AliExpress находки → RETAIL

EDUCATION (общее обучение):
- Английский язык, языки → EDUCATION
- Школьные предметы → EDUCATION
- Курсы трейдинга крипты → CRYPTO (аудитория = трейдеры!)
- Курсы программирования → TECH (аудитория = разработчики!)

NEWS (новости):
- Политические новости → NEWS
- Криптоновости, Bitcoin news → CRYPTO (НЕ NEWS!)
- AI новости про модели → AI_ML (НЕ NEWS!)

ENTERTAINMENT:
- Мемы, юмор → ENTERTAINMENT
- Обзоры игр → ENTERTAINMENT
- Кино, сериалы → ENTERTAINMENT

---
FORMAT: First write "Reasoning: [your analysis]", then "<category>EXACT_NAME</category>"

Reasoning:"""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "stream": False,
        "think": False,  # Отключаем thinking - модель должна думать в ответе
        "keep_alive": -1,  # v33: НИКОГДА не выгружать модель из GPU!
        "options": {
            "temperature": 0.3,  # Низкая для детерминированности
            "num_predict": 300   # V2.0: увеличено для Chain-of-Thought reasoning
        }
    }

    if DEBUG_CLASSIFIER:
        print(f"\n{'='*60}")
        print(f"OLLAMA DEBUG - Context ({len(context)} chars):")
        print(context[:1500] + ("..." if len(context) > 1500 else ""))
        print(f"{'='*60}\n")

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)

        if response.status_code != 200:
            print(f"OLLAMA: HTTP {response.status_code}")
            return None

        data = response.json()
        message = data.get("message", {})
        content = message.get("content", "").strip()
        thinking = message.get("thinking", "").strip()

        if DEBUG_CLASSIFIER:
            if thinking:
                print(f"OLLAMA THINKING: {thinking[:800]}...")
            print(f"OLLAMA CONTENT: {content[:300]}")

        # Парсим content (должен содержать <category>)
        category = parse_category_response(content) if content else None

        # v33.0: thinking fallback удалён (think=False, поле всегда пустое)

        if DEBUG_CLASSIFIER:
            print(f"OLLAMA RESULT: {category}")

        return category

    except requests.exceptions.ConnectionError:
        print("OLLAMA: Не запущен! Запусти: ollama serve")
        return None
    except requests.exceptions.Timeout:
        if retry_count < MAX_RETRIES:
            wait = RETRY_DELAY * (retry_count + 1)
            print(f"OLLAMA: Таймаут, retry {retry_count + 1}/{MAX_RETRIES} через {wait}с...")
            time.sleep(wait)
            return _call_ollama_sync(context, retry_count + 1)
        print(f"OLLAMA: Таймаут после {MAX_RETRIES} попыток!")
        return None
    except Exception as e:
        print(f"OLLAMA: Ошибка - {e}")
        return None


async def _call_ollama(context: str) -> Optional[str]:
    """Async обёртка для синхронного requests."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _call_ollama_sync, context)


# === УПРАВЛЕНИЕ МОДЕЛЬЮ ===

def _preload_model():
    """Прогрев модели при старте — загружает в GPU."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "messages": [], "keep_alive": -1},
            timeout=120
        )
        if response.status_code == 200:
            print(f"Модель {OLLAMA_MODEL} загружена в GPU")
    except Exception as e:
        print(f"Предупреждение: не удалось прогреть модель - {e}")


def _unload_model():
    """Выгрузка модели при выходе — освобождает GPU."""
    try:
        requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "messages": [], "keep_alive": 0},
            timeout=10
        )
        print(f"Модель {OLLAMA_MODEL} выгружена из GPU")
    except:
        pass  # Не критично при выходе


# === ОСНОВНОЙ КЛАССИФИКАТОР ===

class ChannelClassifier:
    """
    Классификатор каналов через локальный Ollama.
    v33.0: Автоматический прогрев/выгрузка модели.
    """

    def __init__(self):
        self.cache = _load_cache()
        self.results = {}

        # v33: Прогреваем модель при старте
        _preload_model()

        print(f"CLASSIFIER V2.0: Ollama ({OLLAMA_MODEL}) + Chain-of-Thought + 30+ rules")

    def unload(self):
        """Выгружает модель из GPU. Вызывать при завершении работы."""
        _unload_model()

    async def classify_sync(
        self,
        channel_id: int,
        title: str,
        description: str,
        messages: list
    ) -> Optional[str]:
        """
        Классифицирует канал через Ollama с thinking mode.
        Возвращает категорию или None.
        """
        # Проверяем кэш
        cached = _get_cached(channel_id, self.cache)
        if cached:
            return cached

        # Готовим контекст
        context = _prepare_context(title, description, messages)

        # Запрос к Ollama (без keyword костылей!)
        category = await _call_ollama(context)

        # Сохраняем в кэш
        if category is not None:
            _set_cached(channel_id, category, self.cache)
            self.results[channel_id] = category

        return category

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
