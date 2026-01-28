"""
Модуль скоринга качества Telegram канала.
v15.2: Reactions Floating Weights + улучшенные Trust Penalties.

Архитектура:
- RAW SCORE (0-100): Качество "витрины" (cv_views, reach, comments, reactions...)
- TRUST FACTOR (0.0-1.0): Множитель доверия (forensics + statistical + ghost + decay)
- FINAL SCORE = RAW SCORE × TRUST FACTOR

v15.2 Changes:
- Floating Weights для реакций (если отключены → баллы в forward)
- BOT WALL усилен: ×0.8 → ×0.6
- HOLLOW VIEWS адаптивные пороги по размеру канала
- SATELLITE: НЕ штрафовать если комменты живые (avg >= 1)

Decay Analysis (v15.1):
- ЗДОРОВАЯ ОРГАНИКА (0.3-0.95): Старые посты накопили просмотры → MAX баллы
- ВИРАЛЬНЫЙ РОСТ (1.05-2.0): Канал растёт → MAX баллы
- BOT WALL (×0.6): ratio 0.98-1.02 = подозрительно ровно
- BUDGET CLIFF (×0.7): ratio < 0.2 = деньги кончились

Ghost Protocol (v15.0):
- GHOST CHANNEL (×0.5): 20k+ subs, <0.1% online
- ZOMBIE AUDIENCE (×0.7): 5k+ subs, <0.3% online
- MEMBER DISCREPANCY (×0.8): Расхождение count >10%

Statistical Trust Penalties (v13.5):
- HOLLOW VIEWS (×0.6): Reach > adaptive threshold + Forward <0.5%
- ZOMBIE ENGAGEMENT (×0.7): Reach >50% + Reaction <0.1%
- SATELLITE (×0.8): Source share >50% + avg_comments < 1

Пример:
- Органика: Raw 75, Decay 0.72 → Trust 1.0 → 75 EXCELLENT
- Bot Wall: Raw 65, Decay 1.00 → Trust 0.6 → 39 MEDIUM
- Ghost: Raw 65 × Trust 0.5 (Ghost Channel) = 32 HIGH_RISK
"""
from typing import Any
from .shared_utils import calculate_cv
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
    # v15.0: New metrics
    calculate_posts_per_day,
    analyze_private_invites,
    # v22.3: Для определения reactions_enabled
    get_message_reactions_count,
    # v22.4: Правильная проверка включены ли реакции
    check_reactions_enabled,
    # v45.0: ER Trend для детекции зомби-каналов
    calculate_er_trend,
)
from .forensics import UserForensics
from .config import SIZE_THRESHOLDS


# ============================================================================
# v13.0: RAW SCORE WEIGHTS (сумма = 100)
# ============================================================================

RAW_WEIGHTS = {
    # v48.0: КАЧЕСТВО КОНТЕНТА (42 балла)
    # Бизнес-ориентированный скоринг: виральность и регулярность важнее технических метрик
    'quality': {
        'forward_rate': 15,  # v48.0: +2 (виральность = "Святой Грааль")
        'cv_views': 12,      # v48.0: -3 (снизили, но важно для детекции)
        'reach': 8,          # v48.0: +1
        'regularity': 7,     # v48.0: NEW! Стабильность постинга
        # views_decay убран из баллов → остался в Trust Factor (bot_wall)
    },
    # v48.0: ENGAGEMENT (38 баллов)
    # Тренд важнее абсолютных чисел, реакции легко накрутить
    'engagement': {
        'comments': 15,      # Комментарии (floating если закрыты)
        'er_trend': 10,      # v48.0: NEW! Канал растёт или умирает?
        'reaction_rate': 8,  # v48.0: -7 (легко накрутить)
        'stability': 5,      # Стабильность реакций
        # er_variation убран → заменён на er_trend
    },
    # РЕПУТАЦИЯ (20 баллов) — без изменений
    'reputation': {
        'verified': 0,       # v38.4: Верификация убрана
        'age': 7,
        'premium': 7,
        'source': 6,
    },
}

# v48.0: Итоги по категориям
CATEGORY_TOTALS = {
    'quality': 42,      # v48.0: было 40, +2
    'engagement': 38,   # v48.0: было 40, -2
    'reputation': 20,
}

# ============================================================================
# v13.0: TRUST FACTOR MULTIPLIERS
# ============================================================================

TRUST_FACTORS = {
    # Forensics-based penalties
    'id_clustering_fatality': 0.0,    # Ферма ботов = обнуление
    'id_clustering_suspicious': 0.5,  # Подозрительная кластеризация
    'geo_dc_mismatch': 0.2,           # Чужие датацентры
    'premium_zero': 0.8,              # 0% премиумов

    # Content-based penalties
    'hidden_comments': 0.7,           # Скрытые комментарии

    # Conviction-based penalties
    'conviction_critical': 0.3,       # Conviction >= 70
    'conviction_high': 0.6,           # Conviction >= 50

    # v15.0: Spam Posting penalties
    'spam_posting_spam': 0.55,        # >20 posts/day
    'spam_posting_heavy': 0.75,       # 12-20 posts/day
    'spam_posting_active': 0.90,      # 6-12 posts/day

    # v15.0: Private Links penalties (всё в %)
    'private_100': 0.25,              # 100% приватных
    'private_80': 0.35,               # >80% приватных
    'private_60': 0.50,               # >60% приватных
    'private_crypto_combo': 0.45,     # CRYPTO + >40% приватных
    'private_hidden_combo': 0.40,     # >50% + комменты выкл
}

# Backward compatibility alias
WEIGHTS = RAW_WEIGHTS


# ============================================================================
# ФУНКЦИИ КОНВЕРТАЦИИ МЕТРИК В БАЛЛЫ (v13.0)
# ============================================================================

def cv_to_points(cv: float, forward_rate: float = 0, max_pts: int = None) -> int:
    """
    v13.0: CV Views -> баллы (default max 15).
    Естественность распределения просмотров.

    CV 30-60% = идеально (естественная вариация)
    CV < 10% = подозрительно ровно (боты)
    CV > 100% = экстремальные скачки (накрутка волнами или вирус)

    Viral Exception: CV > 100% + forward_rate > 3% = виральный контент, не штрафуем.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['quality']['cv_views']  # 15

    if cv < 10:
        return 0   # Слишком ровно - бот
    if cv < 30:
        return int(max_pts * 0.67)  # ~10
    if cv < 60:
        return max_pts  # 15 - отлично
    if cv < 100:
        return int(max_pts * 0.5)   # ~7 - подозрительно высоко

    # CV >= 100% - волновая накрутка или вирус
    if forward_rate > 3.0:
        return int(max_pts * 0.5)   # Viral Exception - спасаем
    return 0  # Накрутка волнами


def reach_to_points(reach: float, members: int = 0, max_pts: int = None) -> int:
    """
    v13.0: Reach % -> баллы (default max 10). Учитывает размер канала.
    Без отрицательных штрафов - просто 0 за плохие значения.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['quality']['reach']  # 10

    # Размерные пороги для "накрутки"
    # v23.0: использует SIZE_THRESHOLDS из config.py
    if members < SIZE_THRESHOLDS['micro']:
        scam_threshold = 200  # Микроканалы - до 200% норма
        high_is_good = 150
    elif members < SIZE_THRESHOLDS['small']:
        scam_threshold = 150
        high_is_good = 100
    elif members < SIZE_THRESHOLDS['medium']:
        scam_threshold = 130
        high_is_good = 80
    else:
        scam_threshold = 120
        high_is_good = 60

    if reach > scam_threshold:
        return 0  # Накрутка

    if reach > high_is_good:
        return int(max_pts * 0.5)  # 5

    if reach < 5:
        return 0  # Мёртвая аудитория
    if reach < 10:
        return int(max_pts * 0.4)  # 4
    if reach < 20:
        return int(max_pts * 0.6)  # 6
    if reach < 50:
        return int(max_pts * 0.8)  # 8
    return max_pts  # 10


def reaction_rate_to_points(rate: float, members: int = 0, max_pts: int = None) -> int:
    """
    v13.0: Reaction rate % -> баллы (default max 15, до 22 при floating weights).
    Без отрицательных штрафов.

    Args:
        rate: Reaction rate в процентах
        members: Количество подписчиков
        max_pts: Максимум баллов (15 по умолчанию, 22 при floating weights)
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['engagement']['reaction_rate']  # 15
    # Размерные пороги
    # v23.0: использует SIZE_THRESHOLDS из config.py
    if members < SIZE_THRESHOLDS['micro']:
        scam_threshold = 20
        high_threshold = 15
    elif members < SIZE_THRESHOLDS['small']:
        scam_threshold = 12
        high_threshold = 8
    else:
        scam_threshold = 10
        high_threshold = 5

    if rate > scam_threshold:
        return 0  # Накрутка

    if rate > high_threshold:
        return int(max_pts * 0.3)  # Подозрительно много
    if rate < 0.3:
        return int(max_pts * 0.2)  # Мёртвая аудитория
    if rate < 1:
        return int(max_pts * 0.5)
    if rate < 3:
        return int(max_pts * 0.8)
    return max_pts


def decay_to_points(ratio: float, reaction_rate: float = 0, max_pts: int = None) -> tuple[int, dict]:
    """
    v15.1: Views Decay Analysis - исправленная логика.

    ratio = avg_views_new / avg_views_old

    ПРАВИЛЬНОЕ понимание:
    - ratio < 1.0 = Старые посты имеют БОЛЬШЕ просмотров → НОРМА (накопительный эффект)
    - ratio ≈ 1.0 = Идеально ровно → ПОДОЗРИТЕЛЬНО (автонакрутка)
    - ratio > 1.0 = Новые посты больше → Виральность ИЛИ свежая накрутка

    Зоны:
    - GREEN (0.3 - 0.95): Здоровая органика, старые накопили просмотры
    - GREEN (1.05 - 2.0): Виральный рост, канал на хайпе
    - RED (0.98 - 1.02): "Стена ботов" - слишком ровно
    - RED (< 0.2): "Обрыв" - деньги на накрутку кончились

    Returns:
        (points, info_dict) с деталями анализа
    """
    if max_pts is None:
        max_pts = 0  # v48.0: views_decay теперь info_only, баллы не начисляются

    info = {'ratio': ratio, 'zone': 'unknown', 'description': ''}

    # Сценарий 1: ЗДОРОВАЯ ОРГАНИКА (0.3 - 0.95)
    # Старые посты накопили просмотры естественным путём
    # ratio 0.72 значит: новые = 72% от старых, старые на 28% больше - это НОРМА
    if 0.3 <= ratio <= 0.95:
        info['zone'] = 'healthy_organic'
        info['description'] = f'Старые посты на {(1/ratio - 1)*100:.0f}% больше (накопительный эффект)'
        return max_pts, info  # 8/8 MAX

    # Сценарий 2: ВИРАЛЬНЫЙ РОСТ (1.05 - 2.0)
    # Канал растёт, новые посты набирают больше (хайп, реклама, виральность)
    if 1.05 <= ratio <= 2.0:
        info['zone'] = 'viral_growth'
        info['description'] = f'Новые посты на {(ratio - 1)*100:.0f}% больше (рост канала)'
        return max_pts, info  # 8/8 MAX

    # Сценарий 3: СТЕНА БОТОВ (0.98 - 1.02)
    # Слишком ровные просмотры = автонакрутка фиксированного числа
    # В реальности так НЕ бывает - всегда есть разброс
    if 0.98 <= ratio <= 1.02:
        info['zone'] = 'bot_wall'
        info['description'] = f'Подозрительно ровно ({ratio:.2f}) - возможна автонакрутка'
        return 2, info  # Штраф

    # Сценарий 4: ОБРЫВ (< 0.2)
    # Новые посты = 20% от старых - бюджет на накрутку кончился
    # Админ перестал платить, а органики нет
    if ratio < 0.2:
        info['zone'] = 'budget_cliff'
        info['description'] = f'Обрыв: новые = {ratio*100:.0f}% от старых (деньги кончились?)'
        return 0, info  # SCAM signal

    # Сценарий 5: УМЕРЕННЫЙ РОСТ (0.95 - 1.05)
    # Небольшое колебание около 1.0 - нормально
    if 0.95 < ratio < 1.05:
        info['zone'] = 'stable'
        info['description'] = 'Стабильные просмотры'
        return 6, info  # Хорошо, но не идеально

    # Сценарий 6: НЕБОЛЬШОЙ РАЗРЫВ (0.2 - 0.3)
    # Большой разрыв, но не критичный - подозрительно
    if 0.2 <= ratio < 0.3:
        info['zone'] = 'suspicious_gap'
        info['description'] = f'Большой разрыв: новые = {ratio*100:.0f}% от старых'
        return 3, info  # Умеренный штраф

    # Сценарий 7: СЛИШКОМ БОЛЬШОЙ РОСТ (> 2.0)
    # Новые посты в 2+ раза больше старых - возможно свежая накрутка
    if ratio > 2.0:
        info['zone'] = 'suspicious_growth'
        info['description'] = f'Подозрительный рост: новые в {ratio:.1f}x больше'
        return 4, info  # Умеренный штраф

    # Fallback
    info['zone'] = 'unknown'
    info['description'] = f'Необычное значение: {ratio:.2f}'
    return 4, info


def stability_to_points(data: dict, max_pts: int = None) -> int:
    """
    v52.2: Reaction Stability -> баллы (двухфакторная логика).

    Два фактора:
    1. CV (Coefficient of Variation) количества реакций (без топ-аутлайера)
    2. Концентрация топ-поста (доля от всех реакций)

    Логика скоринга:
    | CV       | Концентрация | Баллы | Интерпретация            |
    |----------|--------------|-------|--------------------------|
    | < 15%    | любая        | 1     | Боты (слишком однородно) |
    | 15-80%   | < 40%        | 5     | Здоровый живой канал     |
    | 15-80%   | 40-60%       | 3     | Есть хит, но ОК          |
    | любой    | > 60%        | 1     | Накрутка одного поста    |
    | > 80%    | любая        | 2     | Хаос (слишком разброс)   |

    Живой канал: умеренная вариация (15-80%) + распределённые реакции (<40% в топе).
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['engagement']['stability']  # 5

    # v52.2: Совместимость с разными форматами breakdown
    # - Новый формат (metrics.py): stability_cv, top_concentration
    # - Старый формат (breakdown): value, top_concentration
    cv = data.get('stability_cv') or data.get('value', 50.0)  # fallback для breakdown
    concentration = data.get('top_concentration', 0.2)  # default = healthy

    # Приоритет 1: Экстремальная концентрация = накрутка одного поста
    if concentration > 0.60:
        return 1  # Один пост собрал >60% всех реакций

    # Приоритет 2: Слишком однородно = боты
    if cv < 15:
        return 1  # CV < 15% = подозрительно ровные реакции

    # Приоритет 3: Хаос = слишком большой разброс
    if cv > 80:
        return 2  # CV > 80% = экстремальная вариация

    # Здоровая зона CV (15-80%)
    if concentration < 0.40:
        return 5  # Здоровый канал: умеренный CV + распределённые реакции
    else:
        return 3  # Есть хит (40-60% в топе), но CV нормальный


def source_to_points(max_share: float, repost_ratio: float = 1.0, max_pts: int = None) -> int:
    """
    v13.0: Source diversity -> баллы (default max 5).
    Без отрицательных штрафов.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['reputation']['source']  # 5

    # Если репостов мало (<10%) - оригинальный контент
    if repost_ratio < 0.10:
        return max_pts

    if max_share > 0.7:
        return 0  # Сателлит
    if max_share > 0.5:
        return int(max_pts * 0.4)  # 2
    return max_pts


# round_to_points УДАЛЕНА в v3.0
# Причина: метрика не дискриминирует, баллы перенесены в cv_to_points


def forward_rate_to_points(rate: float, members: int = 0, max_pts: int = None) -> int:
    """
    v13.0: Forward Rate % -> баллы (default max 7, до 15 при floating weights).

    Args:
        rate: Forward rate в процентах
        members: Количество подписчиков
        max_pts: Максимум баллов (7 по умолчанию, 15 при floating weights)
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['quality']['forward_rate']  # 7

    # Размерные пороги
    # v23.0: использует SIZE_THRESHOLDS из config.py
    if members > SIZE_THRESHOLDS['large']:
        thresholds = {'viral': 1.5, 'excellent': 0.7, 'good': 0.3, 'medium': 0.1}
    elif members > SIZE_THRESHOLDS['medium']:
        thresholds = {'viral': 2.0, 'excellent': 1.0, 'good': 0.5, 'medium': 0.2}
    else:
        thresholds = {'viral': 3.0, 'excellent': 1.5, 'good': 0.5, 'medium': 0.1}

    if rate > 15:
        return 0  # Накрутка

    if rate >= thresholds['viral']:
        return max_pts
    if rate >= thresholds['excellent']:
        return int(max_pts * 0.8)
    if rate >= thresholds['good']:
        return int(max_pts * 0.6)
    if rate >= thresholds['medium']:
        return int(max_pts * 0.3)
    if rate >= 0.05:
        return int(max_pts * 0.15)
    return 0


def age_to_points(age_days: int, max_pts: int = None) -> int:
    """
    v13.0: Возраст канала -> баллы (default max 5).
    Старый канал = стабильная аудитория.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['reputation']['age']  # 5

    if age_days < 0:
        return 0
    if age_days < 90:
        return 0   # < 3 месяцев - newborn
    if age_days < 180:
        return 1   # 3-6 месяцев - young
    if age_days < 365:
        return 2   # 6-12 месяцев - mature
    if age_days < 730:
        return 4   # 1-2 года - established
    return max_pts  # 5 - > 2 лет - veteran


def regularity_to_points(posts_per_day: float, max_pts: int = None) -> int:
    """
    v48.0: Регулярность постинга → баллы (max 7).

    Идеал: 1-5 постов в день = профессиональный канал.
    <1 в неделю = мёртвый канал.
    >20 в день = спам-помойка.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['quality']['regularity']  # 7

    if posts_per_day < 0.14:      # < 1 в неделю
        return 0                   # Мёртвый канал
    if posts_per_day < 0.5:       # 3-4 в неделю
        return int(max_pts * 0.4)  # 3 балла
    if posts_per_day < 1.0:       # почти каждый день
        return int(max_pts * 0.7)  # 5 баллов
    if posts_per_day <= 5.0:      # 1-5 в день = ИДЕАЛ
        return max_pts             # 7 баллов
    if posts_per_day <= 10.0:     # 5-10 в день
        return int(max_pts * 0.7)  # 5 баллов
    if posts_per_day <= 20.0:     # 10-20 в день
        return int(max_pts * 0.4)  # 3 балла
    return int(max_pts * 0.15)    # >20 = спам, 1 балл


def er_trend_to_points(er_trend_data: dict, max_pts: int = None) -> int:
    """
    v48.0: Тренд вовлеченности → баллы (max 10).

    Растёт = покупай сейчас (дешевле не будет).
    Падает = аудитория выгорает.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['engagement']['er_trend']  # 10

    status = er_trend_data.get('status', 'insufficient_data')
    # trend = er_trend_data.get('er_trend', 1.0)  # Not used directly, status is derived from it

    if status == 'insufficient_data':
        return int(max_pts * 0.5)  # 5 баллов (недостаточно данных)

    if status == 'always_dead':
        return 0                    # Всегда мёртвый

    if status == 'growing':         # trend >= 1.1
        return max_pts              # 10 баллов

    if status == 'stable':          # 0.9 <= trend < 1.1
        return int(max_pts * 0.7)   # 7 баллов

    if status == 'declining':       # 0.7 <= trend < 0.9
        return int(max_pts * 0.3)   # 3 балла

    # status == 'dying' (trend < 0.7)
    return 0                        # Канал умирает


def calculate_floating_weights(comments_enabled: bool, reactions_enabled: bool = True) -> dict:
    """
    v48.0: Плавающие веса для комментов И реакций.

    Базовые веса: 15 comments + 8 reactions + 15 forward = 38

    Сценарии:
    - Всё включено:           15 comments + 8 reactions + 15 forward = 38
    - Без комментов:          0 comments + 13 reactions + 25 forward = 38
    - Без реакций:            20 comments + 0 reactions + 18 forward = 38
    - Без обоих:              0 comments + 0 reactions + 38 forward = 38
    """
    base_comments = RAW_WEIGHTS['engagement']['comments']        # 15
    base_reactions = RAW_WEIGHTS['engagement']['reaction_rate']  # 8 (v48.0)
    base_forward = RAW_WEIGHTS['quality']['forward_rate']        # 15 (v48.0)

    if comments_enabled and reactions_enabled:
        # Всё включено - стандартные веса
        return {
            'comments_max': base_comments,      # 15
            'reaction_rate_max': base_reactions, # 8
            'forward_rate_max': base_forward     # 15
        }
    elif comments_enabled and not reactions_enabled:
        # Реакции отключены - их баллы в комменты и forward
        return {
            'comments_max': 20,         # 15 + 5
            'reaction_rate_max': 0,
            'forward_rate_max': 18      # 15 + 3
        }
    elif not comments_enabled and reactions_enabled:
        # Комменты отключены - их баллы в реакции и forward
        return {
            'comments_max': 0,
            'reaction_rate_max': 13,    # 8 + 5
            'forward_rate_max': 25      # 15 + 10
        }
    else:
        # Оба отключены - всё в forward
        return {
            'comments_max': 0,
            'reaction_rate_max': 0,
            'forward_rate_max': 38      # v48.0: Все 38 баллов
        }


def calculate_adaptive_weights(forensics_available: bool, users_count: int) -> dict:
    """
    v12.0: Определяем режим скоринга (normal/hardcore).
    В v12.0 нет штрафов - просто разные способы заработать баллы.

    Если forensics доступен - можно заработать баллы за качество аудитории.
    Если нет - эти баллы недоступны (максимум 95 вместо 100).
    """
    MIN_USERS_FOR_FORENSICS = 10

    if forensics_available and users_count >= MIN_USERS_FOR_FORENSICS:
        return {
            'mode': 'normal',
            'forensics_available': True,
            'flatness_enabled': False
        }
    else:
        return {
            'mode': 'hardcore',
            'forensics_available': False,
            'flatness_enabled': True  # F16 как замена forensics
        }


def calculate_trust_factor(
    forensics_result,
    comments_enabled: bool,
    conviction_score: int,
    is_verified: bool = False,
    # v13.5: Statistical Trust Parameters
    reach: float = 0,
    forward_rate: float = 0,
    reaction_rate: float = 0,
    source_share: float = 0,
    # v15.0: Ghost Protocol Parameters
    members: int = 0,
    online_count: int = 0,
    participants_count: int = 0,
    # v15.1: Decay Trust Parameters
    decay_ratio: float = 0.7,
    # v51.2: CV views для проверки bot_wall false positives
    cv_views: float = 0,
    # v15.2: Satellite Parameters
    avg_comments: float = 0,
    # v47.4: Comment Trust из LLM анализа (0-100)
    comment_trust: int = 0,
    # v15.0: New Penalties
    posting_data: dict = None,
    network_data: dict = None,
    private_data: dict = None,
    category: str = None,
    # v45.0: ER Trend для детекции зомби-каналов
    er_trend_data: dict = None
) -> tuple[float, dict]:
    """
    v41.0: Вычисляет мультипликатор доверия.
    Включает Forensics + Statistical Trust + Ghost Protocol + Decay Analysis.

    Trust Factor - это число от 0.0 до 1.0, которое УМНОЖАЕТСЯ на Raw Score.
    Различные сигналы недоверия снижают множитель.

    v41.0: ad_load_data УДАЛЁН — теперь LLM ad_percentage в llm_trust_factor.

    Args:
        forensics_result: Результат UserForensics.analyze()
        comments_enabled: Включены ли комментарии
        conviction_score: Effective conviction score
        is_verified: Верифицирован ли канал Telegram
        reach: Reach % (avg_views / members * 100)
        forward_rate: Forward rate % (avg_forwards / avg_views * 100)
        reaction_rate: Reaction rate % (avg_reactions / avg_views * 100)
        source_share: Max share % от одного источника репостов
        members: Количество подписчиков канала
        online_count: Количество юзеров онлайн (из GetFullChannel)
        participants_count: Точный count подписчиков (из GetFullChannel)
        decay_ratio: avg_views_new / avg_views_old (v15.1)

    Returns:
        (trust_factor, details) где:
        - trust_factor: float 0.0-1.0
        - details: dict с причинами снижения доверия
    """
    multipliers = []
    details = {}

    # 1. ID Clustering (из forensics) - КРИТИЧНО
    if forensics_result and forensics_result.status == 'complete':
        clustering = forensics_result.id_clustering
        neighbor_ratio = clustering.get('neighbor_ratio', 0)

        if clustering.get('fatality'):
            # FATALITY обрабатывается раньше, но на всякий случай
            multipliers.append(TRUST_FACTORS['id_clustering_fatality'])
            details['id_clustering'] = {
                'multiplier': 0.0,
                'reason': 'FATALITY - ферма ботов',
                'neighbor_ratio': neighbor_ratio
            }
        elif clustering.get('suspicious') or neighbor_ratio > 0.15:
            multipliers.append(TRUST_FACTORS['id_clustering_suspicious'])
            details['id_clustering'] = {
                'multiplier': 0.5,
                'reason': f'Подозрительная кластеризация ({neighbor_ratio:.0%})',
                'neighbor_ratio': neighbor_ratio
            }

    # 2. Geo/DC Check (из forensics)
    if forensics_result and forensics_result.status == 'complete':
        geo = forensics_result.geo_dc_check
        if geo.get('triggered'):
            multipliers.append(TRUST_FACTORS['geo_dc_mismatch'])
            details['geo_dc'] = {
                'multiplier': 0.2,
                'reason': f"{geo.get('foreign_ratio', 0):.0%} на чужих DC",
                'foreign_ratio': geo.get('foreign_ratio', 0)
            }

    # 3. Premium Density (из forensics) - 0% премиумов подозрительно
    if forensics_result and forensics_result.status == 'complete':
        premium = forensics_result.premium_density
        premium_ratio = premium.get('premium_ratio', 0)
        total_users = premium.get('total_users', 0)

        if premium_ratio == 0 and total_users >= 10:
            multipliers.append(TRUST_FACTORS['premium_zero'])
            details['premium'] = {
                'multiplier': 0.8,
                'reason': '0% премиумов при достаточной выборке'
            }

    # 4. Ad Load - v41.0: REMOVED
    # Теперь LLM ad_percentage влияет на llm_trust_factor в llm_analyzer.py
    # Больше не используем keyword-based ad_load здесь

    # 5. Hidden Comments - скрытые комментарии
    # v38.4: Штраф для ВСЕХ каналов (верификация не коррелирует с качеством)
    if not comments_enabled:
        # Смягчённый штраф ×0.85 вместо ×0.7
        multipliers.append(0.85)
        details['hidden_comments'] = {
            'multiplier': 0.85,
            'reason': 'Комментарии скрыты'
        }

    # 6. Conviction Score - накопленные подозрения
    if conviction_score >= 70:
        multipliers.append(TRUST_FACTORS['conviction_critical'])
        details['conviction'] = {
            'multiplier': 0.3,
            'reason': f'Conviction {conviction_score} (критично)'
        }
    elif conviction_score >= 50:
        multipliers.append(TRUST_FACTORS['conviction_high'])
        details['conviction'] = {
            'multiplier': 0.6,
            'reason': f'Conviction {conviction_score} (высокий)'
        }

    # =========================================================================
    # v13.5: STATISTICAL TRUST PENALTIES
    # Детекция накрутки по математическим аномалиям
    # =========================================================================

    # 7. HOLLOW VIEWS - V47.4 "No-Mercy Edition"
    # Reach > 300% = Презумпция Виновности
    # Алиби 1: forward_rate > 3.0% (виральность через репосты)
    # Алиби 2: avg_comments > порог AND comment_trust >= 70 (живая дискуссия)
    # Реакции НЕ спасают (накручиваются за 5 секунд)
    HOLLOW_THRESHOLD = 300  # Унифицированный порог для всех размеров

    if reach > HOLLOW_THRESHOLD:
        # Алиби 1: Виральность через репосты
        has_virality_alibi = forward_rate > 3.0

        # Алиби 2: Живая дискуссия (адаптивный порог по размеру)
        if members < SIZE_THRESHOLDS['micro']:  # < 200
            comments_threshold = 0.5
        elif members < SIZE_THRESHOLDS['small']:  # < 1000
            comments_threshold = 1.0
        elif members < SIZE_THRESHOLDS['medium']:  # < 5000
            comments_threshold = 2.0
        else:
            comments_threshold = 5.0
        has_comments_alibi = avg_comments > comments_threshold and comment_trust >= 70

        if not has_virality_alibi and not has_comments_alibi:
            multipliers.append(0.6)
            details['hollow_views'] = {
                'multiplier': 0.6,
                'reason': f'Reach {reach:.0f}% > 300% без алиби (forward {forward_rate:.1f}%, comments {avg_comments:.1f}, trust {comment_trust})'
            }

    # 8. ZOMBIE ENGAGEMENT - Высокий охват, никто не реагирует
    # Reach >50% + Reaction <0.1% = боты смотрят, но не ставят реакции
    if reach > 50 and reaction_rate < 0.1:
        multipliers.append(0.7)
        details['zombie_engagement'] = {
            'multiplier': 0.7,
            'reason': f'Reach {reach:.0f}% но Reactions {reaction_rate:.2f}%'
        }

    # 9. SATELLITE - Канал-сателлит (>50% постов из одного источника)
    # v15.2: НЕ штрафовать если комменты живые (avg >= 1)
    # Если аудитория активно комментирует репосты — она живая, реклама будет работать
    if source_share > 50:
        if avg_comments < 1:
            # Мёртвые комменты + много репостов = сателлит
            multipliers.append(0.8)
            details['satellite'] = {
                'multiplier': 0.8,
                'reason': f'Source share {source_share:.0f}%, мёртвые комменты (avg {avg_comments:.1f})'
            }
        # Если комменты живые — НЕ штрафуем за репосты

    # =========================================================================
    # v15.0: GHOST PROTOCOL
    # Детекция мёртвой/накрученной аудитории по online_count
    # =========================================================================

    # Вычисляем online ratio (% юзеров онлайн от общего числа подписчиков)
    online_ratio = (online_count / members * 100) if members > 0 else 0

    # 10. GHOST CHANNEL - Мёртвая аудитория (крупный канал с 0 онлайн)
    # 20k+ подписчиков, но онлайн <0.1% = накрученные боты
    if members > 20000 and online_count > 0 and online_ratio < 0.1:
        multipliers.append(0.5)
        details['ghost_channel'] = {
            'multiplier': 0.5,
            'reason': f'{members:,} subs, {online_count} online ({online_ratio:.2f}%)'
        }

    # 11. ZOMBIE AUDIENCE - Подозрительно мало онлайн (средний канал)
    # 5k+ подписчиков, но онлайн <0.3% = подозрительно
    elif members > 5000 and online_count > 0 and online_ratio < 0.3:
        multipliers.append(0.7)
        details['zombie_audience'] = {
            'multiplier': 0.7,
            'reason': f'Low online: {online_count} ({online_ratio:.2f}%)'
        }

    # 12. MEMBER DISCREPANCY - Telegram знает о накрутке
    # Если participants_count (из GetFullChannel) сильно отличается от members
    if participants_count > 0 and members > 0:
        discrepancy = abs(participants_count - members)
        discrepancy_ratio = (discrepancy / members) * 100
        if discrepancy_ratio > 10:
            multipliers.append(0.8)
            details['member_discrepancy'] = {
                'multiplier': 0.8,
                'reason': f'Count mismatch: {members:,} vs {participants_count:,} ({discrepancy_ratio:.0f}%)'
            }

    # =========================================================================
    # v15.1: DECAY TRUST PENALTIES
    # Детекция накрутки по паттернам просмотров старых/новых постов
    # =========================================================================

    # v51.3: BOT WALL УДАЛЁН - слишком много false positives
    # Идея: ratio 0.98-1.02 = "подозрительно ровные просмотры"
    # Проблема: в реальности ratio ~1.0 бывает случайно, не означает накрутку
    # Решение: убрали полностью, оставили только BUDGET_CLIFF

    # 14. BUDGET CLIFF - Деньги на накрутку кончились
    # ratio < 0.2 означает, что новые посты = 20% от старых
    # Админ перестал платить за накрутку, органики нет
    if decay_ratio < 0.2 and decay_ratio > 0:
        multipliers.append(0.7)
        details['budget_cliff'] = {
            'multiplier': 0.7,
            'reason': f'Обрыв: новые = {decay_ratio*100:.0f}% от старых'
        }

    # =========================================================================
    # v15.0: SPAM POSTING PENALTY
    # Штраф за слишком частый постинг (реклама теряется в потоке)
    # =========================================================================

    if posting_data and posting_data.get('trust_multiplier', 1.0) < 1.0:
        posting_mult = posting_data['trust_multiplier']
        posts_per_day = posting_data.get('posts_per_day', 0)
        posting_status = posting_data.get('posting_status', 'normal')

        multipliers.append(posting_mult)
        details['spam_posting'] = {
            'multiplier': posting_mult,
            'reason': f'{posts_per_day:.1f} постов/день ({posting_status})',
            'posts_per_day': posts_per_day,
            'status': posting_status
        }

    # =========================================================================
    # v15.0: SCAM NETWORK PENALTY (накопительный)
    # Штраф за рекламу SCAM/BAD каналов
    # =========================================================================

    if network_data and network_data.get('trust_multiplier', 1.0) < 1.0:
        network_mult = network_data['trust_multiplier']
        scam_count = network_data.get('scam_count', 0)
        bad_count = network_data.get('bad_count', 0)

        multipliers.append(network_mult)

        # Формируем описание
        parts = []
        if scam_count:
            parts.append(f'{scam_count} SCAM')
        if bad_count:
            parts.append(f'{bad_count} BAD')

        details['scam_network'] = {
            'multiplier': network_mult,
            'reason': f"Рекламирует: {' + '.join(parts)}" if parts else 'Плохие связи',
            'scam_count': scam_count,
            'bad_count': bad_count,
            'scam_channels': network_data.get('scam_channels', [])
        }

    # =========================================================================
    # v15.0: PRIVATE LINKS PENALTY (по процентам)
    # Штраф за много приватных ссылок (нельзя проверить качество)
    # =========================================================================

    if private_data and private_data.get('trust_multiplier', 1.0) < 1.0:
        private_mult = private_data['trust_multiplier']
        private_ratio = private_data.get('private_ratio', 0)

        multipliers.append(private_mult)
        details['private_links'] = {
            'multiplier': private_mult,
            'reason': f'{private_ratio*100:.0f}% рекламы — приватные каналы',
            'private_ratio': private_ratio,
            'private_posts': private_data.get('private_posts', 0),
            'total_ad_posts': private_data.get('total_ad_posts', 0)
        }

    # =========================================================================
    # v45.0: ER TREND PENALTY (Dying Engagement)
    # Детекция "зомби-каналов" где вовлечённость падает, а просмотры держатся
    # =========================================================================

    if er_trend_data and er_trend_data.get('status') == 'dying':
        er_trend = er_trend_data.get('er_trend', 1.0)

        # Комбо-детекция: dying ER + стабильные views = "зомби-канал"
        # decay_ratio близок к 1.0 значит просмотры не падают
        is_zombie_combo = (0.7 <= decay_ratio <= 1.3)

        if is_zombie_combo:
            # Жёсткий штраф: ER падает, views держатся = накрутка views
            multipliers.append(0.6)
            details['dying_engagement'] = {
                'multiplier': 0.6,
                'reason': f'ER упал на {(1-er_trend)*100:.0f}%, views стабильны (зомби-канал)',
                'er_trend': er_trend,
                'decay_ratio': decay_ratio,
                'combo': True
            }
        else:
            # Мягкий штраф: просто падение ER без комбо
            multipliers.append(0.75)
            details['dying_engagement'] = {
                'multiplier': 0.75,
                'reason': f'ER упал на {(1-er_trend)*100:.0f}% (умирающий канал)',
                'er_trend': er_trend,
                'combo': False
            }

    # v68.1: Перемножаем все штрафы (не min!)
    # 0.66 × 0.80 = 0.53 — правильное поведение
    trust_factor = 1.0
    for mult in multipliers:
        trust_factor *= mult
    trust_factor = max(0.1, trust_factor)  # Floor 0.1

    return trust_factor, details


# ============================================================================
# ФИНАЛЬНЫЙ СКОРИНГ
# ============================================================================

def verified_to_points(is_verified: bool, max_pts: int = None) -> int:
    """v38.4: Верификация НЕ дает баллов (не коррелирует с качеством)."""
    return 0  # Верифицированные каналы тоже накручивают


def premium_to_points(premium_ratio: float, premium_count: int, max_pts: int = None) -> int:
    """
    v13.0: Premium Density -> баллы (default max 5).
    Качество аудитории по премиум-статусам.
    """
    if max_pts is None:
        max_pts = RAW_WEIGHTS['reputation']['premium']  # 5

    if premium_count == 0:
        return 0  # Нет премиумов = подозрительно
    if premium_ratio > 0.05:
        return max_pts  # >5% премиумов = отлично
    if premium_ratio > 0.02:
        return int(max_pts * 0.6)  # 3
    if premium_ratio > 0.01:
        return int(max_pts * 0.4)  # 2
    return 1  # Есть хоть какие-то премиумы


def check_f16_reaction_flatness(messages: list) -> dict:
    """
    F16: Reaction Flatness - детектор накрутки для каналов без комментов.
    Если CV реакций между постами < 10% — это боты.
    """
    totals = []
    for msg in messages[:5]:
        if hasattr(msg, 'reactions') and msg.reactions:
            reactions_list = getattr(msg.reactions, 'reactions', [])
            if reactions_list:
                total = sum(getattr(r, 'count', 0) for r in reactions_list)
                totals.append(total)

    if len(totals) < 3 or sum(totals) == 0:
        return {
            'triggered': False,
            'penalty': 0,
            'cv': 0,
            'totals': totals,
            'description': 'Недостаточно данных'
        }

    mean = sum(totals) / len(totals)
    if mean == 0:
        return {
            'triggered': False,
            'penalty': 0,
            'cv': 0,
            'totals': totals,
            'description': 'Нет реакций'
        }

    cv = calculate_cv(totals, as_percent=True, sample=False)

    # CV < 10% = подозрительно ровно
    if cv < 10:
        return {
            'triggered': True,
            'penalty': -5,  # v12.0: мягкий штраф вместо -20
            'cv': round(cv, 1),
            'totals': totals,
            'description': f'CV реакций {cv:.1f}% < 10% (подозрительно ровно)'
        }

    return {
        'triggered': False,
        'penalty': 0,
        'cv': round(cv, 1),
        'totals': totals,
        'description': f'CV реакций {cv:.1f}% (норма)'
    }


def comments_to_points(comments_data: dict, members: int = 0, max_pts: int = 10) -> tuple[int, str]:
    """
    v12.0: Комментарии -> баллы (max 10, или до 20 floating при закрытых комментах).
    """
    if not comments_data.get('enabled', False):
        return 0, "disabled"

    avg = comments_data.get('avg_comments', 0)

    # Размерные пороги
    # v23.0: использует SIZE_THRESHOLDS из config.py
    if members < SIZE_THRESHOLDS['micro']:
        if avg < 0.01:
            pts = 0
        elif avg < 0.05:
            pts = int(max_pts * 0.3)  # 3
        elif avg < 0.2:
            pts = int(max_pts * 0.6)  # 6
        elif avg < 0.5:
            pts = int(max_pts * 0.8)  # 8
        else:
            pts = max_pts  # 10
    elif members < SIZE_THRESHOLDS['small']:
        if avg < 0.1:
            pts = 0
        elif avg < 0.3:
            pts = int(max_pts * 0.2)  # 2
        elif avg < 1:
            pts = int(max_pts * 0.5)  # 5
        elif avg < 3:
            pts = int(max_pts * 0.8)  # 8
        else:
            pts = max_pts  # 10
    else:
        if avg < 0.3:
            pts = 0
        elif avg < 0.5:
            pts = int(max_pts * 0.2)  # 2
        elif avg < 2:
            pts = int(max_pts * 0.5)  # 5
        elif avg < 5:
            pts = int(max_pts * 0.8)  # 8
        else:
            pts = max_pts  # 10

    status = f"enabled (avg {avg:.1f})"
    return pts, status


def calculate_final_score(
    chat: Any,
    messages: list,
    comments_data: dict = None,
    users: list = None,
    channel_health: dict = None,  # v15.0: Ghost Protocol данные
    llm_result=None  # v37.2: LLM Analysis Result с tier_cap
) -> dict:
    """
    v37.2: Trust Multiplier System + Ghost Protocol + Tier Cap.

    Формула: Final Score = min(Raw Score × Trust Factor × LLM Trust, Tier Cap)

    v37.2 изменения:
    - Добавлен llm_result параметр для tier_cap
    - EXCLUDED tier → score=0, verdict=EXCLUDED
    - Tier caps: PREMIUM=100, STANDARD=85, LIMITED=70, RESTRICTED=50

    RAW SCORE (0-100) - "витрина":
    - КАЧЕСТВО: 40 баллов (cv_views 15, reach 10, decay 8, forward_rate 7)
    - ENGAGEMENT: 40 баллов (comments 15, reactions 15, er_variation 5, stability 5)
    - РЕПУТАЦИЯ: 20 баллов (verified 5, age 5, premium 5, source 5)

    TRUST FACTOR (0.0-1.0) - мультипликатор доверия:
    - ID Clustering FATALITY → ×0.0
    - ID Clustering Suspicious → ×0.5
    - Geo/DC Mismatch → ×0.2
    - Ad Load >50% → ×0.4
    - Ghost Channel (v15.0) → ×0.5
    - Zombie Audience (v15.0) → ×0.7
    - Hidden Comments → ×0.7
    - Premium 0% → ×0.8
    - Conviction ≥70 → ×0.3

    Args:
        chat: Объект чата/канала
        messages: Список сообщений
        comments_data: Данные о комментариях
        users: Список юзеров для Forensics анализа
    """
    # Дефолтные данные
    if comments_data is None:
        comments_data = {
            'enabled': getattr(chat, 'linked_chat', None) is not None,
            'avg_comments': 0.0,
            'total_comments': 0
        }
    if users is None:
        users = []

    # Определяем режим скоринга
    MIN_USERS_FOR_FORENSICS = 10
    forensics_available = len(users) >= MIN_USERS_FOR_FORENSICS
    adaptive_weights = calculate_adaptive_weights(forensics_available, len(users))
    scoring_mode = adaptive_weights['mode']

    # ===== SCAM CHECK =====
    # v47.4: Передаём comment_trust для алиби в impossible_reach
    comment_trust = llm_result.comments.trust_score if llm_result and llm_result.comments else 0
    is_scam, scam_reason, conviction_details, is_insufficient_data = check_instant_scam(chat, messages, comments_data, comment_trust)

    # v37.2: Новые/маленькие каналы получают NEW_CHANNEL вместо SCAM
    if is_insufficient_data:
        return {
            'channel': getattr(chat, 'username', None) or str(getattr(chat, 'id', 'unknown')),
            'members': getattr(chat, 'members_count', 0),
            'score': 0,
            'verdict': 'NEW_CHANNEL',
            'reason': 'Недостаточно данных для оценки (менее 10 постов или 100 подписчиков)',
            'conviction': {},
            'breakdown': {},
            'categories': {},
            'flags': {
                'is_scam': False,
                'is_fake': False,
                'is_verified': getattr(chat, 'is_verified', False),
                'comments_enabled': comments_data.get('enabled', False),
                'is_new_channel': True
            },
            'raw_stats': get_raw_stats(messages)
        }

    # v52.0: НЕ возвращаем сразу при SCAM! Устанавливаем флаг и продолжаем расчёт
    # Это позволяет сохранить реальные баллы для анализа
    scam_flag = is_scam
    scam_reason_text = scam_reason if is_scam else None

    # Базовые данные
    views = [m.views for m in messages if hasattr(m, 'views') and m.views]
    members = getattr(chat, 'members_count', 0) or 1
    avg_views = sum(views) / len(views) if views else 0
    channel_username = getattr(chat, 'username', None)
    comments_enabled = comments_data.get('enabled', False)
    is_verified = getattr(chat, 'is_verified', False)

    # v22.4: Определяем включены ли реакции
    # ВАЖНО: Если реакций 0, но атрибут reactions есть - реакции ВКЛЮЧЕНЫ
    # Раньше была ошибка: total_reactions > 0 возвращал False если никто не реагировал
    reactions_enabled = check_reactions_enabled(messages)

    # Floating weights для комментариев И реакций (v15.2)
    weights = calculate_floating_weights(comments_enabled, reactions_enabled)

    # ===== USER FORENSICS =====
    forensics_result = None
    if users:
        forensics = UserForensics(users)
        forensics_result = forensics.analyze()

        # v52.0: FATALITY - НЕ возвращаем сразу! Устанавливаем флаг и продолжаем расчёт
        if forensics_result.id_clustering.get('fatality', False):
            scam_flag = True
            scam_reason_text = 'ID Clustering FATALITY - обнаружена ферма ботов'

    breakdown = {}
    categories = {}

    # =========================================================================
    # КАТЕГОРИЯ 1: КАЧЕСТВО КОНТЕНТА (42 балла) — v48.0
    # =========================================================================
    quality_score = 0

    # Вычисляем forward_rate заранее для Viral Exception
    forward_rate = calculate_forwards_ratio(messages)

    # 1.1 CV Views (max 12)
    cv = calculate_cv_views(views)
    cv_pts = cv_to_points(cv, forward_rate)
    quality_score += cv_pts
    breakdown['cv_views'] = {
        'value': round(cv, 2),
        'points': cv_pts,
        'max': WEIGHTS['quality']['cv_views'],
        'viral_exception': cv >= 100 and forward_rate > 3.0
    }

    # 1.2 Reach (max 8)
    reach = calculate_reach(avg_views, members)
    reach_pts = reach_to_points(reach, members)
    quality_score += reach_pts
    breakdown['reach'] = {
        'value': round(reach, 2),
        'points': reach_pts,
        'max': WEIGHTS['quality']['reach']
    }

    # 1.3 Regularity (max 7) — v48.0: NEW! Стабильность постинга
    # Используем is_news=False, реальное значение определится позже
    posting_data = calculate_posts_per_day(messages, is_news=False)
    regularity_pts = regularity_to_points(posting_data['posts_per_day'])
    quality_score += regularity_pts
    breakdown['regularity'] = {
        'value': round(posting_data['posts_per_day'], 2),
        'points': regularity_pts,
        'max': WEIGHTS['quality']['regularity'],
        'status': posting_data['posting_status']
    }

    # 1.4 Views Decay — v48.0: INFO ONLY (для Trust Factor bot_wall)
    # НЕ добавляем в quality_score! Остаётся для детекции ботов.
    reaction_rate = calculate_reaction_rate(messages)
    decay_ratio = calculate_views_decay(messages)
    decay_pts, decay_info = decay_to_points(decay_ratio, reaction_rate)
    # quality_score += decay_pts  # v48.0: УБРАНО из баллов
    breakdown['views_decay'] = {
        'value': round(decay_ratio, 2),
        'points': 0,              # v48.0: info only
        'max': 0,                 # v48.0: info only
        'zone': decay_info['zone'],
        'description': decay_info['description'],
        'status': 'info_only'     # v48.0: маркер для UI
    }

    # 1.5 Forward Rate (max 15, или до 38 floating)
    forward_max = weights['forward_rate_max']
    forward_pts = forward_rate_to_points(forward_rate, members, forward_max)
    quality_score += forward_pts
    breakdown['forward_rate'] = {
        'value': round(forward_rate, 3),
        'points': forward_pts,
        'max': forward_max,
        'floating_boost': forward_max > WEIGHTS['quality']['forward_rate']
    }

    categories['quality'] = {
        'score': quality_score,
        'max': CATEGORY_TOTALS['quality'] + (forward_max - WEIGHTS['quality']['forward_rate'])
    }

    # =========================================================================
    # КАТЕГОРИЯ 2: ENGAGEMENT (38 баллов) — v48.0
    # =========================================================================
    engagement_score = 0

    # 2.1 Comments (max 15, или до 20 floating)
    comments_max = weights['comments_max']
    if comments_max > 0:
        comments_pts, comments_status = comments_to_points(comments_data, members, comments_max)
    else:
        comments_pts = 0
        comments_status = "disabled (floating)"
    engagement_score += comments_pts
    breakdown['comments'] = {
        'value': comments_status,
        'points': comments_pts,
        'max': comments_max,
        'avg': round(comments_data.get('avg_comments', 0), 1),
        'floating_weights': not comments_enabled
    }

    # 2.2 ER Trend (max 10) — v48.0: NEW! Канал растёт или умирает?
    er_trend_data = calculate_er_trend(messages)
    er_trend_pts = er_trend_to_points(er_trend_data)
    engagement_score += er_trend_pts
    breakdown['er_trend'] = {
        **er_trend_data,        # er_new, er_old, er_trend, status, posts_new, posts_old
        'points': er_trend_pts,
        'max': WEIGHTS['engagement']['er_trend']
    }

    # 2.3 Reaction Rate (max 8, или до 13 floating)
    reaction_max = weights['reaction_rate_max']
    reaction_pts = reaction_rate_to_points(reaction_rate, members, reaction_max)
    engagement_score += reaction_pts
    breakdown['reaction_rate'] = {
        'value': round(reaction_rate, 3),
        'points': reaction_pts,
        'max': reaction_max,
        'floating_boost': reaction_max > WEIGHTS['engagement']['reaction_rate']
    }

    # 2.4 Reaction Stability (max 5) — v52.2: двухфакторная логика
    stability = calculate_reaction_stability(messages)
    stability_pts = stability_to_points(stability)
    engagement_score += stability_pts
    breakdown['reaction_stability'] = {
        'value': round(stability.get('stability_cv', 50.0), 1),
        'top_concentration': round(stability.get('top_concentration', 0.2), 3),
        'points': stability_pts,
        'max': WEIGHTS['engagement']['stability'],
        'posts_with_reactions': stability.get('posts_with_reactions', 0),
        'mean_reactions': stability.get('mean_reactions', 0),
        'max_reactions': stability.get('max_reactions', 0)
    }

    # v48.0: er_variation УДАЛЁН (заменён на er_trend)

    categories['engagement'] = {
        'score': engagement_score,
        'max': CATEGORY_TOTALS['engagement'] + (comments_max - WEIGHTS['engagement']['comments']) + (reaction_max - WEIGHTS['engagement']['reaction_rate'])
    }

    # =========================================================================
    # КАТЕГОРИЯ 3: РЕПУТАЦИЯ (20 баллов)
    # =========================================================================
    reputation_score = 0

    # 3.1 Verified (max 5)
    verified_pts = verified_to_points(is_verified)
    reputation_score += verified_pts
    breakdown['verified'] = {
        'value': is_verified,
        'points': verified_pts,
        'max': WEIGHTS['reputation']['verified']
    }

    # 3.2 Channel Age (max 5)
    age_days = get_channel_age_days(chat)
    age_pts = age_to_points(age_days)
    reputation_score += age_pts

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
    breakdown['age'] = {
        'value': age_days,
        'points': age_pts,
        'max': WEIGHTS['reputation']['age'],
        'status': age_status
    }

    # 3.3 Premium Density (max 5) - из Forensics
    premium_pts = 0
    premium_ratio = 0  # v65.1: Инициализация до if-блока (fix UnboundLocalError)
    premium_count = 0  # v65.1: Инициализация до if-блока
    if forensics_result and forensics_result.status == 'complete':
        premium_ratio = forensics_result.premium_density.get('premium_ratio', 0)
        premium_count = forensics_result.premium_density.get('premium_count', 0)
        premium_pts = premium_to_points(premium_ratio, premium_count)
    reputation_score += premium_pts
    breakdown['premium'] = {
        'value': round(forensics_result.premium_density.get('premium_ratio', 0) * 100, 1) if forensics_result else 0,
        'ratio': premium_ratio if forensics_result else 0,  # v65.0: для recalculator
        'count': premium_count if forensics_result else 0,  # v65.0: для recalculator
        'points': premium_pts,
        'max': WEIGHTS['reputation']['premium'],
        'status': 'available' if forensics_result else 'no_data'
    }

    # 3.4 Source Diversity (max 5)
    source_max_share = calculate_source_diversity(messages)
    forwards = sum(1 for m in messages if getattr(m, 'forward_from_chat', None))
    repost_ratio = forwards / len(messages) if messages else 0
    source_pts = source_to_points(source_max_share, repost_ratio)
    reputation_score += source_pts
    breakdown['source_diversity'] = {
        'value': round(1 - source_max_share, 2),
        'points': source_pts,
        'max': WEIGHTS['reputation']['source'],
        'repost_ratio': round(repost_ratio, 2)
    }

    categories['reputation'] = {
        'score': reputation_score,
        'max': CATEGORY_TOTALS['reputation']
    }

    # =========================================================================
    # v13.0: RAW SCORE (0-100) - "витрина"
    # =========================================================================
    raw_score = quality_score + engagement_score + reputation_score
    raw_score = min(100, max(0, raw_score))  # Cap at 0-100

    # Дополнительные данные для Trust Factor
    regularity_cv = calculate_post_regularity(messages)

    # =========================================================================
    # v13.5: TRUST FACTOR (0.0-1.0) - мультипликатор доверия
    # Включает Forensics + Statistical Trust Penalties
    # =========================================================================
    effective_conviction = conviction_details.get('effective_conviction', 0)

    # v13.5: Подготовка метрик для Statistical Trust
    # source_share уже вычислен выше как source_max_share (0.0-1.0)
    # Конвертируем в проценты для consistency
    source_share_percent = source_max_share * 100

    # v15.0: Извлекаем Ghost Protocol данные
    if channel_health is None:
        channel_health = {}
    online_count = channel_health.get('online_count', 0)
    participants_count = channel_health.get('participants_count', 0)

    # =========================================================================
    # v15.0: NEW METRICS - Spam Posting + Private Links
    # =========================================================================

    # Определяем категорию канала (если есть)
    channel_category = getattr(chat, 'category', None)

    # Posting frequency: NEWS каналы имеют выше пороги
    is_news = channel_category == 'NEWS' if channel_category else False
    posting_data = calculate_posts_per_day(messages, is_news=is_news)

    # Private links: анализируем % приватных ссылок в рекламе
    private_data = analyze_private_invites(
        messages,
        category=channel_category,
        comments_enabled=comments_enabled
    )

    # Scam network: требует БД, передаём None (будет вычислен в cli.py если нужно)
    network_data = None

    # Сохраняем данные в breakdown для отображения
    breakdown['posting_frequency'] = {
        'posts_per_day': posting_data['posts_per_day'],
        'status': posting_data['posting_status'],
        'trust_multiplier': posting_data['trust_multiplier']
    }
    breakdown['private_links'] = {
        'private_ratio': private_data.get('private_ratio', 0),
        'private_posts': private_data.get('private_posts', 0),
        'total_ad_posts': private_data.get('total_ad_posts', 0),
        'trust_multiplier': private_data.get('trust_multiplier', 1.0)
    }

    trust_factor, trust_details = calculate_trust_factor(
        forensics_result=forensics_result,
        comments_enabled=comments_enabled,
        conviction_score=effective_conviction,
        is_verified=is_verified,
        # v13.5: Statistical Trust Parameters
        reach=reach,
        forward_rate=forward_rate,
        reaction_rate=reaction_rate,
        source_share=source_share_percent,
        # v15.0: Ghost Protocol Parameters
        members=members,
        online_count=online_count,
        participants_count=participants_count,
        # v15.1: Decay Trust Parameters
        decay_ratio=decay_ratio,
        # v51.2: CV views для проверки bot_wall false positives
        cv_views=cv,
        # v15.2: Satellite Parameters
        avg_comments=comments_data.get('avg_comments', 0),
        # v47.4: Comment Trust из LLM анализа (переменная вычислена выше)
        comment_trust=comment_trust,
        # v15.0: New Penalties
        posting_data=posting_data,
        network_data=network_data,
        private_data=private_data,
        category=channel_category,
        # v45.0: ER Trend для детекции зомби-каналов
        er_trend_data=er_trend_data
    )

    # F16: Reaction Flatness в Hardcore mode (дополнительный сигнал для Trust)
    if adaptive_weights['flatness_enabled']:
        flatness_result = check_f16_reaction_flatness(messages)
        breakdown['reaction_flatness'] = flatness_result
        if flatness_result['triggered']:
            # Flatness = ×0.8 (мягче чем hidden_comments)
            if trust_factor > 0.8:
                trust_factor = 0.8
            trust_details['reaction_flatness'] = {
                'multiplier': 0.8,
                'reason': f"CV реакций {flatness_result['cv']:.1f}% (подозрительно ровно)"
            }

    # =========================================================================
    # v37.2: FINAL SCORE = min(RAW × TRUST × LLM_TRUST, TIER_CAP)
    # =========================================================================

    # v37.2: Трёхэтапная система с tier_cap
    tier = None
    tier_cap = 100
    llm_trust_factor = 1.0
    exclusion_reason = None

    if llm_result:
        # Получаем данные из LLM анализа
        tier = getattr(llm_result, 'tier', None)
        tier_cap = getattr(llm_result, 'tier_cap', 100)
        llm_trust_factor = getattr(llm_result, 'llm_trust_factor', 1.0)
        exclusion_reason = getattr(llm_result, 'exclusion_reason', None)

        # ЭТАП 1: Проверка на EXCLUDED
        if tier == "EXCLUDED":
            final_score = 0
            verdict = 'EXCLUDED'
            # Возвращаем ранний результат для EXCLUDED
            forensics_breakdown = None
            if forensics_result:
                forensics_breakdown = {
                    'users_analyzed': forensics_result.users_analyzed,
                    'status': forensics_result.status,
                    'id_clustering': forensics_result.id_clustering,
                    'geo_dc_check': forensics_result.geo_dc_check,
                    'premium_density': forensics_result.premium_density,
                    'hidden_flags': forensics_result.hidden_flags
                }
            return {
                'channel': channel_username or str(getattr(chat, 'id', 'unknown')),
                'members': members,
                'raw_score': raw_score,
                'trust_factor': round(trust_factor, 2),
                'trust_details': trust_details,
                'score': 0,
                'final_score': 0,
                'verdict': 'EXCLUDED',
                # v52.0: SCAM detection - сохраняем флаг даже для EXCLUDED
                'is_scam': scam_flag,
                'scam_reason': scam_reason_text,
                'exclusion_reason': exclusion_reason,
                'tier': 'EXCLUDED',
                'tier_cap': 0,
                'llm_trust_factor': llm_trust_factor,
                'scoring_mode': scoring_mode,
                'categories': categories,
                'breakdown': breakdown,
                'forensics': forensics_breakdown,
                'conviction': conviction_details,
                'flags': {
                    'is_scam': scam_flag,  # v52.0: использует наш флаг
                    'is_fake': getattr(chat, 'is_fake', False),
                    'is_verified': is_verified,
                    'comments_enabled': comments_enabled,
                    'reactions_enabled': reactions_enabled,
                    'floating_weights': not comments_enabled or not reactions_enabled,
                    'hardcore_mode': scoring_mode == 'hardcore'
                },
                'channel_health': channel_health,
                'raw_stats': get_raw_stats(messages)
            }

        # ЭТАП 2-3: Расчёт с tier_cap
        base_score = raw_score * trust_factor * llm_trust_factor
        final_score = int(min(base_score, tier_cap))
    else:
        # Старая формула без LLM
        final_score = int(raw_score * trust_factor)

    final_score = max(0, min(100, final_score))

    # v52.0: Вердикт с учётом scam_flag
    # Если scam_flag=True, вердикт ВСЕГДА SCAM, независимо от баллов
    if scam_flag:
        verdict = 'SCAM'
    elif final_score >= 75:
        verdict = 'EXCELLENT'
    elif final_score >= 55:
        verdict = 'GOOD'
    elif final_score >= 40:
        verdict = 'MEDIUM'
    elif final_score >= 25:
        verdict = 'HIGH_RISK'
    else:
        verdict = 'SCAM'

    # Forensics breakdown
    forensics_breakdown = None
    if forensics_result:
        forensics_breakdown = {
            'users_analyzed': forensics_result.users_analyzed,
            'status': forensics_result.status,
            'id_clustering': forensics_result.id_clustering,
            'geo_dc_check': forensics_result.geo_dc_check,
            'premium_density': forensics_result.premium_density,
            'hidden_flags': forensics_result.hidden_flags
        }

    # v68.1: Объединённый trust_factor = forensic × LLM
    combined_trust = max(0.1, trust_factor * llm_trust_factor)

    return {
        'channel': channel_username or str(getattr(chat, 'id', 'unknown')),
        'members': members,
        # v68.1: trust_factor теперь КОМБИНИРОВАННЫЙ (forensic × LLM)
        'raw_score': raw_score,
        'trust_factor': round(combined_trust, 2),  # v68.1: combined!
        'trust_details': trust_details,
        'score': final_score,
        'final_score': final_score,  # v37.2: алиас для совместимости
        'verdict': verdict,
        # v52.0: SCAM detection - сохраняем реальные баллы + флаг
        'is_scam': scam_flag,
        'scam_reason': scam_reason_text,
        # v37.2: Tier System
        'tier': tier,
        'tier_cap': tier_cap,
        'llm_trust_factor': round(llm_trust_factor, 2),  # v68.1: оставляем для совместимости
        'forensic_trust_factor': round(trust_factor, 2),  # v68.1: отдельно forensic
        'scoring_mode': scoring_mode,
        'categories': categories,
        'breakdown': breakdown,
        'forensics': forensics_breakdown,
        'conviction': conviction_details,
        'flags': {
            'is_scam': scam_flag,  # v52.0: использует наш флаг, не chat.is_scam
            'is_fake': getattr(chat, 'is_fake', False),
            'is_verified': is_verified,
            'comments_enabled': comments_enabled,
            'reactions_enabled': reactions_enabled,  # v15.2
            'floating_weights': not comments_enabled or not reactions_enabled,
            'hardcore_mode': scoring_mode == 'hardcore'
        },
        'channel_health': channel_health,  # v15.0: Ghost Protocol
        'raw_stats': get_raw_stats(messages)
    }
