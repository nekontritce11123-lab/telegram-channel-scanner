"""
scanner/utils.py - общие utility функции

v1.0: clean_text
v2.0: Удалены мёртвые функции (load_json_cache, save_json_cache, safe_int, safe_float)
      - JSONCache теперь в cache.py
      - safe_int/safe_float локально в main.py
"""

import re


def clean_text(text: str, remove_symbols_emoji: bool = False) -> str:
    """
    Очищает текст от ссылок и лишнего.

    Args:
        text: Исходный текст
        remove_symbols_emoji: Удалять ли emoji символов (диапазон U+1F300-1F5FF)

    Returns:
        Очищенный текст
    """
    if not text:
        return ""

    # Удаляем ссылки
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r't\.me/\S+', '', text)

    # Удаляем повторяющиеся emoji (лица)
    text = re.sub(r'[\U0001F600-\U0001F64F]{3,}', '', text)

    # Опционально удаляем символьные emoji
    if remove_symbols_emoji:
        text = re.sub(r'[\U0001F300-\U0001F5FF]{3,}', '', text)

    # Сжимаем множественные переносы строк
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
