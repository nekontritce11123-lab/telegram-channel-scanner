"""
Brand Safety модуль v45.0 - детекция токсичного контента.

⚠️ DEPRECATED в v46.0 — используется LLM Brand Safety вместо стоп-слов.
   См. scanner/llm_analyzer.py → analyze_brand_safety()

LLM преимущества:
- Понимает контекст ("ставки" в спорте vs казино)
- Детектирует обфускацию (к@зин0, p0rn)
- Понимает эвфемизмы и сленг

Старый модуль (стоп-слова) оставлен для справки.
Не импортируется в crawler.py с v46.0.
"""

import re
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class ContentSafetyResult:
    """Результат проверки контента на токсичность."""
    is_toxic: bool
    toxic_category: Optional[str]  # GAMBLING, ADULT, SCAM, None
    toxic_matches: List[str]       # Найденные стоп-слова
    toxic_ratio: float             # % постов с токсичным контентом
    severity: str                  # "CRITICAL", "HIGH", "MEDIUM", "LOW"


# Стоп-ворды по категориям (регистронезависимые)
STOP_WORDS = {
    "GAMBLING": [
        # Казино
        "казино", "casino", "рулетка", "roulette", "слоты", "slots",
        "джекпот", "jackpot", "спины", "фриспины", "freespins",
        "игровые автоматы", "однорукий бандит",

        # Ставки
        "букмекер", "bookmaker", "ставки на спорт", "1xbet", "1хбет",
        "fonbet", "фонбет", "melbet", "мелбет", "леон", "leon",
        "betway", "bet365", "pinnacle", "marathonbet", "марафон",
        "лига ставок", "winline", "винлайн", "олимп", "olimp",

        # Покер
        "покер", "poker", "холдем", "holdem", "омаха", "pokerstar",
        "ggpoker", "partypoker",

        # Общие gambling триггеры
        "бонус за регистрацию", "депозит удвоим", "первый депозит",
        "выигрыш гарантирован", "беспроигрышная стратегия",
    ],

    "ADULT": [
        # Явный контент
        "порно", "порн", "porno", "porn", "xxx", "секс видео",
        "18+", "только для взрослых", "adult only",
        "эротика", "эротическ", "erotica", "erotic",

        # Эскорт/проституция
        "эскорт", "escort", "интим услуги", "девушки по вызову",
        "проститут", "шлюх", "путан", "досуг для взрослых",

        # Сленг
        "onlyfans", "фансли", "fansly",

        # Детская порнография (критично!)
        "цп", "малолетк", "несовершеннолетн",
    ],

    "SCAM": [
        # Даркнет
        "даркнет", "darknet", "dark web", "тор браузер",
        "гидра", "hydra", "silk road", "rutor",

        # Наркотики
        "закладка", "кладмен", "наркот", "спайс", "мефедрон",
        "амфетамин", "кокаин", "героин", "метадон",

        # Кардинг/мошенничество
        "кардинг", "carding", "обнал", "дропы", "дроп схема",
        "слив карт", "cvv", "fullz", "скам проект",
        "пробив данных", "база данных паспортов",

        # Оружие
        "купить оружие", "травмат без лицензии", "ствол без документов",
    ],
}

# Пороги токсичности (% постов с токсичным контентом)
TOXICITY_THRESHOLDS = {
    "CRITICAL": 0.20,  # >20% = точно токсичный канал
    "HIGH": 0.10,      # >10% = высокий риск
    "MEDIUM": 0.05,    # >5% = средний риск
    "LOW": 0.02,       # >2% = низкий риск
}


def _normalize_text(text: str) -> str:
    """Нормализует текст для поиска."""
    if not text:
        return ""
    # Приводим к нижнему регистру, убираем лишние пробелы
    text = text.lower().strip()
    # Заменяем цифры на буквы (антиобфускация)
    text = text.replace("0", "о").replace("3", "з").replace("1", "i")
    return text


def _check_text_for_stopwords(text: str, category: str) -> List[str]:
    """Проверяет текст на стоп-ворды категории."""
    matches = []
    normalized = _normalize_text(text)

    for word in STOP_WORDS.get(category, []):
        word_lower = word.lower()
        if word_lower in normalized:
            matches.append(word)

    return matches


def check_content_safety(messages: list, threshold_override: float = None) -> ContentSafetyResult:
    """
    Проверяет посты канала на токсичный контент.

    Args:
        messages: Список постов (с атрибутом message/text)
        threshold_override: Переопределить порог токсичности

    Returns:
        ContentSafetyResult с детальной информацией
    """
    if not messages:
        return ContentSafetyResult(
            is_toxic=False,
            toxic_category=None,
            toxic_matches=[],
            toxic_ratio=0.0,
            severity="LOW"
        )

    # Собираем текст из всех постов
    all_matches = {"GAMBLING": [], "ADULT": [], "SCAM": []}
    posts_with_toxic = {"GAMBLING": 0, "ADULT": 0, "SCAM": 0}

    for msg in messages:
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text
        elif hasattr(msg, 'caption') and msg.caption:
            text = msg.caption

        if not text:
            continue

        # Проверяем каждую категорию
        for category in ["GAMBLING", "ADULT", "SCAM"]:
            matches = _check_text_for_stopwords(text, category)
            if matches:
                all_matches[category].extend(matches)
                posts_with_toxic[category] += 1

    total_posts = len(messages)

    # Определяем наиболее токсичную категорию
    # Приоритет: SCAM > ADULT > GAMBLING
    worst_category = None
    worst_ratio = 0.0
    worst_matches = []

    for category in ["SCAM", "ADULT", "GAMBLING"]:
        ratio = posts_with_toxic[category] / total_posts if total_posts > 0 else 0
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst_category = category
            # Уникальные совпадения (макс 10 примеров)
            worst_matches = list(set(all_matches[category]))[:10]

    # Определяем severity
    threshold = threshold_override or TOXICITY_THRESHOLDS["MEDIUM"]

    if worst_ratio >= TOXICITY_THRESHOLDS["CRITICAL"]:
        severity = "CRITICAL"
    elif worst_ratio >= TOXICITY_THRESHOLDS["HIGH"]:
        severity = "HIGH"
    elif worst_ratio >= TOXICITY_THRESHOLDS["MEDIUM"]:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    # Канал токсичен если превышен порог
    is_toxic = worst_ratio >= threshold

    return ContentSafetyResult(
        is_toxic=is_toxic,
        toxic_category=worst_category if is_toxic else None,
        toxic_matches=worst_matches if is_toxic else [],
        toxic_ratio=round(worst_ratio, 3),
        severity=severity
    )


def get_exclusion_reason(safety_result: ContentSafetyResult) -> Optional[str]:
    """Формирует причину исключения для UI."""
    if not safety_result.is_toxic:
        return None

    category_labels = {
        "GAMBLING": "CASINO_RISK",
        "ADULT": "ADULT_CONTENT",
        "SCAM": "SCAM_CONTENT",
    }

    label = category_labels.get(safety_result.toxic_category, "TOXIC_CONTENT")
    matches_str = ", ".join(safety_result.toxic_matches[:5])

    return f"{label}: {matches_str}"


def get_trust_multiplier(safety_result: ContentSafetyResult) -> float:
    """
    Возвращает Trust Factor множитель на основе Brand Safety.

    CRITICAL: 0.0 (EXCLUDED)
    HIGH: 0.3
    MEDIUM: 0.7
    LOW: 1.0
    """
    if not safety_result.is_toxic:
        return 1.0

    multipliers = {
        "CRITICAL": 0.0,
        "HIGH": 0.3,
        "MEDIUM": 0.7,
        "LOW": 1.0,
    }

    return multipliers.get(safety_result.severity, 1.0)
