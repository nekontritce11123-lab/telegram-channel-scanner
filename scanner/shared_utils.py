"""
scanner/shared_utils.py - общие утилиты для работы с сообщениями

v1.0: iterate_reactions_with_emoji, get_sorted_messages
     Извлечены из metrics.py для переиспользования в scorer.py и других модулях.
v1.1: calculate_cv - универсальный расчёт коэффициента вариации (DRY refactoring)
v1.2: get_message_reactions_count, get_channel_age_days - для conviction.py (break circular import)
"""

from datetime import datetime, timezone
from typing import Any, Generator, Tuple


def get_reaction_emoji(reaction: Any) -> str:
    """
    Безопасно получает emoji реакции.

    Поддерживает:
    - Pyrogram ReactionCount с атрибутом reaction.emoji
    - Прямой атрибут emoji

    Returns:
        Строка с emoji или "?" если не удалось извлечь.
    """
    # Pyrogram ReactionCount имеет атрибут reaction
    if hasattr(reaction, 'reaction'):
        r = reaction.reaction
        # ReactionEmoji имеет атрибут emoji
        if hasattr(r, 'emoji'):
            return r.emoji
    # Fallback: может быть напрямую emoji
    if hasattr(reaction, 'emoji'):
        return reaction.emoji
    return "?"


def iterate_reactions_with_emoji(message: Any) -> Generator[Tuple[str, int], None, None]:
    """
    Безопасный итератор по реакциям сообщения.

    Обрабатывает все edge cases:
    - Нет атрибута reactions
    - reactions = None
    - reactions.reactions = None
    - count = None или 0

    Yields:
        Tuple[emoji: str, count: int] для каждой реакции с count > 0.

    Example:
        for emoji, count in iterate_reactions_with_emoji(message):
            total_counts[emoji] = total_counts.get(emoji, 0) + count
    """
    if not hasattr(message, 'reactions') or not message.reactions:
        return

    reactions = message.reactions
    if not hasattr(reactions, 'reactions') or not reactions.reactions:
        return

    for r in reactions.reactions:
        emoji = get_reaction_emoji(r)
        count = getattr(r, 'count', 0) or 0
        if count > 0:
            yield emoji, count


def get_sorted_messages(
    messages: list,
    require_views: bool = False,
    reverse: bool = False
) -> list:
    """
    Сортирует сообщения по дате с опциональным фильтром.

    Args:
        messages: Список сообщений (Pyrogram Message или аналогичные объекты)
        require_views: Если True, включает только сообщения с views > 0
        reverse: Если True, сортировка от новых к старым

    Returns:
        Отсортированный список сообщений.

    Example:
        # Старые посты первыми
        sorted_msgs = get_sorted_messages(messages)

        # Новые посты первыми, только с просмотрами
        sorted_msgs = get_sorted_messages(messages, require_views=True, reverse=True)
    """
    filtered = [
        m for m in messages
        if hasattr(m, 'date') and m.date
        and (not require_views or (hasattr(m, 'views') and m.views))
    ]
    return sorted(filtered, key=lambda m: m.date, reverse=reverse)


def calculate_cv(values: list, as_percent: bool = True, sample: bool = True) -> float:
    """
    Универсальный расчёт коэффициента вариации (CV).

    CV = (стандартное отклонение / среднее) × 100%

    Args:
        values: Список числовых значений
        as_percent: Вернуть в процентах (×100). Default: True
        sample: Использовать sample variance (n-1). Default: True
                False = population variance (n)

    Returns:
        CV как float. Если as_percent=True, возвращает 0-100+.
        Возвращает 0.0 если недостаточно данных или mean=0.

    Example:
        # CV просмотров постов (sample variance, в процентах)
        cv = calculate_cv([100, 120, 95, 110])  # ~10%

        # CV интервалов между постами (population variance)
        cv = calculate_cv(intervals, sample=False)
    """
    if not values or len(values) < 2:
        return 0.0

    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0

    divisor = len(values) - 1 if sample else len(values)
    variance = sum((v - mean) ** 2 for v in values) / divisor
    std_dev = variance ** 0.5
    cv = std_dev / mean

    return cv * 100 if as_percent else cv


def get_message_reactions_count(message: Any) -> int:
    """
    Безопасно получает общее количество реакций на сообщение.

    v1.2: Moved here from metrics.py to break circular import with conviction.py.

    Args:
        message: Pyrogram Message object или аналогичный

    Returns:
        Общее число реакций (int). 0 если нет реакций.
    """
    if not hasattr(message, 'reactions') or not message.reactions:
        return 0

    reactions = message.reactions

    # Pyrogram: reactions.reactions - список ReactionCount
    if hasattr(reactions, 'reactions') and reactions.reactions:
        total = 0
        for r in reactions.reactions:
            total += getattr(r, 'count', 0) or 0
        return total

    return 0


def get_channel_age_days(chat: Any) -> int:
    """
    Возвращает возраст канала в днях.

    v1.2: Moved here from metrics.py to break circular import with conviction.py.

    Args:
        chat: Pyrogram Chat object или аналогичный

    Returns:
        Возраст в днях (int). 365 по умолчанию если дата неизвестна.
    """
    chat_date = getattr(chat, 'date', None)
    if not chat_date:
        return 365  # По умолчанию считаем старым

    if chat_date.tzinfo is None:
        chat_date = chat_date.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return max(1, (now - chat_date).days)
