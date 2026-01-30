"""
Модуль расчёта метрик качества Telegram канала.
v41.1: Floating weights для закрытых комментов.
v51.0: SIZE_THRESHOLDS из config.py вместо hardcoded.
v51.1: shared_utils для iterate_reactions_with_emoji и get_sorted_messages.
v52.0: FraudConvictionSystem и analyze_private_invites вынесены в отдельные модули.
"""
from collections import Counter
from typing import Any

from scanner.config import SIZE_THRESHOLDS
from scanner.scorer_constants import TrustMultipliers
from scanner.shared_utils import (
    get_reaction_emoji as _get_reaction_emoji,
    iterate_reactions_with_emoji,
    get_sorted_messages,
    calculate_cv,
    get_message_reactions_count,
    get_channel_age_days,
)


# ============================================================================
# КАТЕГОРИЯ B: ОСНОВНЫЕ МЕТРИКИ (70 баллов)
# ============================================================================

def calculate_cv_views(views: list[int]) -> float:
    """
    B1: Coefficient of Variation просмотров.
    Чем выше CV, тем естественнее разброс.
    Боты дают ровные числа (низкий CV).
    """
    if not views or len(views) < 2:
        return 0.0

    return calculate_cv(views, as_percent=True, sample=True)


def calculate_reach(avg_views: float, members_count: int) -> float:
    """
    B2: Охват аудитории (% подписчиков видит посты).
    """
    if members_count <= 0:
        return 0.0
    return (avg_views / members_count) * 100


def calculate_forwards_ratio(messages: list) -> float:
    """
    B4: Соотношение пересылок к просмотрам (%).
    """
    total_forwards = sum(m.forwards or 0 for m in messages if hasattr(m, 'forwards'))
    total_views = sum(m.views or 0 for m in messages if hasattr(m, 'views'))

    if total_views == 0:
        return 0.0

    return (total_forwards / total_views) * 100


def calculate_reaction_rate(messages: list) -> float:
    """
    B5: Соотношение реакций к просмотрам (%).
    """
    total_reactions = 0
    total_views = 0

    for m in messages:
        total_reactions += get_message_reactions_count(m)
        total_views += m.views or 0 if hasattr(m, 'views') else 0

    if total_views == 0:
        return 0.0

    return (total_reactions / total_views) * 100


# ============================================================================
# КАТЕГОРИЯ C: ВРЕМЕННЫЕ МЕТРИКИ (15 баллов)
# ============================================================================

def calculate_views_decay(messages: list) -> float:
    """
    C1: Накопление просмотров (нормализованное).
    Измеряет organic engagement, корректно работает с растущими каналами.

    Нормализуем просмотры на baseline (средние по каналу),
    чтобы растущие каналы не штрафовались.

    Возвращает ratio: normalized_old / normalized_new.
    ratio ~1.0 = норма (для растущих каналов)
    ratio > 1.0 = органика накапливается
    ratio < 0.7 = подозрительно (посты не набирают со временем)
    """
    if len(messages) < 12:
        return 1.0  # Мало данных

    # Сортируем по дате (новые первые)
    sorted_msgs = sorted(
        [m for m in messages if hasattr(m, 'date') and m.date and m.views],
        key=lambda m: m.date,
        reverse=True
    )

    quarter = len(sorted_msgs) // 4
    if quarter < 3:
        return 1.0

    new_views = [m.views for m in sorted_msgs[:quarter]]
    old_views = [m.views for m in sorted_msgs[-quarter:]]

    if not new_views or not old_views:
        return 1.0

    # Baseline - средние просмотры по всем постам
    all_views = [m.views for m in sorted_msgs]
    baseline = sum(all_views) / len(all_views) if all_views else 1

    if baseline == 0:
        return 1.0

    # Нормализуем на baseline
    new_normalized = [v / baseline for v in new_views]
    old_normalized = [v / baseline for v in old_views]

    new_avg_norm = sum(new_normalized) / len(new_normalized)
    old_avg_norm = sum(old_normalized) / len(old_normalized)

    if new_avg_norm == 0:
        return 1.0

    return old_avg_norm / new_avg_norm


def calculate_post_regularity(messages: list) -> float:
    """
    C3: Вариация интервалов между постами.
    Слишком ровные интервалы = бот.
    Возвращает CV интервалов.
    """
    if len(messages) < 5:
        return 0.5

    sorted_msgs = sorted(
        [m for m in messages if hasattr(m, 'date') and m.date],
        key=lambda m: m.date
    )

    intervals = []
    for i in range(1, len(sorted_msgs)):
        delta = (sorted_msgs[i].date - sorted_msgs[i-1].date).total_seconds() / 3600
        if delta > 0:
            intervals.append(delta)

    if len(intervals) < 5:
        return 0.5

    mean_interval = sum(intervals) / len(intervals)
    if mean_interval == 0:
        return 0.5

    variance = sum((i - mean_interval) ** 2 for i in intervals) / len(intervals)
    std_interval = variance ** 0.5

    return std_interval / mean_interval


def calculate_posts_per_day(messages: list, is_news: bool = False) -> dict:
    """
    Рассчитывает частоту постинга.

    Пороги (обычный канал):
    - < 6/day = normal (×1.0)
    - 6-12/day = active (×0.90)
    - 12-20/day = heavy (×0.75)
    - > 20/day = spam (×0.55)

    Для NEWS пороги выше: 20/40/60
    """
    sorted_msgs = sorted(
        [m for m in messages if hasattr(m, 'date') and m.date],
        key=lambda m: m.date
    )

    if len(sorted_msgs) < 2:
        return {
            'posts_per_day': 0,
            'total_days': 0,
            'posting_status': 'insufficient_data',
            'trust_multiplier': 1.0
        }

    total_seconds = (sorted_msgs[-1].date - sorted_msgs[0].date).total_seconds()
    total_days = max(total_seconds / 86400, 0.1)
    posts_per_day = len(sorted_msgs) / total_days

    # Пороги для NEWS выше
    if is_news:
        thresholds = (20, 40, 60)
    else:
        thresholds = (6, 12, 20)

    # Статус и множитель
    if posts_per_day < thresholds[0]:
        status = 'normal'
        trust_mult = 1.0
    elif posts_per_day < thresholds[1]:
        status = 'active'
        trust_mult = TrustMultipliers.SPAM_POSTING_ACTIVE  # 0.90
    elif posts_per_day < thresholds[2]:
        status = 'heavy'
        trust_mult = TrustMultipliers.SPAM_POSTING_HEAVY   # 0.75
    else:
        status = 'spam'
        trust_mult = TrustMultipliers.SPAM_POSTING_SPAM    # 0.55

    return {
        'posts_per_day': round(posts_per_day, 1),
        'total_days': round(total_days, 1),
        'posting_status': status,
        'trust_multiplier': trust_mult
    }


# ============================================================================
# КАТЕГОРИЯ D: АНАЛИЗ РЕАКЦИЙ (10 баллов)
# ============================================================================

def check_reactions_enabled(messages: list) -> bool:
    """
    v22.4: Проверяет включены ли реакции на канале.

    Логика:
    - Если реакции ОТКЛЮЧЕНЫ: ни один пост не имеет атрибута reactions
    - Если реакции ВКЛЮЧЕНЫ (но никто не реагировал): атрибут есть, но пустой/None
    - Если есть хоть одна реакция: точно включены

    Возвращает True если реакции включены (даже если 0 реакций).
    """
    if not messages:
        return True  # По умолчанию считаем включёнными

    # Проверяем есть ли реакции хоть на одном посте
    total_reactions = sum(get_message_reactions_count(m) for m in messages)
    if total_reactions > 0:
        return True  # Есть реакции = точно включены

    # Проверяем есть ли атрибут reactions хоть у одного поста
    # Telegram не возвращает reactions если они отключены на канале
    for m in messages:
        if hasattr(m, 'reactions') and m.reactions is not None:
            # Атрибут есть, но реакций нет = включены, просто никто не реагировал
            return True

    # Ни у одного поста нет атрибута reactions = реакции отключены
    return False


def get_reaction_emoji(reaction: Any) -> str:
    """
    Безопасно получает emoji реакции.
    v51.1: Делегирует в shared_utils для единообразия.
    """
    return _get_reaction_emoji(reaction)


def calculate_reaction_stability(messages: list) -> dict:
    """
    v52.2: Стабильность КОЛИЧЕСТВА реакций между постами.

    Двухфакторная метрика:
    1. CV (Coefficient of Variation) количества реакций, исключая топ-аутлайер
       - CV < 15% = подозрительно однородно (боты)
       - CV 15-80% = здоровая вариация (живой канал)
       - CV > 80% = хаос (накрутка или мёртвые посты)

    2. Концентрация топ-поста (доля реакций от общей суммы)
       - < 40% = нормально (реакции распределены)
       - 40-60% = есть хит, но ОК
       - > 60% = один пост накручен, остальные мёртвые

    Логика: живой канал имеет разные реакции на разные посты,
    но без экстремальной концентрации в одном.
    """
    # Собираем количество реакций на каждый пост
    reaction_counts = []

    for m in messages:
        count = get_message_reactions_count(m)
        reaction_counts.append(count)

    # Фильтруем посты с реакциями
    non_zero_counts = [c for c in reaction_counts if c > 0]

    if len(non_zero_counts) < 3:
        return {
            'stability_cv': 50.0,
            'top_concentration': 0.2,
            'status': 'insufficient_data',
            'posts_with_reactions': len(non_zero_counts),
            'total_posts': len(reaction_counts)
        }

    total_reactions = sum(non_zero_counts)

    # Концентрация топ-поста
    max_reactions = max(non_zero_counts)
    top_concentration = max_reactions / total_reactions if total_reactions > 0 else 0

    # CV без топ-аутлайера (robust CV)
    # Убираем один максимальный пост чтобы не искажать картину
    counts_without_top = sorted(non_zero_counts)[:-1] if len(non_zero_counts) > 3 else non_zero_counts

    if len(counts_without_top) < 2:
        # Слишком мало данных для CV
        return {
            'stability_cv': 50.0,
            'top_concentration': round(top_concentration, 3),
            'status': 'insufficient_data_for_cv',
            'posts_with_reactions': len(non_zero_counts),
            'total_posts': len(reaction_counts)
        }

    # Расчёт CV
    cv = calculate_cv(counts_without_top, as_percent=True, sample=True)
    mean_count = sum(counts_without_top) / len(counts_without_top) if counts_without_top else 0

    return {
        'stability_cv': round(cv, 1),
        'top_concentration': round(top_concentration, 3),
        'posts_with_reactions': len(non_zero_counts),
        'total_posts': len(reaction_counts),
        'mean_reactions': round(mean_count, 1),
        'max_reactions': max_reactions,
        'total_reactions': total_reactions
    }


def calculate_er_variation(messages: list) -> float:
    """
    D2: Вариация Engagement Rate между постами.
    CV должен быть высоким (разный ER на разных постах).
    """
    ers = []

    for m in messages:
        reactions = get_message_reactions_count(m)
        views = m.views or 0 if hasattr(m, 'views') else 0

        if views > 0:
            er = (reactions / views) * 100
            ers.append(er)

    if len(ers) < 5:
        return 50.0  # Мало данных - нейтральное значение

    cv = calculate_cv(ers, as_percent=True, sample=False)
    return cv if cv > 0 else 50.0


def calculate_er_trend(messages: list) -> dict:
    """
    v45.0: Сравнивает ER новых постов с ER старых постов.
    Детектирует "зомби-каналы" где вовлеченность падает.

    ER = reactions / views * 100
    Trend = er_new / er_old

    Args:
        messages: Список сообщений с date, views, reactions

    Returns:
        {
            'er_new': float,      # Средний ER новых постов (первый квартиль)
            'er_old': float,      # Средний ER старых постов (последний квартиль)
            'er_trend': float,    # er_new / er_old (1.0 = стабильно)
            'status': str,        # 'growing'|'stable'|'declining'|'dying'|'always_dead'
            'posts_new': int,     # Кол-во постов в новой группе
            'posts_old': int,     # Кол-во постов в старой группе
        }

    Статусы:
        - growing: trend >= 1.1 (ER растёт, канал развивается)
        - stable: 0.9 <= trend < 1.1 (норма)
        - declining: 0.7 <= trend < 0.9 (предупреждение)
        - dying: trend < 0.7 (канал "стух", Trust Penalty)
        - always_dead: er_old < 0.1% (канал изначально без вовлечения)
        - insufficient_data: мало постов для анализа
    """
    # Фильтруем посты с датой и просмотрами
    valid_msgs = [
        m for m in messages
        if hasattr(m, 'date') and m.date
        and hasattr(m, 'views') and m.views and m.views > 0
    ]

    if len(valid_msgs) < 12:
        return {
            'er_new': 0.0,
            'er_old': 0.0,
            'er_trend': 1.0,
            'status': 'insufficient_data',
            'posts_new': 0,
            'posts_old': 0
        }

    # Сортируем по дате (новые первые)
    sorted_msgs = sorted(valid_msgs, key=lambda m: m.date, reverse=True)

    # Делим на квартили
    quarter = len(sorted_msgs) // 4
    if quarter < 3:
        quarter = 3  # Минимум 3 поста в группе

    new_msgs = sorted_msgs[:quarter]
    old_msgs = sorted_msgs[-quarter:]

    # Вычисляем ER для каждой группы
    def calc_group_er(msgs):
        ers = []
        for m in msgs:
            reactions = get_message_reactions_count(m)
            if m.views > 0:
                er = (reactions / m.views) * 100
                ers.append(er)
        return sum(ers) / len(ers) if ers else 0.0

    er_new = calc_group_er(new_msgs)
    er_old = calc_group_er(old_msgs)

    # Edge case: канал изначально мёртвый
    if er_old < 0.1:
        return {
            'er_new': round(er_new, 3),
            'er_old': round(er_old, 3),
            'er_trend': None,
            'status': 'always_dead',
            'posts_new': len(new_msgs),
            'posts_old': len(old_msgs)
        }

    # Вычисляем тренд
    er_trend = er_new / er_old if er_old > 0 else 1.0

    # Определяем статус
    if er_trend >= 1.1:
        status = 'growing'
    elif er_trend >= 0.9:
        status = 'stable'
    elif er_trend >= 0.7:
        status = 'declining'
    else:
        status = 'dying'

    return {
        'er_new': round(er_new, 3),
        'er_old': round(er_old, 3),
        'er_trend': round(er_trend, 3),
        'status': status,
        'posts_new': len(new_msgs),
        'posts_old': len(old_msgs)
    }


# ============================================================================
# КАТЕГОРИЯ E: ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ (5 баллов + бонусы)
# ============================================================================

def calculate_source_diversity(messages: list) -> float:
    """
    E1: Разнообразие источников репостов.
    Если >70% репостов из одного канала = сателлит.
    Возвращает max_share (доля самого частого источника).
    """
    sources = []

    for m in messages:
        fwd = getattr(m, 'forward_from_chat', None)
        if fwd:
            source_id = getattr(fwd, 'id', None)
            if source_id:
                sources.append(source_id)

    if not sources:
        return 0.0  # Нет репостов - ок

    source_counts = Counter(sources)
    max_share = max(source_counts.values()) / len(sources)

    return max_share


# check_round_numbers УДАЛЕНА в v3.0
# Причина: современные накрутчики не используют круглые числа, метрика давала шум

# check_is_ad_post и calculate_ad_load УДАЛЕНЫ в v41.0
# Причина: заменены на LLM ad_percentage детекцию


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def get_raw_stats(messages: list) -> dict:
    """Собирает сырую статистику по сообщениям."""
    total_views = 0
    total_forwards = 0
    total_reactions = 0

    for m in messages:
        total_views += m.views or 0 if hasattr(m, 'views') else 0
        total_forwards += m.forwards or 0 if hasattr(m, 'forwards') else 0
        total_reactions += get_message_reactions_count(m)

    posts_count = len(messages)
    avg_views = total_views / posts_count if posts_count else 0

    return {
        'total_views': total_views,
        'total_forwards': total_forwards,
        'total_reactions': total_reactions,
        'avg_views': round(avg_views, 1),
        'posts_analyzed': posts_count
    }


# ============================================================================
# BACKWARD COMPATIBILITY EXPORTS (v52.0)
# These items have been moved to separate modules but are re-exported here
# for backward compatibility. Direct imports from new modules are preferred.
# ============================================================================
from .conviction import FraudConvictionSystem, FraudFactor, check_instant_scam
from .ad_detection import analyze_private_invites
