"""
LLM Анализатор каналов v41.0

Два модуля:
1. AdAnalyzer — % рекламных постов (контекстный анализ через LLM)
2. CommentAnalyzer — Bot Detection + Trust Score

v41.0 изменения:
- ad_percentage теперь влияет на llm_trust_factor (ad_mult)
- authenticity УДАЛЕНА (дубликат bot_percentage)
- Unified: llm_trust_factor = ad_mult × bot_mult
- Keyword-based ad_load больше не используется

Метрики:
- ad_percentage: % рекламных постов → ad_mult (0.4-1.0)
- bot_percentage: % ботов в комментариях → bot_mult (0.3-1.0)
- trust_score: доверие аудитории к контенту

Использует Ollama + Qwen3-8B
"""

import json
import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

import requests

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
    except Exception as e:
        warnings.append(f"L1: Parse error - {e}")

    # Level 2: json_repair library
    if HAS_JSON_REPAIR:
        try:
            repaired = repair_json(response)
            if repaired:
                data = json.loads(repaired)
                warnings.append("L2: json_repair succeeded")
                return _fill_defaults(data, default_values), warnings
        except Exception as e:
            warnings.append(f"L2: json_repair failed - {e}")
    else:
        warnings.append("L2: json_repair not installed, skipping")

    # Level 3: Regex extraction
    try:
        data = _regex_extract_fields(response)
        if data:
            warnings.append(f"L3: Regex extracted {len(data)} fields")
            return _fill_defaults(data, default_values), warnings
    except Exception as e:
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

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_TIMEOUT = 180  # Больше чем classifier — анализ сложнее

# Кэш
CACHE_DIR = Path(__file__).parent.parent / "cache"
LLM_CACHE_FILE = CACHE_DIR / "llm_analyzer_cache.json"
CACHE_TTL_DAYS = 7

# DEBUG
DEBUG_LLM_ANALYZER = False  # v41.0: отключен для компактного вывода

# Лимиты
MAX_POSTS_FOR_ANALYSIS = 30
MAX_COMMENTS_FOR_ANALYSIS = 999  # v40.2: без лимита (сколько API даёт)
MAX_CHARS_PER_POST = 600


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
    """Полный результат LLM анализа v41.0"""
    posts: Optional[PostAnalysisResult]
    comments: Optional[CommentAnalysisResult]

    # Расчётные метрики
    llm_bonus: float = 0.0           # +0-15 points
    llm_trust_factor: float = 1.0    # ×0.15-1.0

    # v37.0: Трёхэтапная система
    tier: str = "PREMIUM"            # PREMIUM/STANDARD/LIMITED/RESTRICTED/EXCLUDED
    tier_cap: int = 100              # Максимальный скор для тира
    exclusion_reason: Optional[str] = None  # Причина исключения (если EXCLUDED)

    # v41.0: Детали для отладки (ad_mult + bot_mult)
    _ad_mult: float = 1.0            # v41.0: множитель от ad_percentage
    _brand_mult: float = 1.0
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

        # --- Ad Multiplier (v41.0) ---
        ad_mult = 1.0
        if self.posts and self.posts.ad_percentage is not None:
            ad_pct = self.posts.ad_percentage
            if ad_pct <= 20:
                ad_mult = 1.0      # Норма
            elif ad_pct <= 35:
                ad_mult = 0.85     # Много рекламы
            elif ad_pct <= 50:
                ad_mult = 0.65     # Очень много
            else:
                ad_mult = 0.40     # Спам
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

        # --- Combined LLM Trust Factor (v41.0) ---
        # Перемножаем независимые факторы с floor 0.15
        self.llm_trust_factor = max(0.15, ad_mult * bot_mult)

        self._brand_mult = 1.0
        self._political_mult = 1.0

        if DEBUG_LLM_ANALYZER:
            print(f"📊 V3.0: ad_mult={ad_mult:.2f}, bot_mult={bot_mult:.2f} → llm_trust={self.llm_trust_factor:.2f}")


# === КЭШИРОВАНИЕ ===

def _load_cache() -> dict:
    if not LLM_CACHE_FILE.exists():
        return {}
    try:
        with open(LLM_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        with open(LLM_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"LLM Cache save error: {e}")


# === ПОДГОТОВКА ДАННЫХ ===

def _clean_text(text: str) -> str:
    """Очищает текст от ссылок и лишнего"""
    if not text:
        return ""
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r't\.me/\S+', '', text)
    text = re.sub(r'[\U0001F600-\U0001F64F]{3,}', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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
            raw_texts.append(_clean_text(text))

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
            clean = _clean_text(text)[:200]
            if clean and len(clean) > 5:
                texts.append(f"[{i+1}]: {clean}")

    return "\n".join(texts)


# === OLLAMA API ===

def _call_ollama(system_prompt: str, user_message: str) -> Optional[str]:
    """Запрос к Ollama"""
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
        print(f"OLLAMA: Таймаут ({OLLAMA_TIMEOUT} сек)")
        return None
    except Exception as e:
        print(f"OLLAMA: Ошибка - {e}")
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


# === COMMENT ANALYZER V40.1 ===

COMMENT_ANALYZER_SYSTEM = """You are a comment authenticity analyzer V40.1.
Your goal is ACCURATE bot detection. Most Telegram channels have 0-5% bots.

## CRITICAL: 0% BOTS IS NORMAL!
Healthy channels typically have ZERO bots. Only count as bot if you see CLEAR evidence.
Do NOT inflate bot_percentage "just in case" - that creates false positives.

## WHAT MAKES A COMMENT HUMAN (NOT bot):

1. TECHNICAL TERMS = 100% HUMAN
   "gguf", "npm", "API", "llama.cpp", version numbers, library names
   → Bots cannot generate domain-specific knowledge

2. EMOTION = 100% HUMAN
   Profanity, frustration, sarcasm, arguments, memes, slang
   "ЗАЕБАЛСЯ", "ниипёт", "горишь", "садись, два" → definitely human

3. CONVERSATION = 100% HUMAN
   Back-and-forth dialogue, follow-up questions, corrections
   "Жду gguf" → "Выложили" → "качаю" = real users talking

4. SHORT ≠ BOT
   "works", "+1", "спасибо", "ггуф нужен)" are NORMAL human replies

## WHAT MAKES A COMMENT BOT:

Count as BOT if you see these patterns:
- IDENTICAL text from multiple users (copy-paste)
- Generic English praise on Russian channel ("Great post!", "Amazing!")
- Promotional spam unrelated to channel topic
- Motivational quotes with no connection to content

## CRYPTO SPAM = ALWAYS BOT (very important!):
- Airdrop spam: "Клеймим Аирдроп", "дроп от", "клейм токена", "claim", "airdrop"
- Korean/Chinese spam on Russian channel (에어드랍, 드롭, 클레임)
- Phishing links: random domains with /claim, /airdrop, /reward
- Link-only comments (just URL, no context)
- "Проверьте кошелёк", "check your wallet" spam

Output ONLY valid JSON."""

COMMENT_ANALYZER_PROMPT_V3 = """Analyze these Telegram comments for bot detection.

## CHANNEL TYPE: {channel_type}

## POST CONTEXT:
{posts_context}

## COMMENTS:
{comments_text}

---

## YOUR TASK:

Count how many comments are CLEARLY bots vs humans.

### HUMAN indicators (count as REAL):
- Any technical jargon or domain knowledge
- Profanity, emotion, sarcasm, slang
- Questions about the post content
- Debates, disagreements, corrections
- Personal experience ("я пробовал", "у меня работает")
- Conversation flow (replies to each other)
- Short but contextually relevant ("works", "+1", "спасибо")

### BOT indicators (count as BOT):
- IDENTICAL text from different users (copy-paste)
- Generic English on Russian channel ("Great!", "Amazing!")
- Completely off-topic spam
- Suspiciously formal language
- CRYPTO SPAM (count ALL as bots!):
  * Airdrop messages: "Клеймим Аирдроп", "дроп от", "клейм токена"
  * Korean/Chinese text on Russian channel (에어드랍, 드롭)
  * Phishing links: domains with /claim, /airdrop, /reward
  * Link-only comments (just URL without context)
  * "Проверьте кошелёк" wallet check spam

## CALIBRATION:

IMPORTANT: Most healthy channels have 0-5% bots!
- If all comments have personality/context → bot_percentage = 0%
- If 1-2 generic comments in 50 → bot_percentage = 2-4%
- If 5+ identical/spam comments → bot_percentage = 10%+

Only high bot_percentage (>10%) if you see MULTIPLE clear bot patterns.

## EXAMPLES:

Channel with 50 comments, all have technical terms or emotion:
→ bot_percentage = 0%

Channel with 50 comments, 2 say just "👍" on technical post:
→ bot_percentage = 4%

Channel with 50 comments, 10 are identical "Отличный пост!":
→ bot_percentage = 20%

Output ONLY this JSON format (NO other fields!):
{{"bot_percentage": <0-100>, "bot_signals": [<patterns found>], "trust_score": <0-100>, "trust_signals": [<positive signals>]}}"""


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

    # V2.0: Use safe_parse_json with fallback (v41.0: no authenticity)
    default_values = {
        "bot_percentage": 50,
        "bot_signals": [],
        "trust_score": 50,
        "trust_signals": []
    }
    data, warnings = safe_parse_json(response, default_values)

    if DEBUG_LLM_ANALYZER and warnings:
        print(f"JSON PARSE WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if data:
        return CommentAnalysisResult(
            bot_percentage=int(data.get("bot_percentage", 50)),
            bot_signals=data.get("bot_signals", []),
            trust_score=int(data.get("trust_score", 50)),
            trust_signals=data.get("trust_signals", []),
            raw_response=response
        )

    if DEBUG_LLM_ANALYZER:
        print(f"COMMENT ANALYZER: Failed to parse response")
    return None


# === AD PERCENTAGE ANALYZER V40.0 ===

AD_ANALYZER_SYSTEM = """You are a Telegram advertising analyst V40.0.
Your goal is ACCURATE classification, not maximum ad detection.
CRITICAL: Distinguish between THIRD-PARTY ADS and AUTHOR'S OWN CONTENT.
When uncertain, default to NOT counting as ad.
Output ONLY valid JSON, no other text."""

AD_ANALYZER_PROMPT = """Analyze advertising content in this Telegram channel.

POSTS:
{posts_text}

---

## STEP 1: DETECT CHANNEL TYPE (do this FIRST!)

Look at ALL posts and determine what kind of channel this is:
- ARTIST/CREATOR: Posts about paintings, drawings, music, designs, handmade items
- DEVELOPER: Posts about code, projects, tools, tutorials
- BLOGGER: Personal stories, opinions, lifestyle content
- NEWS: Reposts, aggregated content from other sources
- COMPANY: Official brand channel

⚠️ CRITICAL RULE: If channel is ARTIST/CREATOR type:
- Posts selling their own artwork (auctions, prices, "ставки") = NOT ADS (0%)
- Posts about their own creative process = NOT ADS
- Links to their own store/gallery = NOT ADS
- ONLY count as AD if they promote SOMEONE ELSE's products

## STEP 2: COUNT ONLY THIRD-PARTY ADVERTISING

### COUNT AS AD (promoting OTHER people's stuff):
- Posts marked #реклама, #партнёр, #ad, #sponsored
- Promotions of OTHER channels (not author's own)
- Affiliate links for EXTERNAL products (?ref=, promo codes)
- Crypto shills: token contracts (0x...), "fair launch"
- Paid partnerships with external brands

### NEVER COUNT AS AD (author's own content):
- Author selling THEIR OWN products (art, courses, services)
- Auctions for author's own work ("аукцион", "ставки", "лот")
- Author's monetization: Boosty, Patreon, Ko-fi, донаты
- Author's other channels/platforms
- Tool mentions without affiliate context
- Personal reviews without payment disclosure

## EXAMPLES:

ARTIST CHANNEL posting "Аукцион! Картина 'Закат'. Старт 5000₽. Ставки в комментариях 👇"
→ This is the artist selling THEIR OWN painting
→ NOT AN AD (ad_count = 0)

TECH CHANNEL posting "Рекомендую курс от @other_channel, промокод SAVE20"
→ This promotes ANOTHER channel with promo code
→ THIS IS AN AD (ad_count = 1)

BLOGGER posting "Мой новый курс на Boosty уже доступен!"
→ Author's own monetization
→ NOT AN AD (ad_count = 0)

## CALIBRATION:
- If channel sells author's own products → ad_percentage should be LOW (0-10%)
- Only count THIRD-PARTY paid promotions
- When uncertain → default to NOT AD

Output JSON: {{"channel_type": "<artist|developer|blogger|news|company|unknown>", "ad_count": <number>, "monetization_count": <number>, "total_posts": <number>, "ad_percentage": <0-100>}}"""


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

    # Парсим JSON
    default_values = {"ad_count": 0, "total_posts": len(messages), "ad_percentage": 0}
    data, warnings = safe_parse_json(response, default_values)

    if DEBUG_LLM_ANALYZER and warnings:
        print(f"JSON PARSE WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if data:
        ad_count = int(data.get("ad_count", 0))

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
        self.cache = _load_cache()
        print(f"LLM ANALYZER v40.0: Ollama ({OLLAMA_MODEL})")

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
        result = LLMAnalysisResult(posts=None, comments=None)

        # V40.0: Определяем тип канала для калибровки промптов
        channel_type = infer_channel_type(messages, category)
        if DEBUG_LLM_ANALYZER:
            print(f"📊 Channel type detected: {channel_type} (category: {category})")

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
        _save_cache(self.cache)


# v42.0: Удалён мёртвый код print_analysis_result() — 0 вызовов в проекте
