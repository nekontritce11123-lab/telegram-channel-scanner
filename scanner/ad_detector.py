"""
ad_detector.py - Детекция продажи рекламы по описанию канала.
v69.2: Улучшенный LLM промпт + Telegram сленг (ВП, collab).

Уровни:
    2 = Можно купить (явные маркеры рекламы)
    1 = Возможно (есть контакты / ВП)
    0 = Нельзя (нет контактов или явный отказ)
"""

import re
import requests
import logging
from typing import Optional

from scanner.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)


# =============================================================================
# LLM ДЕТЕКЦИЯ (основная)
# =============================================================================

AD_DETECTION_PROMPT = """Ты — эксперт по анализу Telegram-трафика.
Твоя задача — определить статус монетизации канала, анализируя ТОЛЬКО его описание (Bio).

ЛОГИКА ОЦЕНКИ (верни ТОЛЬКО одну цифру):

2 = [КОММЕРЦИЯ / РЕКЛАМА]
В описании есть явные маркеры продажи:
- Ключи: "Реклама", "PR", "Сотрудничество", "Promo", "Ads", "Commercial", "Прайс", "Менеджер".
- Сленг: "По вопросам размещения", "Booking", "Collab", "Partnership".
- Ссылки на ботов с названиями вроде @...prbot, @...paybot.

1 = [КОНТАКТ ЕСТЬ / ВП / ПОТЕНЦИАЛ]
Слова "реклама" нет, но канал открыт к диалогу:
- Просто указан линк на админа (@username) или бот обратной связи.
- Сленг взаимного пиара: "ВП", "Mutual", "Взаимный пиар", "Кросс-промо".
- Ключи: "Связь", "Contact", "Предложения", "По вопросам".

0 = [ЗАКРЫТ / ПУСТО]
- Описание пустое.
- Явно написано: "Рекламу не продаю", "No ads", "Без ВП".
- Указаны только ссылки на свои ресурсы (Insta, Youtube, сайт) без контактов для связи.
- Контакты есть, но с пометкой "Только по важным вопросам" или "Предложка".

ВАЖНО:
- Если описание пустое → верни 0.
- Если есть только ссылка на чат канала → верни 0.

ВЫВОД:
Верни ТОЛЬКО цифру: 0, 1 или 2."""


def detect_ad_status_llm(description: Optional[str]) -> Optional[int]:
    """
    LLM-детекция статуса рекламы через Ollama.

    Returns:
        0/1/2 или None если LLM недоступен
    """
    if not description or len(description.strip()) < 3:
        return 0  # Пустое описание = точно 0

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": AD_DETECTION_PROMPT},
            {"role": "user", "content": f"Description: {description}"}
        ],
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.1,  # Минимум креативности — нужен точный ответ
            "num_predict": 10    # Ожидаем только число
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        if response.status_code != 200:
            logger.warning(f"OLLAMA ad_status: HTTP {response.status_code}")
            return None

        data = response.json()
        content = data.get("message", {}).get("content", "").strip()

        # Извлекаем число из ответа (AI может выдать "2." или "Ответ: 2")
        clean = content.replace('.', '').strip()
        for char in clean:
            if char in '012':
                result = int(char)
                logger.debug(f"LLM ad_status: {result} (raw: {content[:50]})")
                return result

        logger.warning(f"OLLAMA ad_status: не удалось распарсить: {content[:100]}")
        return None

    except requests.exceptions.ConnectionError:
        logger.debug("OLLAMA ad_status: сервер недоступен, используем regex")
        return None
    except requests.exceptions.Timeout:
        logger.warning("OLLAMA ad_status: таймаут")
        return None
    except Exception as e:
        logger.error(f"OLLAMA ad_status: ошибка - {e}")
        return None


# =============================================================================
# REGEX ДЕТЕКЦИЯ (fallback)
# =============================================================================

# Уровень 2: Явно продают рекламу
AD_EXPLICIT_PATTERNS = [
    # Русский
    r'реклам[аы]',
    r'рекламн',
    r'сотрудничеств',
    r'размещени',
    r'партн[её]рств',
    r'прайс',
    r'по вопросам рекламы',
    r'реклама\s*[:@]',
    r'@\w+.*реклама',
    r'реклама.*@\w+',
    r'покупк[аи]\s+рекламы',
    r'заказать?\s+рекламу',
    r'менеджер',
    # Английский
    r'\bpr\b',
    r'пиар\b',
    r'\bprice\b',
    r'\brates\b',
    r'for\s+ads',
    r'advertising',
    r'ad\s+placement',
    r'sponsored\s+posts?',
    r'paid\s+promotion',
    r'\bpromo\b',
    r'\bcommercial\b',
    r'\bbooking\b',
    r'\bcollab\b',
    r'\bpartnership\b',
]

# Уровень 1: Есть контакты / ВП (но не реклама явно)
CONTACT_PATTERNS = [
    r'@[a-zA-Z]\w{3,}',           # @username (минимум 4 символа)
    r't\.me/[a-zA-Z]\w+',         # t.me/link
    r'telegram\.me/\w+',          # telegram.me/link
    r'связь',
    r'контакт',
    r'contact',
    r'написать',
    r'обращаться',
    r'пишите',
    r'напишите',
    r'write\s+to',
    r'dm\s+for',
    r'message\s+us',
    r'предложени',
    r'по вопросам',
    # ВП / взаимный пиар
    r'\bвп\b',
    r'взаимн',
    r'кросс-промо',
    r'\bmutual\b',
]

# Уровень 0: Явно НЕ продают
NO_ADS_PATTERNS = [
    r'без\s+рекламы',
    r'нет\s+рекламы',
    r'рекламу\s+не\s+(публикую|размещаю|беру|принимаю|продаю)',
    r'не\s+размещаю?\s+реклам',
    r'no\s+ads',
    r'ads?\s+free',
    r'ad-free',
    r'рекламы\s+нет',
    r'без\s+вп',
]


def detect_ad_status_regex(description: Optional[str]) -> int:
    """
    Regex-детекция статуса рекламы (fallback).

    Returns:
        2 = Можно купить (явные маркеры рекламы)
        1 = Возможно (есть контакты)
        0 = Нельзя (нет контактов или явно отказ)
    """
    if not description:
        return 0

    text = description.lower()

    # Сначала проверяем явный отказ от рекламы
    for pattern in NO_ADS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return 0

    # Проверяем явные маркеры рекламы
    for pattern in AD_EXPLICIT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return 2

    # Проверяем наличие контактов
    for pattern in CONTACT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return 1

    return 0


# =============================================================================
# ОСНОВНАЯ ФУНКЦИЯ
# =============================================================================

def detect_ad_status(description: Optional[str], use_llm: bool = True) -> int:
    """
    Определяет статус рекламы по описанию канала.

    Args:
        description: Описание канала (может быть None или пустое)
        use_llm: Использовать LLM (True) или только regex (False)

    Returns:
        2 = Можно купить (явные маркеры рекламы)
        1 = Возможно (есть контакты / ВП)
        0 = Нельзя (нет контактов или явно отказ)
    """
    if not description:
        return 0

    # Пробуем LLM
    if use_llm:
        llm_result = detect_ad_status_llm(description)
        if llm_result is not None:
            return llm_result
        logger.debug("LLM недоступен, используем regex fallback")

    # Fallback на regex
    return detect_ad_status_regex(description)


def get_ad_status_label(status: int) -> str:
    """Возвращает текстовое описание статуса."""
    labels = {
        2: "Можно купить",
        1: "Возможно",
        0: "Нельзя",
    }
    return labels.get(status, "Неизвестно")


# =============================================================================
# ИЗВЛЕЧЕНИЕ КОНТАКТОВ ДЛЯ РЕКЛАМЫ
# =============================================================================

AD_KEYWORDS = ['реклама', 'pr', 'сотрудничество', 'менеджер', 'размещение', 'прайс', 'продвижение', 'партнер', 'реклам']


def extract_ad_contacts(
    description: str,
    posts: list = None,
    channel_username: str = None
) -> list:
    """
    Extract advertising contacts from channel description and posts.

    Args:
        description: Channel description text
        posts: Optional list of post texts to also scan
        channel_username: Channel's own username to exclude

    Returns:
        List of contact dicts: [{'contact': '@username', 'type': 'telegram', 'source': 'description', 'confidence': 80}]
    """
    if not description:
        return []

    contacts = []
    seen = set()

    # Normalize channel username for comparison
    own_username = channel_username.lower().lstrip('@') if channel_username else None

    # Extract @username mentions
    for match in re.finditer(r'@([a-zA-Z][a-zA-Z0-9_]{3,31})', description):
        username = match.group(1).lower()

        # Skip own username
        if own_username and username == own_username:
            continue

        # Skip if already seen
        if username in seen:
            continue
        seen.add(username)

        # Check if near ad keyword for confidence scoring
        start = max(0, match.start() - 50)
        end = min(len(description), match.end() + 50)
        context = description[start:end].lower()
        has_keyword = any(kw in context for kw in AD_KEYWORDS)

        # Detect bot contacts
        contact_type = 'bot' if username.endswith('bot') else 'telegram'

        contacts.append({
            'contact': f'@{username}',
            'type': contact_type,
            'source': 'description',
            'confidence': 80 if has_keyword else 30
        })

    # Extract t.me/username links
    for match in re.finditer(r't(?:elegram)?\.me/([a-zA-Z][a-zA-Z0-9_]{3,31})', description, re.IGNORECASE):
        username = match.group(1).lower()

        if own_username and username == own_username:
            continue
        if username in seen:
            continue
        seen.add(username)

        start = max(0, match.start() - 50)
        end = min(len(description), match.end() + 50)
        context = description[start:end].lower()
        has_keyword = any(kw in context for kw in AD_KEYWORDS)

        contact_type = 'bot' if username.endswith('bot') else 'telegram_link'

        contacts.append({
            'contact': f't.me/{username}',
            'type': contact_type,
            'source': 'description',
            'confidence': 70 if has_keyword else 25
        })

    return contacts
