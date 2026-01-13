"""
Модуль скоринга качества Telegram канала.
v3.0: Система совокупных факторов, Reaction Stability, без Round Numbers.
"""
from typing import Any
from .metrics import (
    check_instant_scam,
    calculate_cv_views,
    calculate_reach,
    calculate_reaction_rate,
    calculate_views_decay,
    calculate_post_regularity,
    calculate_reaction_stability,
    calculate_er_variation,
    calculate_source_diversity,
    calculate_forwards_ratio,
    get_channel_age_days,
    get_raw_stats,
)


# ============================================================================
# ФУНКЦИИ КОНВЕРТАЦИИ МЕТРИК В БАЛЛЫ
# ============================================================================

def cv_to_points(cv: float) -> int:
    """
    CV Views -> баллы (max 14).
    v4.0: Инвертирована логика для CV > 60%.
    CV > 100% = экстремальные скачки = накрутка волнами.
    """
    if cv < 10:
        return 0   # Слишком ровно - бот
    if cv < 30:
        return 10  # Норма
    if cv < 60:
        return 14  # Хорошо - естественная вариация
    if cv < 100:
        return 8   # Подозрительно высокая вариация
    return 0       # CV > 100% = явный скам паттерн (волновая накрутка)


def reach_to_points(reach: float, members: int = 0) -> int:
    """
    Reach % -> баллы (max 12). Учитывает размер канала.
    v4.1: Смягчены пороги для малых каналов - reach 80-100% это хорошо!
    """
    # Размерные пороги для "накрутки"
    if members < 200:
        scam_threshold = 200  # Микроканалы - до 200% норма
        high_is_good = 150    # До 150% = отлично
    elif members < 1000:
        scam_threshold = 150  # Малые - до 150%
        high_is_good = 100    # До 100% = отлично
    elif members < 5000:
        scam_threshold = 130  # Средние - до 130%
        high_is_good = 80     # До 80% = отлично
    else:
        scam_threshold = 120  # Большие - до 120%
        high_is_good = 60     # До 60% = отлично

    if reach > scam_threshold:
        return 0  # Накрутка просмотров для данного размера

    # v4.1: Высокий reach для малых каналов - это ХОРОШО (лояльная аудитория)
    if reach > high_is_good:
        return 4  # Высоковато, но в пределах нормы

    if reach < 5:
        return 0  # Мёртвая аудитория
    if reach < 10:
        return 4
    if reach < 20:
        return 8
    if reach < 50:
        return 10
    return 12  # 50%+ до high_is_good - отлично!


def reaction_rate_to_points(rate: float, members: int = 0) -> int:
    """
    Reaction rate % -> баллы (max 15). Учитывает размер канала.
    v4.2: +5 баллов для max=100.
    """
    # Размерные пороги - малые каналы имеют лояльное ядро
    if members < 200:
        scam_threshold = 20  # Микроканалы - до 20% норма
        high_threshold = 15
    elif members < 1000:
        scam_threshold = 12  # Малые - до 12%
        high_threshold = 8
    else:
        scam_threshold = 10  # Большие - до 10%
        high_threshold = 5

    if rate > scam_threshold:
        return 0  # Накрутка реакций для данного размера
    if rate > high_threshold:
        return 5  # Подозрительно много (но в пределах)
    if rate < 0.3:
        return 3  # Мёртвая аудитория
    if rate < 1:
        return 8
    if rate < 3:
        return 12
    return 15


def decay_to_points(ratio: float) -> int:
    """Views decay ratio -> баллы (max 8)"""
    if ratio < 0.7:
        return 0
    if ratio < 1.0:
        return 2
    if ratio < 1.5:
        return 5
    if ratio < 3.0:
        return 8
    return 4  # Слишком большая разница


def regularity_to_points(cv: float) -> int:
    """Post regularity CV -> баллы (max 3)"""
    if cv < 0.2:
        return 0  # Бот - слишком ровные интервалы
    if cv < 0.5:
        return 2
    return 3


def stability_to_points(data: dict) -> int:
    """
    Reaction Stability -> баллы (max 8).
    v4.1: Высокий CV = разнообразный контент = ХОРОШО, не штрафовать!
    """
    cv = data.get('stability_cv', 50.0)

    if cv < 15:
        return 2   # Слишком идеально - возможна манипуляция ботами
    if cv < 50:
        return 8   # Отлично - стабильные предпочтения аудитории
    if cv < 100:
        return 7   # Хорошо - умеренная вариация (разный контент)
    if cv < 200:
        return 6   # Нормально - разнообразный контент, живая аудитория
    return 5       # Очень высокая вариация - всё равно живая аудитория!


def er_cv_to_points(cv: float, members: int = 0) -> int:
    """
    ER variation CV -> баллы (max 10).
    v4.1: Микроканалы имеют низкую ER вариацию по математике - смягчить пороги.
    """
    # Микроканалы: маленькие числа → меньше статистическая вариация
    if members < 200:
        if cv < 15:
            return 0   # Слишком ровно - боты
        if cv < 30:
            return 5   # Нормально для микро
        if cv < 50:
            return 8   # Хорошо
        return 10      # Отлично

    # Стандартные пороги для больших каналов
    if cv < 20:
        return 0
    if cv < 40:
        return 3
    if cv < 70:
        return 7
    return 10


def source_to_points(max_share: float, repost_ratio: float = 1.0) -> int:
    """Source diversity -> баллы (max 5). Учитывает долю репостов."""
    # Если репостов мало (<10%) - не штрафовать за концентрацию источников
    if repost_ratio < 0.10:
        return 5  # Канал с оригинальным контентом

    if max_share > 0.7:
        return 0  # Сателлит (>70% из одного источника)
    if max_share > 0.5:
        return 2
    return 5


# round_to_points УДАЛЕНА в v3.0
# Причина: метрика не дискриминирует, баллы перенесены в cv_to_points


def forward_rate_to_points(rate: float, members: int = 0) -> int:
    """
    Forward Rate % -> баллы (max 5).
    v4.3: Виральность контента - люди расшаривают = бесплатный охват для рекламы.
    Учитывает размер канала (большие каналы имеют ниже forward rate естественно).
    """
    # Большие каналы имеют ниже forward rate из-за насыщения аудитории
    if members > 50000:
        thresholds = {'excellent': 1.5, 'good': 0.7, 'medium': 0.3}
    elif members > 5000:
        thresholds = {'excellent': 2.0, 'good': 1.0, 'medium': 0.5}
    else:
        thresholds = {'excellent': 3.0, 'good': 1.5, 'medium': 0.5}

    # Защита от накрутки пересылок
    if rate > 15:
        return 0  # Подозрительно много - возможна накрутка через сеть каналов

    if rate >= thresholds['excellent']:
        return 5  # Виральный контент
    if rate >= thresholds['good']:
        return 4  # Хорошо расшаривают
    if rate >= thresholds['medium']:
        return 3  # Средне
    if rate >= 0.1:
        return 1  # Минимум
    return 0      # Контент не расшаривают


def age_to_bonus(age_days: int) -> int:
    """
    Возраст канала -> бонус (max 8).
    v4.3: Старый канал = стабильная аудитория = лучше для рекламы.
    """
    if age_days < 0:
        return 0   # Дата недоступна
    if age_days < 90:
        return 0   # < 3 месяцев - newborn
    if age_days < 180:
        return 2   # 3-6 месяцев - young
    if age_days < 365:
        return 4   # 6-12 месяцев - mature
    if age_days < 730:
        return 6   # 1-2 года - established
    return 8       # > 2 лет - veteran


# ============================================================================
# ФИНАЛЬНЫЙ СКОРИНГ
# ============================================================================

def comments_to_points(comments_data: dict, members: int = 0, reach: float = 0) -> tuple[int, str]:
    """
    Конвертирует данные о комментариях в баллы (max 20).
    v4.2: +5 баллов от удалённой Originality.
    При подозрительном reach (>150%) комментарии НЕ могут компенсировать.
    Возвращает (points, status_string).
    """
    if not comments_data.get('enabled', False):
        return 0, "disabled"  # RED FLAG

    avg = comments_data.get('avg_comments', 0)

    # Если reach подозрительный, ограничить max баллы
    if reach > 200:
        max_pts = 8   # Очень подозрительно - комментарии не спасут
    elif reach > 150:
        max_pts = 15  # Подозрительно - ограничить влияние комментов
    else:
        max_pts = 25  # Нормальный reach (v4.2: +10 от originality, max=100)

    # Размерные пороги - малые каналы имеют меньше комментаторов
    # v4.2: max = 25 (добавлено 10 от originality)
    if members < 200:
        # Микроканалы - смягчены пороги (0.1 комментов = норма!)
        if avg < 0.01:
            pts = 0   # Вообще нет комментов
        elif avg < 0.05:
            pts = 8   # Очень мало, но есть
        elif avg < 0.2:
            pts = 15  # Нормально для микро
        elif avg < 0.5:
            pts = 20  # Хорошо
        else:
            pts = 25  # Отлично
    elif members < 1000:
        # Малые каналы: ожидаемо ~0.3-1 комментов
        if avg < 0.1:
            pts = 0
        elif avg < 0.3:
            pts = 5
        elif avg < 1:
            pts = 12
        elif avg < 3:
            pts = 20
        else:
            pts = 25
    else:
        # Большие каналы: стандартные пороги
        if avg < 0.3:
            pts = 0
        elif avg < 0.5:
            pts = 5
        elif avg < 2:
            pts = 12
        elif avg < 5:
            pts = 20
        else:
            pts = 25

    # Применить ограничение от reach
    final_pts = min(pts, max_pts)
    status = f"enabled (avg {avg:.1f})"
    if reach > 150:
        status += f" [reach penalty]"

    return final_pts, status


def calculate_final_score(chat: Any, messages: list, comments_data: dict = None) -> dict:
    """
    Полный расчёт качества канала.
    v3.0: Система совокупных факторов, Reaction Stability.
    Возвращает score 0-100 и детальный breakdown.
    """
    # Дефолтные данные о комментариях если не переданы
    if comments_data is None:
        comments_data = {
            'enabled': getattr(chat, 'linked_chat', None) is not None,
            'avg_comments': 0.0,
            'total_comments': 0
        }

    # ===== КАТЕГОРИЯ A: СИСТЕМА СОВОКУПНЫХ ФАКТОРОВ =====
    is_scam, scam_reason, conviction_details = check_instant_scam(chat, messages, comments_data)

    if is_scam:
        return {
            'channel': getattr(chat, 'username', None) or str(getattr(chat, 'id', 'unknown')),
            'members': getattr(chat, 'members_count', 0),
            'score': 0,
            'verdict': 'SCAM',
            'reason': scam_reason,
            'conviction': conviction_details,  # Детали conviction score
            'breakdown': {},
            'flags': {
                'is_scam': getattr(chat, 'is_scam', False),
                'is_fake': getattr(chat, 'is_fake', False),
                'is_verified': getattr(chat, 'is_verified', False),
                'comments_enabled': comments_data.get('enabled', False)
            },
            'raw_stats': get_raw_stats(messages)
        }

    score = 0
    breakdown = {}

    # Данные для расчётов
    views = [m.views for m in messages if hasattr(m, 'views') and m.views]
    members = getattr(chat, 'members_count', 0) or 1
    avg_views = sum(views) / len(views) if views else 0

    # ===== КАТЕГОРИЯ B: ОСНОВНЫЕ МЕТРИКИ =====

    # B1: CV Views (14 pts) - +2 от удалённых Round Numbers
    cv = calculate_cv_views(views)
    cv_score = cv_to_points(cv)
    score += cv_score
    breakdown['cv_views'] = {'value': round(cv, 2), 'points': cv_score, 'max': 14}

    # B2: Reach (12 pts) - с учётом размера канала
    reach = calculate_reach(avg_views, members)
    reach_score = reach_to_points(reach, members)
    score += reach_score
    breakdown['reach'] = {'value': round(reach, 2), 'points': reach_score, 'max': 12}

    # B3: Comments (15 pts) - v4.0: снижен с 25, зависит от reach
    comments_pts, comments_status = comments_to_points(comments_data, members, reach)
    score += comments_pts
    breakdown['comments'] = {
        'value': comments_status,
        'points': comments_pts,
        'max': 25,
        'total': comments_data.get('total_comments', 0),
        'avg': round(comments_data.get('avg_comments', 0), 1)
    }

    # B4: Reaction Rate (10 pts) - с учётом размера канала
    reaction_rate = calculate_reaction_rate(messages)
    reaction_score = reaction_rate_to_points(reaction_rate, members)
    score += reaction_score
    breakdown['reaction_rate'] = {'value': round(reaction_rate, 3), 'points': reaction_score, 'max': 15}

    # B5: Originality - УДАЛЕНА в v4.2
    # Причина: не дискриминирует (все каналы получают 100%)
    # 5 баллов убраны из общего пула

    # ===== КАТЕГОРИЯ C: ВРЕМЕННЫЕ МЕТРИКИ =====

    # C1: Views Decay (8 pts)
    decay_ratio = calculate_views_decay(messages)
    decay_score = decay_to_points(decay_ratio)
    score += decay_score
    breakdown['views_decay'] = {'value': round(decay_ratio, 2), 'points': decay_score, 'max': 8}

    # C2: Post Regularity (3 pts)
    regularity_cv = calculate_post_regularity(messages)
    regularity_score = regularity_to_points(regularity_cv)
    score += regularity_score
    breakdown['regularity'] = {'value': round(regularity_cv, 2), 'points': regularity_score, 'max': 3}

    # ===== КАТЕГОРИЯ D: АНАЛИЗ РЕАКЦИЙ =====

    # D1: Reaction Stability (8 pts) - v3.0: стабильность пропорций вместо разнообразия
    stability = calculate_reaction_stability(messages)
    stability_score = stability_to_points(stability)
    score += stability_score
    breakdown['reaction_stability'] = {
        'value': stability.get('stability_cv', 50.0),
        'points': stability_score,
        'max': 8,
        'unique_types': stability.get('unique_types', 0),
        'distribution': stability.get('distribution', {})
    }

    # D2: ER Variation (10 pts) - v4.1: с учётом размера канала
    er_cv = calculate_er_variation(messages)
    er_score = er_cv_to_points(er_cv, members)
    score += er_score
    breakdown['er_variation'] = {'value': round(er_cv, 1), 'points': er_score, 'max': 10}

    # ===== КАТЕГОРИЯ E: ДОПОЛНИТЕЛЬНЫЕ =====

    # E1: Source Diversity (5 pts) - с учётом доли репостов
    source_max = calculate_source_diversity(messages)
    # v4.2: Вычисляем repost_ratio напрямую (originality удалена)
    forwards = sum(1 for m in messages if getattr(m, 'forward_from_chat', None))
    repost_ratio = forwards / len(messages) if messages else 0
    source_score = source_to_points(source_max, repost_ratio)
    score += source_score
    breakdown['source_diversity'] = {
        'value': round(1 - source_max, 2),
        'points': source_score,
        'max': 5,
        'repost_ratio': round(repost_ratio, 2)
    }

    # Round Numbers УДАЛЕНА в v3.0 - баллы перенесены в CV Views

    # E2: Forward Rate (5 pts) - v4.3: Виральность контента
    forward_rate = calculate_forwards_ratio(messages)
    forward_score = forward_rate_to_points(forward_rate, members)
    score += forward_score
    breakdown['forward_rate'] = {
        'value': round(forward_rate, 3),
        'points': forward_score,
        'max': 5,
        'status': 'viral' if forward_rate >= 3.0 else ('good' if forward_rate >= 1.0 else 'low')
    }

    # ===== КАТЕГОРИЯ F: БОНУСЫ =====

    # F1: Verified Bonus (+10)
    is_verified = getattr(chat, 'is_verified', False)
    if is_verified:
        score += 10
        breakdown['verified_bonus'] = {'value': True, 'points': 10, 'max': 10}

    # F2: Channel Age Bonus (+8) - v4.3: Старый канал = стабильная аудитория
    age_days = get_channel_age_days(chat)
    age_bonus = age_to_bonus(age_days)
    if age_bonus > 0:
        score += age_bonus
        # Определяем категорию возраста
        if age_days >= 730:
            age_status = 'veteran'
        elif age_days >= 365:
            age_status = 'established'
        elif age_days >= 180:
            age_status = 'mature'
        elif age_days >= 90:
            age_status = 'young'
        else:
            age_status = 'newborn'
        breakdown['age_bonus'] = {
            'value': age_days,
            'points': age_bonus,
            'max': 8,
            'status': age_status
        }

    # ===== v4.0: CONVICTION PENALTY =====
    # Даже если канал не SCAM, высокий conviction штрафует score
    conviction_score = conviction_details.get('conviction_score', 0)
    effective_conviction = conviction_details.get('effective_conviction', 0)

    if effective_conviction >= 40:
        # Штраф пропорционален conviction: каждые 10 пунктов выше 40 = -5 баллов
        penalty = int((effective_conviction - 40) * 0.5)
        penalty = min(penalty, 30)  # Максимум -30 баллов
        score -= penalty
        breakdown['conviction_penalty'] = {
            'value': effective_conviction,
            'points': -penalty,
            'max': -30,
            'factors_triggered': conviction_details.get('factors_triggered', 0)
        }

    # ===== ФИНАЛЬНЫЙ ВЕРДИКТ =====
    # v4.3: Max теперь 118 (100 base + 10 verified + 8 age)
    # Для вердикта используем base score (без бонусов) для справедливого сравнения
    base_score = score - (10 if is_verified else 0) - age_bonus
    base_score = min(100, max(0, base_score))

    # Полный score с бонусами (не ограничен 100)
    score = max(0, score)

    # Вердикт по base score
    if base_score >= 75:
        verdict = 'EXCELLENT'
    elif base_score >= 55:
        verdict = 'GOOD'
    elif base_score >= 40:
        verdict = 'MEDIUM'
    elif base_score >= 25:
        verdict = 'HIGH_RISK'
    else:
        verdict = 'SCAM'

    return {
        'channel': getattr(chat, 'username', None) or str(getattr(chat, 'id', 'unknown')),
        'members': members,
        'score': score,
        'base_score': base_score,  # v4.3: Score без бонусов (для справедливого сравнения)
        'verdict': verdict,
        'conviction': conviction_details,  # v4.3: Показываем conviction для всех каналов
        'breakdown': breakdown,
        'flags': {
            'is_scam': getattr(chat, 'is_scam', False),
            'is_fake': getattr(chat, 'is_fake', False),
            'is_verified': is_verified,
            'comments_enabled': getattr(chat, 'linked_chat', None) is not None
        },
        'raw_stats': get_raw_stats(messages)
    }
