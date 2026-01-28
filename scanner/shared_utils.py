"""
scanner/shared_utils.py - общие утилиты для работы с сообщениями

v1.0: iterate_reactions_with_emoji, get_sorted_messages
     Извлечены из metrics.py для переиспользования в scorer.py и других модулях.
"""

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
