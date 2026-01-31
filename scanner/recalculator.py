"""
Модуль пересчёта метрик v79.0

Позволяет изменять формулы скоринга и пересчитывать все каналы
без обращения к Telegram API.

Включает полный Trust Calculator с 27 множителями:
- Forensics: id_clustering (2), geo_dc_mismatch, premium_zero
- LLM: bot_penalty, ad_penalty
- Conviction: conviction_critical, conviction_high
- Statistical: hollow_views, zombie_engagement, satellite
- Ghost Protocol: ghost_channel, zombie_audience, member_discrepancy
- Decay: budget_cliff
- Posting: spam_posting (3 levels)
- Private Links: private_100/80/60, private_crypto_combo, private_hidden_combo
- Other: hidden_comments, dying_engagement (2), scam_network

Использование:
    python crawler.py --recalculate-local     # Пересчёт score из breakdown
    python crawler.py --recalculate-llm       # Пересчёт LLM анализа из текстов
    python crawler.py --recalculate-local --sync  # С синхронизацией на сервер
"""

import gzip
import json
from dataclasses import dataclass, field
from functools import reduce
from typing import Optional

from .database import CrawlerDB, ChannelRecord
from .scorer import (
    cv_to_points, reach_to_points, reaction_rate_to_points,
    forward_rate_to_points, age_to_points, regularity_to_points,
    stability_to_points, source_to_points, premium_to_points,
    er_trend_to_points, RAW_WEIGHTS, CATEGORY_TOTALS,
    calculate_floating_weights
)
from .json_compression import decompress_breakdown
from .config import GOOD_THRESHOLD
from .scorer_constants import TrustMultipliers, SpamPostingTiers


# =============================================================================
# TRUST CALCULATOR v79.0 - Complete trust factor calculation with all 27 multipliers
# =============================================================================

@dataclass
class TrustInput:
    """Input data for trust factor calculation."""
    # From forensics_json
    id_clustering_ratio: float = 0.0  # % of neighbor IDs
    id_clustering_fatality: bool = False
    geo_dc_foreign_ratio: float = 0.0  # % foreign DC
    premium_ratio: float = 0.0
    premium_count: int = 0
    users_analyzed: int = 0

    # From llm_analysis
    bot_percentage: int = 0
    ad_percentage: int = 0

    # From conviction system
    conviction_score: int = 0

    # From breakdown metrics
    reach: float = 0.0
    forward_rate: float = 0.0
    reaction_rate: float = 0.0
    views_decay_ratio: float = 1.0
    avg_comments: float = 0.0
    source_max_share: float = 0.0

    # From channel_health
    members: int = 0
    online_count: int = 0
    participants_count: int = 0

    # From posting data
    posts_per_day: float = 0.0
    category: str = None

    # From private links analysis
    private_ratio: float = 0.0

    # Flags
    comments_enabled: bool = True
    er_trend_status: str = 'insufficient_data'

    # Scam network
    scam_network_count: int = 0
    bad_network_count: int = 0


@dataclass
class TrustResult:
    """Result of trust factor calculation."""
    trust_factor: float
    multipliers: dict = field(default_factory=dict)
    penalties: list = field(default_factory=list)
    # Note: floor of 0.1 is applied in calculate_trust_factor() for non-fatality cases
    # FATALITY (id_clustering_fatality) returns exactly 0.0


def calculate_bot_mult_v78(bot_pct: int) -> float:
    """v78.0: Порог 40% (слабая модерация - норма)."""
    if bot_pct is None or bot_pct <= 40:
        return 1.0
    penalty = (bot_pct - 40) / 100.0
    return max(0.3, 1.0 - penalty)


def calculate_ad_mult(ad_pct: int) -> float:
    """Штраф за рекламу."""
    if ad_pct is None:
        return 1.0
    if ad_pct <= 20:
        return 1.0
    elif ad_pct <= 40:
        return 0.95
    elif ad_pct <= 60:
        return 0.85
    elif ad_pct <= 80:
        return 0.70
    else:
        return 0.50


def calculate_trust_factor(input: TrustInput) -> TrustResult:
    """
    UNIFIED trust_factor function with ALL 27 multipliers.

    Multipliers covered:
    1. id_clustering_fatality (0.0)
    2. id_clustering_suspicious (0.5)
    3. geo_dc_mismatch (0.2)
    4. premium_zero (0.8)
    5. bot_penalty (dynamic)
    6. ad_penalty (dynamic)
    7. conviction_critical (0.3)
    8. conviction_high (0.6)
    9. hollow_views (0.6)
    10. zombie_engagement (0.7)
    11. satellite (0.8)
    12. ghost_channel (0.5)
    13. zombie_audience (0.7)
    14. member_discrepancy (0.8)
    15. budget_cliff (0.7)
    16. spam_posting_spam (0.55)
    17. spam_posting_heavy (0.75)
    18. spam_posting_active (0.90)
    19. private_100 (0.25)
    20. private_80 (0.35)
    21. private_60 (0.50)
    22. private_crypto_combo (0.45)
    23. private_hidden_combo (0.40)
    24. hidden_comments (0.85)
    25. dying_engagement_combo (0.6)
    26. dying_engagement_solo (0.75)
    27. scam_network (dynamic)
    """
    multipliers = {}
    penalties = []

    # 1. FORENSICS PENALTIES

    # ID Clustering
    if input.id_clustering_fatality or input.id_clustering_ratio > 0.30:
        multipliers['id_clustering_fatality'] = TrustMultipliers.ID_CLUSTERING_FATALITY
        penalties.append('ID Clustering FATALITY (>30% neighbor IDs)')
    elif input.id_clustering_ratio > 0.15:
        multipliers['id_clustering_suspicious'] = TrustMultipliers.ID_CLUSTERING_SUSPICIOUS
        penalties.append(f'ID Clustering suspicious ({input.id_clustering_ratio:.0%})')

    # Geo/DC Mismatch
    if input.geo_dc_foreign_ratio > 0.75:
        multipliers['geo_dc_mismatch'] = TrustMultipliers.GEO_DC_MISMATCH
        penalties.append(f'Geo/DC mismatch ({input.geo_dc_foreign_ratio:.0%} foreign)')

    # Premium Zero
    if input.users_analyzed >= 10 and input.premium_count == 0:
        multipliers['premium_zero'] = TrustMultipliers.PREMIUM_ZERO
        penalties.append('Zero premium users')

    # 2. LLM PENALTIES

    bot_mult = calculate_bot_mult_v78(input.bot_percentage)
    if bot_mult < 1.0:
        multipliers['bot_penalty'] = bot_mult
        penalties.append(f'Bot comments ({input.bot_percentage}%)')

    ad_mult = calculate_ad_mult(input.ad_percentage)
    if ad_mult < 1.0:
        multipliers['ad_penalty'] = ad_mult
        penalties.append(f'High ad percentage ({input.ad_percentage}%)')

    # 3. CONVICTION PENALTIES

    if input.conviction_score >= 70:
        multipliers['conviction_critical'] = TrustMultipliers.CONVICTION_CRITICAL
        penalties.append(f'Critical conviction ({input.conviction_score})')
    elif input.conviction_score >= 50:
        multipliers['conviction_high'] = TrustMultipliers.CONVICTION_HIGH
        penalties.append(f'High conviction ({input.conviction_score})')

    # 4. STATISTICAL PENALTIES

    # Hollow Views
    if input.reach > 300 and input.forward_rate < 3.0 and input.avg_comments < 1:
        multipliers['hollow_views'] = 0.6
        penalties.append(f'Hollow views (reach {input.reach:.0f}% without virality)')

    # Zombie Engagement
    if input.reach > 50 and input.reaction_rate < 0.1:
        multipliers['zombie_engagement'] = 0.7
        penalties.append('Zombie engagement (high reach, no reactions)')

    # Satellite
    if input.source_max_share > 0.5 and input.avg_comments < 1:
        multipliers['satellite'] = 0.8
        penalties.append(f'Satellite channel ({input.source_max_share:.0%} from one source)')

    # 5. GHOST PROTOCOL

    if input.members > 20000 and input.online_count > 0:
        online_percent = (input.online_count / input.members) * 100
        if online_percent < 0.1:
            multipliers['ghost_channel'] = 0.5
            penalties.append(f'Ghost channel ({online_percent:.2f}% online)')

    if input.members > 5000 and input.online_count > 0:
        online_percent = (input.online_count / input.members) * 100
        if online_percent < 0.3 and 'ghost_channel' not in multipliers:
            multipliers['zombie_audience'] = 0.7
            penalties.append(f'Zombie audience ({online_percent:.2f}% online)')

    # Member Discrepancy
    if input.participants_count > 0 and input.members > 0:
        discrepancy = abs(input.participants_count - input.members) / input.members
        if discrepancy > 0.1:
            multipliers['member_discrepancy'] = 0.8
            penalties.append(f'Member discrepancy ({discrepancy:.0%})')

    # 6. DECAY PENALTIES

    # Budget Cliff
    if input.views_decay_ratio < 0.2:
        multipliers['budget_cliff'] = 0.7
        penalties.append(f'Budget cliff (decay {input.views_decay_ratio:.2f})')

    # Bot Wall (not a penalty, just detection)
    # 0.98-1.02 is suspicious but handled elsewhere

    # 7. POSTING PENALTIES (v78.0 category-aware)

    # Get thresholds based on category
    tier = SpamPostingTiers.CATEGORY_TIERS.get(input.category, SpamPostingTiers.DEFAULT)
    active_threshold, heavy_threshold, spam_threshold = tier

    if input.posts_per_day > spam_threshold:
        multipliers['spam_posting_spam'] = TrustMultipliers.SPAM_POSTING_SPAM
        penalties.append(f'Spam posting ({input.posts_per_day:.1f}/day)')
    elif input.posts_per_day > heavy_threshold:
        multipliers['spam_posting_heavy'] = TrustMultipliers.SPAM_POSTING_HEAVY
        penalties.append(f'Heavy posting ({input.posts_per_day:.1f}/day)')
    elif input.posts_per_day > active_threshold:
        multipliers['spam_posting_active'] = TrustMultipliers.SPAM_POSTING_ACTIVE
        penalties.append(f'Active posting ({input.posts_per_day:.1f}/day)')

    # 8. PRIVATE LINKS PENALTIES

    if input.private_ratio >= 1.0:
        multipliers['private_100'] = TrustMultipliers.PRIVATE_100
        penalties.append('100% private ad links')
    elif input.private_ratio > 0.8:
        multipliers['private_80'] = TrustMultipliers.PRIVATE_80
        penalties.append(f'High private links ({input.private_ratio:.0%})')
    elif input.private_ratio > 0.6:
        multipliers['private_60'] = TrustMultipliers.PRIVATE_60
        penalties.append(f'Many private links ({input.private_ratio:.0%})')

    # Combos
    if input.category == 'CRYPTO' and input.private_ratio > 0.4:
        if 'private_crypto_combo' not in multipliers:
            multipliers['private_crypto_combo'] = TrustMultipliers.PRIVATE_CRYPTO_COMBO
            penalties.append('CRYPTO + private links combo')

    if not input.comments_enabled and input.private_ratio > 0.5:
        if 'private_hidden_combo' not in multipliers:
            multipliers['private_hidden_combo'] = TrustMultipliers.PRIVATE_HIDDEN_COMBO
            penalties.append('Hidden comments + private links combo')

    # 9. HIDDEN COMMENTS

    if not input.comments_enabled:
        multipliers['hidden_comments'] = TrustMultipliers.HIDDEN_COMMENTS
        penalties.append('Comments disabled')

    # 10. DYING ENGAGEMENT

    if input.er_trend_status == 'dying':
        if 0.7 <= input.views_decay_ratio <= 1.3:
            multipliers['dying_engagement_combo'] = 0.6
            penalties.append('Dying engagement + no organic growth')
        else:
            multipliers['dying_engagement_solo'] = 0.75
            penalties.append('Dying engagement trend')

    # 11. SCAM NETWORK

    if input.scam_network_count > 0 or input.bad_network_count > 0:
        network_mult = (0.9 ** input.scam_network_count) * (0.95 ** input.bad_network_count)
        multipliers['scam_network'] = round(network_mult, 2)
        penalties.append(f'Scam network ({input.scam_network_count} scam, {input.bad_network_count} bad)')

    # CALCULATE FINAL TRUST FACTOR
    # Special case: FATALITY returns exactly 0.0 (no floor)
    if 'id_clustering_fatality' in multipliers:
        trust = 0.0
    elif not multipliers:
        trust = 1.0
    else:
        trust = reduce(lambda a, b: a * b, multipliers.values(), 1.0)
        trust = max(0.1, round(trust, 2))  # Floor 0.1 for non-fatality cases

    return TrustResult(
        trust_factor=trust,
        multipliers=multipliers,
        penalties=penalties
    )


def extract_trust_input(
    breakdown: dict,
    forensics: dict = None,
    llm_analysis: dict = None,
    channel_data: dict = None
) -> TrustInput:
    """
    Extract TrustInput from scanner's database row format.

    Args:
        breakdown: Breakdown dict from breakdown_json
        forensics: Forensics dict from forensics_json
        llm_analysis: LLM analysis dict from breakdown_json
        channel_data: Channel data dict with members, online_count, etc.

    Returns:
        TrustInput populated from available data
    """
    forensics = forensics or {}
    llm_analysis = llm_analysis or {}
    channel_data = channel_data or {}

    # Helper to safely get nested values
    def get_value(d: dict, key: str, default=0):
        val = d.get(key, {})
        if isinstance(val, dict):
            return val.get('value', default)
        return val if val is not None else default

    # Extract forensics data
    id_clustering = forensics.get('id_clustering', {})
    geo_dc = forensics.get('geo_dc_analysis', {})
    premium_density = forensics.get('premium_density', {})

    # Extract breakdown metrics
    trust_details = breakdown.get('trust_details', {})
    er_trend_data = breakdown.get('er_trend', {})
    source_data = breakdown.get('source_diversity', {}) or breakdown.get('source', {})

    # Get er_trend status
    er_trend_status = 'insufficient_data'
    if isinstance(er_trend_data, dict):
        er_trend_status = er_trend_data.get('status', 'insufficient_data')

    # Get views_decay_ratio
    views_decay_ratio = 1.0
    views_decay = breakdown.get('views_decay', {})
    if isinstance(views_decay, dict):
        views_decay_ratio = views_decay.get('value', 1.0)

    # Get comments data
    comments_data = breakdown.get('comments', {})
    avg_comments = 0.0
    if isinstance(comments_data, dict):
        avg_comments = comments_data.get('value', 0.0)

    # Get source_max_share (value = 1 - max_share in breakdown)
    source_max_share = 0.0
    if isinstance(source_data, dict):
        # source_diversity value is stored as (1 - max_share), so invert it
        diversity_value = source_data.get('value', 0)
        source_max_share = 1 - diversity_value if diversity_value else 0

    # Extract private ratio from trust_details
    private_ratio = 0.0
    for key, detail in trust_details.items():
        if 'private' in key.lower() and isinstance(detail, dict):
            private_ratio = detail.get('ratio', 0.0)
            break

    # Count scam/bad networks from trust_details
    scam_network_count = 0
    bad_network_count = 0
    scam_network_detail = trust_details.get('scam_network', {})
    if isinstance(scam_network_detail, dict):
        scam_network_count = scam_network_detail.get('scam_count', 0)
        bad_network_count = scam_network_detail.get('bad_count', 0)

    return TrustInput(
        # Forensics
        id_clustering_ratio=id_clustering.get('neighbor_ratio', 0.0),
        id_clustering_fatality=id_clustering.get('fatality', False),
        geo_dc_foreign_ratio=geo_dc.get('foreign_ratio', 0.0),
        premium_ratio=premium_density.get('premium_ratio', 0.0),
        premium_count=premium_density.get('premium_count', 0),
        users_analyzed=premium_density.get('users_analyzed', 0),

        # LLM analysis
        bot_percentage=llm_analysis.get('bot_percentage', 0),
        ad_percentage=llm_analysis.get('ad_percentage', 0),

        # Conviction (from trust_details)
        conviction_score=trust_details.get('conviction', {}).get('score', 0) if isinstance(trust_details.get('conviction'), dict) else 0,

        # Breakdown metrics
        reach=get_value(breakdown, 'reach', 0.0),
        forward_rate=get_value(breakdown, 'forward_rate', 0.0),
        reaction_rate=get_value(breakdown, 'reaction_rate', 0.0),
        views_decay_ratio=views_decay_ratio,
        avg_comments=avg_comments,
        source_max_share=source_max_share,

        # Channel data
        members=channel_data.get('members', 0),
        online_count=channel_data.get('online_count', 0),
        participants_count=channel_data.get('participants_count', 0),

        # Posting data
        posts_per_day=breakdown.get('regularity', {}).get('value', 0.0) if isinstance(breakdown.get('regularity'), dict) else 0.0,
        category=channel_data.get('category'),

        # Private ratio
        private_ratio=private_ratio,

        # Flags
        comments_enabled=breakdown.get('comments_enabled', True),
        er_trend_status=er_trend_status,

        # Scam network
        scam_network_count=scam_network_count,
        bad_network_count=bad_network_count,
    )


# =============================================================================
# LEGACY FUNCTIONS (kept for backward compatibility)
# =============================================================================


def recalculate_trust_from_breakdown(breakdown: dict, llm_analysis: dict = None) -> float:
    """
    Пересчитывает trust_factor из сохранённых trust_details и llm_analysis.

    Args:
        breakdown: Breakdown dict containing trust_details
        llm_analysis: Optional LLM analysis dict with llm_trust_factor

    Returns:
        float: Recalculated trust factor (0.1-1.0)
    """
    multipliers = []

    # 1. Trust details (spam_posting, hollow_views, ghost_channel, etc.)
    trust_details = breakdown.get('trust_details', {})
    for key, detail in trust_details.items():
        if isinstance(detail, dict) and 'multiplier' in detail:
            mult = detail['multiplier']
            if isinstance(mult, (int, float)) and mult < 1.0:
                multipliers.append(mult)

    # 2. LLM trust factor
    if llm_analysis:
        llm_trust = llm_analysis.get('llm_trust_factor', 1.0)
        if llm_trust and isinstance(llm_trust, (int, float)) and llm_trust < 1.0:
            multipliers.append(llm_trust)

    # Multiply all penalties together
    trust_factor = 1.0
    for mult in multipliers:
        trust_factor *= mult

    return max(0.1, round(trust_factor, 2))  # Floor 0.1, round to 2 decimals


@dataclass
class RecalculateResult:
    """Результат пересчёта."""
    total: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def recalculate_score_from_breakdown(breakdown: dict, members: int = 0) -> tuple[int, dict, dict]:
    """
    v55.1: Пересчитывает score из сохранённых значений метрик.

    Args:
        breakdown: Сохранённый breakdown из БД
        members: Количество подписчиков

    Returns:
        (new_score, new_categories, updated_breakdown) - новый score, итоги по категориям, обновлённый breakdown
    """
    if not breakdown:
        return 0, {}, breakdown

    # Извлекаем значения метрик
    def get_value(key: str) -> float:
        data = breakdown.get(key, {})
        if isinstance(data, dict):
            return data.get('value', 0) or 0
        return 0

    def get_dict(key: str) -> dict:
        data = breakdown.get(key, {})
        return data if isinstance(data, dict) else {}

    def update_points(key: str, points: int, max_pts: int):
        """v55.1: Обновляет points и max в breakdown item."""
        if key in breakdown and isinstance(breakdown[key], dict):
            breakdown[key]['points'] = points
            breakdown[key]['max'] = max_pts

    # Engagement flags (needed for floating weights)
    comments_enabled = breakdown.get('comments_enabled', True)
    reactions_enabled = breakdown.get('reactions_enabled', True)

    # v76.0: Calculate floating weights based on comments/reactions availability
    weights = calculate_floating_weights(comments_enabled, reactions_enabled)

    # Quality (42 балла)
    cv_views = get_value('cv_views')
    forward_rate = get_value('forward_rate')
    reach = get_value('reach')
    regularity_data = get_dict('regularity')
    # v65.1: Ключ 'value' содержит posts_per_day
    posts_per_day = regularity_data.get('value', regularity_data.get('posts_per_day', 0))

    cv_pts = cv_to_points(cv_views, forward_rate)
    reach_pts = reach_to_points(reach, members)
    forward_pts = forward_rate_to_points(forward_rate, members, weights['forward_rate_max'])
    regularity_pts = regularity_to_points(posts_per_day)

    quality_score = cv_pts + reach_pts + forward_pts + regularity_pts

    # v55.1: Обновляем points в breakdown
    update_points('cv_views', cv_pts, RAW_WEIGHTS['quality']['cv_views'])
    update_points('reach', reach_pts, RAW_WEIGHTS['quality']['reach'])
    update_points('forward_rate', forward_pts, RAW_WEIGHTS['quality']['forward_rate'])
    if 'regularity' in breakdown and isinstance(breakdown['regularity'], dict):
        breakdown['regularity']['points'] = regularity_pts
        breakdown['regularity']['max'] = RAW_WEIGHTS['quality']['regularity']

    # Engagement (38 баллов)
    comments_data = get_dict('comments')

    # comments - используем сохранённые points, т.к. логика сложная (floating weights)
    comments_pts = comments_data.get('points', 0)

    reaction_rate = get_value('reaction_rate')
    stability_data = get_dict('reaction_stability') or get_dict('stability')
    er_trend_data = get_dict('er_trend')

    reaction_pts = reaction_rate_to_points(reaction_rate, members, weights['reaction_rate_max']) if reactions_enabled else 0
    stability_pts = stability_to_points(stability_data)
    er_trend_pts = er_trend_to_points(er_trend_data)

    engagement_score = comments_pts + reaction_pts + stability_pts + er_trend_pts

    # v55.1: Обновляем points в breakdown
    update_points('reaction_rate', reaction_pts, RAW_WEIGHTS['engagement']['reaction_rate'])
    if 'reaction_stability' in breakdown and isinstance(breakdown['reaction_stability'], dict):
        breakdown['reaction_stability']['points'] = stability_pts
        breakdown['reaction_stability']['max'] = RAW_WEIGHTS['engagement']['stability']
    if 'er_trend' in breakdown and isinstance(breakdown['er_trend'], dict):
        breakdown['er_trend']['points'] = er_trend_pts
        breakdown['er_trend']['max'] = RAW_WEIGHTS['engagement']['er_trend']

    # Reputation (20 баллов)
    age = get_value('age')
    premium_data = get_dict('premium')
    premium_ratio = premium_data.get('ratio', 0)
    premium_count = premium_data.get('count', 0)
    source_data = get_dict('source_diversity') or get_dict('source')
    source_max_share = 1 - get_value('source_diversity')  # value = 1 - max_share
    repost_ratio = source_data.get('repost_ratio', 0)

    age_pts = age_to_points(int(age))
    premium_pts = premium_to_points(premium_ratio, premium_count)
    source_pts = source_to_points(source_max_share, repost_ratio)

    reputation_score = age_pts + premium_pts + source_pts

    # v55.1: Обновляем points в breakdown
    update_points('age', age_pts, RAW_WEIGHTS['reputation']['age'])
    if 'premium' in breakdown and isinstance(breakdown['premium'], dict):
        breakdown['premium']['points'] = premium_pts
        breakdown['premium']['max'] = RAW_WEIGHTS['reputation']['premium']
    if 'source_diversity' in breakdown and isinstance(breakdown['source_diversity'], dict):
        breakdown['source_diversity']['points'] = source_pts
        breakdown['source_diversity']['max'] = RAW_WEIGHTS['reputation']['source']

    # Итоговый score
    raw_score = quality_score + engagement_score + reputation_score
    raw_score = min(100, raw_score)  # Cap at 100

    # Categories для breakdown_json
    categories = {
        'quality': {'score': quality_score, 'max': CATEGORY_TOTALS['quality']},
        'engagement': {'score': engagement_score, 'max': CATEGORY_TOTALS['engagement']},
        'reputation': {'score': reputation_score, 'max': CATEGORY_TOTALS['reputation']},
    }

    return raw_score, categories, breakdown


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
    # v65.0: Добавлен forensics_json для чтения premium_ratio и premium_count
    cursor.execute("""
        SELECT username, members, breakdown_json, trust_factor, score, forensics_json
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
        old_trust_factor = row[3] or 1.0
        old_score = row[4] or 0
        forensics_json = row[5]  # v65.0: Для premium данных

        try:
            # Парсим breakdown
            data = json.loads(breakdown_json)
            breakdown = data.get('breakdown', {}) if isinstance(data, dict) else {}

            # Recalculate trust_factor from breakdown's trust_details
            llm_analysis = data.get('llm_analysis', {})
            trust_factor = recalculate_trust_from_breakdown(breakdown, llm_analysis)

            # Декомпрессируем если сжат (короткие ключи cv, re и т.д.)
            breakdown = decompress_breakdown(breakdown)

            if not breakdown:
                result.skipped += 1
                continue

            # v65.0: Добавляем premium данные из forensics_json в breakdown
            if forensics_json:
                try:
                    forensics_data = json.loads(forensics_json)
                    premium_density = forensics_data.get('premium_density', {})
                    if premium_density and 'premium' in breakdown:
                        # Добавляем ratio и count для recalculate_score_from_breakdown
                        breakdown['premium']['ratio'] = premium_density.get('premium_ratio', 0)
                        breakdown['premium']['count'] = premium_density.get('premium_count', 0)
                except (json.JSONDecodeError, TypeError):
                    pass

            # v55.1: Пересчитываем (теперь возвращает и обновлённый breakdown)
            raw_score, categories, updated_breakdown = recalculate_score_from_breakdown(breakdown, members)

            # Применяем trust_factor
            new_score = int(raw_score * trust_factor)

            # v65.1: Расчёт verdict по тем же порогам что в scorer.py
            if new_score >= 75:
                new_verdict = 'EXCELLENT'
            elif new_score >= 55:
                new_verdict = 'GOOD'
            elif new_score >= 40:
                new_verdict = 'MEDIUM'
            elif new_score >= 25:
                new_verdict = 'HIGH_RISK'
            else:
                new_verdict = 'SCAM'

            # Обновляем в БД
            new_status = 'GOOD' if new_score >= GOOD_THRESHOLD else 'BAD'

            # v55.1: Сохраняем обновлённый breakdown и categories
            data['breakdown'] = updated_breakdown
            data['categories'] = categories
            new_breakdown_json = json.dumps(data, ensure_ascii=False)

            cursor.execute("""
                UPDATE channels
                SET score = ?, status = ?, verdict = ?, breakdown_json = ?, trust_factor = ?
                WHERE username = ?
            """, (new_score, new_status, new_verdict, new_breakdown_json, trust_factor, username))

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

            # v55.1: Пересчитываем score с новым LLM результатом
            raw_score, _, _ = recalculate_score_from_breakdown(breakdown_raw, members)

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


# =============================================================================
# SCORE INPUT / EXTRACTION v79.0 - For test compatibility
# =============================================================================

@dataclass
class ScoreInput:
    """Input data for score calculation."""
    # Quality metrics
    cv_views: float = 0.0
    reach: float = 0.0
    members: int = 0
    posts_per_day: float = 0.0
    forward_rate: float = 0.0
    views_decay_ratio: float = 1.0

    # Engagement metrics
    reaction_rate: float = 0.0
    avg_comments: float = 0.0
    er_trend_status: str = 'critical_decline'
    stability_cv: float = 100.0
    stability_points: int = 0

    # Reputation metrics
    channel_age_days: int = 0
    premium_ratio: float = 0.0
    premium_count: int = 0
    is_verified: bool = False
    source_max_share: float = 1.0
    repost_ratio: float = 1.0

    # Flags
    comments_enabled: bool = True
    reactions_enabled: bool = True


def _extract_avg_comments(comments_data: dict) -> float:
    """
    Extract avg_comments from breakdown.
    Scanner stores: {'value': 'enabled (avg 10.3)', 'points': 15}
    or: {'avg': 10.3, 'points': 15}
    """
    if not comments_data:
        return 0.0

    # New format: direct 'avg' key
    if 'avg' in comments_data:
        return float(comments_data.get('avg', 0))

    # Old format: parse from 'value' string "enabled (avg X.X)"
    value = comments_data.get('value', '')
    if isinstance(value, str) and 'avg' in value:
        import re
        match = re.search(r'avg\s*([0-9.]+)', value)
        if match:
            return float(match.group(1))

    return 0.0


def extract_score_input_from_breakdown(breakdown_json: dict, members: int = 0) -> ScoreInput:
    """
    Extract ScoreInput from saved breakdown_json.
    Use this when recalculating from database.

    Args:
        breakdown_json: The breakdown_json from database
        members: Channel members count (pass from DB row, not stored in breakdown)
    """
    breakdown = breakdown_json.get('breakdown', breakdown_json) if breakdown_json else {}

    # Extract reaction stability data (use `or {}` to handle explicit null)
    stability_data = breakdown.get('reaction_stability') or {}
    stability_cv = stability_data.get('value', 100.0) if stability_data else 100.0
    stability_points = stability_data.get('points', 0) if stability_data else 0

    # comments_enabled/reactions_enabled are in breakdown ROOT
    comments_enabled = breakdown.get('comments_enabled', True)
    reactions_enabled = breakdown.get('reactions_enabled', True)

    # Fallback to metadata if present (for backwards compatibility)
    if 'metadata' in breakdown:
        metadata = breakdown['metadata']
        if 'comments_enabled' in metadata:
            comments_enabled = metadata['comments_enabled']
        if 'reactions_enabled' in metadata:
            reactions_enabled = metadata['reactions_enabled']
        if members == 0 and 'members' in metadata:
            members = metadata['members']

    return ScoreInput(
        cv_views=(breakdown.get('cv_views') or {}).get('value', 0),
        reach=(breakdown.get('reach') or {}).get('value', 0),
        members=members,
        posts_per_day=(breakdown.get('regularity') or {}).get('value', 0),
        forward_rate=(breakdown.get('forward_rate') or {}).get('value', 0),
        views_decay_ratio=(breakdown.get('views_decay') or {}).get('value', 1.0),
        reaction_rate=(breakdown.get('reaction_rate') or {}).get('value', 0),
        avg_comments=_extract_avg_comments(breakdown.get('comments') or {}),
        er_trend_status=(breakdown.get('er_trend') or {}).get('status', 'critical_decline'),
        stability_cv=stability_cv,
        stability_points=stability_points,
        channel_age_days=(breakdown.get('age') or {}).get('value', 0),
        premium_ratio=(breakdown.get('premium') or {}).get('ratio', 0),
        premium_count=(breakdown.get('premium') or {}).get('count', 0),
        is_verified=breakdown.get('verified', False),
        source_max_share=1 - (breakdown.get('source_diversity') or {}).get('value', 0),
        repost_ratio=(breakdown.get('source_diversity') or {}).get('repost_ratio', 1.0),
        comments_enabled=comments_enabled,
        reactions_enabled=reactions_enabled,
    )


# =============================================================================
# CHANNEL ROW / RECALCULATE CHANNEL v79.0 - For test compatibility
# =============================================================================

@dataclass
class ChannelRow:
    """Channel data from database."""
    username: str
    score: int
    raw_score: int
    trust_factor: float
    verdict: str
    status: str
    breakdown_json: dict
    forensics_json: dict
    llm_analysis: dict
    members: int
    online_count: int
    participants_count: int
    bot_percentage: int
    ad_percentage: int
    category: str
    posts_per_day: float
    comments_enabled: bool
    reactions_enabled: bool


@dataclass
class LocalRecalcResult:
    """Result of local recalculation for one channel."""
    username: str
    raw_score: int
    old_score: int
    new_score: int
    old_trust: float
    new_trust: float
    old_verdict: str
    new_verdict: str
    changed: bool
    penalties: list


def extract_trust_input_from_row(row: ChannelRow) -> TrustInput:
    """Extract TrustInput from database row."""
    forensics = row.forensics_json or {}
    breakdown = row.breakdown_json or {}
    bd = breakdown.get('breakdown', breakdown)

    # ID Clustering
    id_data = forensics.get('id_clustering') or {}
    id_ratio = id_data.get('percentage', 0) / 100 if id_data.get('percentage') else 0
    # Also check neighbor_ratio (alternative key)
    if id_ratio == 0:
        id_ratio = id_data.get('neighbor_ratio', 0) or 0
    id_fatality = id_data.get('fatality', False)

    # Geo/DC
    geo_data = forensics.get('geo_dc_analysis') or {}
    geo_ratio = geo_data.get('percentage', 0) / 100 if geo_data.get('percentage') else 0
    # Also check foreign_ratio (alternative key)
    if geo_ratio == 0:
        geo_ratio = geo_data.get('foreign_ratio', 0) or 0

    # Premium
    premium_data = forensics.get('premium_density') or {}
    premium_ratio = premium_data.get('premium_ratio', 0) or 0
    premium_count = premium_data.get('premium_count', 0) or 0
    users_analyzed = forensics.get('users_analyzed', 0) or premium_data.get('users_analyzed', 0) or 0

    # Conviction
    conviction_data = breakdown.get('conviction_details') or {}
    conviction_score = conviction_data.get('conviction_score', 0) or 0

    # Metrics from breakdown
    reach = (bd.get('reach') or {}).get('value', 0) or 0
    forward_rate = (bd.get('forward_rate') or {}).get('value', 0) or 0
    reaction_rate = (bd.get('reaction_rate') or {}).get('value', 0) or 0
    decay_ratio = (bd.get('views_decay') or {}).get('value', 1.0) or 1.0
    avg_comments = (bd.get('comments') or {}).get('avg', 0) or 0
    source_data = bd.get('source_diversity') or {}
    source_max_share = 1 - (source_data.get('value', 1) or 1)

    # ER Trend
    er_status = (bd.get('er_trend') or {}).get('status', 'insufficient_data')

    # Private links
    private_data = bd.get('private_links') or {}
    private_ratio = private_data.get('private_ratio', 0) or 0

    return TrustInput(
        id_clustering_ratio=id_ratio,
        id_clustering_fatality=id_fatality,
        geo_dc_foreign_ratio=geo_ratio,
        premium_ratio=premium_ratio,
        premium_count=premium_count,
        users_analyzed=users_analyzed,
        bot_percentage=row.bot_percentage or 0,
        ad_percentage=row.ad_percentage or 0,
        conviction_score=conviction_score,
        reach=reach,
        forward_rate=forward_rate,
        reaction_rate=reaction_rate,
        views_decay_ratio=decay_ratio,
        avg_comments=avg_comments,
        source_max_share=source_max_share,
        members=row.members or 0,
        online_count=row.online_count or 0,
        participants_count=row.participants_count or 0,
        posts_per_day=row.posts_per_day or 0,
        category=row.category,
        private_ratio=private_ratio,
        comments_enabled=row.comments_enabled,
        er_trend_status=er_status,
    )


def recalculate_channel(row: ChannelRow) -> LocalRecalcResult:
    """Recalculate single channel from breakdown."""
    from .scorer_constants import VerdictThresholds

    # Validate data exists
    if not row.breakdown_json or 'breakdown' not in row.breakdown_json:
        return LocalRecalcResult(
            username=row.username,
            raw_score=0,
            old_score=row.score,
            new_score=row.score,  # Keep old score
            old_trust=row.trust_factor,
            new_trust=row.trust_factor,  # Keep old trust
            old_verdict=row.verdict,
            new_verdict=row.verdict,  # Keep old verdict
            changed=False,
            penalties=[],
        )

    # Extract inputs and recalculate
    trust_input = extract_trust_input_from_row(row)
    trust_result = calculate_trust_factor(trust_input)

    # Recalculate raw score
    breakdown = row.breakdown_json.get('breakdown', row.breakdown_json)
    new_raw, _, _ = recalculate_score_from_breakdown(breakdown, row.members)

    # Final score
    new_trust = trust_result.trust_factor
    new_final = round(new_raw * new_trust)

    # Determine verdict
    if new_final >= VerdictThresholds.EXCELLENT:
        new_verdict = 'EXCELLENT'
    elif new_final >= VerdictThresholds.GOOD:
        new_verdict = 'GOOD'
    elif new_final >= VerdictThresholds.MEDIUM:
        new_verdict = 'MEDIUM'
    elif new_final >= VerdictThresholds.HIGH_RISK:
        new_verdict = 'HIGH_RISK'
    else:
        new_verdict = 'SCAM'

    # Check if changed
    changed = (
        row.score != new_final or
        abs(row.trust_factor - new_trust) > 0.01 or
        row.verdict != new_verdict
    )

    return LocalRecalcResult(
        username=row.username,
        raw_score=new_raw,
        old_score=row.score,
        new_score=new_final,
        old_trust=row.trust_factor,
        new_trust=new_trust,
        old_verdict=row.verdict,
        new_verdict=new_verdict,
        changed=changed,
        penalties=trust_result.penalties,
    )
