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
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Для HTTP запросов к Ollama
import requests

logger = logging.getLogger(__name__)

# v2.1: Общие утилиты (clean_text)
from scanner.utils import clean_text

# v23.0: unified cache from cache.py
from scanner.cache import get_classification_cache

# v43.0: Централизованная конфигурация
from scanner.config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    MAX_POSTS_FOR_AI,
    MAX_CHARS_PER_POST,
    DEBUG_CLASSIFIER,
    CATEGORIES,
)

# Shared Ollama client utilities
from .client import call_ollama, OllamaConfig


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
# v23.0: unified cache from cache.py
# Старые функции _load_cache/_save_cache/_get_cached/_set_cached удалены
# Используем get_classification_cache() в классе ChannelClassifier

# === ПОДГОТОВКА ДАННЫХ ===

def _prepare_context(title: str, description: str, messages: list, image_descriptions: str = "") -> str:
    """Формирует контекст для LLM."""
    parts = []

    if title:
        parts.append(f"Channel name: {title[:256]}")

    if description:
        clean_desc = clean_text(description)[:1000]
        if clean_desc:
            parts.append(f"Description: {clean_desc}")

    # v63.0: Image analysis from Florence-2
    if image_descriptions:
        parts.append(image_descriptions)

    posts_text = []
    for msg in messages[:MAX_POSTS_FOR_AI]:
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text

        if text:
            clean = clean_text(text)[:MAX_CHARS_PER_POST]
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

    Note: This function has special logic (debug output, custom prompt,
    thinking field parsing) that differs from the generic call_ollama(),
    so it's kept as a separate implementation.
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
    except (KeyError, TypeError, ValueError) as e:
        # KeyError: неожиданная структура JSON ответа
        # TypeError/ValueError: ошибки преобразования данных
        print(f"OLLAMA: Ошибка обработки ответа - {e}")
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
    except requests.exceptions.RequestException as e:
        # Любые ошибки сети при прогреве (connection, timeout, etc.)
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
    except (requests.exceptions.RequestException, OSError) as e:
        logger.debug(f"Model unload skipped: {e}")  # Не критично при выходе


# === ОСНОВНОЙ КЛАССИФИКАТОР ===

class ChannelClassifier:
    """
    Классификатор каналов через локальный Ollama.
    v33.0: Автоматический прогрев/выгрузка модели.
    v23.0: unified cache from cache.py
    """

    def __init__(self):
        # v23.0: unified cache from cache.py
        self.cache = get_classification_cache()
        self.results = {}

        # v33: Прогреваем модель при старте
        _preload_model()

        print(f"Classifier: Ollama ({OLLAMA_MODEL})")

    def unload(self):
        """Выгружает модель из GPU. Вызывать при завершении работы."""
        _unload_model()

    async def classify_sync(
        self,
        channel_id: int,
        title: str,
        description: str,
        messages: list,
        image_descriptions: str = ""  # v63.0: Vision analysis
    ) -> Optional[str]:
        """
        Классифицирует канал через Ollama с thinking mode.
        Возвращает категорию или None.
        """
        # v23.0: unified cache from cache.py
        cache_key = str(channel_id)
        cached_data = self.cache.get(cache_key)
        if cached_data and isinstance(cached_data, dict):
            cached = cached_data.get("category")
            if cached:
                return cached
        elif cached_data and isinstance(cached_data, str):
            # Поддержка старого формата (просто строка)
            return cached_data

        # Готовим контекст
        context = _prepare_context(title, description, messages, image_descriptions)

        # Запрос к Ollama (без keyword костылей!)
        category = await _call_ollama(context)

        # Сохраняем в кэш
        if category is not None:
            # v23.0: unified cache from cache.py
            self.cache.set(cache_key, {"category": category})
            self.results[channel_id] = category

        return category

    def save_cache(self):
        """Сохраняет кэш на диск."""
        # v23.0: unified cache from cache.py (JSONCache автоматически сохраняет)
        pass  # JSONCache сохраняет при каждом set(), явный save не нужен


# === ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ===

_classifier: Optional[ChannelClassifier] = None


def get_classifier() -> ChannelClassifier:
    """Возвращает глобальный экземпляр классификатора."""
    global _classifier
    if _classifier is None:
        _classifier = ChannelClassifier()
    return _classifier
