"""
Regression tests for scorer.py - freezes current behavior BEFORE refactoring.

These tests capture the exact current behavior of the scoring system to detect
any unintended changes during refactoring. Each test is focused on a single
behavior aspect.

Testing Patterns:
- Factory pattern for test data
- One assertion per test where possible
- Test behavior, not implementation
"""
import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any, Optional, List


# ============================================================================
# FACTORIES: Mock Data Creation
# ============================================================================

@dataclass
class MockReactionCount:
    """Factory: single reaction with count."""
    count: int
    emoji: str = "thumbsup"

    @property
    def reaction(self):
        return self


@dataclass
class MockReactions:
    """Factory: container for message reactions."""
    reactions: List[MockReactionCount] = field(default_factory=list)


@dataclass
class MockReplies:
    """Factory: comment replies container."""
    replies: int = 0
    comments: bool = True


@dataclass
class MockLinkedChat:
    """Factory: linked discussion chat."""
    id: int = 987654321
    title: str = "Discussion"


@dataclass
class MockMessage:
    """Factory: Telegram message object."""
    id: int
    views: int
    forwards: int = 0
    text: str = ""
    message: str = ""
    date: datetime = None
    reactions: Optional[MockReactions] = None
    replies: Optional[MockReplies] = None
    forward_from_chat: Any = None

    def __post_init__(self):
        if self.date is None:
            self.date = datetime.now(timezone.utc) - timedelta(hours=self.id * 4)


@dataclass
class MockChat:
    """Factory: Telegram channel object."""
    id: int = 123456789
    username: str = "test_channel"
    title: str = "Test Channel"
    members_count: int = 5000
    participants_count: int = 5000
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    linked_chat: Optional[MockLinkedChat] = None
    date: datetime = None

    def __post_init__(self):
        if self.date is None:
            self.date = datetime.now(timezone.utc) - timedelta(days=400)


@dataclass
class MockUser:
    """Factory: Telegram user for forensics."""
    id: int
    is_premium: bool = False
    is_scam: bool = False
    is_fake: bool = False
    is_deleted: bool = False
    is_bot: bool = False
    username: Optional[str] = None
    first_name: str = "User"
    dc_id: int = 2  # Europe/Russia DC
    photo: Any = None


# ============================================================================
# FACTORY FUNCTIONS: Create Test Fixtures
# ============================================================================

def create_messages(
    count: int = 20,
    base_views: int = 1000,
    cv_target: float = 40.0,
    reaction_rate_pct: float = 2.5,
    forward_rate_pct: float = 1.0,
    include_reactions: bool = True,
    days_span: int = 30
) -> List[MockMessage]:
    """
    Factory: creates list of messages with controlled characteristics.

    Uses deterministic variation to ensure reproducible tests.
    """
    import random
    random.seed(42)  # Reproducibility

    messages = []
    std = base_views * (cv_target / 100)

    for i in range(count):
        views = max(10, int(random.gauss(base_views, std)))
        forwards = int(views * forward_rate_pct / 100)

        reactions = None
        if include_reactions:
            total = max(1, int(views * reaction_rate_pct / 100))
            reactions = MockReactions(reactions=[
                MockReactionCount(count=int(total * 0.6), emoji="thumbsup"),
                MockReactionCount(count=int(total * 0.25), emoji="fire"),
                MockReactionCount(count=int(total * 0.15), emoji="heart"),
            ])

        post_date = datetime.now(timezone.utc) - timedelta(days=days_span * i / count)

        messages.append(MockMessage(
            id=i + 1,
            views=views,
            forwards=forwards,
            reactions=reactions,
            date=post_date,
            text=f"Test post #{i + 1}"
        ))

    return messages


def create_users_normal(count: int = 30, premium_pct: float = 3.0) -> List[MockUser]:
    """Factory: creates normal user distribution (non-bot)."""
    import random
    random.seed(42)

    users = []
    premium_count = int(count * premium_pct / 100)

    for i in range(count):
        user_id = 100000000 + random.randint(10000000, 999999999)
        users.append(MockUser(
            id=user_id,
            is_premium=(i < premium_count),
            dc_id=random.choice([2, 4])  # Russian DCs
        ))

    return users


def create_users_bot_farm(count: int = 30) -> List[MockUser]:
    """Factory: creates bot farm user pattern (clustered IDs)."""
    base_id = 500000000
    return [
        MockUser(
            id=base_id + i * 50,  # Clustered IDs
            is_premium=False,
            dc_id=1  # Foreign DC
        )
        for i in range(count)
    ]


def create_known_channel_fixture():
    """
    Factory: creates a known channel with predictable characteristics.

    This fixture represents a "typical good channel" and is used
    to detect scoring regressions.
    """
    chat = MockChat(
        id=123456789,
        username="known_channel",
        members_count=5000,
        participants_count=5000,
        is_verified=False,
        linked_chat=MockLinkedChat(id=987654321),
        date=datetime.now(timezone.utc) - timedelta(days=730)  # 2 years old
    )

    # 30% reach, 40% CV, standard engagement
    messages = create_messages(
        count=30,
        base_views=1500,  # 30% of 5000
        cv_target=40.0,
        reaction_rate_pct=2.5,
        forward_rate_pct=1.0
    )

    comments_data = {
        'enabled': True,
        'avg_comments': 2.5,
        'total_comments': 75
    }

    users = create_users_normal(count=30, premium_pct=5.0)

    channel_health = {
        'online_count': 150,  # 3% online
        'participants_count': 5000
    }

    return chat, messages, comments_data, users, channel_health


# ============================================================================
# TEST 1: calculate_final_score with known channel
# ============================================================================

class TestCalculateFinalScoreKnownChannel:
    """Regression tests for calculate_final_score with known fixture."""

    def test_returns_dict_with_required_keys(self):
        """Result contains all required top-level keys."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        required_keys = [
            'channel', 'members', 'score', 'verdict', 'raw_score',
            'trust_factor', 'breakdown', 'categories', 'flags'
        ]
        for key in required_keys:
            assert key in result, f"Missing required key: {key}"

    def test_score_is_in_valid_range(self):
        """Final score is between 0 and 100."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        assert 0 <= result['score'] <= 100

    def test_raw_score_is_in_valid_range(self):
        """Raw score is between 0 and 100."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        assert 0 <= result['raw_score'] <= 100

    def test_trust_factor_is_in_valid_range(self):
        """Trust factor is between 0.0 and 1.0."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        assert 0.0 <= result['trust_factor'] <= 1.0

    def test_known_channel_verdict_is_positive(self):
        """Known good channel gets GOOD or better verdict."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        assert result['verdict'] in ['EXCELLENT', 'GOOD', 'MEDIUM']

    def test_known_channel_score_above_threshold(self):
        """Known good channel scores above MEDIUM threshold (40+)."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        assert result['score'] >= 40, f"Expected score >= 40, got {result['score']}"

    def test_breakdown_contains_all_metrics(self):
        """Breakdown contains all scoring metrics."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        expected_metrics = [
            'cv_views', 'reach', 'forward_rate', 'regularity',
            'comments', 'reaction_rate', 'reaction_stability', 'er_trend',
            'verified', 'age', 'premium', 'source_diversity'
        ]
        for metric in expected_metrics:
            assert metric in result['breakdown'], f"Missing metric: {metric}"

    def test_categories_sum_equals_raw_score(self):
        """Sum of category scores equals raw_score."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        categories_sum = sum(cat['score'] for cat in result['categories'].values())
        assert categories_sum == result['raw_score']


# ============================================================================
# TEST 2: Trust Factor with Forensics
# ============================================================================

class TestTrustFactorWithForensics:
    """Regression tests for trust factor calculation with forensics data."""

    def test_healthy_users_high_trust(self):
        """Healthy user distribution results in high trust factor."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, _, health = create_known_channel_fixture()
        healthy_users = create_users_normal(count=30, premium_pct=5.0)

        result = calculate_final_score(chat, messages, comments_data, healthy_users, health)

        assert result['trust_factor'] >= 0.7, f"Expected trust >= 0.7, got {result['trust_factor']}"

    def test_bot_farm_triggers_fatality(self):
        """Bot farm users trigger FATALITY (trust = 0)."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, _, health = create_known_channel_fixture()
        bot_users = create_users_bot_farm(count=30)

        result = calculate_final_score(chat, messages, comments_data, bot_users, health)

        assert result['verdict'] == 'SCAM'
        assert result['is_scam'] is True

    def test_premium_users_improve_score(self):
        """High premium ratio improves reputation score."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, _, health = create_known_channel_fixture()
        premium_users = create_users_normal(count=30, premium_pct=10.0)

        result = calculate_final_score(chat, messages, comments_data, premium_users, health)

        assert result['breakdown']['premium']['points'] > 0

    def test_no_users_still_calculates(self):
        """Scoring works without user data (hardcore mode)."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, _, health = create_known_channel_fixture()

        result = calculate_final_score(chat, messages, comments_data, users=[], channel_health=health)

        assert result['scoring_mode'] == 'hardcore'
        assert result['score'] >= 0

    def test_hidden_comments_penalty_applied(self):
        """Hidden comments reduces trust factor."""
        from scanner.scorer import calculate_trust_factor

        trust_with_comments, _ = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0
        )

        trust_without_comments, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=False,
            conviction_score=0
        )

        assert trust_without_comments < trust_with_comments
        assert 'hidden_comments' in details

    def test_high_conviction_penalty_applied(self):
        """High conviction score reduces trust factor to 0.3."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=75
        )

        assert trust <= 0.3
        assert 'conviction' in details
        assert details['conviction']['multiplier'] == 0.3


# ============================================================================
# TEST 3: Verdict Thresholds
# ============================================================================

class TestVerdictThresholds:
    """Regression tests for verdict threshold boundaries."""

    def test_excellent_threshold_at_75(self):
        """Score >= 75 gives EXCELLENT verdict."""
        from scanner.scorer import calculate_final_score

        # Create channel that should score high
        chat = MockChat(
            members_count=5000,
            linked_chat=MockLinkedChat(),
            date=datetime.now(timezone.utc) - timedelta(days=1000)
        )
        messages = create_messages(
            count=30, base_views=2000, cv_target=45.0,
            reaction_rate_pct=3.0, forward_rate_pct=2.0
        )
        comments_data = {'enabled': True, 'avg_comments': 5.0}
        users = create_users_normal(count=40, premium_pct=8.0)

        result = calculate_final_score(chat, messages, comments_data, users)

        if result['score'] >= 75:
            assert result['verdict'] == 'EXCELLENT'

    def test_good_threshold_at_55(self):
        """Score 55-74 gives GOOD verdict."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data, users, health = create_known_channel_fixture()
        result = calculate_final_score(chat, messages, comments_data, users, health)

        if 55 <= result['score'] < 75:
            assert result['verdict'] == 'GOOD'

    def test_medium_threshold_at_40(self):
        """Score 40-54 gives MEDIUM verdict."""
        from scanner.scorer import calculate_final_score

        chat = MockChat(
            members_count=3000,
            linked_chat=MockLinkedChat(),
            date=datetime.now(timezone.utc) - timedelta(days=200)
        )
        messages = create_messages(count=20, base_views=600, cv_target=30.0)
        comments_data = {'enabled': True, 'avg_comments': 1.0}

        result = calculate_final_score(chat, messages, comments_data)

        if 40 <= result['score'] < 55:
            assert result['verdict'] == 'MEDIUM'

    def test_high_risk_threshold_at_25(self):
        """Score 25-39 gives HIGH_RISK verdict."""
        from scanner.scorer import calculate_final_score

        chat = MockChat(
            members_count=5000,
            linked_chat=None,  # No comments
            date=datetime.now(timezone.utc) - timedelta(days=60)
        )
        messages = create_messages(
            count=15, base_views=200, cv_target=25.0,
            reaction_rate_pct=0.5
        )
        comments_data = {'enabled': False, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        if 25 <= result['score'] < 40:
            assert result['verdict'] == 'HIGH_RISK'

    def test_scam_threshold_below_25(self):
        """Score < 25 gives SCAM verdict."""
        from scanner.scorer import calculate_final_score

        chat = MockChat(
            members_count=10000,
            is_scam=True  # Telegram flagged
        )
        messages = create_messages(count=20)
        comments_data = {'enabled': True, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        assert result['verdict'] == 'SCAM'

    def test_new_channel_verdict_for_insufficient_data(self):
        """Channels with <10 posts or <100 members get NEW_CHANNEL."""
        from scanner.scorer import calculate_final_score

        chat = MockChat(
            members_count=50,  # < 100
            date=datetime.now(timezone.utc) - timedelta(days=7)
        )
        messages = create_messages(count=5)  # < 10
        comments_data = {'enabled': True, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        assert result['verdict'] == 'NEW_CHANNEL'


# ============================================================================
# TEST 4: RAW_WEIGHTS Applied Correctly
# ============================================================================

class TestRawWeightsApplied:
    """Regression tests verifying RAW_WEIGHTS are applied correctly."""

    def test_weights_sum_to_100(self):
        """Total of all RAW_WEIGHTS equals 100."""
        from scanner.scorer import RAW_WEIGHTS

        total = sum(
            weight
            for category in RAW_WEIGHTS.values()
            for weight in category.values()
        )

        assert total == 100, f"RAW_WEIGHTS sum is {total}, expected 100"

    def test_category_totals_match_weights(self):
        """CATEGORY_TOTALS matches sum of weights per category."""
        from scanner.scorer import RAW_WEIGHTS, CATEGORY_TOTALS

        for category, metrics in RAW_WEIGHTS.items():
            expected = sum(metrics.values())
            actual = CATEGORY_TOTALS[category]
            assert expected == actual, f"{category}: expected {expected}, got {actual}"

    def test_quality_category_is_42(self):
        """Quality category totals 42 points (v48.0)."""
        from scanner.scorer import CATEGORY_TOTALS

        assert CATEGORY_TOTALS['quality'] == 42

    def test_engagement_category_is_38(self):
        """Engagement category totals 38 points (v48.0)."""
        from scanner.scorer import CATEGORY_TOTALS

        assert CATEGORY_TOTALS['engagement'] == 38

    def test_reputation_category_is_20(self):
        """Reputation category totals 20 points."""
        from scanner.scorer import CATEGORY_TOTALS

        assert CATEGORY_TOTALS['reputation'] == 20

    def test_cv_views_max_is_12(self):
        """cv_views max points is 12 (v48.0)."""
        from scanner.scorer import RAW_WEIGHTS

        assert RAW_WEIGHTS['quality']['cv_views'] == 12

    def test_forward_rate_max_is_15(self):
        """forward_rate max points is 15 (v48.0)."""
        from scanner.scorer import RAW_WEIGHTS

        assert RAW_WEIGHTS['quality']['forward_rate'] == 15

    def test_comments_max_is_15(self):
        """comments max points is 15."""
        from scanner.scorer import RAW_WEIGHTS

        assert RAW_WEIGHTS['engagement']['comments'] == 15

    def test_er_trend_max_is_10(self):
        """er_trend max points is 10 (v48.0)."""
        from scanner.scorer import RAW_WEIGHTS

        assert RAW_WEIGHTS['engagement']['er_trend'] == 10


# ============================================================================
# TEST 5: Point Conversion Functions (Regression)
# ============================================================================

class TestPointConversionFunctions:
    """Regression tests for individual point conversion functions."""

    def test_cv_to_points_optimal_range(self):
        """CV 30-60% returns max points."""
        from scanner.scorer import cv_to_points, RAW_WEIGHTS

        max_pts = RAW_WEIGHTS['quality']['cv_views']

        assert cv_to_points(35) == max_pts
        assert cv_to_points(50) == max_pts
        assert cv_to_points(59) == max_pts

    def test_cv_to_points_too_flat(self):
        """CV < 10% returns 0 (bot signal)."""
        from scanner.scorer import cv_to_points

        assert cv_to_points(5) == 0
        assert cv_to_points(9) == 0

    def test_cv_to_points_extreme_high(self):
        """CV >= 100% returns 0 (wave manipulation)."""
        from scanner.scorer import cv_to_points

        assert cv_to_points(150) == 0
        assert cv_to_points(100) == 0

    def test_age_to_points_thresholds(self):
        """Age converts to points at correct thresholds."""
        from scanner.scorer import age_to_points, RAW_WEIGHTS

        max_pts = RAW_WEIGHTS['reputation']['age']

        assert age_to_points(30) == 0      # < 90 days
        assert age_to_points(100) == 1     # 90-180 days
        assert age_to_points(200) == 2     # 180-365 days
        assert age_to_points(500) == 4     # 365-730 days
        assert age_to_points(800) == max_pts  # > 730 days

    def test_decay_to_points_healthy_organic(self):
        """Decay ratio 0.3-0.95 is healthy organic (max points)."""
        from scanner.scorer import decay_to_points

        pts, info = decay_to_points(0.7)
        assert info['zone'] == 'healthy_organic'

    def test_decay_to_points_viral_growth(self):
        """Decay ratio 1.05-2.0 is viral growth (max points)."""
        from scanner.scorer import decay_to_points

        pts, info = decay_to_points(1.5)
        assert info['zone'] == 'viral_growth'

    def test_decay_to_points_bot_wall(self):
        """Decay ratio 0.98-1.02 is bot wall (penalty)."""
        from scanner.scorer import decay_to_points

        pts, info = decay_to_points(1.0)
        assert info['zone'] == 'bot_wall'
        assert pts < 5  # Penalty

    def test_decay_to_points_budget_cliff(self):
        """Decay ratio < 0.2 is budget cliff (0 points)."""
        from scanner.scorer import decay_to_points

        pts, info = decay_to_points(0.15)
        assert info['zone'] == 'budget_cliff'
        assert pts == 0


# ============================================================================
# TEST 6: Floating Weights System
# ============================================================================

class TestFloatingWeights:
    """Regression tests for floating weights redistribution."""

    def test_all_enabled_standard_weights(self):
        """All features enabled uses standard weights."""
        from scanner.scorer import calculate_floating_weights

        weights = calculate_floating_weights(comments_enabled=True, reactions_enabled=True)

        assert weights['comments_max'] == 15
        assert weights['reaction_rate_max'] == 8
        assert weights['forward_rate_max'] == 15

    def test_comments_disabled_redistributes(self):
        """Disabled comments redistributes 15 points."""
        from scanner.scorer import calculate_floating_weights

        weights = calculate_floating_weights(comments_enabled=False, reactions_enabled=True)

        assert weights['comments_max'] == 0
        assert weights['reaction_rate_max'] == 13  # 8 + 5
        assert weights['forward_rate_max'] == 25   # 15 + 10

    def test_reactions_disabled_redistributes(self):
        """Disabled reactions redistributes 8 points."""
        from scanner.scorer import calculate_floating_weights

        weights = calculate_floating_weights(comments_enabled=True, reactions_enabled=False)

        assert weights['comments_max'] == 20       # 15 + 5
        assert weights['reaction_rate_max'] == 0
        assert weights['forward_rate_max'] == 18   # 15 + 3

    def test_both_disabled_all_to_forward(self):
        """Both disabled puts all 38 points in forward_rate."""
        from scanner.scorer import calculate_floating_weights

        weights = calculate_floating_weights(comments_enabled=False, reactions_enabled=False)

        assert weights['comments_max'] == 0
        assert weights['reaction_rate_max'] == 0
        assert weights['forward_rate_max'] == 38

    def test_floating_weights_sum_preserved(self):
        """Total points preserved regardless of configuration."""
        from scanner.scorer import calculate_floating_weights

        configs = [
            (True, True),
            (True, False),
            (False, True),
            (False, False)
        ]

        for comments, reactions in configs:
            weights = calculate_floating_weights(comments, reactions)
            total = sum(weights.values())
            assert total == 38, f"Total {total} != 38 for comments={comments}, reactions={reactions}"


# ============================================================================
# TEST 7: Trust Factor Penalties
# ============================================================================

class TestTrustFactorPenalties:
    """Regression tests for specific trust factor penalties."""

    def test_ghost_channel_penalty(self):
        """Ghost channel (20k+ subs, <0.1% online) gets ×0.5."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            members=25000,
            online_count=10  # 0.04%
        )

        assert 'ghost_channel' in details
        assert details['ghost_channel']['multiplier'] == 0.5

    def test_zombie_audience_penalty(self):
        """Zombie audience (5k+ subs, <0.3% online) gets ×0.7."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            members=10000,
            online_count=20  # 0.2%
        )

        assert 'zombie_audience' in details
        assert details['zombie_audience']['multiplier'] == 0.7

    def test_hollow_views_penalty(self):
        """Hollow views (reach > 300% without alibi) gets ×0.6."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            reach=500,
            forward_rate=0.5,  # No virality alibi
            members=1000,
            avg_comments=0.1,  # No comments alibi
            comment_trust=0
        )

        assert 'hollow_views' in details
        assert details['hollow_views']['multiplier'] == 0.6

    def test_hidden_comments_penalty_value(self):
        """Hidden comments penalty is ×0.85."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=False,
            conviction_score=0
        )

        assert details['hidden_comments']['multiplier'] == 0.85

    def test_budget_cliff_penalty(self):
        """Budget cliff (decay < 0.2) gets ×0.7."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            decay_ratio=0.15
        )

        assert 'budget_cliff' in details
        assert details['budget_cliff']['multiplier'] == 0.7

    def test_trust_multipliers_compound(self):
        """Multiple penalties multiply together (v68.1)."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=False,  # ×0.85
            conviction_score=0,
            members=10000,
            online_count=20  # ×0.7 zombie
        )

        # 0.85 × 0.7 = 0.595
        expected = 0.85 * 0.7
        assert abs(trust - expected) < 0.01, f"Expected ~{expected}, got {trust}"


# ============================================================================
# TEST 8: TRUST_FACTORS Constants
# ============================================================================

class TestTrustFactorsConstants:
    """Regression tests for TRUST_FACTORS constant values."""

    def test_id_clustering_fatality_is_zero(self):
        """ID clustering FATALITY multiplier is 0.0."""
        from scanner.scorer import TRUST_FACTORS

        assert TRUST_FACTORS['id_clustering_fatality'] == 0.0

    def test_id_clustering_suspicious_is_half(self):
        """ID clustering suspicious multiplier is 0.5."""
        from scanner.scorer import TRUST_FACTORS

        assert TRUST_FACTORS['id_clustering_suspicious'] == 0.5

    def test_geo_dc_mismatch_is_severe(self):
        """Geo/DC mismatch multiplier is 0.2."""
        from scanner.scorer import TRUST_FACTORS

        assert TRUST_FACTORS['geo_dc_mismatch'] == 0.2

    def test_conviction_critical_value(self):
        """Critical conviction (>=70) multiplier is 0.3."""
        from scanner.scorer import TRUST_FACTORS

        assert TRUST_FACTORS['conviction_critical'] == 0.3

    def test_conviction_high_value(self):
        """High conviction (>=50) multiplier is 0.6."""
        from scanner.scorer import TRUST_FACTORS

        assert TRUST_FACTORS['conviction_high'] == 0.6


# ============================================================================
# TEST 9: Stability Scoring (v52.2)
# ============================================================================

class TestStabilityScoring:
    """Regression tests for reaction stability scoring."""

    def test_stability_to_points_healthy(self):
        """Healthy stability (CV 15-80%, concentration <40%) gets max points."""
        from scanner.scorer import stability_to_points

        data = {'stability_cv': 45.0, 'top_concentration': 0.25}
        pts = stability_to_points(data)

        assert pts == 5  # Max

    def test_stability_to_points_too_flat(self):
        """Too flat stability (CV <15%) gets 1 point."""
        from scanner.scorer import stability_to_points

        data = {'stability_cv': 10.0, 'top_concentration': 0.20}
        pts = stability_to_points(data)

        assert pts == 1

    def test_stability_to_points_extreme_concentration(self):
        """Extreme concentration (>60%) gets 1 point."""
        from scanner.scorer import stability_to_points

        data = {'stability_cv': 50.0, 'top_concentration': 0.70}
        pts = stability_to_points(data)

        assert pts == 1


# ============================================================================
# TEST 10: Regularity Scoring (v48.0)
# ============================================================================

class TestRegularityScoring:
    """Regression tests for posting regularity scoring."""

    def test_regularity_ideal_range(self):
        """1-5 posts per day gets max points."""
        from scanner.scorer import regularity_to_points

        assert regularity_to_points(1.0) == 7
        assert regularity_to_points(3.0) == 7
        assert regularity_to_points(5.0) == 7

    def test_regularity_dead_channel(self):
        """< 1 post per week gets 0 points."""
        from scanner.scorer import regularity_to_points

        assert regularity_to_points(0.1) == 0

    def test_regularity_spam(self):
        """> 20 posts per day gets minimal points."""
        from scanner.scorer import regularity_to_points

        pts = regularity_to_points(25.0)
        assert pts <= 2
