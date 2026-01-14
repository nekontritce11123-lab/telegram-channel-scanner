"""
Модуль скоринга качества Telegram канала.
v5.0: Floating Weights, Ad Load, Forward Rate boost.
v5.1: Viral Exception - CV > 100% + Forward Rate > 3% = не штрафовать.
v7.0: User Forensics интеграция (ID Clustering, Username Entropy, Hidden Flags).
v7.1: Adaptive Paranoia Mode - если forensics недоступен, включается HARDCORE режим.
v11.0: Executioner System - штрафы вместо нулей за явные нарушения.
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
    calculate_ad_load,
    get_channel_age_days,
    get_raw_stats,
    check_f16_reaction_flatness,  # v7.1: Adaptive Paranoia Mode
)
from .forensics import UserForensics


# ============================================================================
# ФУНКЦИИ КОНВЕРТАЦИИ МЕТРИК В БАЛЛЫ
# ============================================================================

def cv_to_points(cv: float, forward_rate: float = 0, max_pts: int = 15) -> int:
    """
    CV Views -> баллы (max 15, или 25 в Hardcore mode).
    v5.0: Увеличено с 14 до 15.
    v5.1: Viral Exception - если CV > 100%, но forward_rate > 3%, не обнулять.
    v7.1: Динамический max_pts для Adaptive Paranoia Mode.
    v11.0: Executioner - штраф -20 за CV > 100% без виральности.

    CV > 100% = экстремальные скачки = накрутка волнами.
    НО: вирусный пост (100к просмотров при среднем 5к) тоже даёт высокий CV.
    Если контент репостят (forward_rate > 3%) - это "бриллиант", не скам.

    Args:
        cv: Coefficient of Variation просмотров (%)
        forward_rate: Forward Rate (%) для Viral Exception
        max_pts: Максимум баллов (15 в Normal, 25 в Hardcore mode)
    """
    # Пропорциональные пороги относительно max_pts
    if cv < 10:
        return 0   # Слишком ровно - бот
    if cv < 30:
        return int(max_pts * 0.67)  # ~10/15 или ~17/25
    if cv < 60:
        return max_pts  # Хорошо - естественная вариация
    if cv < 100:
        return int(max_pts * 0.53)  # ~8/15 - подозрительно высокая вариация

    # CV >= 100% - потенциальная волновая накрутка
    # v5.1: Viral Exception - если репостят, это вирусный контент, а не накрутка
    if forward_rate > 3.0:
        return int(max_pts * 0.53)   # Вирусный контент - спасаем "бриллиант"

    # v11.0: EXECUTIONER - штраф вместо нуля
    return -20     # CV > 100% без виральности = явный скам паттерн


def reach_to_points(reach: float, members: int = 0) -> int:
    """
    Reach % -> баллы (max 10). Учитывает размер канала.
    v5.0: Снижено с 12 до 10 для перераспределения в Forward Rate.
    v11.0: Executioner - штраф -20 за reach > 200% (физически невозможно).
    """
    # v11.0: EXECUTIONER - reach > 200% физически невозможен для любого канала
    if reach > 200:
        return -20  # Явная накрутка - штраф

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
        return 0  # Накрутка просмотров для данного размера (мягкий 0)

    # Высокий reach для малых каналов - это ХОРОШО (лояльная аудитория)
    if reach > high_is_good:
        return 4  # Высоковато, но в пределах нормы

    if reach < 5:
        return 0  # Мёртвая аудитория
    if reach < 10:
        return 3
    if reach < 20:
        return 6
    if reach < 50:
        return 8
    return 10  # 50%+ до high_is_good - отлично!


def reaction_rate_to_points(rate: float, members: int = 0, max_pts: int = 15) -> int:
    """
    Reaction rate % -> баллы (max 15, или 25 при floating weights).
    v5.0: Динамический max для floating weights.
    v11.0: Executioner - штраф -15 за накрутку реакций.

    Args:
        rate: Reaction rate в процентах
        members: Количество подписчиков
        max_pts: Максимум баллов (15 по умолчанию, 25 при floating weights)
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

    # v11.0: EXECUTIONER - штраф за явную накрутку реакций
    if rate > scam_threshold:
        return -15  # Накрутка реакций для данного размера

    # Пропорциональное распределение баллов относительно max_pts
    if rate > high_threshold:
        return int(max_pts * 0.33)  # Подозрительно много (но в пределах)
    if rate < 0.3:
        return int(max_pts * 0.2)   # Мёртвая аудитория
    if rate < 1:
        return int(max_pts * 0.53)  # ~8/15
    if rate < 3:
        return int(max_pts * 0.8)   # ~12/15
    return max_pts  # Отлично


def decay_to_points(ratio: float, reaction_rate: float = 0) -> int:
    """
    Views decay ratio -> баллы (max 8).
    v5.0: Поправка на Growth Trend - растущие каналы не штрафуются.

    Если ratio < 0.7 (новые посты лучше старых), но engagement высокий (>2%),
    это Growth Trend - канал растёт органически, а не накрутка.
    """
    if ratio < 0.7:
        # v5.0: Проверяем Growth Trend
        if reaction_rate > 2.0:
            return 4  # Growth Trend - канал растёт, не штрафуем сильно
        return 0  # Накрутка просмотров
    if ratio < 1.0:
        return 2
    if ratio < 1.5:
        return 5
    if ratio < 3.0:
        return 8
    return 4  # Слишком большая разница


def regularity_to_points(cv: float) -> int:
    """
    Post regularity CV -> баллы (max 2).
    v5.0: Снижено с 3 до 2. Профи используют отложенный постинг - это не боты.
    """
    if cv < 0.2:
        return 0  # Бот - слишком ровные интервалы
    if cv < 0.5:
        return 1
    return 2


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
    """
    Source diversity -> баллы (max 5). Учитывает долю репостов.
    v11.0: Executioner - штраф -20 за сателлит-канал.
    """
    # Если репостов мало (<10%) - не штрафовать за концентрацию источников
    if repost_ratio < 0.10:
        return 5  # Канал с оригинальным контентом

    # v11.0: EXECUTIONER - штраф за сателлит
    if max_share > 0.7:
        return -20  # Сателлит (>70% из одного источника) - это мусор
    if max_share > 0.5:
        return 2
    return 5


# round_to_points УДАЛЕНА в v3.0
# Причина: метрика не дискриминирует, баллы перенесены в cv_to_points


def forward_rate_to_points(rate: float, members: int = 0, max_pts: int = 15) -> int:
    """
    Forward Rate % -> баллы (max 15, или 20 при floating weights).
    v5.0: Виральность контента - репост = бесплатный охват для рекламодателя.
    Учитывает размер канала (большие каналы имеют ниже forward rate естественно).

    Args:
        rate: Forward rate в процентах
        members: Количество подписчиков (для размерных порогов)
        max_pts: Максимум баллов (15 по умолчанию, 20 при floating weights)
    """
    # Большие каналы имеют ниже forward rate из-за насыщения аудитории
    if members > 50000:
        thresholds = {'viral': 1.5, 'excellent': 0.7, 'good': 0.3, 'medium': 0.1}
    elif members > 5000:
        thresholds = {'viral': 2.0, 'excellent': 1.0, 'good': 0.5, 'medium': 0.2}
    else:
        thresholds = {'viral': 3.0, 'excellent': 1.5, 'good': 0.5, 'medium': 0.1}

    # Защита от накрутки пересылок
    if rate > 15:
        return 0  # Подозрительно много - возможна накрутка через сеть каналов

    # Пропорциональное распределение баллов относительно max_pts
    if rate >= thresholds['viral']:
        return max_pts  # Виральный контент
    if rate >= thresholds['excellent']:
        return int(max_pts * 0.8)  # Отлично расшаривают
    if rate >= thresholds['good']:
        return int(max_pts * 0.6)  # Хорошо
    if rate >= thresholds['medium']:
        return int(max_pts * 0.3)  # Средне
    if rate >= 0.05:
        return int(max_pts * 0.1)  # Минимум
    return 0  # Контент не расшаривают


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


def calculate_floating_weights(comments_enabled: bool) -> dict:
    """
    v5.0: Плавающие веса - если комменты закрыты, их баллы перераспределяются.

    Логика: "Рот закрыт, но люди голосуют лайками и репостами"
    - 15 баллов комментариев → 10 в Reactions, 5 в Forward Rate

    Returns:
        dict с max баллами для каждой метрики
    """
    if comments_enabled:
        return {
            'comments_max': 15,
            'reaction_rate_max': 15,
            'forward_rate_max': 15
        }
    else:
        # Комменты закрыты - перераспределяем их 15 баллов
        return {
            'comments_max': 0,
            'reaction_rate_max': 25,  # +10 от комментов
            'forward_rate_max': 20    # +5 от комментов
        }


def calculate_adaptive_weights(forensics_available: bool, users_count: int) -> dict:
    """
    v7.1: Adaptive Paranoia Mode - адаптивные веса в зависимости от доступности данных.

    Если forensics доступен (есть юзеры) - NORMAL MODE:
    - Стандартные веса v5.1
    - User Forensics активен

    Если forensics недоступен (нет юзеров) - HARDCORE MODE:
    - CV Views усилен до 25 pts (главный индикатор)
    - Forward Rate усилен до 20 pts (виральность критична)
    - Ad Load штраф усилен до -25
    - Штраф -15 за закрытость
    - F16 Reaction Flatness включён

    Философия: "Спрятал аудиторию — докажи что не скам безупречной математикой"
    """
    MIN_USERS_FOR_FORENSICS = 10

    if forensics_available and users_count >= MIN_USERS_FOR_FORENSICS:
        # NORMAL MODE: стандартные веса + User Forensics
        return {
            'mode': 'normal',
            'cv_views_max': 15,
            'comments_max': 15,
            'reaction_rate_max': 15,
            'forward_rate_max': 15,
            'ad_load_max': -15,
            'hidden_penalty': 0,
            'flatness_enabled': False
        }
    else:
        # HARDCORE MODE: forensics недоступен
        return {
            'mode': 'hardcore',
            'cv_views_max': 25,       # +10 (главный индикатор)
            'comments_max': 0,        # нет данных о юзерах
            'reaction_rate_max': 20,  # +5 (floating)
            'forward_rate_max': 20,   # +5 (виральность критична)
            'ad_load_max': -25,       # -10 (строже)
            'hidden_penalty': -15,    # ШТРАФ за закрытость
            'flatness_enabled': True  # включить F16
        }


def ad_load_to_penalty(ad_load_data: dict, max_penalty: int = -15) -> int:
    """
    v5.0: Штраф за заспамленность рекламой.
    v7.1: Динамический max_penalty для Adaptive Paranoia Mode.

    Логика: Канал-помойка из рекламы = слепая аудитория = плохая конверсия.

    Пороги (Normal mode, max_penalty=-15):
    - Ad Load < 10%: 0 штрафа (чистый канал)
    - Ad Load 10-30%: -5 баллов (умеренно)
    - Ad Load 30-50%: -10 баллов (много рекламы)
    - Ad Load > 50%: -15 баллов (спам-канал)

    В Hardcore mode (max_penalty=-25) штрафы пропорционально увеличены.

    Args:
        ad_load_data: Данные о рекламной нагрузке
        max_penalty: Максимальный штраф (-15 в Normal, -25 в Hardcore mode)
    """
    ad_percent = ad_load_data.get('ad_load_percent', 0)

    # Пропорциональные штрафы относительно max_penalty
    if ad_percent < 10:
        return 0   # Чистый канал
    if ad_percent < 30:
        return int(max_penalty * 0.33)  # ~-5/-15 или ~-8/-25
    if ad_percent < 50:
        return int(max_penalty * 0.67)  # ~-10/-15 или ~-17/-25
    return max_penalty  # Спам-канал


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


def calculate_final_score(
    chat: Any,
    messages: list,
    comments_data: dict = None,
    users: list = None
) -> dict:
    """
    Полный расчёт качества канала.
    v5.0: Floating Weights, Ad Load, Forward Rate boost, Growth Trend.
    v7.0: User Forensics - ID Clustering, Username Entropy, Hidden Flags.
    v7.1: Adaptive Paranoia Mode - HARDCORE режим если forensics недоступен.
    Возвращает score 0-100 и детальный breakdown.

    Args:
        chat: Объект чата/канала
        messages: Список сообщений
        comments_data: Данные о комментариях
        users: Список юзеров для Forensics анализа (v7.0)
    """
    # Дефолтные данные о комментариях если не переданы
    if comments_data is None:
        comments_data = {
            'enabled': getattr(chat, 'linked_chat', None) is not None,
            'avg_comments': 0.0,
            'total_comments': 0
        }

    # v7.0: Дефолтный пустой список юзеров
    if users is None:
        users = []

    # v7.1: Определяем режим скоринга (Normal vs Hardcore)
    MIN_USERS_FOR_FORENSICS = 10
    forensics_available = len(users) >= MIN_USERS_FOR_FORENSICS
    adaptive_weights = calculate_adaptive_weights(forensics_available, len(users))
    scoring_mode = adaptive_weights['mode']

    # ===== КАТЕГОРИЯ A: СИСТЕМА СОВОКУПНЫХ ФАКТОРОВ =====
    is_scam, scam_reason, conviction_details = check_instant_scam(chat, messages, comments_data)

    if is_scam:
        return {
            'channel': getattr(chat, 'username', None) or str(getattr(chat, 'id', 'unknown')),
            'members': getattr(chat, 'members_count', 0),
            'score': 0,
            'verdict': 'SCAM',
            'reason': scam_reason,
            'conviction': conviction_details,
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
    channel_username = getattr(chat, 'username', None)

    # ===== v5.0: FLOATING WEIGHTS =====
    comments_enabled = comments_data.get('enabled', False)
    weights = calculate_floating_weights(comments_enabled)

    # ===== КАТЕГОРИЯ B: ОСНОВНЫЕ МЕТРИКИ =====

    # v5.1: Вычисляем forward_rate заранее для Viral Exception в CV Views
    forward_rate = calculate_forwards_ratio(messages)

    # B1: CV Views (15 pts Normal, 25 pts Hardcore) - v7.1: adaptive weights
    cv = calculate_cv_views(views)
    cv_max = adaptive_weights['cv_views_max']
    cv_score = cv_to_points(cv, forward_rate, cv_max)  # v7.1: передаём max_pts
    score += cv_score
    viral_exception = cv >= 100 and forward_rate > 3.0
    breakdown['cv_views'] = {
        'value': round(cv, 2),
        'points': cv_score,
        'max': cv_max,
        'viral_exception': viral_exception,  # v5.1: показываем если сработало
        'hardcore_boost': cv_max > 15  # v7.1: показываем если усилено
    }

    # B2: Reach (10 pts) - v5.0: снижено с 12
    reach = calculate_reach(avg_views, members)
    reach_score = reach_to_points(reach, members)
    score += reach_score
    breakdown['reach'] = {'value': round(reach, 2), 'points': reach_score, 'max': 10}

    # B3: Comments (15 pts или 0 при floating) - v5.0: зависит от floating weights
    comments_max = weights['comments_max']
    if comments_max > 0:
        comments_pts, comments_status = comments_to_points(comments_data, members, reach)
        # Ограничиваем максимумом из floating weights
        comments_pts = min(comments_pts, comments_max)
    else:
        comments_pts = 0
        comments_status = "disabled (floating weights)"
    score += comments_pts
    breakdown['comments'] = {
        'value': comments_status,
        'points': comments_pts,
        'max': comments_max,
        'total': comments_data.get('total_comments', 0),
        'avg': round(comments_data.get('avg_comments', 0), 1),
        'floating_weights': not comments_enabled
    }

    # B4: Reaction Rate (15 или 25 при floating) - v5.0: динамический max
    reaction_rate = calculate_reaction_rate(messages)
    reaction_max = weights['reaction_rate_max']
    reaction_score = reaction_rate_to_points(reaction_rate, members, reaction_max)
    score += reaction_score
    breakdown['reaction_rate'] = {
        'value': round(reaction_rate, 3),
        'points': reaction_score,
        'max': reaction_max,
        'floating_boost': reaction_max > 15
    }

    # ===== КАТЕГОРИЯ C: ВРЕМЕННЫЕ МЕТРИКИ =====

    # C1: Views Decay (8 pts) - v5.0: Growth Trend check
    decay_ratio = calculate_views_decay(messages)
    decay_score = decay_to_points(decay_ratio, reaction_rate)  # v5.0: передаём reaction_rate
    score += decay_score
    breakdown['views_decay'] = {
        'value': round(decay_ratio, 2),
        'points': decay_score,
        'max': 8,
        'growth_trend': decay_ratio < 0.7 and reaction_rate > 2.0
    }

    # C2: Post Regularity (2 pts) - v5.0: снижено с 3
    regularity_cv = calculate_post_regularity(messages)
    regularity_score = regularity_to_points(regularity_cv)
    score += regularity_score
    breakdown['regularity'] = {'value': round(regularity_cv, 2), 'points': regularity_score, 'max': 2}

    # ===== КАТЕГОРИЯ D: АНАЛИЗ РЕАКЦИЙ =====

    # D1: Reaction Stability (5 pts) - v5.0: снижено с 8
    stability = calculate_reaction_stability(messages)
    stability_score = stability_to_points(stability)
    # Пропорционально уменьшаем (было max 8, стало 5)
    stability_score = min(stability_score, 5)
    score += stability_score
    breakdown['reaction_stability'] = {
        'value': stability.get('stability_cv', 50.0),
        'points': stability_score,
        'max': 5,
        'unique_types': stability.get('unique_types', 0),
        'distribution': stability.get('distribution', {})
    }

    # D2: ER Variation (10 pts) - без изменений
    er_cv = calculate_er_variation(messages)
    er_score = er_cv_to_points(er_cv, members)
    score += er_score
    breakdown['er_variation'] = {'value': round(er_cv, 1), 'points': er_score, 'max': 10}

    # ===== КАТЕГОРИЯ E: ДОПОЛНИТЕЛЬНЫЕ =====

    # E1: Source Diversity (5 pts) - без изменений
    source_max = calculate_source_diversity(messages)
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

    # E2: Forward Rate (15 или 20 при floating) - v5.0: увеличено с 5
    # forward_rate уже вычислен выше для Viral Exception (v5.1)
    forward_max = weights['forward_rate_max']
    forward_score = forward_rate_to_points(forward_rate, members, forward_max)
    score += forward_score
    breakdown['forward_rate'] = {
        'value': round(forward_rate, 3),
        'points': forward_score,
        'max': forward_max,
        'status': 'viral' if forward_rate >= 3.0 else ('good' if forward_rate >= 1.0 else 'low'),
        'floating_boost': forward_max > 15
    }

    # ===== v5.0: AD LOAD PENALTY (v7.1: adaptive max) =====
    ad_load_data = calculate_ad_load(messages, channel_username)
    ad_max_penalty = adaptive_weights['ad_load_max']
    ad_penalty = ad_load_to_penalty(ad_load_data, ad_max_penalty)
    if ad_penalty < 0:
        score += ad_penalty  # Штраф (отрицательное число)
        breakdown['ad_load_penalty'] = {
            'value': ad_load_data['ad_load_percent'],
            'points': ad_penalty,
            'max': ad_max_penalty,
            'status': ad_load_data['status'],
            'ad_count': ad_load_data['ad_count'],
            'hardcore_boost': ad_max_penalty < -15  # v7.1: показываем если усилено
        }

    # ===== v7.1: HIDDEN PENALTY (Hardcore mode only) =====
    hidden_penalty = adaptive_weights['hidden_penalty']
    if hidden_penalty < 0:
        score += hidden_penalty  # Штраф за закрытую аудиторию
        breakdown['hidden_penalty'] = {
            'value': 'Forensics unavailable',
            'points': hidden_penalty,
            'description': 'Штраф за закрытую аудиторию (нет данных о юзерах)'
        }

    # ===== v7.1: F16 REACTION FLATNESS (Hardcore mode only) =====
    if adaptive_weights['flatness_enabled']:
        flatness_result = check_f16_reaction_flatness(messages)
        if flatness_result['triggered']:
            score += flatness_result['penalty']  # Штраф (отрицательное число)
        breakdown['reaction_flatness'] = {
            'triggered': flatness_result['triggered'],
            'penalty': flatness_result['penalty'],
            'cv': flatness_result['cv'],
            'totals': flatness_result['totals'],
            'description': flatness_result['description']
        }

    # ===== КАТЕГОРИЯ F: БОНУСЫ =====

    # F1: Verified Bonus (+10)
    is_verified = getattr(chat, 'is_verified', False)
    if is_verified:
        score += 10
        breakdown['verified_bonus'] = {'value': True, 'points': 10, 'max': 10}

    # F2: Channel Age Bonus (+8)
    age_days = get_channel_age_days(chat)
    age_bonus = age_to_bonus(age_days)
    if age_bonus > 0:
        score += age_bonus
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

    # ===== CONVICTION PENALTY =====
    effective_conviction = conviction_details.get('effective_conviction', 0)

    if effective_conviction >= 40:
        penalty = int((effective_conviction - 40) * 0.5)
        penalty = min(penalty, 30)
        score -= penalty
        breakdown['conviction_penalty'] = {
            'value': effective_conviction,
            'points': -penalty,
            'max': -30,
            'factors_triggered': conviction_details.get('factors_triggered', 0)
        }

    # ===== v11.0: USER FORENSICS - EXECUTIONER SYSTEM =====
    forensics_result = None
    if users:
        forensics = UserForensics(users)
        forensics_result = forensics.analyze()

        # Применяем штраф/бонус за forensics
        # v11.0: total_penalty может быть и положительным (premium bonus)
        if forensics_result.total_penalty != 0:
            score += forensics_result.total_penalty

        # v11.0: Обновлённая структура forensics breakdown
        breakdown['forensics'] = {
            'total_penalty': forensics_result.total_penalty,
            'users_analyzed': forensics_result.users_analyzed,
            'status': forensics_result.status,
            # Method 1: ID Clustering (FATALITY -100)
            'id_clustering': {
                'triggered': forensics_result.id_clustering.get('triggered', False),
                'fatality': forensics_result.id_clustering.get('fatality', False),
                'penalty': forensics_result.id_clustering.get('penalty', 0),
                'neighbor_ratio': forensics_result.id_clustering.get('neighbor_ratio', 0),
                'description': forensics_result.id_clustering.get('description', '')
            },
            # Method 2: Geo/DC Check (-50)
            'geo_dc_check': {
                'triggered': forensics_result.geo_dc_check.get('triggered', False),
                'penalty': forensics_result.geo_dc_check.get('penalty', 0),
                'foreign_ratio': forensics_result.geo_dc_check.get('foreign_ratio', 0),
                'users_with_dc': forensics_result.geo_dc_check.get('users_with_dc', 0),
                'dc_distribution': forensics_result.geo_dc_check.get('dc_distribution', {}),
                'description': forensics_result.geo_dc_check.get('description', '')
            },
            # Method 3: Premium Density (-20 / +10)
            'premium_density': {
                'triggered': forensics_result.premium_density.get('triggered', False),
                'is_bonus': forensics_result.premium_density.get('is_bonus', False),
                'penalty': forensics_result.premium_density.get('penalty', 0),
                'premium_ratio': forensics_result.premium_density.get('premium_ratio', 0),
                'premium_count': forensics_result.premium_density.get('premium_count', 0),
                'description': forensics_result.premium_density.get('description', '')
            },
            # Method 4: Hidden Flags (-10)
            'hidden_flags': {
                'triggered': forensics_result.hidden_flags.get('triggered', False),
                'penalty': forensics_result.hidden_flags.get('penalty', 0),
                'counts': forensics_result.hidden_flags.get('counts', {}),
                'description': forensics_result.hidden_flags.get('description', '')
            }
        }
    else:
        # Нет юзеров для анализа - добавляем информационную секцию
        breakdown['forensics'] = {
            'total_penalty': 0,
            'users_analyzed': 0,
            'status': 'skipped',
            'description': 'Нет данных для User Forensics'
        }

    # ===== ФИНАЛЬНЫЙ ВЕРДИКТ =====
    # v5.0: Max теперь 118 (100 base + 10 verified + 8 age)
    base_score = score - (10 if is_verified else 0) - age_bonus
    base_score = min(100, max(0, base_score))

    score = max(0, score)

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
        'channel': channel_username or str(getattr(chat, 'id', 'unknown')),
        'members': members,
        'score': score,
        'base_score': base_score,
        'verdict': verdict,
        'scoring_mode': scoring_mode,  # v7.1: Normal или Hardcore
        'conviction': conviction_details,
        'breakdown': breakdown,
        'flags': {
            'is_scam': getattr(chat, 'is_scam', False),
            'is_fake': getattr(chat, 'is_fake', False),
            'is_verified': is_verified,
            'comments_enabled': comments_enabled,
            'floating_weights_active': not comments_enabled,
            'hardcore_mode': scoring_mode == 'hardcore'  # v7.1
        },
        'ad_load': ad_load_data,  # v5.0: Полные данные об Ad Load
        'raw_stats': get_raw_stats(messages)
    }
