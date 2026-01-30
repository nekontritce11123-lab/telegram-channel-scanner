"""
Trust Factor Calculator v79.0
ЕДИНАЯ функция trust_factor со ВСЕМИ множителями.
"""
from dataclasses import dataclass, field
from typing import Optional
from functools import reduce

# Add parent directory to path (works from any location)
import os
import sys
_parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from scanner.scorer_constants import TrustMultipliers


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

    def __post_init__(self):
        # Ensure minimum floor
        self.trust_factor = max(0.1, self.trust_factor)


def calculate_bot_mult_v78(bot_pct: int) -> float:
    """v78.0: Порог 40% (слабая модерация — норма)."""
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
    ЕДИНАЯ функция trust_factor со ВСЕМИ множителями.
    Replaces the incomplete recalc_trust.py logic.
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
    from scanner.scorer_constants import SpamPostingTiers
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
    if not multipliers:
        trust = 1.0
    else:
        trust = reduce(lambda a, b: a * b, multipliers.values(), 1.0)

    trust = max(0.1, round(trust, 2))

    return TrustResult(
        trust_factor=trust,
        multipliers=multipliers,
        penalties=penalties
    )
