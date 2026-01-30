"""
v69.2: AI описание канала.
Генерирует живую выжимку канала (до 350 символов) через Ollama.
"""
import logging
from typing import Optional, List

from .client import call_ollama, OllamaConfig

logger = logging.getLogger(__name__)

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


def _call_ollama_summary(prompt: str) -> Optional[str]:
    """
    Запрос к Ollama для генерации описания.
    Uses call_ollama from client.py with custom config.
    """
    config = OllamaConfig(
        temperature=0.4,  # Немного креативности
        num_predict=500   # Достаточно для 350 символов
    )

    return call_ollama(
        system_prompt=SUMMARY_SYSTEM_PROMPT,
        user_message=prompt,
        config=config
    )


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
