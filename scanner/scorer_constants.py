"""
Scoring algorithm constants. v78.0

Centralized constants extracted from scorer.py for maintainability.
All thresholds, multipliers, and scoring boundaries in one place.
"""


class ScoringWeights:
    """
    Raw score weights per category. v48.0

    Total: 100 points
    - Quality: 42 points (виральность и регулярность)
    - Engagement: 38 points (тренд важнее абсолютных чисел)
    - Reputation: 20 points
    """

    # v48.0: КАЧЕСТВО КОНТЕНТА (42 балла)
    QUALITY = {
        'forward_rate': 15,   # v48.0: +2 (виральность = "Святой Грааль")
        'cv_views': 12,       # v48.0: -3 (снизили, но важно для детекции)
        'reach': 8,           # v48.0: +1
        'regularity': 7,      # v48.0: NEW! Стабильность постинга
    }

    # v48.0: ENGAGEMENT (38 баллов)
    ENGAGEMENT = {
        'comments': 15,       # Комментарии (floating если закрыты)
        'er_trend': 10,       # v48.0: NEW! Канал растёт или умирает?
        'reaction_rate': 8,   # v48.0: -7 (легко накрутить)
        'stability': 5,       # Стабильность реакций
    }

    # РЕПУТАЦИЯ (20 баллов)
    REPUTATION = {
        'verified': 0,        # v38.4: Верификация убрана
        'age': 7,
        'premium': 7,
        'source': 6,
    }

    # v48.0: Итоги по категориям
    CATEGORY_TOTALS = {
        'quality': 42,        # v48.0: было 40, +2
        'engagement': 38,     # v48.0: было 40, -2
        'reputation': 20,
    }


class CVThresholds:
    """
    CV Views scoring thresholds.

    CV (Coefficient of Variation) measures view distribution naturalness.
    - 30-60%: Ideal (natural variation)
    - <10%: Suspicious (bots)
    - >100%: Extreme spikes (wave manipulation or viral)
    """

    BOT_SUSPECTED = 10      # CV < 10% = too uniform, likely bots
    GOOD_MIN = 30           # 30-60% = ideal range
    GOOD_MAX = 60
    SUSPICIOUS_HIGH = 100   # CV >= 100% = wave manipulation or viral

    # Viral Exception: CV > 100% + forward_rate > 3% = viral content
    VIRAL_FORWARD_RATE = 3.0


class ReachThresholds:
    """
    Reach scoring thresholds by channel size. v23.0

    Reach = avg_views / members * 100
    Higher thresholds for smaller channels (micro channels can have 200% reach naturally).
    """

    # Scam thresholds (above = definitely manipulation)
    SCAM_MICRO = 200        # < 200 subs: up to 200% is normal
    SCAM_SMALL = 150        # 200-1000 subs
    SCAM_MEDIUM = 130       # 1000-5000 subs
    SCAM_LARGE = 120        # > 5000 subs

    # High but acceptable thresholds
    HIGH_MICRO = 150
    HIGH_SMALL = 100
    HIGH_MEDIUM = 80
    HIGH_LARGE = 60

    # Dead audience thresholds
    DEAD_MIN = 5            # < 5% = dead audience
    LOW = 10                # 5-10% = low reach
    MEDIUM = 20             # 10-20% = medium reach
    GOOD = 50               # 20-50% = good reach


class ReactionRateThresholds:
    """
    Reaction rate scoring thresholds by channel size.

    Reaction rate = avg_reactions / avg_views * 100
    """

    # Scam thresholds (above = manipulation)
    SCAM_MICRO = 20         # < 200 subs
    SCAM_SMALL = 12         # 200-1000 subs
    SCAM_LARGE = 10         # > 1000 subs

    # High/suspicious thresholds
    HIGH_MICRO = 15
    HIGH_SMALL = 8
    HIGH_LARGE = 5

    # Dead audience
    DEAD = 0.3              # < 0.3% = dead audience
    LOW = 1.0               # 0.3-1% = low engagement
    GOOD = 3.0              # 1-3% = good engagement


class DecayThresholds:
    """
    Views decay analysis thresholds. v15.1

    decay_ratio = avg_views_new / avg_views_old
    - <1.0: Old posts have more views (normal - accumulation effect)
    - ~1.0: Suspiciously uniform (auto-manipulation)
    - >1.0: New posts have more views (viral or fresh manipulation)
    """

    # GREEN zone: Healthy organic
    ORGANIC_MIN = 0.3       # 30% of old = still organic
    ORGANIC_MAX = 0.95      # 95% of old = healthy

    # GREEN zone: Viral growth
    VIRAL_MIN = 1.05
    VIRAL_MAX = 2.0

    # RED zone: Bot wall (too uniform)
    BOT_WALL_MIN = 0.98
    BOT_WALL_MAX = 1.02

    # RED zone: Budget cliff (manipulation stopped)
    BUDGET_CLIFF = 0.2      # New = 20% of old

    # Moderate growth zone
    MODERATE_MIN = 0.95
    MODERATE_MAX = 1.05

    # Small gap zone
    SMALL_GAP_MIN = 0.2
    SMALL_GAP_MAX = 0.3


class StabilityThresholds:
    """
    Reaction stability scoring thresholds.

    Based on CV of reactions and top post concentration.
    """

    CV_BOT = 15             # CV < 15% = bots (too uniform)
    CV_HEALTHY_MAX = 80     # CV > 80% = chaos (too much variation)

    # Top post concentration
    CONCENTRATION_CRITICAL = 0.60   # >60% in one post = manipulation
    CONCENTRATION_HEALTHY = 0.40    # <40% = healthy distribution


class SourceDiversityThresholds:
    """
    Source diversity scoring thresholds.

    Based on max share from single source and repost ratio.
    """

    ORIGINAL_CONTENT = 0.10     # <10% reposts = original content
    SATELLITE = 0.70            # >70% from one source = satellite
    DEPENDENT = 0.50            # >50% from one source = dependent


class ForwardRateThresholds:
    """
    Forward rate scoring thresholds by channel size.

    forward_rate = avg_forwards / avg_views * 100
    """

    SCAM_MAX = 15               # >15% = definitely manipulation

    # Large channels (>50k subs)
    LARGE_VIRAL = 1.5
    LARGE_EXCELLENT = 0.7
    LARGE_GOOD = 0.3
    LARGE_MEDIUM = 0.1

    # Medium channels (5k-50k subs)
    MEDIUM_VIRAL = 2.0
    MEDIUM_EXCELLENT = 1.0
    MEDIUM_GOOD = 0.5
    MEDIUM_MEDIUM = 0.2

    # Small channels (<5k subs)
    SMALL_VIRAL = 3.0
    SMALL_EXCELLENT = 1.5
    SMALL_GOOD = 0.5
    SMALL_MEDIUM = 0.1

    MINIMAL = 0.05              # Minimum for any points


class AgeThresholds:
    """
    Channel age scoring thresholds (in days).

    Older channel = more stable audience.
    """

    NEWBORN = 90        # < 3 months
    YOUNG = 180         # 3-6 months
    MATURE = 365        # 6-12 months
    ESTABLISHED = 730   # 1-2 years
    # > 730 days = veteran


class RegularityThresholds:
    """
    Posting regularity thresholds. v48.0

    posts_per_day ideal range: 1-5 posts/day
    """

    DEAD = 0.14         # < 1 post per week = dead channel
    RARE = 0.5          # 3-4 posts per week
    ALMOST_DAILY = 1.0  # almost every day
    IDEAL_MAX = 5.0     # 1-5 per day = ideal
    ACTIVE = 10.0       # 5-10 per day = active
    HEAVY = 20.0        # 10-20 per day = heavy posting
    # > 20 = spam


class ERTrendThresholds:
    """
    Engagement Rate trend thresholds. v48.0

    Based on er_trend = old_er / new_er ratio.
    """

    GROWING = 1.1       # trend >= 1.1 = growing
    STABLE_MIN = 0.9    # 0.9 <= trend < 1.1 = stable
    STABLE_MAX = 1.1
    DECLINING_MIN = 0.7 # 0.7 <= trend < 0.9 = declining
    # trend < 0.7 = dying


class TrustMultipliers:
    """
    Trust factor penalty multipliers. v13.0

    Trust Factor (0.0-1.0) multiplies Raw Score.
    Multiple penalties are multiplied together (not min).
    """

    # Forensics-based penalties
    ID_CLUSTERING_FATALITY = 0.0    # Bot farm = zero score
    ID_CLUSTERING_SUSPICIOUS = 0.5  # Suspicious clustering
    GEO_DC_MISMATCH = 0.2           # Foreign datacenters
    PREMIUM_ZERO = 0.8              # 0% premium users

    # Content-based penalties
    HIDDEN_COMMENTS = 0.85          # v38.4: softened from 0.7

    # Conviction-based penalties
    CONVICTION_CRITICAL = 0.3       # Conviction >= 70
    CONVICTION_HIGH = 0.6           # Conviction >= 50

    # v15.0: Spam posting penalties
    SPAM_POSTING_SPAM = 0.55        # >20 posts/day
    SPAM_POSTING_HEAVY = 0.75       # 12-20 posts/day
    SPAM_POSTING_ACTIVE = 0.90      # 6-12 posts/day

    # v15.0: Private links penalties
    PRIVATE_100 = 0.25              # 100% private links
    PRIVATE_80 = 0.35               # >80% private links
    PRIVATE_60 = 0.50               # >60% private links
    PRIVATE_CRYPTO_COMBO = 0.45     # CRYPTO + >40% private
    PRIVATE_HIDDEN_COMBO = 0.40     # >50% + comments disabled


class StatisticalTrustThresholds:
    """
    Statistical trust penalty thresholds. v13.5
    """

    # v47.4: HOLLOW VIEWS - unified threshold
    HOLLOW_REACH = 300              # Reach > 300% = guilty until proven
    HOLLOW_VIRALITY_ALIBI = 3.0     # forward_rate > 3% = virality alibi
    HOLLOW_COMMENTS_TRUST = 70      # comment_trust >= 70 = comments alibi

    # Comments alibi thresholds by size
    HOLLOW_COMMENTS_MICRO = 0.5     # < 200 subs
    HOLLOW_COMMENTS_SMALL = 1.0     # 200-1000 subs
    HOLLOW_COMMENTS_MEDIUM = 2.0    # 1000-5000 subs
    HOLLOW_COMMENTS_LARGE = 5.0     # > 5000 subs

    # ZOMBIE ENGAGEMENT thresholds
    ZOMBIE_REACH = 50               # Reach > 50%
    ZOMBIE_REACTION = 0.1           # Reaction < 0.1%

    # SATELLITE thresholds
    SATELLITE_SOURCE_SHARE = 50     # >50% from one source
    SATELLITE_AVG_COMMENTS = 1      # avg_comments < 1 = dead


class GhostProtocolThresholds:
    """
    Ghost protocol thresholds for dead audience detection. v15.0

    Based on online_count / members ratio.
    """

    # GHOST CHANNEL - dead audience (large channel with ~0 online)
    GHOST_MEMBERS = 20000           # 20k+ subs
    GHOST_ONLINE_RATIO = 0.1        # < 0.1% online

    # ZOMBIE AUDIENCE - suspiciously low online (medium channel)
    ZOMBIE_MEMBERS = 5000           # 5k+ subs
    ZOMBIE_ONLINE_RATIO = 0.3       # < 0.3% online

    # MEMBER DISCREPANCY - Telegram knows about manipulation
    DISCREPANCY_RATIO = 10          # >10% difference


class DecayTrustThresholds:
    """
    Decay-based trust penalty thresholds. v15.1
    """

    # BUDGET CLIFF - manipulation money ran out
    BUDGET_CLIFF_RATIO = 0.2        # new = 20% of old

    # ZOMBIE COMBO - dying ER + stable views
    ZOMBIE_DECAY_MIN = 0.7
    ZOMBIE_DECAY_MAX = 1.3


class VerdictThresholds:
    """
    Final score verdict boundaries. v68.1

    Based on Final Score = Raw Score * Trust Factor
    """

    EXCELLENT = 75      # >= 75: EXCELLENT
    GOOD = 55           # >= 55: GOOD
    MEDIUM = 40         # >= 40: MEDIUM
    HIGH_RISK = 25      # >= 25: HIGH_RISK
    # < 25: SCAM


class ConvictionThresholds:
    """
    Conviction score thresholds for trust penalties.
    """

    CRITICAL = 70       # >= 70: critical penalty (×0.3)
    HIGH = 50           # >= 50: high penalty (×0.6)


class FloatingWeightsConfig:
    """
    Floating weights configuration. v48.0

    When comments/reactions are disabled, their points are redistributed.
    """

    # Base weights
    BASE_COMMENTS = 15
    BASE_REACTIONS = 8
    BASE_FORWARD = 15

    # Without comments
    NO_COMMENTS_REACTIONS = 13      # 8 + 5
    NO_COMMENTS_FORWARD = 25        # 15 + 10

    # Without reactions
    NO_REACTIONS_COMMENTS = 20      # 15 + 5
    NO_REACTIONS_FORWARD = 18       # 15 + 3

    # Without both
    NO_BOTH_FORWARD = 38            # All 38 points


class AdaptiveWeightsConfig:
    """
    Adaptive weights configuration. v12.0

    Different scoring modes based on forensics availability.
    """

    MIN_USERS_FOR_FORENSICS = 10    # Need at least 10 users for forensics


class NeighborRatioThresholds:
    """
    ID clustering neighbor ratio thresholds.
    """

    SUSPICIOUS = 0.15   # >15% neighbors = suspicious clustering
    FATALITY = 0.30     # >30% neighbors = bot farm (FATALITY)


# Point multipliers for scoring functions
class PointMultipliers:
    """
    Common point multipliers used across scoring functions.
    """

    FULL = 1.0
    HIGH = 0.8
    GOOD = 0.7
    MEDIUM = 0.6
    HALF = 0.5
    LOW = 0.4
    VERY_LOW = 0.3
    MINIMAL = 0.2
    TINY = 0.15


class SpamPostingTiers:
    """
    Category-specific posting thresholds. v78.0

    Tiers based on natural posting frequency per category.
    Thresholds: (active, heavy, spam) posts per day.
    """

    HIGH_FREQUENCY = (20, 40, 60)    # NEWS, ADULT
    MEDIUM_FREQUENCY = (10, 18, 30)  # ENTERTAINMENT, AI_ML, FINANCE, EDUCATION
    LOW_FREQUENCY = (6, 12, 20)      # CRYPTO, LIFESTYLE, BUSINESS, TECH, HEALTH
    MINIMAL = (4, 8, 15)             # RETAIL, TRAVEL, REAL_ESTATE, BEAUTY, GAMBLING

    CATEGORY_TIERS = {
        'NEWS': HIGH_FREQUENCY,
        'ADULT': HIGH_FREQUENCY,
        'ENTERTAINMENT': MEDIUM_FREQUENCY,
        'AI_ML': MEDIUM_FREQUENCY,
        'FINANCE': MEDIUM_FREQUENCY,
        'EDUCATION': MEDIUM_FREQUENCY,
        'CRYPTO': LOW_FREQUENCY,
        'LIFESTYLE': LOW_FREQUENCY,
        'BUSINESS': LOW_FREQUENCY,
        'TECH': LOW_FREQUENCY,
        'HEALTH': LOW_FREQUENCY,
        'RETAIL': MINIMAL,
        'TRAVEL': MINIMAL,
        'REAL_ESTATE': MINIMAL,
        'BEAUTY': MINIMAL,
        'GAMBLING': MINIMAL,
    }

    DEFAULT = LOW_FREQUENCY
