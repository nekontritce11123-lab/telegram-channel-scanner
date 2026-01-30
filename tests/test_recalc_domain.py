"""
Tests for recalc domain layer - trust factor, score calculation, and verdict logic.

Focuses on:
- TrustCalculator: calculate_trust_factor() penalties and multipliers
- ScoreCalculator: recalculate_score_from_breakdown() raw score computation
- Verdicts: threshold-based verdict determination

Uses factory pattern for test data creation.
"""
import pytest
from dataclasses import dataclass
from typing import Optional, Any


# =============================================================================
# MOCK CLASSES FOR FORENSICS
# =============================================================================

@dataclass
class MockForensicsResult:
    """Mock forensics result for trust factor testing."""
    status: str = 'complete'
    users_analyzed: int = 30
    id_clustering: dict = None
    geo_dc_check: dict = None
    premium_density: dict = None
    hidden_flags: dict = None

    def __post_init__(self):
        if self.id_clustering is None:
            self.id_clustering = {
                'neighbor_ratio': 0.05,
                'fatality': False,
                'suspicious': False
            }
        if self.geo_dc_check is None:
            self.geo_dc_check = {
                'triggered': False,
                'foreign_ratio': 0.1
            }
        if self.premium_density is None:
            self.premium_density = {
                'premium_ratio': 0.03,
                'premium_count': 1,
                'total_users': 30
            }
        if self.hidden_flags is None:
            self.hidden_flags = {}


# =============================================================================
# FACTORY FUNCTIONS FOR TEST DATA
# =============================================================================

def get_mock_forensics(**overrides) -> MockForensicsResult:
    """
    Create mock forensics result with sensible defaults.

    Defaults represent a healthy channel with:
    - Low neighbor ratio (5%)
    - No fatality or suspicious flags
    - Low foreign DC ratio (10%)
    - 3% premium users
    """
    defaults = {
        'status': 'complete',
        'users_analyzed': 30,
        'id_clustering': {
            'neighbor_ratio': 0.05,
            'fatality': False,
            'suspicious': False
        },
        'geo_dc_check': {
            'triggered': False,
            'foreign_ratio': 0.1
        },
        'premium_density': {
            'premium_ratio': 0.03,
            'premium_count': 1,
            'total_users': 30
        },
        'hidden_flags': {}
    }

    # Apply overrides
    for key, value in overrides.items():
        if key in defaults and isinstance(defaults[key], dict) and isinstance(value, dict):
            defaults[key].update(value)
        else:
            defaults[key] = value

    return MockForensicsResult(**defaults)


def get_mock_breakdown(**overrides) -> dict:
    """
    Create mock breakdown dict for score recalculation.

    Defaults represent a healthy channel with:
    - CV views: 40% (optimal range)
    - Reach: 30% (good)
    - Forward rate: 1% (good)
    - Reaction rate: 2% (healthy engagement)
    - Comments enabled with avg 2.5
    """
    defaults = {
        'cv_views': {'value': 40.0, 'points': 12, 'max': 12},
        'reach': {'value': 30.0, 'points': 8, 'max': 8},
        'forward_rate': {'value': 1.0, 'points': 12, 'max': 15},
        'regularity': {'value': 2.0, 'points': 7, 'max': 7},  # 2 posts/day
        'views_decay': {'value': 0.7, 'points': 0, 'max': 0, 'zone': 'healthy_organic'},
        'comments': {'value': 'enabled (avg 2.5)', 'points': 10, 'max': 15, 'avg': 2.5},
        'reaction_rate': {'value': 2.0, 'points': 6, 'max': 8},
        'reaction_stability': {'value': 45.0, 'top_concentration': 0.25, 'points': 5, 'max': 5},
        'er_trend': {'status': 'stable', 'er_trend': 0.95, 'points': 7, 'max': 10},
        'verified': {'value': False, 'points': 0, 'max': 0},
        'age': {'value': 400, 'points': 4, 'max': 7},  # ~1 year
        'premium': {'value': 3.0, 'ratio': 0.03, 'count': 1, 'points': 4, 'max': 7},
        'source_diversity': {'value': 0.8, 'repost_ratio': 0.1, 'points': 6, 'max': 6},
        'comments_enabled': True,
        'reactions_enabled': True,
        'trust_details': {}
    }
    defaults.update(overrides)
    return defaults


def get_mock_er_trend_data(**overrides) -> dict:
    """Create mock ER trend data."""
    defaults = {
        'status': 'stable',
        'er_trend': 0.95,
        'er_new': 2.5,
        'er_old': 2.6,
        'posts_new': 10,
        'posts_old': 10
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# TRUST CALCULATOR TESTS
# =============================================================================

class TestTrustFactorNoPenalties:
    """Tests for trust factor calculation with no penalties."""

    def test_trust_factor_no_penalties(self):
        """Trust factor should return 1.0 when no penalties apply."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0
        )

        assert trust == 1.0, f"Expected 1.0 with no penalties, got {trust}"
        assert details == {}, "Details should be empty with no penalties"

    def test_trust_factor_healthy_forensics(self):
        """Healthy forensics should not reduce trust."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics()

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        # No penalties should apply for healthy forensics
        assert trust == 1.0, f"Healthy forensics should give trust 1.0, got {trust}"

    def test_trust_factor_with_healthy_metrics(self):
        """Full healthy metrics should return trust 1.0."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics()

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0,
            reach=30.0,
            forward_rate=1.0,
            reaction_rate=2.0,
            source_share=20.0,
            members=5000,
            online_count=150,  # 3% online
            participants_count=5000,
            decay_ratio=0.7,
            cv_views=40.0,
            avg_comments=2.5
        )

        assert trust == 1.0, f"Healthy metrics should give trust 1.0, got {trust}"


class TestTrustFactorBotPenalty:
    """Tests for bot-related trust penalties."""

    def test_trust_factor_id_clustering_suspicious(self):
        """ID clustering suspicious (>15%) should reduce trust to 0.5."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            id_clustering={
                'neighbor_ratio': 0.20,  # >15%
                'fatality': False,
                'suspicious': True
            }
        )

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert 'id_clustering' in details
        assert details['id_clustering']['multiplier'] == 0.5
        assert trust == 0.5

    def test_trust_factor_zero_premium_penalty(self):
        """0% premium users should apply 0.8 penalty."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            premium_density={
                'premium_ratio': 0,
                'premium_count': 0,
                'total_users': 30
            }
        )

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert 'premium' in details
        assert details['premium']['multiplier'] == 0.8
        assert trust == 0.8


class TestTrustFactorIDClusteringFatality:
    """Tests for ID clustering FATALITY (bot farm detection)."""

    def test_trust_factor_id_clustering_fatality(self):
        """ID clustering FATALITY (>30%) should return 0.0 (floored to 0.1)."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            id_clustering={
                'neighbor_ratio': 0.35,  # >30%
                'fatality': True,
                'suspicious': True
            }
        )

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert 'id_clustering' in details
        assert details['id_clustering']['multiplier'] == 0.0
        # Result should be floored to 0.1
        assert trust == 0.1, f"FATALITY should floor to 0.1, got {trust}"


class TestTrustFactorGeoDcMismatch:
    """Tests for Geo/DC mismatch penalty."""

    def test_trust_factor_geo_dc_mismatch(self):
        """Geo/DC mismatch (>75% foreign DC) should apply 0.2 penalty."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            geo_dc_check={
                'triggered': True,
                'foreign_ratio': 0.80  # >75%
            }
        )

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert 'geo_dc' in details
        assert details['geo_dc']['multiplier'] == 0.2
        assert trust == 0.2

    def test_trust_factor_geo_dc_no_trigger(self):
        """Low foreign DC ratio should not trigger penalty."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            geo_dc_check={
                'triggered': False,
                'foreign_ratio': 0.20  # Acceptable
            }
        )

        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert 'geo_dc' not in details
        assert trust == 1.0


class TestTrustFactorMultiplePenalties:
    """Tests for multiple penalties multiplied together."""

    def test_trust_factor_multiple_penalties(self):
        """Multiple penalties should multiply, not use min()."""
        from scanner.scorer import calculate_trust_factor

        # Hidden comments (0.85) + high conviction (0.6)
        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=False,  # 0.85 penalty
            conviction_score=55      # 0.6 penalty
        )

        assert 'hidden_comments' in details
        assert 'conviction' in details
        expected = 0.85 * 0.6  # = 0.51
        assert abs(trust - expected) < 0.01, f"Expected {expected}, got {trust}"

    def test_trust_factor_three_penalties_multiply(self):
        """Three penalties should all multiply together."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            premium_density={
                'premium_ratio': 0,
                'premium_count': 0,
                'total_users': 30
            }
        )

        # Premium zero (0.8) + Hidden comments (0.85) + High conviction (0.6)
        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=False,  # 0.85
            conviction_score=55      # 0.6
        )

        # 0.8 * 0.85 * 0.6 = 0.408
        expected = 0.8 * 0.85 * 0.6
        assert abs(trust - expected) < 0.01, f"Expected {expected:.3f}, got {trust}"


class TestTrustFactorMinimumFloor:
    """Tests for trust factor minimum floor (0.1)."""

    def test_trust_factor_minimum_floor(self):
        """Trust factor should not go below 0.1."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            id_clustering={
                'neighbor_ratio': 0.35,
                'fatality': True,
                'suspicious': True
            }
        )

        # FATALITY gives 0.0 multiplier
        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert trust >= 0.1, f"Trust factor should not go below 0.1, got {trust}"

    def test_trust_factor_extreme_penalties_floored(self):
        """Multiple extreme penalties should floor at 0.1."""
        from scanner.scorer import calculate_trust_factor

        forensics = get_mock_forensics(
            id_clustering={
                'neighbor_ratio': 0.20,
                'fatality': False,
                'suspicious': True  # 0.5
            },
            geo_dc_check={
                'triggered': True,
                'foreign_ratio': 0.80  # 0.2
            }
        )

        # 0.5 * 0.2 = 0.1, exactly at floor
        trust, details = calculate_trust_factor(
            forensics_result=forensics,
            comments_enabled=True,
            conviction_score=0
        )

        assert trust == 0.1, f"Expected floor of 0.1, got {trust}"


class TestTrustFactorStatisticalPenalties:
    """Tests for statistical trust penalties (hollow views, zombie engagement, etc.)."""

    def test_trust_factor_hollow_views(self):
        """Hollow views (reach >300%, low forward rate) should apply 0.6 penalty."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            reach=400,          # > 300% threshold
            forward_rate=0.5,   # < 3% virality alibi
            members=5000,
            avg_comments=0.5,   # < threshold for size
            comment_trust=50    # < 70 alibi threshold
        )

        assert 'hollow_views' in details
        assert details['hollow_views']['multiplier'] == 0.6

    def test_trust_factor_hollow_views_virality_alibi(self):
        """High forward rate should provide virality alibi for hollow views."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            reach=400,          # > 300%
            forward_rate=5.0,   # > 3% = virality alibi
            members=5000
        )

        # Virality alibi should prevent hollow_views penalty
        assert 'hollow_views' not in details

    def test_trust_factor_zombie_engagement(self):
        """High reach + low reactions should trigger zombie engagement."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            reach=60,           # > 50%
            reaction_rate=0.05  # < 0.1%
        )

        assert 'zombie_engagement' in details
        assert details['zombie_engagement']['multiplier'] == 0.7


class TestTrustFactorGhostProtocol:
    """Tests for Ghost Protocol penalties."""

    def test_trust_factor_ghost_channel(self):
        """Ghost channel (20k+ subs, <0.1% online) should apply 0.5 penalty."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            members=25000,
            online_count=10  # 0.04% online
        )

        assert 'ghost_channel' in details
        assert details['ghost_channel']['multiplier'] == 0.5

    def test_trust_factor_zombie_audience(self):
        """Zombie audience (5k+ subs, <0.3% online) should apply 0.7 penalty."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            members=10000,
            online_count=20  # 0.2% online
        )

        assert 'zombie_audience' in details
        assert details['zombie_audience']['multiplier'] == 0.7


class TestTrustFactorConviction:
    """Tests for conviction-based penalties."""

    def test_trust_factor_conviction_critical(self):
        """Conviction >= 70 should apply 0.3 penalty."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=75
        )

        assert 'conviction' in details
        assert details['conviction']['multiplier'] == 0.3

    def test_trust_factor_conviction_high(self):
        """Conviction >= 50 should apply 0.6 penalty."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=55
        )

        assert 'conviction' in details
        assert details['conviction']['multiplier'] == 0.6


# =============================================================================
# SCORE CALCULATOR TESTS
# =============================================================================

class TestRawScorePerfectChannel:
    """Tests for perfect channel raw score calculation."""

    def test_raw_score_perfect_channel(self):
        """All metrics good should give score close to 100."""
        from scanner.recalculator import recalculate_score_from_breakdown

        breakdown = get_mock_breakdown(
            cv_views={'value': 45.0, 'points': 12, 'max': 12},  # Optimal CV
            reach={'value': 55.0, 'points': 8, 'max': 8},      # High reach
            forward_rate={'value': 3.0, 'points': 15, 'max': 15},  # Viral
            regularity={'value': 3.0, 'points': 7, 'max': 7},  # Ideal posting
            comments={'value': 'enabled', 'points': 15, 'max': 15, 'avg': 5.0},
            reaction_rate={'value': 3.0, 'points': 8, 'max': 8},
            reaction_stability={'value': 50.0, 'top_concentration': 0.2, 'points': 5, 'max': 5},
            er_trend={'status': 'growing', 'er_trend': 1.2, 'points': 10, 'max': 10},
            age={'value': 800, 'points': 7, 'max': 7},  # Veteran
            premium={'value': 6.0, 'ratio': 0.06, 'count': 5, 'points': 7, 'max': 7},
            source_diversity={'value': 0.95, 'repost_ratio': 0.05, 'points': 6, 'max': 6}
        )

        raw_score, categories, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        # Perfect channel should score ~100 (quality 42 + engagement 38 + reputation 20)
        assert raw_score >= 90, f"Perfect channel should score ~100, got {raw_score}"
        assert raw_score <= 100, f"Score should be capped at 100, got {raw_score}"

    def test_raw_score_quality_category(self):
        """Quality category should sum correctly."""
        from scanner.recalculator import recalculate_score_from_breakdown

        breakdown = get_mock_breakdown()
        raw_score, categories, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        assert 'quality' in categories
        assert categories['quality']['max'] == 42  # v48.0 total
        assert categories['quality']['score'] <= categories['quality']['max']


class TestRawScoreDeadChannel:
    """Tests for dead/bad channel raw score calculation."""

    def test_raw_score_dead_channel(self):
        """All metrics bad should give score close to 0."""
        from scanner.recalculator import recalculate_score_from_breakdown

        breakdown = get_mock_breakdown(
            cv_views={'value': 5.0, 'points': 0, 'max': 12},   # Too flat (bots)
            reach={'value': 2.0, 'points': 0, 'max': 8},       # Dead audience
            forward_rate={'value': 0.01, 'points': 0, 'max': 15},  # No forwards
            regularity={'value': 0.05, 'points': 0, 'max': 7}, # Dead posting
            comments={'value': 'disabled', 'points': 0, 'max': 0, 'avg': 0},
            reaction_rate={'value': 0.1, 'points': 1, 'max': 8},  # Almost dead
            reaction_stability={'value': 5.0, 'top_concentration': 0.7, 'points': 1, 'max': 5},
            er_trend={'status': 'dying', 'er_trend': 0.5, 'points': 0, 'max': 10},
            age={'value': 30, 'points': 0, 'max': 7},          # Newborn
            premium={'value': 0, 'ratio': 0, 'count': 0, 'points': 0, 'max': 7},
            source_diversity={'value': 0.3, 'repost_ratio': 0.8, 'points': 0, 'max': 6},
            comments_enabled=False,
            reactions_enabled=True
        )

        raw_score, categories, _ = recalculate_score_from_breakdown(breakdown, members=10000)

        # Dead channel should score very low
        assert raw_score < 20, f"Dead channel should score <20, got {raw_score}"


class TestRawScoreFloatingWeights:
    """Tests for floating weights when comments/reactions disabled."""

    def test_raw_score_floating_weights_no_comments(self):
        """Comments disabled should redistribute points to forward_rate."""
        from scanner.recalculator import recalculate_score_from_breakdown

        # Channel with comments disabled
        breakdown = get_mock_breakdown(
            comments={'value': 'disabled', 'points': 0, 'max': 0, 'avg': 0},
            forward_rate={'value': 2.0, 'points': 20, 'max': 25},  # Gets bonus
            comments_enabled=False,
            reactions_enabled=True
        )

        raw_score, categories, updated_breakdown = recalculate_score_from_breakdown(
            breakdown, members=5000
        )

        # Forward rate max should be increased due to floating weights
        # (25 instead of 15 when comments disabled)
        assert updated_breakdown['forward_rate']['max'] == 15  # Base max in breakdown
        # Score should still be reasonable
        assert raw_score > 0

    def test_raw_score_floating_weights_both_disabled(self):
        """Both comments and reactions disabled should give all to forward."""
        from scanner.recalculator import recalculate_score_from_breakdown

        breakdown = get_mock_breakdown(
            comments={'value': 'disabled', 'points': 0, 'max': 0},
            reaction_rate={'value': 0, 'points': 0, 'max': 0},
            forward_rate={'value': 3.0, 'points': 30, 'max': 38},
            comments_enabled=False,
            reactions_enabled=False
        )

        raw_score, categories, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        # Score should account for all forward points
        assert raw_score > 0


class TestRawScoreCappedAt100:
    """Tests for raw score cap at 100."""

    def test_raw_score_capped_at_100(self):
        """Raw score should never exceed 100."""
        from scanner.recalculator import recalculate_score_from_breakdown

        # Artificially inflate all points beyond max
        breakdown = get_mock_breakdown(
            cv_views={'value': 45.0, 'points': 20, 'max': 12},
            reach={'value': 55.0, 'points': 15, 'max': 8},
            forward_rate={'value': 5.0, 'points': 20, 'max': 15},
            regularity={'value': 3.0, 'points': 10, 'max': 7},
            comments={'value': 'enabled', 'points': 20, 'max': 15, 'avg': 10.0},
            reaction_rate={'value': 5.0, 'points': 15, 'max': 8},
            reaction_stability={'value': 50.0, 'points': 10, 'max': 5},
            er_trend={'status': 'growing', 'points': 15, 'max': 10},
            age={'value': 1000, 'points': 10, 'max': 7},
            premium={'value': 10.0, 'ratio': 0.1, 'count': 10, 'points': 10, 'max': 7},
            source_diversity={'value': 1.0, 'repost_ratio': 0, 'points': 10, 'max': 6}
        )

        raw_score, _, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        # Score must be capped
        assert raw_score <= 100, f"Score should be capped at 100, got {raw_score}"


class TestRawScoreCategories:
    """Tests for category breakdown in score calculation."""

    def test_categories_structure(self):
        """Categories should have correct structure."""
        from scanner.recalculator import recalculate_score_from_breakdown

        breakdown = get_mock_breakdown()
        _, categories, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        assert 'quality' in categories
        assert 'engagement' in categories
        assert 'reputation' in categories

        for cat in ['quality', 'engagement', 'reputation']:
            assert 'score' in categories[cat]
            assert 'max' in categories[cat]
            assert categories[cat]['score'] >= 0
            assert categories[cat]['score'] <= categories[cat]['max']

    def test_category_totals_match_v48(self):
        """Category max totals should match v48.0 spec."""
        from scanner.recalculator import recalculate_score_from_breakdown
        from scanner.scorer import CATEGORY_TOTALS

        breakdown = get_mock_breakdown()
        _, categories, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        assert categories['quality']['max'] == CATEGORY_TOTALS['quality']  # 42
        assert categories['engagement']['max'] == CATEGORY_TOTALS['engagement']  # 38
        assert categories['reputation']['max'] == CATEGORY_TOTALS['reputation']  # 20


# =============================================================================
# VERDICT TESTS
# =============================================================================

class TestVerdictExcellent:
    """Tests for EXCELLENT verdict (score >= 75)."""

    def test_verdict_excellent_at_75(self):
        """Score exactly 75 should give EXCELLENT verdict."""
        from scanner.scorer_constants import VerdictThresholds

        score = 75
        assert score >= VerdictThresholds.EXCELLENT

    def test_verdict_excellent_above_75(self):
        """Score above 75 should give EXCELLENT verdict."""
        from scanner.scorer_constants import VerdictThresholds

        for score in [76, 85, 95, 100]:
            assert score >= VerdictThresholds.EXCELLENT


class TestVerdictGood:
    """Tests for GOOD verdict (score >= 55, < 75)."""

    def test_verdict_good_at_55(self):
        """Score exactly 55 should give GOOD verdict."""
        from scanner.scorer_constants import VerdictThresholds

        score = 55
        assert score >= VerdictThresholds.GOOD
        assert score < VerdictThresholds.EXCELLENT

    def test_verdict_good_range(self):
        """Scores 55-74 should give GOOD verdict."""
        from scanner.scorer_constants import VerdictThresholds

        for score in [55, 60, 70, 74]:
            assert score >= VerdictThresholds.GOOD
            assert score < VerdictThresholds.EXCELLENT


class TestVerdictMedium:
    """Tests for MEDIUM verdict (score >= 40, < 55)."""

    def test_verdict_medium_at_40(self):
        """Score exactly 40 should give MEDIUM verdict."""
        from scanner.scorer_constants import VerdictThresholds

        score = 40
        assert score >= VerdictThresholds.MEDIUM
        assert score < VerdictThresholds.GOOD

    def test_verdict_medium_range(self):
        """Scores 40-54 should give MEDIUM verdict."""
        from scanner.scorer_constants import VerdictThresholds

        for score in [40, 45, 50, 54]:
            assert score >= VerdictThresholds.MEDIUM
            assert score < VerdictThresholds.GOOD


class TestVerdictHighRisk:
    """Tests for HIGH_RISK verdict (score >= 25, < 40)."""

    def test_verdict_high_risk_at_25(self):
        """Score exactly 25 should give HIGH_RISK verdict."""
        from scanner.scorer_constants import VerdictThresholds

        score = 25
        assert score >= VerdictThresholds.HIGH_RISK
        assert score < VerdictThresholds.MEDIUM

    def test_verdict_high_risk_range(self):
        """Scores 25-39 should give HIGH_RISK verdict."""
        from scanner.scorer_constants import VerdictThresholds

        for score in [25, 30, 35, 39]:
            assert score >= VerdictThresholds.HIGH_RISK
            assert score < VerdictThresholds.MEDIUM


class TestVerdictScam:
    """Tests for SCAM verdict (score < 25)."""

    def test_verdict_scam_below_25(self):
        """Score below 25 should give SCAM verdict."""
        from scanner.scorer_constants import VerdictThresholds

        for score in [0, 10, 20, 24]:
            assert score < VerdictThresholds.HIGH_RISK

    def test_verdict_scam_at_zero(self):
        """Score 0 should give SCAM verdict."""
        from scanner.scorer_constants import VerdictThresholds

        score = 0
        assert score < VerdictThresholds.HIGH_RISK


class TestVerdictDetermination:
    """Integration tests for verdict determination logic."""

    def test_verdict_from_score_function(self):
        """Test verdict determination matches thresholds."""
        from scanner.scorer_constants import VerdictThresholds

        def get_verdict(score: int) -> str:
            if score >= VerdictThresholds.EXCELLENT:
                return 'EXCELLENT'
            elif score >= VerdictThresholds.GOOD:
                return 'GOOD'
            elif score >= VerdictThresholds.MEDIUM:
                return 'MEDIUM'
            elif score >= VerdictThresholds.HIGH_RISK:
                return 'HIGH_RISK'
            else:
                return 'SCAM'

        assert get_verdict(100) == 'EXCELLENT'
        assert get_verdict(75) == 'EXCELLENT'
        assert get_verdict(74) == 'GOOD'
        assert get_verdict(55) == 'GOOD'
        assert get_verdict(54) == 'MEDIUM'
        assert get_verdict(40) == 'MEDIUM'
        assert get_verdict(39) == 'HIGH_RISK'
        assert get_verdict(25) == 'HIGH_RISK'
        assert get_verdict(24) == 'SCAM'
        assert get_verdict(0) == 'SCAM'

    def test_verdict_thresholds_are_correct(self):
        """Verify threshold constants are correct."""
        from scanner.scorer_constants import VerdictThresholds

        assert VerdictThresholds.EXCELLENT == 75
        assert VerdictThresholds.GOOD == 55
        assert VerdictThresholds.MEDIUM == 40
        assert VerdictThresholds.HIGH_RISK == 25


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestTrustAndScoreIntegration:
    """Integration tests for trust factor and score calculation."""

    def test_final_score_calculation(self):
        """Final score = raw_score * trust_factor."""
        from scanner.recalculator import recalculate_score_from_breakdown
        from scanner.scorer import calculate_trust_factor

        breakdown = get_mock_breakdown()
        raw_score, _, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        trust, _ = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0
        )

        final_score = int(raw_score * trust)
        assert final_score == raw_score  # trust = 1.0

    def test_final_score_with_penalty(self):
        """Final score reduced by trust penalties."""
        from scanner.recalculator import recalculate_score_from_breakdown
        from scanner.scorer import calculate_trust_factor

        breakdown = get_mock_breakdown()
        raw_score, _, _ = recalculate_score_from_breakdown(breakdown, members=5000)

        trust, _ = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=False,  # 0.85 penalty
            conviction_score=0
        )

        final_score = int(raw_score * trust)
        expected = int(raw_score * 0.85)
        assert final_score == expected


# =============================================================================
# NULL HANDLING TESTS (Bug #5)
# =============================================================================

class TestExtractScoreInputNullHandling:
    """Tests for extract_score_input_from_breakdown null handling (Bug #5)."""

    def test_extract_score_input_handles_null_values(self):
        """Bug #5: breakdown with explicit null values should not crash."""
        from recalc.domain.score_calculator import extract_score_input_from_breakdown

        breakdown_json = {
            'breakdown': {
                'cv_views': None,  # explicit null
                'reach': {'value': 50},
                'comments': None,
                'er_trend': None,
                'reaction_stability': None,
            },
            'llm_analysis': None,  # The killer null
        }

        # Should not crash
        result = extract_score_input_from_breakdown(breakdown_json)

        # Should return defaults for null values
        assert result.cv_views == 0
        assert result.reach == 50
        assert result.avg_comments == 0.0

    def test_extract_score_input_handles_all_null_breakdown(self):
        """All null values in breakdown should return defaults."""
        from recalc.domain.score_calculator import extract_score_input_from_breakdown

        breakdown_json = {
            'breakdown': {
                'cv_views': None,
                'reach': None,
                'regularity': None,
                'forward_rate': None,
                'views_decay': None,
                'reaction_rate': None,
                'comments': None,
                'er_trend': None,
                'reaction_stability': None,
                'age': None,
                'premium': None,
                'source_diversity': None,
            }
        }

        result = extract_score_input_from_breakdown(breakdown_json)

        # All should be defaults
        assert result.cv_views == 0
        assert result.reach == 0
        assert result.posts_per_day == 0
        assert result.forward_rate == 0
        assert result.views_decay_ratio == 1.0  # Default is 1.0, not 0
        assert result.reaction_rate == 0
        assert result.avg_comments == 0.0
        # Note: er_trend_status defaults to 'critical_decline' when missing (safest assumption)
        assert result.er_trend_status == 'critical_decline'
        assert result.channel_age_days == 0
        assert result.premium_ratio == 0
        assert result.premium_count == 0


class TestExtractTrustInputNullHandling:
    """Tests for extract_trust_input null handling (Bug #5)."""

    def test_extract_trust_input_handles_null_forensics(self):
        """Bug #5: forensics_json with explicit null values should not crash."""
        from recalc.infrastructure.db_repository import ChannelRow
        from recalc.modes.local import extract_trust_input

        row = ChannelRow(
            username='test',
            score=50,
            raw_score=50,
            trust_factor=1.0,
            verdict='MEDIUM',
            status='GOOD',
            breakdown_json={'breakdown': {}, 'conviction_details': None},
            forensics_json={'id_clustering': None, 'geo_dc_analysis': None, 'premium_density': None},
            llm_analysis={},
            members=1000,
            online_count=10,
            participants_count=100,
            bot_percentage=0,
            ad_percentage=0,
            category='TECH',
            posts_per_day=1.0,
            comments_enabled=True,
            reactions_enabled=True,
        )

        # Should not crash
        result = extract_trust_input(row)
        assert result is not None
        assert result.id_clustering_ratio == 0
        assert result.id_clustering_fatality == False
        assert result.geo_dc_foreign_ratio == 0
        assert result.premium_ratio == 0

    def test_extract_trust_input_handles_null_breakdown_metrics(self):
        """Null metrics in breakdown should not crash trust extraction."""
        from recalc.infrastructure.db_repository import ChannelRow
        from recalc.modes.local import extract_trust_input

        row = ChannelRow(
            username='test',
            score=50,
            raw_score=50,
            trust_factor=1.0,
            verdict='MEDIUM',
            status='GOOD',
            breakdown_json={
                'breakdown': {
                    'reach': None,
                    'forward_rate': None,
                    'reaction_rate': None,
                    'views_decay': None,
                    'comments': None,
                    'source_diversity': None,
                    'er_trend': None,
                    'private_links': None,
                },
                'conviction_details': None,
            },
            forensics_json={},
            llm_analysis={},
            members=1000,
            online_count=10,
            participants_count=100,
            bot_percentage=0,
            ad_percentage=0,
            category='TECH',
            posts_per_day=1.0,
            comments_enabled=True,
            reactions_enabled=True,
        )

        # Should not crash
        result = extract_trust_input(row)
        assert result is not None
        assert result.reach == 0
        assert result.forward_rate == 0
        assert result.reaction_rate == 0


class TestRecalculateChannelNullHandling:
    """Tests for recalculate_channel null handling (Bug #6)."""

    def test_recalculate_channel_skips_missing_breakdown(self):
        """Bug #6: Channels without breakdown should be skipped."""
        from recalc.infrastructure.db_repository import ChannelRow
        from recalc.modes.local import recalculate_channel

        row = ChannelRow(
            username='test',
            score=50,
            raw_score=50,
            trust_factor=1.0,
            verdict='MEDIUM',
            status='GOOD',
            breakdown_json={},  # Empty - no 'breakdown' key
            forensics_json={},
            llm_analysis={},
            members=1000,
            online_count=10,
            participants_count=100,
            bot_percentage=0,
            ad_percentage=0,
            category='TECH',
            posts_per_day=1.0,
            comments_enabled=True,
            reactions_enabled=True,
        )

        result = recalculate_channel(row)

        # Should not change
        assert result.changed == False
        assert result.new_score == 50  # Kept old score

    def test_recalculate_channel_skips_none_breakdown(self):
        """Channels with None breakdown should be skipped."""
        from recalc.infrastructure.db_repository import ChannelRow
        from recalc.modes.local import recalculate_channel

        row = ChannelRow(
            username='test',
            score=50,
            raw_score=50,
            trust_factor=1.0,
            verdict='MEDIUM',
            status='GOOD',
            breakdown_json=None,  # None - should be skipped
            forensics_json={},
            llm_analysis={},
            members=1000,
            online_count=10,
            participants_count=100,
            bot_percentage=0,
            ad_percentage=0,
            category='TECH',
            posts_per_day=1.0,
            comments_enabled=True,
            reactions_enabled=True,
        )

        result = recalculate_channel(row)

        # Should not change
        assert result.changed == False
        assert result.new_score == 50  # Kept old score
        assert result.new_verdict == 'MEDIUM'  # Kept old verdict