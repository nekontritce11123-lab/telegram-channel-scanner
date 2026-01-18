"""
AI Классификатор тем Telegram каналов.
v33.0: Полный редизайн промптов

Архитектура:
  - 16 категорий (без OTHER — LLM обязан выбрать)
  - Ollama + Qwen3-8B (think=False для детерминированности)
  - XML теги для парсинга: <category>
  - temperature=0.3
  - ВСЕ 16 категорий в user_message с priority rules
  - Кэширование результатов на 7 дней
"""

import os
import json
import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Для HTTP запросов к Ollama
import requests


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
OLLAMA_TIMEOUT = 120

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
3. TECH - программирование, DevOps, разработка ПО
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

def _call_ollama_sync(context: str) -> Optional[str]:
    """
    Синхронный запрос к Ollama v33.0.
    think=False, temperature=0.3 для детерминированности.
    """
    # v33.0: ВСЕ 16 категорий + priority rules
    user_message = f"""CHANNEL CONTENT:
{context[:8000]}

---
TASK: Classify this channel using EXACT category name.

CATEGORIES:
1. AI_ML - нейросети, ChatGPT, GPT, Claude, Gemini, AI новости, Midjourney
2. CRYPTO - трейдинг, скальпинг, фьючерсы, Binance, Bybit, криптовалюты
3. TECH - программирование, DevOps, разработка ПО
4. FINANCE - акции, форекс, банки (НЕ крипто)
5. BUSINESS - B2B, маркетинг, консалтинг, стартапы
6. NEWS - новости, политика
7. ENTERTAINMENT - игры, мемы, кино
8. EDUCATION - курсы, обучение (НЕ трейдинг)
9. LIFESTYLE - личный блог, CEO блоги
10. HEALTH - фитнес, медицина
11. BEAUTY - косметика, мода
12. TRAVEL - туризм
13. RETAIL - магазины, обзоры товаров
14. REAL_ESTATE - недвижимость
15. GAMBLING - ставки, казино
16. ADULT - 18+

PRIORITY RULES:
- нейросети/ChatGPT/AI → AI_ML
- трейдинг/фьючерсы/crypto → CRYPTO
- CEO блог/founder → LIFESTYLE (не TECH/BUSINESS)
- обзоры товаров → RETAIL (не TECH)
- курсы трейдинга → CRYPTO (аудитория = трейдеры)

Answer: <category>"""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "stream": False,
        "think": False,  # Отключаем thinking - модель должна думать в ответе
        "options": {
            "temperature": 0.3,  # Низкая для детерминированности
            "num_predict": 100   # Короткий ответ
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
        print(f"OLLAMA: Таймаут ({OLLAMA_TIMEOUT} сек)")
        return None
    except Exception as e:
        print(f"OLLAMA: Ошибка - {e}")
        return None


async def _call_ollama(context: str) -> Optional[str]:
    """Async обёртка для синхронного requests."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _call_ollama_sync, context)


# === ОСНОВНОЙ КЛАССИФИКАТОР ===

class ChannelClassifier:
    """
    Классификатор каналов через локальный Ollama.
    v32.0: Thinking mode + XML tags, без keyword костылей.
    """

    def __init__(self):
        self.cache = _load_cache()
        self.results = {}
        print(f"CLASSIFIER v33.0: Ollama ({OLLAMA_MODEL}) + 16 categories")

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
