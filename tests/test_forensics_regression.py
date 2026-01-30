"""
Regression tests for scanner/forensics.py - UserForensics user analysis.

Tests cover:
- ID Clustering detection (farm detection)
- Geo/DC mismatch detection (foreign bots)
- Premium density thresholds
- Minimum users threshold for analysis
- Edge cases (empty data, single user)

Testing Patterns:
- Factory pattern for user mocks
- Parameterized tests for thresholds
- Edge case coverage
"""
import pytest
from dataclasses import dataclass
from typing import Optional, List

# Import the module under test
from scanner.forensics import (
    UserForensics,
    ForensicsResult,
    MIN_USERS_FOR_ANALYSIS,
    CLUSTER_NEIGHBOR_THRESHOLD,
    CLUSTER_MAX_GAP,
    CLUSTER_PENALTY,
    GEO_FOREIGN_THRESHOLD,
    GEO_PENALTY,
    PREMIUM_ZERO_PENALTY,
    PREMIUM_HIGH_THRESHOLD,
    PREMIUM_HIGH_BONUS,
    RU_NATIVE_DCS,
    FOREIGN_DCS,
)


# ============================================================================
# USER MOCK FACTORY
# ============================================================================

@dataclass
class MockUser:
    """
    Mock user object compatible with UserForensics analysis.
    Mimics RawUserWrapper structure.
    """
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = "Test"
    last_name: Optional[str] = None
    is_scam: bool = False
    is_fake: bool = False
    is_restricted: bool = False
    is_deleted: bool = False
    is_bot: bool = False
    is_premium: bool = False
    dc_id: Optional[int] = 2  # DC 2 = Europe/Russia (native)


class UserFactory:
    """Factory for creating mock users with various configurations."""

    _counter = 0

    @classmethod
    def reset_counter(cls):
        """Reset the ID counter for deterministic tests."""
        cls._counter = 0

    @classmethod
    def create(
        cls,
        user_id: Optional[int] = None,
        is_premium: bool = False,
        dc_id: Optional[int] = 2,
        is_scam: bool = False,
        is_fake: bool = False,
        is_bot: bool = False,
        is_deleted: bool = False,
        is_restricted: bool = False,
    ) -> MockUser:
        """Create a single mock user with specified attributes."""
        if user_id is None:
            cls._counter += 1
            user_id = 100000000 + cls._counter * 100000

        return MockUser(
            id=user_id,
            username=f"user_{user_id}" if cls._counter % 3 == 0 else None,
            is_premium=is_premium,
            dc_id=dc_id,
            is_scam=is_scam,
            is_fake=is_fake,
            is_bot=is_bot,
            is_deleted=is_deleted,
            is_restricted=is_restricted,
        )

    @classmethod
    def create_random_ids(cls, count: int, premium_ratio: float = 0.0) -> List[MockUser]:
        """
        Create users with randomly distributed IDs (not clustered).
        Simulates organic audience.
        """
        cls.reset_counter()
        users = []
        premium_count = int(count * premium_ratio)

        for i in range(count):
            # IDs spread across a wide range (not neighbors)
            user_id = 100000000 + i * 50000 + (i * 7919 % 10000)
            is_premium = i < premium_count

            users.append(MockUser(
                id=user_id,
                is_premium=is_premium,
                dc_id=2 if i % 4 != 0 else 4,  # Mix of Russian DCs
            ))

        return users

    @classmethod
    def create_clustered_ids(
        cls,
        count: int,
        gap: int = 50,
        base_id: int = 500000000
    ) -> List[MockUser]:
        """
        Create users with clustered (neighboring) IDs.
        Simulates bot farm registration.

        Args:
            count: Number of users
            gap: ID gap between users (< CLUSTER_MAX_GAP = neighbor)
            base_id: Starting ID
        """
        users = []
        for i in range(count):
            users.append(MockUser(
                id=base_id + i * gap,
                is_premium=False,
                dc_id=1,  # Foreign DC
            ))
        return users

    @classmethod
    def create_with_dc_distribution(
        cls,
        count: int,
        foreign_ratio: float = 0.0
    ) -> List[MockUser]:
        """
        Create users with specified DC distribution.

        Args:
            count: Number of users
            foreign_ratio: Ratio of users on foreign DCs (1, 3, 5)
        """
        users = []
        foreign_count = int(count * foreign_ratio)

        for i in range(count):
            if i < foreign_count:
                dc_id = [1, 3, 5][i % 3]  # Foreign DCs
            else:
                dc_id = [2, 4][i % 2]  # Native Russian DCs

            users.append(MockUser(
                id=200000000 + i * 100000,
                dc_id=dc_id,
            ))

        return users

    @classmethod
    def create_with_premium_ratio(cls, count: int, premium_ratio: float) -> List[MockUser]:
        """Create users with specified premium ratio."""
        users = []
        premium_count = int(count * premium_ratio)

        for i in range(count):
            users.append(MockUser(
                id=300000000 + i * 100000,
                is_premium=i < premium_count,
                dc_id=2,
            ))

        return users


# ============================================================================
# TEST: ID CLUSTERING - NORMAL (NO PENALTY)
# ============================================================================

class TestIdClusteringNormal:
    """Tests for ID clustering detection with normal (random) IDs."""

    def test_random_ids_no_penalty(self):
        """Random IDs should not trigger clustering penalty."""
        users = UserFactory.create_random_ids(count=30)
        forensics = UserForensics(users)

        result = forensics.detect_id_clusters()

        assert result['penalty'] == 0
        assert result['fatality'] is False
        assert result['triggered'] is False
        assert result['neighbor_ratio'] < CLUSTER_NEIGHBOR_THRESHOLD

    def test_wide_gap_ids_no_penalty(self):
        """IDs with gaps > CLUSTER_MAX_GAP should not be neighbors."""
        users = []
        for i in range(20):
            # Gap of 1000 between IDs (> CLUSTER_MAX_GAP of 500)
            users.append(MockUser(id=100000000 + i * 1000))

        forensics = UserForensics(users)
        result = forensics.detect_id_clusters()

        assert result['penalty'] == 0
        assert result['neighbor_count'] == 0
        assert result['neighbor_ratio'] == 0.0

    def test_mixed_random_and_some_neighbors(self):
        """Mix of random and a few neighbor IDs should not trigger fatality."""
        users = []
        # 15 random IDs
        for i in range(15):
            users.append(MockUser(id=100000000 + i * 50000))
        # 5 neighbor IDs (25% of 20 = under 30% threshold)
        base_id = 900000000
        for i in range(5):
            users.append(MockUser(id=base_id + i * 100))

        forensics = UserForensics(users)
        result = forensics.detect_id_clusters()

        # Should not trigger FATALITY (need >30%)
        assert result['fatality'] is False
        # Penalty should be 0 since fatality is False
        assert result['penalty'] == 0


# ============================================================================
# TEST: ID CLUSTERING - FATALITY (>30% NEIGHBOR IDS)
# ============================================================================

class TestIdClusteringFatality:
    """Tests for ID clustering FATALITY detection (bot farms)."""

    def test_all_neighbor_ids_triggers_fatality(self):
        """100% neighbor IDs should trigger FATALITY."""
        # All IDs within CLUSTER_MAX_GAP of each other
        users = UserFactory.create_clustered_ids(count=30, gap=50)

        forensics = UserForensics(users)
        result = forensics.detect_id_clusters()

        assert result['fatality'] is True
        assert result['penalty'] == CLUSTER_PENALTY  # -100
        assert result['triggered'] is True
        assert result['neighbor_ratio'] > CLUSTER_NEIGHBOR_THRESHOLD

    def test_exactly_30_percent_not_fatality(self):
        """Exactly 30% neighbor ratio should NOT trigger fatality (> required)."""
        # 30 users total, need >30% neighbors for fatality
        # 29 pairs possible, 30% = 8.7 pairs, so 9 pairs = ~31% triggers
        # Let's create 10 random + 20 with mixed gaps
        users = []

        # 21 users with wide gaps (not neighbors)
        for i in range(21):
            users.append(MockUser(id=100000000 + i * 1000))

        # 9 users with narrow gaps (neighbors) = 8 neighbor pairs
        base = 900000000
        for i in range(9):
            users.append(MockUser(id=base + i * 100))

        # Total: 30 users, 29 pairs possible, 8 neighbor pairs = 27.6%
        forensics = UserForensics(users)
        result = forensics.detect_id_clusters()

        assert result['fatality'] is False
        assert result['neighbor_ratio'] <= CLUSTER_NEIGHBOR_THRESHOLD

    def test_just_over_30_percent_triggers_fatality(self):
        """Just over 30% neighbor ratio should trigger fatality."""
        # Create users where >30% are neighbors
        users = []

        # 18 users with wide gaps
        for i in range(18):
            users.append(MockUser(id=100000000 + i * 1000))

        # 12 clustered users (11 neighbor pairs)
        base = 900000000
        for i in range(12):
            users.append(MockUser(id=base + i * 100))

        # Total: 30 users, 29 pairs, 11 neighbor pairs = 37.9%
        forensics = UserForensics(users)
        result = forensics.detect_id_clusters()

        assert result['fatality'] is True
        assert result['penalty'] == CLUSTER_PENALTY

    def test_fatality_penalty_value(self):
        """FATALITY penalty should be exactly -100."""
        users = UserFactory.create_clustered_ids(count=20, gap=10)
        forensics = UserForensics(users)

        result = forensics.detect_id_clusters()

        assert result['penalty'] == -100
        assert CLUSTER_PENALTY == -100


# ============================================================================
# TEST: GEO/DC MISMATCH (>75% FOREIGN DC)
# ============================================================================

class TestGeoDcMismatch:
    """Tests for Geo/DC mismatch detection (foreign bots)."""

    def test_all_native_dc_no_penalty(self):
        """Users all on native DCs should not trigger penalty."""
        users = UserFactory.create_with_dc_distribution(count=20, foreign_ratio=0.0)
        forensics = UserForensics(users)

        result = forensics.check_geo_dc(is_ru_channel=True)

        assert result['penalty'] == 0
        assert result['triggered'] is False
        assert result['foreign_ratio'] == 0.0

    def test_under_75_percent_foreign_no_penalty(self):
        """<75% foreign DC should not trigger penalty."""
        users = UserFactory.create_with_dc_distribution(count=20, foreign_ratio=0.70)
        forensics = UserForensics(users)

        result = forensics.check_geo_dc(is_ru_channel=True)

        assert result['penalty'] == 0
        assert result['triggered'] is False
        assert result['foreign_ratio'] <= GEO_FOREIGN_THRESHOLD

    def test_over_75_percent_foreign_triggers_penalty(self):
        """
        >75% foreign DC should trigger penalty.
        """
        users = UserFactory.create_with_dc_distribution(count=20, foreign_ratio=0.80)
        forensics = UserForensics(users)

        result = forensics.check_geo_dc(is_ru_channel=True)

        assert result['penalty'] == GEO_PENALTY  # -50
        assert result['triggered'] is True
        assert result['foreign_ratio'] > GEO_FOREIGN_THRESHOLD

    def test_all_foreign_dc_max_penalty(self):
        """100% foreign DC should trigger maximum penalty."""
        users = []
        for i in range(20):
            users.append(MockUser(
                id=100000000 + i * 100000,
                dc_id=[1, 3, 5][i % 3],  # All foreign DCs
            ))

        forensics = UserForensics(users)
        result = forensics.check_geo_dc(is_ru_channel=True)

        assert result['penalty'] == GEO_PENALTY
        assert result['foreign_ratio'] == 1.0
        assert result['triggered'] is True

    def test_non_ru_channel_no_penalty(self):
        """Non-Russian channel should not get geo penalty."""
        users = UserFactory.create_with_dc_distribution(count=20, foreign_ratio=1.0)
        forensics = UserForensics(users)

        result = forensics.check_geo_dc(is_ru_channel=False)

        assert result['penalty'] == 0
        assert result['triggered'] is False

    def test_users_without_dc_ignored(self):
        """Users without DC (no photo) should be skipped."""
        users = []
        for i in range(20):
            # Half with DC, half without
            dc = 1 if i < 10 else None  # Foreign DC for those with photo
            users.append(MockUser(id=100000000 + i * 100000, dc_id=dc))

        forensics = UserForensics(users)
        result = forensics.check_geo_dc(is_ru_channel=True)

        # Only 10 users have DC
        assert result['users_with_dc'] == 10

    def test_dc_distribution_tracked(self):
        """DC distribution should be properly tracked in result."""
        users = []
        # 10 users on DC 2, 5 on DC 1, 5 on DC 4
        for i in range(10):
            users.append(MockUser(id=100000000 + i * 100000, dc_id=2))
        for i in range(5):
            users.append(MockUser(id=200000000 + i * 100000, dc_id=1))
        for i in range(5):
            users.append(MockUser(id=300000000 + i * 100000, dc_id=4))

        forensics = UserForensics(users)
        result = forensics.check_geo_dc(is_ru_channel=True)

        assert result['dc_distribution'][2] == 10
        assert result['dc_distribution'][1] == 5
        assert result['dc_distribution'][4] == 5
        assert result['users_with_dc'] == 20


# ============================================================================
# TEST: PREMIUM DENSITY
# ============================================================================

class TestPremiumDensity:
    """Tests for premium user density analysis."""

    def test_zero_premium_penalty(self):
        """0% premium users should trigger penalty."""
        users = UserFactory.create_with_premium_ratio(count=20, premium_ratio=0.0)
        forensics = UserForensics(users)

        result = forensics.check_premium_density()

        assert result['penalty'] == PREMIUM_ZERO_PENALTY  # -20
        assert result['triggered'] is True
        assert result['is_bonus'] is False
        assert result['premium_ratio'] == 0.0

    def test_low_premium_no_penalty_no_bonus(self):
        """Low premium (1-5%) should give neither penalty nor bonus."""
        # Use count=40 so 3% = 1.2 rounds to 1 premium user (not 0)
        users = UserFactory.create_with_premium_ratio(count=40, premium_ratio=0.03)
        forensics = UserForensics(users)

        result = forensics.check_premium_density()

        # With 1/40 = 2.5% premium, no bonus (< 5%) and no penalty (> 0%)
        assert result['penalty'] == 0
        assert result['triggered'] is False
        assert result['is_bonus'] is False

    def test_high_premium_bonus(self):
        """
        >5% premium users should give bonus.
        """
        users = UserFactory.create_with_premium_ratio(count=20, premium_ratio=0.10)
        forensics = UserForensics(users)

        result = forensics.check_premium_density()

        assert result['penalty'] == PREMIUM_HIGH_BONUS  # +10
        assert result['triggered'] is True
        assert result['is_bonus'] is True
        assert result['premium_ratio'] > PREMIUM_HIGH_THRESHOLD

    def test_exactly_5_percent_no_bonus(self):
        """Exactly 5% premium should NOT trigger bonus (> required)."""
        users = UserFactory.create_with_premium_ratio(count=20, premium_ratio=0.05)
        forensics = UserForensics(users)

        result = forensics.check_premium_density()

        # 0.05 is not > 0.05, so no bonus
        assert result['is_bonus'] is False
        assert result['penalty'] == 0

    def test_premium_count_accurate(self):
        """Premium count should be accurately tracked."""
        users = UserFactory.create_with_premium_ratio(count=25, premium_ratio=0.20)
        forensics = UserForensics(users)

        result = forensics.check_premium_density()

        assert result['premium_count'] == 5  # 20% of 25
        assert result['total_users'] == 25


# ============================================================================
# TEST: MINIMUM USERS THRESHOLD
# ============================================================================

class TestMinUsersThreshold:
    """Tests for minimum users threshold (skip analysis with <10 users)."""

    def test_under_10_users_skip_id_clustering(self):
        """ID clustering should be skipped with <10 users."""
        users = [MockUser(id=100000000 + i * 10) for i in range(5)]
        forensics = UserForensics(users)

        result = forensics.detect_id_clusters()

        assert result['penalty'] == 0
        assert result['triggered'] is False
        assert result['fatality'] is False
        assert result['total_users'] == 5
        assert 'Недостаточно' in result['description']

    def test_exactly_10_users_analyzed(self):
        """Exactly 10 users should be analyzed."""
        users = UserFactory.create_clustered_ids(count=10, gap=50)
        forensics = UserForensics(users)

        result = forensics.detect_id_clusters()

        # 10 users analyzed (>= MIN_USERS_FOR_ANALYSIS)
        assert result['total_users'] == 10
        # With clustered IDs, should detect
        assert result['triggered'] is True or result['neighbor_ratio'] > 0

    def test_full_analyze_with_insufficient_users(self):
        """Full analyze() should return insufficient_data status."""
        users = [MockUser(id=100000000 + i) for i in range(5)]
        forensics = UserForensics(users)

        result = forensics.analyze()

        assert result.status == 'insufficient_data'
        assert result.total_penalty == 0
        assert result.users_analyzed == 5

    def test_full_analyze_with_sufficient_users(self):
        """Full analyze() should return complete status with enough users."""
        users = UserFactory.create_random_ids(count=15)
        forensics = UserForensics(users)

        result = forensics.analyze()

        assert result.status == 'complete'
        assert result.users_analyzed == 15

    def test_premium_zero_penalty_requires_min_users(self):
        """Zero premium penalty only applies with sufficient sample."""
        # <10 users with 0% premium - no penalty
        users = [MockUser(id=100000000 + i * 100000, is_premium=False) for i in range(5)]
        forensics = UserForensics(users)

        result = forensics.check_premium_density()

        # Should not penalize since sample is too small
        assert result['penalty'] == 0


# ============================================================================
# TEST: EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases (empty data, single user, etc.)."""

    def test_empty_user_list(self):
        """Empty user list should not crash and return neutral results."""
        forensics = UserForensics([])

        # Test all methods
        id_result = forensics.detect_id_clusters()
        geo_result = forensics.check_geo_dc()
        premium_result = forensics.check_premium_density()
        flags_result = forensics.check_hidden_flags()

        assert id_result['penalty'] == 0
        assert geo_result['penalty'] == 0
        assert premium_result['penalty'] == 0
        assert flags_result['penalty'] == 0

    def test_single_user(self):
        """Single user should not crash and return neutral results."""
        users = [MockUser(id=100000000)]
        forensics = UserForensics(users)

        result = forensics.analyze()

        assert result.status == 'insufficient_data'
        assert result.total_penalty == 0

    def test_users_without_ids(self):
        """Users with None IDs should be handled gracefully."""
        users = [
            MockUser(id=100000000),
            MockUser(id=None),  # type: ignore
            MockUser(id=100000500),
        ]
        forensics = UserForensics(users)

        result = forensics.detect_id_clusters()

        # Should not crash - the code filters users without valid IDs
        # Note: the actual implementation may count all users or filter them
        # The key assertion is that it doesn't crash
        assert result['penalty'] == 0  # With <10 users, no penalty anyway
        assert result['total_users'] <= 3

    def test_users_with_hidden_flags(self):
        """Users with scam/fake flags should be detected."""
        users = [MockUser(id=100000000 + i * 100000) for i in range(15)]
        users[0].is_scam = True
        users[1].is_fake = True
        users[2].is_bot = True

        forensics = UserForensics(users)
        result = forensics.check_hidden_flags()

        assert result['counts']['scam'] == 1
        assert result['counts']['fake'] == 1
        assert result['counts']['bot'] == 1
        assert result['triggered'] is True  # scam or fake present
        assert result['penalty'] == -10

    def test_only_deleted_users_no_flag_penalty(self):
        """Deleted users alone should not trigger flag penalty."""
        users = [MockUser(id=100000000 + i * 100000, is_deleted=True) for i in range(15)]
        forensics = UserForensics(users)

        result = forensics.check_hidden_flags()

        assert result['counts']['deleted'] == 15
        assert result['triggered'] is False  # Only scam/fake trigger
        assert result['penalty'] == 0

    def test_all_users_same_id(self):
        """All users with same ID (edge case) should not crash."""
        users = [MockUser(id=100000000) for _ in range(15)]
        forensics = UserForensics(users)

        result = forensics.detect_id_clusters()

        # All same ID means 0 gap = all neighbors
        # But this is an extreme edge case
        assert 'neighbor_ratio' in result


# ============================================================================
# TEST: FULL ANALYZE INTEGRATION
# ============================================================================

class TestFullAnalyze:
    """Integration tests for the full analyze() method."""

    def test_healthy_channel_no_penalties(self):
        """Healthy channel with organic users should have minimal penalties."""
        # Use 50 users with 10% premium to ensure we get 5+ premium users (> 5% threshold)
        users = UserFactory.create_random_ids(count=50, premium_ratio=0.10)
        forensics = UserForensics(users)

        result = forensics.analyze(is_ru_channel=True)

        assert result.status == 'complete'
        assert result.id_clustering['fatality'] is False
        assert result.geo_dc_check['triggered'] is False
        # With 10% premium (5/50 users), should get bonus
        assert result.premium_density['premium_ratio'] > PREMIUM_HIGH_THRESHOLD
        assert result.premium_density['is_bonus'] is True
        assert result.total_penalty >= 0  # Bonus can make it positive

    def test_bot_farm_multiple_penalties(self):
        """Bot farm should trigger multiple penalties."""
        # Clustered IDs + foreign DC + 0 premium
        users = []
        base_id = 500000000
        for i in range(30):
            users.append(MockUser(
                id=base_id + i * 50,  # Clustered
                dc_id=1,  # Foreign DC
                is_premium=False,
            ))

        forensics = UserForensics(users)
        result = forensics.analyze(is_ru_channel=True)

        assert result.status == 'complete'
        assert result.id_clustering['fatality'] is True
        assert result.id_clustering['penalty'] == -100
        assert result.geo_dc_check['triggered'] is True
        assert result.geo_dc_check['penalty'] == -50
        assert result.premium_density['penalty'] == -20
        # Total: -100 + -50 + -20 = -170
        assert result.total_penalty == -170

    def test_penalty_accumulation(self):
        """Total penalty should be sum of all individual penalties."""
        users = UserFactory.create_clustered_ids(count=20, gap=50)
        # Add scam user
        users[0].is_scam = True

        forensics = UserForensics(users)
        result = forensics.analyze(is_ru_channel=True)

        expected_total = (
            result.id_clustering['penalty'] +
            result.geo_dc_check['penalty'] +
            result.premium_density['penalty'] +
            result.hidden_flags['penalty']
        )

        assert result.total_penalty == expected_total


# ============================================================================
# TEST: CONSTANTS VALIDATION
# ============================================================================

class TestConstants:
    """Tests to verify constant values match documentation."""

    def test_cluster_threshold(self):
        """CLUSTER_NEIGHBOR_THRESHOLD should be 0.30 (30%)."""
        assert CLUSTER_NEIGHBOR_THRESHOLD == 0.30

    def test_cluster_max_gap(self):
        """CLUSTER_MAX_GAP should be 500."""
        assert CLUSTER_MAX_GAP == 500

    def test_cluster_penalty(self):
        """CLUSTER_PENALTY should be -100 (FATALITY)."""
        assert CLUSTER_PENALTY == -100

    def test_geo_threshold(self):
        """GEO_FOREIGN_THRESHOLD should be 0.75 (75%)."""
        assert GEO_FOREIGN_THRESHOLD == 0.75

    def test_geo_penalty(self):
        """GEO_PENALTY should be -50."""
        assert GEO_PENALTY == -50

    def test_premium_thresholds(self):
        """Premium thresholds should match documentation."""
        assert PREMIUM_ZERO_PENALTY == -20
        assert PREMIUM_HIGH_THRESHOLD == 0.05
        assert PREMIUM_HIGH_BONUS == 10

    def test_min_users(self):
        """MIN_USERS_FOR_ANALYSIS should be 10."""
        assert MIN_USERS_FOR_ANALYSIS == 10

    def test_dc_sets(self):
        """DC sets should be correct."""
        assert RU_NATIVE_DCS == {2, 4}
        assert FOREIGN_DCS == {1, 3, 5}
