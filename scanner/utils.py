"""
scanner/utils.py - общие utility функции

v1.0: clean_text, load_json_cache, save_json_cache
v1.1: safe_int, safe_float (из mini-app/backend/main.py)

Избегаем дублирования кода между модулями.
"""

import json
import re
from pathlib import Path
from typing import Optional


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


def load_json_cache(path: Path) -> dict:
    """
    Загружает JSON кэш из файла.

    Args:
        path: Путь к файлу кэша

    Returns:
        dict с данными или пустой dict при ошибке
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, IOError):
        # Ошибка чтения/парсинга - начинаем с пустого кэша
        return {}


def save_json_cache(path: Path, data: dict, indent: int = 2) -> bool:
    """
    Сохраняет JSON кэш в файл.

    Args:
        path: Путь к файлу кэша
        data: Данные для сохранения
        indent: Отступ для форматирования (по умолчанию 2)

    Returns:
        True если успешно, False при ошибке
    """
    path.parent.mkdir(exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return True
    except (OSError, IOError, TypeError) as e:
        # OSError/IOError: ошибки файловой системы
        # TypeError: несериализуемые данные в JSON
        print(f"Cache save error: {e}")
        return False


def safe_int(value, default: int = 0) -> int:
    """
    Безопасное преобразование в int.

    Args:
        value: Значение для преобразования (может быть None, str, float)
        default: Значение по умолчанию при ошибке

    Returns:
        int значение или default
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    """
    Безопасное преобразование в float.

    Args:
        value: Значение для преобразования (может быть None, str, int)
        default: Значение по умолчанию при ошибке

    Returns:
        float значение или default
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
