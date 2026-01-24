"""
Модуль пересчёта метрик v52.0

Позволяет изменять формулы скоринга и пересчитывать все каналы
без обращения к Telegram API.

Использование:
    python crawler.py --recalculate-local     # Пересчёт score из breakdown
    python crawler.py --recalculate-llm       # Пересчёт LLM анализа из текстов
    python crawler.py --recalculate-local --sync  # С синхронизацией на сервер
"""

import gzip
import json
from dataclasses import dataclass
from typing import Optional

from .database import CrawlerDB, ChannelRecord
from .scorer import (
    cv_to_points, reach_to_points, reaction_rate_to_points,
    forward_rate_to_points, age_to_points, regularity_to_points,
    stability_to_points, source_to_points, premium_to_points,
    er_trend_to_points, RAW_WEIGHTS, CATEGORY_TOTALS
)
from .json_compression import decompress_breakdown
from .config import GOOD_THRESHOLD


@dataclass
class RecalculateResult:
    """Результат пересчёта."""
    total: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def recalculate_score_from_breakdown(breakdown: dict, members: int = 0) -> tuple[int, dict]:
    """
    Пересчитывает score из сохранённых значений метрик.

    Args:
        breakdown: Сохранённый breakdown из БД
        members: Количество подписчиков

    Returns:
        (new_score, new_categories) - новый score и итоги по категориям
    """
    if not breakdown:
        return 0, {}

    # Извлекаем значения метрик
    def get_value(key: str) -> float:
        data = breakdown.get(key, {})
        if isinstance(data, dict):
            return data.get('value', 0) or 0
        return 0

    def get_dict(key: str) -> dict:
        data = breakdown.get(key, {})
        return data if isinstance(data, dict) else {}

    # Quality (42 балла)
    cv_views = get_value('cv_views')
    forward_rate = get_value('forward_rate')
    reach = get_value('reach')
    regularity_data = get_dict('regularity')
    posts_per_day = regularity_data.get('posts_per_day', 0)

    quality_score = 0
    quality_score += cv_to_points(cv_views, forward_rate)
    quality_score += reach_to_points(reach, members)
    quality_score += forward_rate_to_points(forward_rate, members)
    quality_score += regularity_to_points(posts_per_day)

    # Engagement (38 баллов)
    comments_data = get_dict('comments')
    comments_enabled = breakdown.get('comments_enabled', True)
    reactions_enabled = breakdown.get('reactions_enabled', True)

    # comments - нужен avg для расчёта
    avg_comments = comments_data.get('avg', 0)
    comments_pts = comments_data.get('points', 0)  # Используем сохранённые, т.к. логика сложная

    reaction_rate = get_value('reaction_rate')
    stability_data = get_dict('reaction_stability') or get_dict('stability')
    er_trend_data = get_dict('er_trend')

    engagement_score = 0
    engagement_score += comments_pts  # Сохранённый расчёт
    engagement_score += reaction_rate_to_points(reaction_rate, members) if reactions_enabled else 0
    engagement_score += stability_to_points(stability_data)
    engagement_score += er_trend_to_points(er_trend_data)

    # Reputation (20 баллов)
    age = get_value('age')
    premium_data = get_dict('premium')
    premium_ratio = premium_data.get('ratio', 0)
    premium_count = premium_data.get('count', 0)
    source_data = get_dict('source_diversity') or get_dict('source')
    source_max_share = 1 - get_value('source_diversity')  # value = 1 - max_share
    repost_ratio = source_data.get('repost_ratio', 0)

    reputation_score = 0
    reputation_score += age_to_points(int(age))
    reputation_score += premium_to_points(premium_ratio, premium_count)
    reputation_score += source_to_points(source_max_share, repost_ratio)

    # Итоговый score
    raw_score = quality_score + engagement_score + reputation_score

    # Categories для breakdown_json
    categories = {
        'quality': {'score': quality_score, 'max': CATEGORY_TOTALS['quality']},
        'engagement': {'score': engagement_score, 'max': CATEGORY_TOTALS['engagement']},
        'reputation': {'score': reputation_score, 'max': CATEGORY_TOTALS['reputation']},
    }

    return raw_score, categories


def recalculate_local(db: CrawlerDB, verbose: bool = True) -> RecalculateResult:
    """
    Пересчитывает scores для всех каналов из сохранённых breakdown.

    Args:
        db: Подключение к базе данных
        verbose: Выводить прогресс

    Returns:
        RecalculateResult с статистикой
    """
    result = RecalculateResult()

    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT username, members, breakdown_json, trust_factor, score
        FROM channels
        WHERE status IN ('GOOD', 'BAD') AND breakdown_json IS NOT NULL
    """)
    rows = cursor.fetchall()

    result.total = len(rows)
    if verbose:
        print(f"Найдено {result.total} каналов с breakdown для пересчёта")

    for row in rows:
        username = row[0]
        members = row[1] or 0
        breakdown_json = row[2]
        trust_factor = row[3] or 1.0
        old_score = row[4] or 0

        try:
            # Парсим breakdown
            data = json.loads(breakdown_json)
            breakdown = data.get('breakdown', {}) if isinstance(data, dict) else {}

            # Декомпрессируем если сжат (короткие ключи cv, re и т.д.)
            breakdown = decompress_breakdown(breakdown)

            if not breakdown:
                result.skipped += 1
                continue

            # Пересчитываем
            raw_score, categories = recalculate_score_from_breakdown(breakdown, members)

            # Применяем trust_factor
            new_score = int(raw_score * trust_factor)

            # Обновляем в БД
            new_status = 'GOOD' if new_score >= GOOD_THRESHOLD else 'BAD'

            # Сохраняем новые categories в breakdown_json
            data['categories'] = categories
            new_breakdown_json = json.dumps(data, ensure_ascii=False)

            cursor.execute("""
                UPDATE channels
                SET score = ?, status = ?, breakdown_json = ?
                WHERE username = ?
            """, (new_score, new_status, new_breakdown_json, username))

            result.updated += 1

            if verbose and old_score != new_score:
                print(f"  @{username}: {old_score} -> {new_score}")

        except Exception as e:
            result.errors += 1
            if verbose:
                print(f"  ERROR @{username}: {e}")

    db.conn.commit()

    if verbose:
        print(f"\nИтого: обновлено {result.updated}, пропущено {result.skipped}, ошибок {result.errors}")

    return result


def recalculate_llm(db: CrawlerDB, verbose: bool = True) -> RecalculateResult:
    """
    Пересчитывает LLM анализ для всех каналов из сохранённых текстов.

    Требует: Ollama запущен, posts_text_gz/comments_text_gz заполнены.

    Args:
        db: Подключение к базе данных
        verbose: Выводить прогресс

    Returns:
        RecalculateResult с статистикой
    """
    from .llm_analyzer import LLMAnalyzer
    from .config import ensure_ollama_running

    # Проверяем Ollama
    try:
        ensure_ollama_running()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return RecalculateResult(errors=1)

    result = RecalculateResult()

    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT username, category, posts_text_gz, comments_text_gz, breakdown_json, members, trust_factor
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
          AND posts_text_gz IS NOT NULL
    """)
    rows = cursor.fetchall()

    result.total = len(rows)
    if verbose:
        print(f"Найдено {result.total} каналов с текстами для LLM пересчёта")

    analyzer = LLMAnalyzer()

    for i, row in enumerate(rows, 1):
        username = row[0]
        category = row[1] or 'DEFAULT'
        posts_text_gz = row[2]
        comments_text_gz = row[3]
        breakdown_json = row[4]
        members = row[5] or 0
        trust_factor = row[6] or 1.0

        try:
            # Распаковываем тексты
            posts_texts = json.loads(gzip.decompress(posts_text_gz).decode('utf-8'))

            comments_texts = []
            if comments_text_gz:
                comments_texts = json.loads(gzip.decompress(comments_text_gz).decode('utf-8'))

            # Создаём mock-сообщения для LLM
            class MockMessage:
                def __init__(self, text: str):
                    self.text = text

            mock_messages = [MockMessage(t) for t in posts_texts]

            # Запускаем LLM анализ
            llm_result = analyzer.analyze(
                channel_id=hash(username) % 10000000,  # Fake ID
                messages=mock_messages,
                comments=comments_texts,
                category=category
            )

            if llm_result is None:
                result.skipped += 1
                if verbose:
                    print(f"  [{i}/{result.total}] @{username}: SKIP (LLM timeout)")
                continue

            # Обновляем breakdown с новым LLM анализом
            data = json.loads(breakdown_json) if breakdown_json else {'breakdown': {}, 'categories': {}}

            # Декомпрессируем если сжат
            breakdown_raw = data.get('breakdown', {})
            breakdown_raw = decompress_breakdown(breakdown_raw)
            data['llm_analysis'] = {
                'tier': llm_result.tier,
                'tier_cap': llm_result.tier_cap,
                'exclusion_reason': llm_result.exclusion_reason,
                'llm_bonus': round(llm_result.llm_bonus, 2),
                'llm_trust_factor': round(llm_result.llm_trust_factor, 3),
            }

            new_breakdown_json = json.dumps(data, ensure_ascii=False)

            # Пересчитываем score с новым LLM результатом
            raw_score, _ = recalculate_score_from_breakdown(breakdown_raw, members)

            # Применяем trust_factor и LLM modifiers
            final_score = raw_score + llm_result.llm_bonus
            final_score = int(final_score * trust_factor * llm_result.llm_trust_factor)
            final_score = min(final_score, llm_result.tier_cap)

            new_status = 'GOOD' if final_score >= GOOD_THRESHOLD else 'BAD'

            cursor.execute("""
                UPDATE channels
                SET score = ?, status = ?, breakdown_json = ?, tier = ?
                WHERE username = ?
            """, (final_score, new_status, new_breakdown_json, llm_result.tier, username))

            result.updated += 1

            if verbose:
                print(f"  [{i}/{result.total}] @{username}: tier={llm_result.tier}, score={final_score}")

        except Exception as e:
            result.errors += 1
            if verbose:
                print(f"  [{i}/{result.total}] @{username}: ERROR - {e}")

    db.conn.commit()

    if verbose:
        print(f"\nИтого: обновлено {result.updated}, пропущено {result.skipped}, ошибок {result.errors}")

    return result


def get_channels_without_texts(db: CrawlerDB) -> list[str]:
    """Возвращает список каналов без сохранённых текстов."""
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT username FROM channels
        WHERE status IN ('GOOD', 'BAD') AND posts_text_gz IS NULL
    """)
    return [row[0] for row in cursor.fetchall()]
