"""
v69.2: AI описание канала.
Генерирует живую выжимку канала (до 350 символов) через Ollama.
"""
import requests
import time
import logging
from typing import Optional, List

from scanner.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)

# Retry settings
MAX_RETRIES = 2
RETRY_DELAY = 5  # seconds

# System prompt для генерации описания
SUMMARY_SYSTEM_PROMPT = """Ты — опытный медиа-аналитик.
Твоя задача — на основе описания и последних постов написать "Выжимку сути" канала.

ТРЕБОВАНИЯ К ТЕКСТУ:
1. Объём: Строго 2-3 предложения (до 350 символов).
2. Стиль: Лаконичный, конкретный, без воды. Как будто один друг советует канал другому.
3. Структура:
   - О чём канал (Тематика + Формат).
   - Для кого/Зачем (Ценность).

ЖЕСТКИЕ ЗАПРЕТЫ (Штраф за использование):
- НЕ начинай с фраз: "Этот канал посвящен...", "В данном канале...", "Автор рассказывает...". Сразу к сути!
- НЕ используй списки и буллиты. Только связный текст.
- НЕ дублируй описание канала слово в слово.
- НЕ используй клише: "погрузитесь в мир", "уникальный контент".

ПРИМЕР ИДЕАЛЬНОГО ОТВЕТА:
"Агрегатор новостей нейросетей с упором на практическое применение. Публикуют промпты для Midjourney, обзоры новых плагинов и гайды по установке локальных LLM. Полезно разработчикам и дизайнерам для отслеживания трендов."

ПРИМЕР 2:
"Авторский блог про эмиграцию в Сербию. Реальные истории о ВНЖ, ценах на жилье и адаптации без прикрас. Много личного опыта, советов по налогам и бытовых лайфхаков для релокантов."
"""


def _call_ollama_summary(prompt: str, retry_count: int = 0) -> Optional[str]:
    """
    Запрос к Ollama для генерации описания.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.4,  # Немного креативности
            "num_predict": 500   # Достаточно для 350 символов
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        if response.status_code != 200:
            logger.warning(f"OLLAMA summary: HTTP {response.status_code}")
            return None

        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        return content

    except requests.exceptions.ConnectionError:
        logger.error("OLLAMA: Не запущен! Запусти: ollama serve")
        return None
    except requests.exceptions.Timeout:
        if retry_count < MAX_RETRIES:
            wait = RETRY_DELAY * (retry_count + 1)
            logger.warning(f"OLLAMA summary: Таймаут, retry {retry_count + 1}/{MAX_RETRIES} через {wait}с...")
            time.sleep(wait)
            return _call_ollama_summary(prompt, retry_count + 1)
        logger.error(f"OLLAMA summary: Таймаут после {MAX_RETRIES} попыток!")
        return None
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"OLLAMA summary: Ошибка обработки ответа - {e}")
        return None


def _clean_summary(text: str) -> str:
    """Очистка и форматирование описания."""
    # Убираем кавычки в начале/конце
    text = text.strip()
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]

    # Убираем markdown форматирование
    text = text.replace('**', '').replace('*', '')

    # Убираем переносы строк внутри текста
    text = ' '.join(text.split())

    return text.strip()


def generate_channel_summary(
    title: str,
    description: Optional[str],
    posts: List[str],
    max_posts: int = 10
) -> Optional[str]:
    """
    Генерирует AI описание канала.

    Args:
        title: Название канала
        description: Описание канала (из bio)
        posts: Список текстов последних постов
        max_posts: Максимум постов для анализа

    Returns:
        Описание канала (до 350 символов) или None
    """
    # Подготавливаем посты
    posts_sample = []
    for i, post in enumerate(posts[:max_posts]):
        if post and len(post.strip()) > 20:  # Пропускаем слишком короткие
            clean = post.strip()[:500]  # Ограничиваем длину поста
            posts_sample.append(f"[{i+1}]: {clean}")

    if not posts_sample and not description:
        logger.warning(f"generate_summary: Нет данных для {title}")
        return None

    # Формируем промпт
    prompt_parts = [f"Название: {title}"]

    if description:
        prompt_parts.append(f"Описание: {description}")
    else:
        prompt_parts.append("Описание: отсутствует")

    if posts_sample:
        prompt_parts.append("Посты:")
        prompt_parts.extend(posts_sample[:max_posts])
    else:
        prompt_parts.append("Посты: недоступны")

    prompt = "\n".join(prompt_parts)

    # Ограничиваем общую длину промпта
    if len(prompt) > 4000:
        prompt = prompt[:4000] + "..."

    logger.debug(f"generate_summary prompt ({len(prompt)} chars): {prompt[:200]}...")

    # Вызываем Ollama
    response = _call_ollama_summary(prompt)

    if not response:
        return None

    # Очищаем и проверяем результат
    summary = _clean_summary(response)

    # Проверка минимальной длины
    if len(summary) < 50:
        logger.warning(f"generate_summary: Слишком короткий ответ ({len(summary)} chars)")
        return None

    # Ограничение максимальной длины (до 400 с запасом)
    if len(summary) > 400:
        # Обрезаем на последнем предложении
        summary = summary[:400]
        last_period = summary.rfind('.')
        if last_period > 200:
            summary = summary[:last_period + 1]

    logger.info(f"generate_summary: OK ({len(summary)} chars)")
    return summary
