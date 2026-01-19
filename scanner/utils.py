"""
Общие утилиты для scanner модулей.
Избегаем дублирования кода между classifier.py и llm_analyzer.py
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
    except Exception:
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
    except Exception as e:
        print(f"Cache save error: {e}")
        return False
