"""
LLM Анализатор каналов v37.2

Два модуля:
1. PostAnalyzer — Brand Safety + Ad Saturation (анализ постов)
2. CommentAnalyzer — Comment Authenticity + Trust Score (анализ комментариев)

v37.2 изменения:
- political_risk коэффициент увеличен с 0.3 до 0.5 (политика = 2-я угроза после насилия)
- ADULT категория → RESTRICTED tier (защита)
- Brand Safety формула: 100 - max(tox×0.5, violence×0.6, pol_risk×0.5, mis×0.4)

v37.0 изменения (полная переработка системы оценки):
- Трёхэтапная система — Exclusion → Tier → Score
- political_quantity (% контента) + political_risk (опасность) — 2D политическая оценка
- violence отдельно от toxicity (разные Floor Levels по GARM)
- 5 тиров: PREMIUM/STANDARD/LIMITED/RESTRICTED/EXCLUDED с caps
- Floor Level exclusions (violence≥50, toxicity≥70, political_risk≥80)

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
DEBUG_LLM_ANALYZER = True

# Лимиты
MAX_POSTS_FOR_ANALYSIS = 30
MAX_COMMENTS_FOR_ANALYSIS = 50
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
    """Результат анализа комментариев"""
    authenticity: int          # 0-100 (100 = все живые)
    bot_percentage: int        # 0-100%
    bot_signals: list
    trust_score: int           # 0-100
    trust_signals: list
    raw_response: str = ""


@dataclass
class LLMAnalysisResult:
    """Полный результат LLM анализа v37.0"""
    posts: Optional[PostAnalysisResult]
    comments: Optional[CommentAnalysisResult]

    # Расчётные метрики
    llm_bonus: float = 0.0           # +0-15 points
    llm_trust_factor: float = 1.0    # ×0.15-1.0

    # v37.0: Трёхэтапная система
    tier: str = "PREMIUM"            # PREMIUM/STANDARD/LIMITED/RESTRICTED/EXCLUDED
    tier_cap: int = 100              # Максимальный скор для тира
    exclusion_reason: Optional[str] = None  # Причина исключения (если EXCLUDED)

    # v36.1: Детали для отладки
    _brand_mult: float = 1.0
    _comment_mult: float = 1.0
    _political_mult: float = 1.0

    def calculate_impact_v2(self):
        """
        V2.1: Упрощённый расчёт — только от комментариев.
        Post Analyzer отключен как бесполезный.
        """
        # Дефолтные значения
        self.tier = "STANDARD"
        self.tier_cap = 85
        self.exclusion_reason = None
        self.llm_bonus = 5.0  # Фиксированный бонус

        # LLM Trust Factor — только от комментариев
        comment_mult = 1.0

        if self.comments and self.comments.authenticity:
            auth = self.comments.authenticity
            if auth >= 80:
                comment_mult = 1.0
            elif auth >= 60:
                comment_mult = 0.9
            elif auth >= 40:
                comment_mult = 0.7
            elif auth >= 20:
                comment_mult = 0.5
            else:
                comment_mult = 0.3

        self._comment_mult = comment_mult
        self._brand_mult = 1.0
        self._political_mult = 1.0
        self.llm_trust_factor = comment_mult

        if DEBUG_LLM_ANALYZER:
            print(f"📊 V2.1: STANDARD (comment_mult={comment_mult})")


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


# === COMMENT ANALYZER V2.0 ===

COMMENT_ANALYZER_SYSTEM = """You are a comment authenticity analyzer V2.0.
Detect bots vs real humans and measure audience trust.
V2.0: You also see POST CONTEXT - what posts are being commented on.
Be objective. Output ONLY valid JSON, no other text.
CRITICAL: Analyze ACTUAL comments. Give UNIQUE scores based on what you SEE."""

COMMENT_ANALYZER_PROMPT_V2 = """Analyze these Telegram channel comments WITH post context:

## POST CONTEXT (what is being commented):
{posts_context}

## COMMENTS:
{comments_text}

---
TASK V2.0: Analyze comments in context of the posts above.

1. AUTHENTICITY (0-100, where 100 = all real humans):
   Count each comment type:
   - BOT-like: generic praise ("Great!", "👍", "🔥"), no specific content, repetitive
   - HUMAN-like: specific references to post content, personal stories, questions, debates

   Calculate: authenticity = 100 - (bot_comments / total * 100)

2. TRUST_SCORE (0-100):
   Look for trust signals in comments:
   - "Bought it" / "Купил" / "Сделал" = HIGH trust
   - Specific references to post content = HIGH trust
   - "Source?" / "Proof?" / "Опять реклама" = LOW trust
   - Generic "спасибо" without context = LOW trust

3. SARCASM DETECTION (V2.0):
   ⚠️ SUSPICIOUS if:
   - Post is negative/controversial BUT comments are all positive → possible bot farm
   - Post makes bold claims BUT no one questions → suspicious
   - Zero critical comments on divisive content → suspicious

IMPORTANT: Do NOT use placeholder values. Count ACTUAL patterns.

Output JSON format:
{{"authenticity": <0-100>, "bot_percentage": <0-100>, "bot_signals": [<PATTERNS>], "trust_score": <0-100>, "trust_signals": [<SIGNALS>], "sarcasm_warning": <true/false>}}"""


def analyze_comments(comments: list, posts: list = None) -> Optional[CommentAnalysisResult]:
    """Анализирует комментарии канала V2.0 с контекстом постов"""
    comments_text = _prepare_comments_text(comments)

    if not comments_text or len(comments_text) < 50:
        print("LLM CommentAnalyzer: Недостаточно комментариев для анализа")
        return None

    # V2.0: Добавляем контекст постов для sarcasm detection
    posts_context = "Нет контекста постов"
    if posts:
        posts_context = _prepare_posts_text(posts[:10])[:2000]  # Первые 10 постов

    prompt = COMMENT_ANALYZER_PROMPT_V2.format(
        posts_context=posts_context,
        comments_text=comments_text[:5000]
    )

    if DEBUG_LLM_ANALYZER:
        print(f"\n{'='*60}")
        print(f"COMMENT ANALYZER V2.0 - {len(comments)} comments, {len(comments_text)} chars")
        print(f"Posts context: {len(posts_context)} chars")
        print(f"{'='*60}\n")

    response = _call_ollama(COMMENT_ANALYZER_SYSTEM, prompt)

    if not response:
        return None

    if DEBUG_LLM_ANALYZER:
        print(f"COMMENT ANALYZER RESPONSE:\n{response[:500]}")

    # V2.0: Use safe_parse_json with fallback
    default_values = {
        "authenticity": 50,
        "bot_percentage": 50,
        "bot_signals": [],
        "trust_score": 50,
        "trust_signals": [],
        "sarcasm_warning": False
    }
    data, warnings = safe_parse_json(response, default_values)

    if DEBUG_LLM_ANALYZER and warnings:
        print(f"JSON PARSE WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if data:
        return CommentAnalysisResult(
            authenticity=int(data.get("authenticity", 50)),
            bot_percentage=int(data.get("bot_percentage", 50)),
            bot_signals=data.get("bot_signals", []),
            trust_score=int(data.get("trust_score", 50)),
            trust_signals=data.get("trust_signals", []),
            raw_response=response
        )

    print(f"COMMENT ANALYZER: Failed to parse response")
    return None


# === ГЛАВНЫЙ АНАЛИЗАТОР ===

class LLMAnalyzer:
    """Полный LLM анализ канала"""

    def __init__(self):
        self.cache = _load_cache()
        print(f"LLM ANALYZER v37.0: Ollama ({OLLAMA_MODEL})")

    def analyze(
        self,
        channel_id: int,
        messages: list,
        comments: list,
        category: str = "DEFAULT"
    ) -> LLMAnalysisResult:
        """
        Полный анализ канала.

        Args:
            channel_id: ID канала
            messages: Список постов
            comments: Список комментариев
            category: Категория канала (для корректировок)

        Returns:
            LLMAnalysisResult с метриками
        """
        result = LLMAnalysisResult(posts=None, comments=None)

        # V2.1: Post Analyzer ОТКЛЮЧЕН — бесполезные метрики
        # Человек сам видит что канал про политику/войну
        # toxicity, violence, military_conflict — не влияют на рекламу
        print(f"LLM: PostAnalyzer отключен (V2.1 — бесполезные метрики)")

        # Comment Analyzer — ПОЛЕЗНО: детекция ботов
        if comments and len(comments) >= 5:
            result.comments = analyze_comments(comments, posts=messages)
        else:
            print(f"LLM: Пропуск CommentAnalyzer (мало комментов: {len(comments) if comments else 0})")

        # V2.1: Упрощённый impact — только от комментариев
        result.calculate_impact_v2()

        return result

    def save_cache(self):
        _save_cache(self.cache)


# === ТЕСТОВАЯ ФУНКЦИЯ ===

def print_analysis_result(result: LLMAnalysisResult, channel_name: str = ""):
    """Красиво выводит результат анализа v37.0"""
    print(f"\n{'='*60}")
    print(f"LLM ANALYSIS v37.0: {channel_name}")
    print(f"{'='*60}")

    # v37.0: Тир и cap
    print(f"\n📊 SUITABILITY TIER: {result.tier} (cap={result.tier_cap})")
    if result.exclusion_reason:
        print(f"   ⛔ EXCLUDED: {result.exclusion_reason}")

    if result.posts:
        p = result.posts
        print(f"\n📝 POST ANALYSIS:")
        print(f"   Brand Safety: {p.brand_safety}/100")
        print(f"   - Toxicity: {p.toxicity}")
        print(f"   - Violence: {p.violence}")  # v37.0
        print(f"   - Political Quantity: {p.political_quantity}%")  # v37.0
        print(f"   - Political Risk: {p.political_risk}")  # v37.0
        print(f"   - Misinformation: {p.misinformation}")
        print(f"   Ad Percentage: {p.ad_percentage}%")
        if p.red_flags:
            print(f"   Red Flags: {p.red_flags}")
    else:
        print(f"\n📝 POST ANALYSIS: Пропущен (недостаточно данных)")

    if result.comments:
        c = result.comments
        print(f"\n💬 COMMENT ANALYSIS:")
        print(f"   Authenticity: {c.authenticity}/100 ({100-c.bot_percentage}% живые)")
        print(f"   Bot Signals: {c.bot_signals}")
        print(f"   Trust Score: {c.trust_score}/100")
        print(f"   Trust Signals: {c.trust_signals}")
    else:
        print(f"\n💬 COMMENT ANALYSIS: Пропущен (недостаточно данных)")

    print(f"\n📊 IMPACT ON SCORE:")
    print(f"   LLM Bonus: +{result.llm_bonus:.1f} points")
    print(f"   LLM Trust Factor: ×{result.llm_trust_factor:.2f}")
    print(f"   Tier Cap: {result.tier_cap}")

    # Пример влияния с tier cap
    example_raw = 70
    example_trust = 0.95
    old_score = example_raw * example_trust
    base_new = (example_raw + result.llm_bonus) * example_trust * result.llm_trust_factor
    new_score = min(base_new, result.tier_cap)  # v37.0: применяем cap
    print(f"\n   Example: Raw=70, Trust=0.95")
    print(f"   Old formula: {old_score:.1f}")
    print(f"   New formula: {base_new:.1f} → capped to {new_score:.1f}")

    print(f"{'='*60}\n")
