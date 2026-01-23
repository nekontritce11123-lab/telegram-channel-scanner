"""
LLM Анализатор каналов v47.0 (Grandmaster Edition)

Три модуля:
1. AdAnalyzer — % рекламных постов (контекстный анализ через LLM)
2. CommentAnalyzer — Bot Detection + Trust Score
3. BrandSafetyAnalyzer — детекция токсичного контента (v47.0)

v47.0 изменения (Brand Safety Grandmaster Edition):
- Chain-of-Thought (reasoning field) для повышения точности
- Semantic severity — "Dominant theme" вместо процентов (8B модели плохо считают)
- Context Traps — явные примеры SAFE случаев для снижения false positives
- De-obfuscation как Core Principle (k@zin0 → casino)
- Python считает точный toxic_ratio, не LLM

v46.0 изменения:
- Добавлен LLM Brand Safety анализатор (GAMBLING, ADULT, SCAM)
- LLM понимает контекст, обфускацию, эвфемизмы
- Заменяет стоп-слова фильтр для умной детекции

Метрики:
- ad_percentage: % рекламных постов → ad_mult (0.4-1.0)
- bot_percentage: % ботов в комментариях → bot_mult (0.3-1.0)
- trust_score: доверие аудитории к контенту
- brand_safety: токсичность контента → safety_mult (0.0-1.0)

Использует Ollama + Qwen3-8B
"""

import json
import asyncio
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

import requests

# v2.1: Общие утилиты (clean_text)
from scanner.utils import clean_text

# v23.0: unified cache from cache.py
from scanner.cache import get_llm_cache

# v43.0: Централизованная конфигурация
# v51.0: MAX_POSTS_FOR_AI, MAX_CHARS_PER_POST для унификации
from scanner.config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    MAX_POSTS_FOR_AI,
    MAX_CHARS_PER_POST,
)

# === V2.0: JSON REPAIR ===
try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    print("WARNING: json_repair not installed. pip install json-repair")


# === V2.0: JSON PARSING ===

def safe_parse_json(response: str, default_values: dict = None) -> tuple:
    """
    V2.0: Безопасный парсинг JSON от LLM с multi-level fallback.

    Levels:
    1. Direct json.loads (find JSON object in text)
    2. json_repair library (fix trailing commas, etc.)
    3. Regex extraction of known fields

    Returns:
        (data, warnings): parsed dict and list of warnings
    """
    warnings = []

    if not response or not response.strip():
        warnings.append("Empty response from LLM")
        return default_values or {}, warnings

    # Level 1: Find and parse JSON object
    try:
        # Find balanced braces
        start_idx = response.find('{')
        if start_idx != -1:
            depth = 0
            end_idx = start_idx
            for i, char in enumerate(response[start_idx:], start_idx):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break

            json_candidate = response[start_idx:end_idx]
            data = json.loads(json_candidate)
            warnings.append("L1: Direct JSON parse succeeded")
            return _fill_defaults(data, default_values), warnings
    except json.JSONDecodeError as e:
        warnings.append(f"L1: JSON decode error - {e.msg}")
    except (IndexError, KeyError) as e:
        # IndexError: при работе с индексами response
        # KeyError: при доступе к dict ключам
        warnings.append(f"L1: Parse error - {e}")

    # Level 2: json_repair library
    if HAS_JSON_REPAIR:
        try:
            repaired = repair_json(response)
            if repaired:
                data = json.loads(repaired)
                warnings.append("L2: json_repair succeeded")
                return _fill_defaults(data, default_values), warnings
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # json_repair может вернуть невалидный JSON или сломаться
            warnings.append(f"L2: json_repair failed - {e}")
    else:
        warnings.append("L2: json_repair not installed, skipping")

    # Level 3: Regex extraction
    try:
        data = _regex_extract_fields(response)
        if data:
            warnings.append(f"L3: Regex extracted {len(data)} fields")
            return _fill_defaults(data, default_values), warnings
    except (re.error, TypeError, AttributeError) as e:
        # re.error: ошибка регулярки, TypeError/AttributeError: неверный тип данных
        warnings.append(f"L3: Regex extraction failed - {e}")

    warnings.append("FAILED: All parsing levels exhausted")
    return default_values or {}, warnings


def _fill_defaults(data: dict, default_values: dict) -> dict:
    """Fill missing fields with defaults."""
    if not default_values:
        return data

    for key, default in default_values.items():
        if key not in data or data[key] is None:
            data[key] = default

    return data


def _regex_extract_fields(response: str) -> dict:
    """Level 3: Extract fields via regex patterns."""
    patterns = {
        "toxicity": r'"?toxicity"?\s*[:\s]+(\d+)',
        "violence": r'"?violence"?\s*[:\s]+(\d+)',
        "military_conflict": r'"?military_conflict"?\s*[:\s]+(\d+)',
        "political_quantity": r'"?political_quantity"?\s*[:\s]+(\d+)',
        "political_risk": r'"?political_risk"?\s*[:\s]+(\d+)',
        "misinformation": r'"?misinformation"?\s*[:\s]+(\d+)',
        "ad_percentage": r'"?ad_percentage"?\s*[:\s]+(\d+)',
    }

    data = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            try:
                data[field] = int(match.group(1))
            except ValueError:
                pass

    # Extract red_flags array
    flags_match = re.search(r'"?red_flags"?\s*:\s*\[(.*?)\]', response, re.DOTALL)
    if flags_match:
        content = flags_match.group(1).strip()
        data["red_flags"] = re.findall(r'"([^"]+)"', content) if content else []

    return data if data else None


# === КОНФИГУРАЦИЯ ===
# v43.0: OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, MAX_RETRIES, RETRY_DELAY
# импортируются из scanner.config
# v23.0: кэширование через unified cache.py (get_llm_cache)

# DEBUG
DEBUG_LLM_ANALYZER = False  # v41.0: отключен для компактного вывода

# Лимиты (v51.0: унифицированы через config.py)
MAX_POSTS_FOR_ANALYSIS = MAX_POSTS_FOR_AI  # из config.py (50)
MAX_COMMENTS_FOR_ANALYSIS = 999  # v40.2: без лимита (сколько API даёт)
# MAX_CHARS_PER_POST теперь импортируется из config.py (800)


# === РЕЗУЛЬТАТЫ ===

@dataclass
class PostAnalysisResult:
    """Результат анализа постов V2.0"""
    brand_safety: int          # 0-100 (100 = безопасно), ВЫЧИСЛЯЕТСЯ В PYTHON
    toxicity: int              # 0-100 (hate speech, дискриминация)
    violence: int              # 0-100 (призывы к насилию, графический контент)
    military_conflict: int     # 0-100 (V2.0: военный контент, отдельно от violence)
    political_quantity: int    # 0-100 (% постов с политикой)
    political_risk: int        # 0-100 (опасность политического контента)
    misinformation: int        # 0-100
    ad_percentage: int         # 0-100%
    red_flags: list
    raw_response: str = ""
    _brand_details: dict = None  # V2.0: calculation breakdown for debugging

    # Backwards compatibility: property для старого кода
    @property
    def political(self) -> int:
        """Для обратной совместимости: возвращает political_risk"""
        return self.political_risk


@dataclass
class CommentAnalysisResult:
    """Результат анализа комментариев v41.0 (без authenticity)"""
    bot_percentage: int        # 0-100% (главная метрика)
    bot_signals: list
    trust_score: int           # 0-100
    trust_signals: list
    raw_response: str = ""


@dataclass
class LLMAnalysisResult:
    """Полный результат LLM анализа v46.0"""
    posts: Optional[PostAnalysisResult]
    comments: Optional[CommentAnalysisResult]

    # v46.0: Brand Safety результат
    safety: Optional[dict] = None    # {is_toxic, toxic_category, severity, ...}

    # Расчётные метрики
    llm_bonus: float = 0.0           # +0-15 points
    llm_trust_factor: float = 1.0    # ×0.15-1.0

    # v37.0: Трёхэтапная система
    tier: str = "PREMIUM"            # PREMIUM/STANDARD/LIMITED/RESTRICTED/EXCLUDED
    tier_cap: int = 100              # Максимальный скор для тира
    exclusion_reason: Optional[str] = None  # Причина исключения (если EXCLUDED)

    # v46.0: Детали для отладки (ad_mult + bot_mult + safety_mult)
    _ad_mult: float = 1.0            # v41.0: множитель от ad_percentage
    _safety_mult: float = 1.0        # v46.0: множитель от Brand Safety
    _comment_mult: float = 1.0       # bot_mult
    _political_mult: float = 1.0

    def calculate_impact_v2(self):
        """
        V3.0 (v41.0): Unified LLM Trust Factor.

        Объединяет ad_mult (из ad_percentage) и bot_mult (из bot_percentage).
        Оба фактора перемножаются для финального llm_trust_factor.
        """
        # Дефолтные значения
        self.tier = "STANDARD"
        self.tier_cap = 85
        self.exclusion_reason = None
        self.llm_bonus = 5.0  # Фиксированный бонус

        # --- Ad Multiplier (v45.0) ---
        # Ужесточённые пороги для защиты бюджета рекламодателя
        # При 40% рекламы аудитория уже "выжжена"
        ad_mult = 1.0
        if self.posts and self.posts.ad_percentage is not None:
            ad_pct = self.posts.ad_percentage
            if ad_pct <= 15:
                ad_mult = 1.0      # Премиум канал
            elif ad_pct <= 20:
                ad_mult = 0.95     # Норма
            elif ad_pct <= 25:
                ad_mult = 0.85     # Начало штрафа
            elif ad_pct <= 30:
                ad_mult = 0.70     # Много рекламы
            elif ad_pct <= 40:
                ad_mult = 0.50     # Выжженная аудитория
            elif ad_pct <= 50:
                ad_mult = 0.35     # Очень много
            else:
                ad_mult = 0.20     # Спам
        self._ad_mult = ad_mult

        # --- Bot Multiplier (v40.3) ---
        bot_mult = 1.0
        if self.comments and self.comments.bot_percentage is not None:
            bot_pct = self.comments.bot_percentage
            if bot_pct <= 15:
                bot_mult = 1.0
            else:
                # Линейный штраф от 15% до 85%
                penalty = (bot_pct - 15) / 100.0
                bot_mult = max(0.3, 1.0 - penalty)
        self._comment_mult = bot_mult

        # --- Brand Safety Multiplier (v47.0) ---
        # SAFE/LOW = 1.0, MEDIUM = 0.7, HIGH = 0.3, CRITICAL = 0.0 (EXCLUDED)
        safety_mult = 1.0
        if self.safety and self.safety.get('is_toxic'):
            severity = self.safety.get('severity', 'SAFE')

            # Множители по severity_label (v47.0)
            if severity == 'CRITICAL':
                safety_mult = 0.0  # EXCLUDED
                self.tier = "EXCLUDED"
                self.tier_cap = 0
                self.exclusion_reason = f"TOXIC_{self.safety.get('toxic_category', 'CONTENT')}"
            elif severity == 'HIGH':
                safety_mult = 0.3
                self.tier = "RESTRICTED"
                self.tier_cap = 30
            elif severity == 'MEDIUM':
                safety_mult = 0.7
            # LOW/SAFE не штрафуем
        self._safety_mult = safety_mult

        # --- Combined LLM Trust Factor (v47.0) ---
        # Перемножаем независимые факторы с floor 0.15
        self.llm_trust_factor = max(0.15, ad_mult * bot_mult * safety_mult)

        # v47.0: EXCLUDED override (safety_mult = 0)
        if safety_mult == 0.0:
            self.llm_trust_factor = 0.0

        self._political_mult = 1.0

        if DEBUG_LLM_ANALYZER:
            print(f"📊 V46.0: ad={ad_mult:.2f}, bot={bot_mult:.2f}, safety={safety_mult:.2f} → llm_trust={self.llm_trust_factor:.2f}")


# === КЭШИРОВАНИЕ ===
# v23.0: unified cache from cache.py
# Старые функции _load_cache/_save_cache удалены
# Используем get_llm_cache() в классе LLMAnalyzer

# === ПОДГОТОВКА ДАННЫХ ===

def _detect_footer(posts_texts: list, min_occurrences: int = 5) -> Optional[str]:
    """
    Находит повторяющийся футер в постах.
    Футер = текст в конце поста, который повторяется в min_occurrences постах.
    """
    if len(posts_texts) < min_occurrences:
        return None

    # Берём последние 200 символов каждого поста
    endings = []
    for text in posts_texts:
        if len(text) > 50:
            endings.append(text[-200:])

    if len(endings) < min_occurrences:
        return None

    # Ищем общие подстроки в концах
    # Простой подход: ищем строки которые встречаются часто
    from collections import Counter

    # Разбиваем на строки и ищем повторяющиеся блоки
    line_counts = Counter()
    for ending in endings:
        lines = ending.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) > 10:  # Игнорируем короткие строки
                line_counts[line] += 1

    # Находим строки которые встречаются в >50% постов
    threshold = len(posts_texts) * 0.4
    footer_lines = [line for line, count in line_counts.items() if count >= threshold]

    if footer_lines:
        return footer_lines[0]  # Возвращаем самую частую
    return None


def _remove_footer(text: str, footer: str) -> str:
    """Удаляет футер из текста"""
    if not footer:
        return text

    # Пробуем удалить строку с футером и всё после неё
    idx = text.find(footer)
    if idx > 0:
        return text[:idx].strip()
    return text


def _prepare_posts_text(messages: list) -> str:
    """Подготавливает текст постов для анализа v35.1"""
    # Сначала собираем все тексты
    raw_texts = []
    for msg in messages[:MAX_POSTS_FOR_ANALYSIS]:
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text
        if text and len(text) > 30:
            raw_texts.append(clean_text(text))

    # Детектим повторяющийся футер
    footer = _detect_footer(raw_texts)
    if footer and DEBUG_LLM_ANALYZER:
        print(f"DETECTED FOOTER: '{footer[:50]}...'")

    # Формируем посты без футера
    posts = []
    for i, text in enumerate(raw_texts):
        clean = _remove_footer(text, footer)[:MAX_CHARS_PER_POST]
        if clean and len(clean) > 30:
            posts.append(f"[Post {i+1}]: {clean}")

    return "\n\n".join(posts)


def _prepare_comments_text(comments: list) -> str:
    """Подготавливает текст комментариев для анализа"""
    texts = []
    for i, comment in enumerate(comments[:MAX_COMMENTS_FOR_ANALYSIS]):
        text = ""
        if hasattr(comment, 'message') and comment.message:
            text = comment.message
        elif hasattr(comment, 'text') and comment.text:
            text = comment.text
        elif isinstance(comment, str):
            text = comment

        if text:
            clean = clean_text(text)[:200]
            if clean and len(clean) > 5:
                texts.append(f"[{i+1}]: {clean}")

    return "\n".join(texts)


# === OLLAMA API ===

def _call_ollama(system_prompt: str, user_message: str, retry_count: int = 0) -> Optional[str]:
    """
    Запрос к Ollama с retry логикой.
    v43.0: Добавлен retry при таймаутах (из classifier.py).
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "stream": False,
        "think": False,
        "keep_alive": -1,  # v38.0: Никогда не выгружать модель из памяти
        "options": {
            "temperature": 0.3,
            "num_predict": 500
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        if response.status_code != 200:
            print(f"OLLAMA: HTTP {response.status_code}")
            return None

        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        return content

    except requests.exceptions.ConnectionError:
        print("OLLAMA: Не запущен! Запусти: ollama serve")
        return None
    except requests.exceptions.Timeout:
        if retry_count < MAX_RETRIES:
            wait = RETRY_DELAY * (retry_count + 1)
            print(f"OLLAMA: Таймаут, retry {retry_count + 1}/{MAX_RETRIES} через {wait}с...")
            time.sleep(wait)
            return _call_ollama(system_prompt, user_message, retry_count + 1)
        print(f"OLLAMA: Таймаут после {MAX_RETRIES} попыток!")
        return None
    except (KeyError, TypeError, ValueError) as e:
        # KeyError: неожиданная структура JSON ответа
        # TypeError/ValueError: ошибки преобразования данных
        print(f"OLLAMA: Ошибка обработки ответа - {e}")
        return None


# === CHANNEL TYPE DETECTION V40.0 ===

CHANNEL_TYPE_KEYWORDS = {
    "TECH": ["python", "javascript", "код", "программ", "dev", "api", "github", "npm", "docker", "react", "vue", "backend", "frontend", "llm", "ml", "ai", "нейросет", "модел", "gpt", "ollama", "gguf"],
    "CRYPTO": ["btc", "eth", "крипт", "токен", "defi", "nft", "блокчейн", "биткоин", "эфир", "coin", "swap", "airdrop", "wallet"],
    "NEWS": ["новости", "news", "срочно", "breaking", "политик", "экономик", "инфляц", "курс валют"],
    "ENTERTAINMENT": ["мем", "юмор", "прикол", "смешн", "фильм", "сериал", "игр", "anime", "аниме", "музык"],
    "BUSINESS": ["бизнес", "стартап", "предприним", "маркетинг", "продаж", "финанс", "инвестиц", "акци"],
}


def infer_channel_type(messages: list = None, category: str = None) -> str:
    """
    V40.0: Определяет тип канала для калибровки промптов.

    Args:
        messages: Список постов (для анализа по ключевым словам)
        category: Категория из classifier (TECH, AI_ML, CRYPTO, etc.)

    Returns:
        str: TECH, CRYPTO, NEWS, ENTERTAINMENT, BUSINESS, или GENERAL
    """
    # Приоритет 1: Explicit category from classifier
    if category:
        cat_upper = category.upper()
        if cat_upper in ["TECH", "AI_ML", "EDUCATION"]:
            return "TECH"
        if cat_upper == "CRYPTO":
            return "CRYPTO"
        if cat_upper == "NEWS":
            return "NEWS"
        if cat_upper in ["ENTERTAINMENT", "LIFESTYLE"]:
            return "ENTERTAINMENT"
        if cat_upper in ["BUSINESS", "FINANCE", "REAL_ESTATE"]:
            return "BUSINESS"

    # Приоритет 2: Анализ контента
    if not messages:
        return "GENERAL"

    # Собираем текст из первых 20 постов
    text_blob = ""
    for msg in messages[:20]:
        if hasattr(msg, 'message') and msg.message:
            text_blob += msg.message.lower() + " "
        elif hasattr(msg, 'text') and msg.text:
            text_blob += msg.text.lower() + " "

    if not text_blob:
        return "GENERAL"

    # Подсчитываем совпадения по типам
    scores = {}
    for ctype, keywords in CHANNEL_TYPE_KEYWORDS.items():
        scores[ctype] = sum(1 for kw in keywords if kw in text_blob)

    # Возвращаем тип с максимальным score (если >= 3 совпадений)
    if scores:
        best_type = max(scores, key=scores.get)
        if scores[best_type] >= 3:
            return best_type

    return "GENERAL"


# === BRAND SAFETY ANALYZER V47.1 (Crypto Trading Context Trap) ===

BRAND_SAFETY_SYSTEM = """You are a Brand Safety Auditor (V47.1).
Your mission is to protect advertisers from placing ads in TOXIC channels (Gambling, Adult, Scam).
You analyze semantic meaning, ignoring obfuscation (leetspeak) and respecting context.

## 🚫 TOXIC CATEGORIES (DETECTION RULES)

### 1. GAMBLING 🎰
- **Targets:** Online casinos, slots, roulette, sports betting, bookmakers.
- **Keywords:** k@zino, sl0ts, 1win, 1xbet, stake, "raising money", "guaranteed profit schemes", "spin".
- **CONTEXT TRAP (SAFE - DO NOT FLAG):**
    - **Crypto Trading/Scalping:** Futures, Long/Short positions, Leverage (x100), Liquidation ("ликвиднулся", "rekt"), "Catching a move/knife".
    - **Exchanges (Safe):** Binance, Bybit, MEXC ("мекс"), OKX, BingX. (These are NOT casinos).
    - **Trading Slang:** "Algo trading" ("алгосы"), "Screener", "Setup", "Spread 10$" ("раскинуть", meaning diversify).
    - **Stock Market:** IPO, volatility, dividends.
- **VERDICT:** Only flag if the post promotes CASINOS or BOOKMAKERS. Trading on exchanges is SAFE.

### 2. ADULT 🔞
- **Targets:** Pornography, Hentai, Escort, OnlyFans (NSFW).
- **Keywords:** p0rn, s.e.x, nudes, "hot girls", эскорт, интим.
- **CONTEXT TRAP (SAFE):** Dating advice, medical health discussions, relationship psychology, art/anime (non-explicit).
- **CRITICAL:** Any content involving minors = IMMEDIATE CRITICAL.
- **VERDICT:** Only flag if the intent is sexual arousal or soliciting services.

### 3. SCAM ⚠️
- **Targets:** Darknet markets, drugs, carding, cash-out schemes, fake documents.
- **Keywords:** даркнет, кладмен, обнал, дропы, CVV, fullz.
- **CONTEXT TRAP (SAFE):** True crime stories, cybersecurity education, crypto news, high-risk trading diaries (losing money on trading is NOT a scam).
- **VERDICT:** Only flag if the channel SELLS or PROMOTES illegal goods/services.

## 🛡️ CORE PRINCIPLES

1. **DE-OBFUSCATION:** Read "k@zin0" as "casino", "p0rn" as "porn".
2. **CONTEXT IS KING:** A trader losing money on "MEXC" is SAFE (High Risk Finance). A player winning on "1win" is TOXIC (Gambling).
3. **PATTERN OVER SINGLE POST:** One toxic post ≠ toxic channel. Look for recurring themes.
4. **CONSERVATIVE:** If you are not 100% sure it's toxic, it is CLEAN.

## OUTPUT INSTRUCTION

1. Analyze step-by-step in `reasoning`. Mention if you see Trading Context vs Gambling Context.
2. Count the EXACT number of toxic posts found.
3. Output valid JSON only."""

BRAND_SAFETY_PROMPT = """Analyze these posts for brand safety.

POSTS:
{posts_text}

Output JSON:
{{"reasoning": "<Explanation identifying context (e.g., 'User discusses futures trading on MEXC, mentions liquidation. This is Crypto Trading, NOT Gambling')>", "toxic_category": "GAMBLING"|"ADULT"|"SCAM"|null, "toxic_post_count": <int>, "total_posts": <int>, "evidence": ["toxic phrase 1", "toxic phrase 2"], "severity_label": "CRITICAL"|"HIGH"|"MEDIUM"|"LOW"|"SAFE"}}

SEVERITY GUIDE (use semantic judgement, not math):
- CRITICAL: Channel exists SOLELY for this toxic topic (Dominant theme, almost every post)
- HIGH: Frequent toxic posts mixed with normal content (Regular pattern)
- MEDIUM: Occasional promotional/toxic posts (Sometimes)
- LOW: Rare mentions or borderline cases (1-2 posts)
- SAFE: No toxic content found or context is clearly educational/news"""


def analyze_brand_safety(messages: list) -> Optional[dict]:
    """
    V47.0: LLM-based Brand Safety анализ (Grandmaster Edition).

    Улучшения V47.0:
    - Chain-of-Thought (reasoning field) для повышения точности
    - Semantic severity (не проценты, а смысл: "Dominant theme", "Occasional")
    - Context Traps — явные примеры SAFE случаев
    - De-obfuscation как Core Principle

    Returns:
        dict: {
            'is_toxic': bool,
            'toxic_category': 'GAMBLING'|'ADULT'|'SCAM'|None,
            'confidence': int (0-100),
            'toxic_ratio': float,
            'severity': 'CRITICAL'|'HIGH'|'MEDIUM'|'LOW'|'SAFE',
            'evidence': list[str],
            'reasoning': str  # V47.0: CoT explanation
        }
    """
    posts_text = _prepare_posts_text(messages)

    if not posts_text or len(posts_text) < 100:
        if DEBUG_LLM_ANALYZER:
            print("LLM BrandSafety: Недостаточно текста для анализа")
        return {
            'is_toxic': False,
            'toxic_category': None,
            'confidence': 0,
            'toxic_ratio': 0.0,
            'severity': 'SAFE',
            'evidence': [],
            'reasoning': 'Not enough text to analyze'
        }

    # Ограничиваем текст для LLM
    truncated_text = posts_text[:8000]

    prompt = BRAND_SAFETY_PROMPT.format(posts_text=truncated_text)

    if DEBUG_LLM_ANALYZER:
        print(f"\n{'='*60}")
        print(f"BRAND SAFETY ANALYZER V47.0 - {len(messages)} posts")
        print(f"{'='*60}\n")

    response = _call_ollama(BRAND_SAFETY_SYSTEM, prompt)

    if not response:
        return None

    if DEBUG_LLM_ANALYZER:
        print(f"BRAND SAFETY RESPONSE:\n{response[:500]}")

    # Парсим ответ
    default_values = {
        "reasoning": "",
        "toxic_category": None,
        "toxic_post_count": 0,
        "total_posts": len(messages),
        "evidence": [],
        "severity_label": "SAFE"
    }
    data, warnings = safe_parse_json(response, default_values)

    if DEBUG_LLM_ANALYZER and warnings:
        print(f"JSON PARSE WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if data:
        toxic_count = int(data.get("toxic_post_count", 0))
        total = int(data.get("total_posts", len(messages)))
        # V47.0: Python считает точный процент, не LLM
        toxic_ratio = toxic_count / total if total > 0 else 0.0

        category = data.get("toxic_category")
        severity = data.get("severity_label", "SAFE")
        reasoning = data.get("reasoning", "")

        # V47.0: Confidence вычисляем из severity (LLM больше не отвечает за confidence)
        # CRITICAL=95, HIGH=80, MEDIUM=60, LOW=40, SAFE=0
        severity_to_confidence = {
            "CRITICAL": 95,
            "HIGH": 80,
            "MEDIUM": 60,
            "LOW": 40,
            "SAFE": 0
        }
        confidence = severity_to_confidence.get(severity, 0)

        # V47.0: is_toxic определяется по severity_label
        # CRITICAL/HIGH = toxic, MEDIUM с ratio > 10% = toxic
        is_toxic = False
        if category and category != "null":
            if severity in ["CRITICAL", "HIGH"]:
                is_toxic = True
            elif severity == "MEDIUM" and toxic_ratio > 0.10:
                is_toxic = True

        result = {
            'is_toxic': is_toxic,
            'toxic_category': category if is_toxic else None,
            'confidence': confidence,
            'toxic_ratio': round(toxic_ratio, 3),
            'severity': severity,
            'evidence': data.get("evidence", [])[:5],  # Макс 5 примеров
            'reasoning': reasoning  # V47.0: CoT explanation
        }

        if DEBUG_LLM_ANALYZER:
            print(f"LLM BrandSafety V47.0: {severity}")
            if reasoning:
                # Показываем первые 150 символов reasoning
                print(f"  💭 Reasoning: {reasoning[:150]}...")
            if is_toxic:
                print(f"  ⚠️ TOXIC: {category} (ratio: {toxic_ratio:.1%})")
            else:
                print(f"  ✅ SAFE")

        return result

    return None


# === COMMENT ANALYZER V40.1 ===

COMMENT_ANALYZER_SYSTEM = """You are a Turing-Test Level Comment Analyst (V45.0).
Analyze the authenticity of the audience based on their comments relative to the Post Context.

## INPUT DATA
1. **CHANNEL INFO:** Type/Category.
2. **POST CONTEXT:** The text users are reacting to.
3. **COMMENTS:** User replies.

## ANALYSIS LOGIC

### 🤖 BOT SIGNALS (Red Flags)
1. **Language Mismatch:** English generic comments ("Great project", "Awesome", "Sir") on a Russian channel.
2. **Context Blindness:** - Post: "Bitcoin crashed, I lost everything."
   - Comment: "Great project! To the moon! 🔥" (Zero context awareness).
3. **Crypto Spam:** "Airdrop", "Claim reward", "Wallet connect", Asian characters spam.
4. **Pattern Repetition:** Multiple users posting identical phrases.

### 👤 HUMAN SIGNALS (Green Flags)
1. **Context Relevance:** Comments discussing specific details from the Post Context.
2. **Technical/Slang:** Terms like "deploy", "API", "скам", "ликвид", "имба".
3. **Debate/Negativity:** "Автор не прав", "Это не работает". Bots are rarely negative/argumentative.
4. **Brevity != Bot:** "+", "Согл", "Кек" are normal human reactions in Telegram.

Output ONLY valid JSON."""

COMMENT_ANALYZER_PROMPT_V3 = """Analyze these comments.

CHANNEL TYPE: {channel_type}
POST CONTEXT: {posts_context}
COMMENTS: {comments_text}

JSON Output:
{{"total_comments": <int>, "suspicious_bot_count": <int>, "bot_signals": ["list of specific reasons"], "authenticity_tier": "HIGH"|"MEDIUM"|"LOW", "trust_sentiment": "POSITIVE"|"NEGATIVE"|"SKEPTICAL"|"NEUTRAL"}}"""


def analyze_comments(comments: list, posts: list = None, channel_type: str = "GENERAL") -> Optional[CommentAnalysisResult]:
    """
    V40.0: Анализирует комментарии канала с учётом типа канала.

    Args:
        comments: Список комментариев
        posts: Контекст постов для sarcasm detection
        channel_type: Тип канала (TECH, CRYPTO, ENTERTAINMENT, etc.)
    """
    comments_text = _prepare_comments_text(comments)

    if not comments_text or len(comments_text) < 50:
        print("LLM CommentAnalyzer: Недостаточно комментариев для анализа")
        return None

    # V40.0: Контекст постов для sarcasm detection
    posts_context = "Нет контекста постов"
    if posts:
        posts_context = _prepare_posts_text(posts[:10])[:2000]

    # V40.0: Используем новый промпт с channel_type
    prompt = COMMENT_ANALYZER_PROMPT_V3.format(
        channel_type=channel_type,
        posts_context=posts_context,
        comments_text=comments_text  # v40.2: без лимита
    )

    if DEBUG_LLM_ANALYZER:
        print(f"\n{'='*60}")
        print(f"COMMENT ANALYZER V40.0 - {len(comments)} comments, {len(comments_text)} chars")
        print(f"Channel type: {channel_type} | Posts context: {len(posts_context)} chars")
        print(f"{'='*60}\n")

    response = _call_ollama(COMMENT_ANALYZER_SYSTEM, prompt)

    if not response:
        return None

    if DEBUG_LLM_ANALYZER:
        print(f"COMMENT ANALYZER RESPONSE:\n{response[:500]}")

    # V50.0: Новый формат с authenticity_tier
    default_values = {
        "total_comments": len(comments),
        "suspicious_bot_count": 0,
        "bot_signals": [],
        "authenticity_tier": "HIGH",
        "trust_sentiment": "NEUTRAL"
    }
    data, warnings = safe_parse_json(response, default_values)

    if DEBUG_LLM_ANALYZER and warnings:
        print(f"JSON PARSE WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if data:
        # V50.0: Конвертируем новый формат в старый для совместимости
        total = int(data.get("total_comments", len(comments)))
        bot_count = int(data.get("suspicious_bot_count", 0))

        # Поддержка старого формата (bot_percentage)
        if "bot_percentage" in data:
            bot_pct = int(data.get("bot_percentage", 0))
        else:
            bot_pct = int(bot_count / total * 100) if total > 0 else 0

        # V50.0: Конвертируем authenticity_tier в trust_score
        tier = data.get("authenticity_tier", "MEDIUM")
        if "trust_score" in data:
            trust_score = int(data.get("trust_score", 50))
        else:
            trust_map = {"HIGH": 95, "MEDIUM": 70, "LOW": 30}
            trust_score = trust_map.get(tier, 50)

        # V50.0: trust_sentiment как trust_signal
        sentiment = data.get("trust_sentiment", "NEUTRAL")
        trust_signals = data.get("trust_signals", [f"Sentiment: {sentiment}"])

        return CommentAnalysisResult(
            bot_percentage=bot_pct,
            bot_signals=data.get("bot_signals", []),
            trust_score=trust_score,
            trust_signals=trust_signals,
            raw_response=response
        )

    if DEBUG_LLM_ANALYZER:
        print(f"COMMENT ANALYZER: Failed to parse response")
    return None


# === AD PERCENTAGE ANALYZER V40.0 ===

AD_ANALYZER_SYSTEM = """You are a conservative Advertising Auditor for Telegram channels (V50.0).
Your goal is to identify paid promotional content with 100% certainty.

## CORE PHILOSOPHY
- **Conservative Approach:** If you are 99% sure it is an ad, but have 1% doubt -> IT IS NOT AN AD.
- **False Positives are fatal:** Marking a genuine review or job post as an "Ad" is a critical failure.

## CLASSIFICATION RULES

### ✅ DEFINITELY AN AD (Count this)
1. **Explicit Tags:** #реклама, #ad, #партнёр, #promo, "erid:".
2. **Paid Markers:** "На правах рекламы", "Спонсор поста", "Заказать рекламу можно тут".
3. **External Push:** Aggressive sales pitch for a 3rd party product with a distinct call-to-action ("Buy now", "Subscribe here").

### ❌ NOT AN AD (Ignore this)
1. **Self-Promotion:** Author promoting their own course, chat, or product (Internal traffic).
2. **Job/Hiring:** "Looking for a developer", "Vacancy".
3. **Genuine Reviews:** "I tested X and liked it" (without promo codes or tracking links).
4. **Cross-promo:** "Subscribe to my friend's channel" (unless clearly paid).
5. **Donations:** Patreon, Boosty, "Support the channel".

## OUTPUT FORMAT
1. First, provide a brief **Reasoning** listing IDs of posts identified as ads.
2. Then, output strictly valid JSON."""

AD_ANALYZER_PROMPT = """Analyze the provided list of posts.
Input Format: <id> text...

POSTS:
{posts_text}

Output JSON structure:
{{"total_posts_scanned": <int>, "ad_post_count": <int>, "ad_post_ids": [<list of integers>], "reasoning": "Brief explanation of why detected posts are ads"}}"""


def analyze_ad_percentage(messages: list) -> Optional[int]:
    """
    V38.0: Лёгкий анализ только ad_percentage через LLM.

    Более точный чем keyword-based, так как понимает контекст.
    Быстрее чем полный PostAnalyzer (5-10 сек vs 30+ сек).

    Returns:
        int: процент рекламных постов (0-100) или None при ошибке
    """
    posts_text = _prepare_posts_text(messages)

    if not posts_text or len(posts_text) < 100:
        if DEBUG_LLM_ANALYZER:
            print("LLM AdAnalyzer: Недостаточно текста для анализа")
        return None

    # v41.0: Обрезаем текст и считаем РЕАЛЬНОЕ количество постов в обрезанном тексте
    truncated_text = posts_text[:6000]
    actual_posts_count = truncated_text.count("[Post ")

    prompt = AD_ANALYZER_PROMPT.format(posts_text=truncated_text)

    if DEBUG_LLM_ANALYZER:
        print(f"\n{'='*60}")
        print(f"AD ANALYZER V40.0 - {len(messages)} posts, {len(posts_text)} chars")
        print(f"{'='*60}\n")

    response = _call_ollama(AD_ANALYZER_SYSTEM, prompt)

    if not response:
        return None

    if DEBUG_LLM_ANALYZER:
        print(f"AD ANALYZER RESPONSE:\n{response[:300]}")

    # V50.0: Новый формат с ad_post_count
    default_values = {"ad_post_count": 0, "total_posts_scanned": len(messages), "ad_post_ids": []}
    data, warnings = safe_parse_json(response, default_values)

    if DEBUG_LLM_ANALYZER and warnings:
        print(f"JSON PARSE WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if data:
        # V50.0: Поддержка нового формата (ad_post_count) и старого (ad_count)
        ad_count = int(data.get("ad_post_count", 0) or data.get("ad_count", 0))

        # v41.0: Используем РЕАЛЬНОЕ количество постов, не то что LLM посчитал
        total = actual_posts_count if actual_posts_count > 0 else len(messages)

        # Пересчитываем процент на основе реального количества
        if total > 0:
            ad_pct = int(ad_count / total * 100)
        else:
            ad_pct = 0

        if DEBUG_LLM_ANALYZER:
            print(f"LLM AdAnalyzer: {ad_pct}% рекламы ({ad_count}/{total} постов)")
        return max(0, min(100, ad_pct))  # Clamp 0-100

    if DEBUG_LLM_ANALYZER:
        print(f"AD ANALYZER: Failed to parse response")
    return None


# === ГЛАВНЫЙ АНАЛИЗАТОР ===

class LLMAnalyzer:
    """Полный LLM анализ канала V40.0"""

    def __init__(self):
        # v23.0: unified cache from cache.py
        self.cache = get_llm_cache()
        print(f"LLM Analyzer: Ollama ({OLLAMA_MODEL})")

    def analyze(
        self,
        channel_id: int,
        messages: list,
        comments: list,
        category: str = "DEFAULT"
    ) -> LLMAnalysisResult:
        """
        V40.0: Полный анализ канала с учётом типа канала.

        Args:
            channel_id: ID канала
            messages: Список постов
            comments: Список комментариев
            category: Категория канала (для корректировок)

        Returns:
            LLMAnalysisResult с метриками
        """
        result = LLMAnalysisResult(posts=None, comments=None, safety=None)

        # V40.0: Определяем тип канала для калибровки промптов
        channel_type = infer_channel_type(messages, category)
        if DEBUG_LLM_ANALYZER:
            print(f"📊 Channel type detected: {channel_type} (category: {category})")

        # V46.0: Brand Safety анализ (перед Ad, чтобы сразу EXCLUDED если CRITICAL)
        safety_result = analyze_brand_safety(messages)
        if safety_result:
            result.safety = safety_result
            if safety_result.get('is_toxic') and safety_result.get('severity') == 'CRITICAL':
                # CRITICAL = сразу EXCLUDED, пропускаем остальные анализы
                if DEBUG_LLM_ANALYZER:
                    print(f"⛔ CRITICAL TOXIC: {safety_result.get('toxic_category')} - skipping other analysis")
                result.calculate_impact_v2()
                return result

        # V40.0: Ad Percentage с улучшенным промптом
        ad_pct = analyze_ad_percentage(messages)
        if ad_pct is not None:
            result.posts = PostAnalysisResult(
                brand_safety=100,  # Не анализируем (бесполезно)
                toxicity=0,
                violence=0,
                military_conflict=0,
                political_quantity=0,
                political_risk=0,
                misinformation=0,
                ad_percentage=ad_pct,
                red_flags=[]
            )

        # V40.0: Comment Analyzer с учётом типа канала
        if comments and len(comments) >= 5:
            result.comments = analyze_comments(comments, posts=messages, channel_type=channel_type)
        elif DEBUG_LLM_ANALYZER:
            # v42.0: под DEBUG флаг
            print(f"LLM: Пропуск CommentAnalyzer (мало комментов: {len(comments) if comments else 0})")

        # V2.1: Упрощённый impact — только от комментариев
        result.calculate_impact_v2()

        return result

    def save_cache(self):
        # v23.0: unified cache from cache.py (JSONCache автоматически сохраняет)
        pass  # JSONCache сохраняет при каждом set(), явный save не нужен


# v42.0: Удалён мёртвый код print_analysis_result() — 0 вызовов в проекте
