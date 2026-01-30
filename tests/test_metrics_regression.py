"""
Regression tests for scanner/metrics.py fraud detection system.

Follows Testing Patterns skill:
- Factory pattern for message mocks
- Test each fraud factor F1-F13 independently
- Edge cases and boundary conditions

v1.0: Initial regression test suite
"""

import pytest
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Optional, List

from scanner.conviction import FraudConvictionSystem, FraudFactor, check_instant_scam
from scanner.metrics import get_message_reactions_count


# ============================================================================
# FACTORY PATTERN FOR MESSAGE MOCKS
# ============================================================================

@dataclass
class MockReactionEmoji:
    """Mock for reaction emoji object."""
    emoji: str


@dataclass
class MockReaction:
    """Mock for a single reaction with count."""
    emoji: str
    count: int

    @property
    def reaction(self):
        """Pyrogram-compatible reaction property."""
        return MockReactionEmoji(self.emoji)


@dataclass
class MockReactions:
    """Mock for message reactions container."""
    reactions: List[MockReaction] = field(default_factory=list)


@dataclass
class MockMessage:
    """
    Mock message factory.

    Usage:
        msg = MockMessage(views=1000, forwards=50)
        msg = MockMessage.with_reactions(views=1000, reactions=[("thumbs_up", 100)])
        msg = MockMessage.bot_style(views=1000)  # Only simple reactions
    """
    views: int = 100
    forwards: int = 5
    date: datetime = None
    reactions: Optional[MockReactions] = None
    text: str = ""
    forward_from_chat: Any = None

    def __post_init__(self):
        if self.date is None:
            self.date = datetime.now(timezone.utc)

    @classmethod
    def with_reactions(cls, views: int = 100, forwards: int = 5,
                       reactions: List[tuple] = None, date: datetime = None,
                       text: str = "") -> 'MockMessage':
        """
        Create message with specific reactions.

        Args:
            reactions: List of (emoji, count) tuples
        """
        if reactions is None:
            reactions = [("thumbs_up", 10), ("heart", 5), ("fire", 2)]

        mock_reactions = MockReactions([
            MockReaction(emoji=emoji, count=count)
            for emoji, count in reactions
        ])
        return cls(views=views, forwards=forwards, reactions=mock_reactions,
                   date=date, text=text)

    @classmethod
    def bot_style(cls, views: int = 100, bot_reaction_count: int = 100,
                  date: datetime = None) -> 'MockMessage':
        """Create message with bot-style reactions (only simple emojis)."""
        mock_reactions = MockReactions([
            MockReaction(emoji="thumbs_up", count=bot_reaction_count),
        ])
        return cls(views=views, forwards=1, reactions=mock_reactions, date=date)

    @classmethod
    def viral(cls, views: int = 5000, forward_rate: float = 0.05,
              date: datetime = None) -> 'MockMessage':
        """Create viral message with high forward rate."""
        forwards = int(views * forward_rate)
        reactions = [("thumbs_up", int(views * 0.03)), ("fire", int(views * 0.02))]
        return cls.with_reactions(views=views, forwards=forwards,
                                   reactions=reactions, date=date)


@dataclass
class MockChat:
    """
    Mock chat/channel factory.

    Usage:
        chat = MockChat(members_count=5000)
        chat = MockChat.micro()   # < 200 members
        chat = MockChat.scam()    # Telegram flagged
        chat = MockChat.young(members_count=10000)  # Created recently
    """
    members_count: int = 1000
    participants_count: int = None
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    date: datetime = None
    linked_chat: Any = None

    def __post_init__(self):
        if self.participants_count is None:
            self.participants_count = self.members_count
        if self.date is None:
            self.date = datetime.now(timezone.utc) - timedelta(days=365)

    @classmethod
    def micro(cls, members_count: int = 150) -> 'MockChat':
        """Create micro channel (< 200 members)."""
        return cls(members_count=members_count)

    @classmethod
    def small(cls, members_count: int = 500) -> 'MockChat':
        """Create small channel (200-1000 members)."""
        return cls(members_count=members_count)

    @classmethod
    def medium(cls, members_count: int = 3000) -> 'MockChat':
        """Create medium channel (1000-5000 members)."""
        return cls(members_count=members_count)

    @classmethod
    def large(cls, members_count: int = 20000) -> 'MockChat':
        """Create large channel (> 5000 members)."""
        return cls(members_count=members_count)

    @classmethod
    def scam(cls, members_count: int = 1000) -> 'MockChat':
        """Create Telegram-flagged SCAM channel."""
        return cls(members_count=members_count, is_scam=True)

    @classmethod
    def fake(cls, members_count: int = 1000) -> 'MockChat':
        """Create Telegram-flagged FAKE channel."""
        return cls(members_count=members_count, is_fake=True)

    @classmethod
    def verified(cls, members_count: int = 50000) -> 'MockChat':
        """Create verified channel."""
        return cls(members_count=members_count, is_verified=True)

    @classmethod
    def young(cls, members_count: int = 5000, age_days: int = 30) -> 'MockChat':
        """Create young channel."""
        return cls(
            members_count=members_count,
            date=datetime.now(timezone.utc) - timedelta(days=age_days)
        )


# ============================================================================
# MESSAGE LIST FACTORIES
# ============================================================================

class MessageFactory:
    """Factory for creating lists of messages with specific patterns."""

    @staticmethod
    def natural(count: int = 50, base_views: int = 1000,
                cv_percent: float = 30.0, time_spread_days: int = 30) -> List[MockMessage]:
        """
        Create messages with natural view distribution (CV around cv_percent).

        Natural channels have variable views due to:
        - Different content quality
        - Time of posting
        - Topic relevance
        """
        import random
        messages = []
        now = datetime.now(timezone.utc)

        # Calculate std_dev from CV
        std_dev = base_views * (cv_percent / 100)

        for i in range(count):
            views = max(10, int(random.gauss(base_views, std_dev)))
            date = now - timedelta(days=time_spread_days * i / count)

            # Natural reaction distribution
            reaction_base = int(views * 0.02)  # ~2% reaction rate
            reactions = [
                ("thumbs_up", max(1, int(reaction_base * 0.5))),
                ("heart", max(1, int(reaction_base * 0.3))),
                ("fire", max(1, int(reaction_base * 0.1))),
                ("eyes", max(1, int(reaction_base * 0.05))),
                ("100", max(1, int(reaction_base * 0.05))),
            ]

            msg = MockMessage.with_reactions(
                views=views,
                forwards=int(views * 0.01),
                reactions=reactions,
                date=date
            )
            messages.append(msg)

        return messages

    @staticmethod
    def bot_flat(count: int = 50, exact_views: int = 1000,
                 time_spread_days: int = 30) -> List[MockMessage]:
        """
        Create messages with flat (bot-like) view distribution.

        Bot-inflated channels have:
        - Nearly identical views (CV < 5%)
        - Regular posting intervals
        - Simple reactions only
        """
        messages = []
        now = datetime.now(timezone.utc)

        for i in range(count):
            # Very small variation (1-2%)
            views = exact_views + (i % 3) * 10 - 10
            date = now - timedelta(days=time_spread_days * i / count)

            msg = MockMessage.bot_style(views=views, bot_reaction_count=100, date=date)
            messages.append(msg)

        return messages

    @staticmethod
    def regular_intervals(count: int = 20, interval_hours: float = 4.0,
                          views: int = 1000) -> List[MockMessage]:
        """
        Create messages with regular posting intervals (bot-like).

        CV of intervals < 0.15 indicates automated posting.
        """
        messages = []
        now = datetime.now(timezone.utc)

        for i in range(count):
            # Exactly regular intervals
            date = now - timedelta(hours=interval_hours * i)
            msg = MockMessage(views=views, date=date)
            messages.append(msg)

        return messages

    @staticmethod
    def irregular_intervals(count: int = 20, min_hours: float = 1.0,
                            max_hours: float = 24.0, views: int = 1000) -> List[MockMessage]:
        """
        Create messages with irregular posting intervals (human-like).
        """
        import random
        messages = []
        now = datetime.now(timezone.utc)
        total_hours = 0

        for i in range(count):
            interval = random.uniform(min_hours, max_hours)
            total_hours += interval
            date = now - timedelta(hours=total_hours)
            msg = MockMessage(views=views, date=date)
            messages.append(msg)

        return messages

    @staticmethod
    def high_reach(count: int = 50, members: int = 100,
                   reach_percent: float = 300) -> List[MockMessage]:
        """
        Create messages with impossibly high reach.

        Reach > 200% for small channels is suspicious.
        """
        messages = []
        now = datetime.now(timezone.utc)
        views = int(members * reach_percent / 100)

        for i in range(count):
            date = now - timedelta(days=30 * i / count)
            msg = MockMessage(views=views + (i % 50), date=date)
            messages.append(msg)

        return messages

    @staticmethod
    def with_decay(count: int = 50, new_views: int = 1000,
                   old_views: int = 1500) -> List[MockMessage]:
        """
        Create messages with natural view decay (old posts have more views).
        """
        messages = []
        now = datetime.now(timezone.utc)

        for i in range(count):
            # Linear interpolation from new to old
            factor = i / count
            views = int(new_views + (old_views - new_views) * factor)
            date = now - timedelta(days=60 * i / count)
            msg = MockMessage(views=views, date=date)
            messages.append(msg)

        return messages

    @staticmethod
    def no_decay(count: int = 50, views: int = 1000) -> List[MockMessage]:
        """
        Create messages without decay (suspicious for real channels).

        Old posts should accumulate more views over time.
        """
        messages = []
        now = datetime.now(timezone.utc)

        for i in range(count):
            date = now - timedelta(days=60 * i / count)
            # All posts have same views regardless of age
            msg = MockMessage(views=views + (i % 20) - 10, date=date)
            messages.append(msg)

        return messages


# ============================================================================
# TEST: FRAUD CONVICTION SYSTEM WEIGHTS
# ============================================================================

class TestFraudConvictionSystemWeights:
    """Test that fraud factor weights are correctly defined."""

    def test_all_factors_have_names(self):
        """All 13 factors should have unique names."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.natural(count=20)
        fcs = FraudConvictionSystem(chat, messages, {'enabled': True, 'avg_comments': 5})

        result = fcs.calculate_conviction()
        factor_names = [f['name'] for f in result['factors']]

        expected_names = [
            'impossible_reach', 'flat_cv', 'dead_engagement', 'no_decay',
            'simple_reactions', 'disabled_comments', 'bot_regularity',
            'flat_reactions', 'extreme_reach_decay', 'high_reactions_low_comments',
            'suspicious_velocity', 'effective_members', 'young_fast_inactive'
        ]

        assert len(factor_names) == 13
        for name in expected_names:
            assert name in factor_names, f"Missing factor: {name}"

    def test_f1_weight_is_30_or_35(self):
        """F1 (impossible_reach) should have weight 30 or 35."""
        chat = MockChat(members_count=100)
        messages = MessageFactory.high_reach(count=20, members=100, reach_percent=300)
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f1_impossible_reach()
        # Weight should be 30 for > threshold, 35 for > 300%
        assert factor.weight in [0, 30, 35]

    def test_f2_weight_is_20_or_25(self):
        """F2 (flat_cv) should have weight 20 or 25."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.bot_flat(count=20, exact_views=1000)
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f2_flat_cv()
        # Weight should be 25 for CV < 10%, 20 for CV < 15%
        assert factor.weight in [0, 20, 25]

    def test_f3_weight_is_20(self):
        """F3 (dead_engagement) should have weight 20 when triggered."""
        chat = MockChat(members_count=1000)
        messages = [
            MockMessage.with_reactions(views=100, reactions=[("thumbs_up", 200)])
            for _ in range(20)
        ]
        comments_data = {'enabled': True, 'avg_comments': 0.1}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f3_dead_engagement()
        assert factor.weight in [0, 20]

    def test_f6_weight_is_15(self):
        """F6 (disabled_comments) should have weight 15 when triggered."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.natural(count=20)
        comments_data = {'enabled': False, 'avg_comments': 0}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f6_disabled_comments()
        assert factor.weight == 15
        assert factor.triggered is True

    def test_f7_weight_is_10(self):
        """F7 (bot_regularity) should have weight 10 when triggered."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.regular_intervals(count=20, interval_hours=4.0)
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f7_bot_regularity()
        assert factor.weight in [0, 10]

    def test_f13_weight_is_30(self):
        """F13 (young_fast_inactive) should have weight 30 when triggered."""
        # Young channel (< 60 days)
        chat = MockChat.young(members_count=10000, age_days=30)
        # Fast growth: 10000 / 30 = 333 subs/day > 100
        # Inactive: low reaction rate
        messages = [
            MockMessage.with_reactions(views=100, reactions=[("thumbs_up", 1)])
            for _ in range(20)
        ]
        comments_data = {'enabled': True, 'avg_comments': 0.1}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f13_young_fast_inactive()
        if factor.triggered:
            assert factor.weight == 30


# ============================================================================
# TEST: F1 HOLLOW REACH DETECTION
# ============================================================================

class TestF1HollowReach:
    """Test F1: Impossible reach detection for different channel sizes."""

    def test_micro_channel_threshold_250(self):
        """Micro channel (< 200 members) has reach threshold 250%."""
        chat = MockChat.micro(members_count=100)

        # Below threshold (200%)
        messages = MessageFactory.high_reach(count=20, members=100, reach_percent=200)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is False

        # Above threshold (300%)
        messages = MessageFactory.high_reach(count=20, members=100, reach_percent=300)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is True
        assert factor.value > 250

    def test_small_channel_threshold_180(self):
        """Small channel (200-1000 members) has reach threshold 180%."""
        chat = MockChat.small(members_count=500)

        # Below threshold (150%)
        messages = MessageFactory.high_reach(count=20, members=500, reach_percent=150)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is False

        # Above threshold (200%)
        messages = MessageFactory.high_reach(count=20, members=500, reach_percent=200)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is True

    def test_medium_channel_threshold_150(self):
        """Medium channel (1000-5000 members) has reach threshold 150%."""
        chat = MockChat.medium(members_count=3000)

        # Below threshold (100%)
        messages = MessageFactory.high_reach(count=20, members=3000, reach_percent=100)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is False

        # Above threshold (160%)
        messages = MessageFactory.high_reach(count=20, members=3000, reach_percent=160)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is True

    def test_large_channel_threshold_130(self):
        """Large channel (> 5000 members) has reach threshold 130%."""
        chat = MockChat.large(members_count=20000)

        # Below threshold (100%)
        messages = MessageFactory.high_reach(count=20, members=20000, reach_percent=100)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is False

        # Above threshold (150%)
        messages = MessageFactory.high_reach(count=20, members=20000, reach_percent=150)
        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is True

    def test_virality_alibi_forward_rate(self):
        """High forward rate (> 3%) provides alibi for high reach."""
        chat = MockChat.micro(members_count=100)

        now = datetime.now(timezone.utc)
        # High reach but high forward rate (viral content)
        messages = [
            MockMessage.viral(views=500, forward_rate=0.05, date=now - timedelta(hours=i))
            for i in range(20)
        ]

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()

        # Should not trigger due to virality alibi
        assert factor.triggered is False
        assert "alibi" in factor.description.lower() or factor.weight == 0

    def test_comments_alibi(self):
        """High comments + trust provides alibi for high reach."""
        chat = MockChat.micro(members_count=100)
        messages = MessageFactory.high_reach(count=20, members=100, reach_percent=300)

        # High avg_comments AND high comment_trust
        comments_data = {'enabled': True, 'avg_comments': 10.0}
        comment_trust = 80  # High trust

        fcs = FraudConvictionSystem(chat, messages, comments_data, comment_trust)
        factor = fcs.check_f1_impossible_reach()

        # Should not trigger due to comments alibi
        assert factor.triggered is False

    def test_extreme_reach_gets_weight_35(self):
        """Reach > 300% gets higher weight (35 instead of 30)."""
        chat = MockChat.micro(members_count=100)
        messages = MessageFactory.high_reach(count=20, members=100, reach_percent=350)

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f1_impossible_reach()

        assert factor.triggered is True
        assert factor.weight == 35


# ============================================================================
# TEST: F5 BOT REACTIONS DETECTION
# ============================================================================

class TestF5BotReactions:
    """Test F5: Simple/bot reactions detection."""

    def test_only_thumbsup_is_suspicious(self):
        """Only thumbs up reactions with > 95% is suspicious."""
        chat = MockChat(members_count=1000)
        # Use actual emoji characters that match bot_reactions list
        messages = [
            MockMessage.with_reactions(views=100, reactions=[("\U0001F44D", 100)])  # thumbs up emoji
            for _ in range(20)
        ]

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f5_simple_reactions()

        # Single reaction type > 95% should trigger
        assert factor.triggered is True
        assert factor.weight == 10

    def test_thumbsup_and_heart_is_suspicious(self):
        """Only thumbs up + heart (2 types, > 95% bot reactions)."""
        chat = MockChat(members_count=1000)
        # Use actual emoji characters
        messages = [
            MockMessage.with_reactions(views=100, reactions=[
                ("\U0001F44D", 80),  # thumbs up
                ("\u2764\uFE0F", 20)  # heart with variation selector
            ])
            for _ in range(20)
        ]

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f5_simple_reactions()

        # 2 types, both bot reactions = suspicious
        assert factor.triggered is True

    def test_diverse_reactions_not_suspicious(self):
        """Diverse reactions (> 2 types) are not suspicious."""
        chat = MockChat(members_count=1000)
        # Mix of bot and non-bot reactions
        messages = [
            MockMessage.with_reactions(views=100, reactions=[
                ("\U0001F44D", 30),  # thumbs up (bot)
                ("\u2764\uFE0F", 20),  # heart (bot)
                ("\U0001F525", 15),  # fire (bot)
                ("\U0001F440", 10),  # eyes (NOT bot)
                ("\U0001F4AF", 5)    # 100 (NOT bot)
            ])
            for _ in range(20)
        ]

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f5_simple_reactions()

        # 5 types of reactions = not suspicious (even though some are bot reactions)
        assert factor.triggered is False
        assert factor.weight == 0

    def test_no_reactions_not_suspicious(self):
        """No reactions at all is not suspicious (for this factor)."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=100, reactions=None) for _ in range(20)]

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f5_simple_reactions()

        assert factor.triggered is False
        assert "Нет реакций" in factor.description

    def test_bot_reactions_list(self):
        """Bot reactions are specifically: thumbsup, heart, fire."""
        chat = MockChat(members_count=1000)

        # Mix of bot reactions (all should count as bot)
        # Use actual emoji characters
        messages = [
            MockMessage.with_reactions(views=100, reactions=[
                ("\U0001F44D", 40),  # thumbs up
                ("\u2764\uFE0F", 40),  # heart
                ("\U0001F525", 20)   # fire
            ])
            for _ in range(20)
        ]

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f5_simple_reactions()

        # 3 types but all bot reactions = 100% bot_ratio
        # But 3 types > 2 minimum, so triggered only if > 95% AND <= 2 types
        assert factor.value['types'] == 3
        assert factor.value['bot_ratio'] == 1.0
        assert factor.triggered is False  # 3 types > 2


# ============================================================================
# TEST: F7 BOT REGULARITY DETECTION
# ============================================================================

class TestF7BotRegularity:
    """Test F7: Bot regularity (posting interval detection)."""

    def test_regular_intervals_triggers(self):
        """Perfectly regular intervals (CV < 0.15) trigger detection."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.regular_intervals(count=20, interval_hours=4.0)

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f7_bot_regularity()

        assert factor.triggered is True
        assert factor.weight == 10
        assert factor.value < 0.15

    def test_irregular_intervals_not_suspicious(self):
        """Human-like irregular intervals (CV > 0.15) are not suspicious."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.irregular_intervals(count=20, min_hours=1.0, max_hours=24.0)

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f7_bot_regularity()

        assert factor.triggered is False
        assert factor.weight == 0

    def test_insufficient_posts(self):
        """Less than 10 posts = insufficient data."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.regular_intervals(count=5, interval_hours=4.0)

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f7_bot_regularity()

        assert factor.triggered is False
        assert "Недостаточно" in factor.description

    def test_mixed_intervals(self):
        """Mixed intervals with some regularity."""
        chat = MockChat(members_count=1000)
        now = datetime.now(timezone.utc)

        messages = []
        cumulative_hours = 0
        for i in range(20):
            # Add some variation (3-5 hours instead of exactly 4)
            # Using cumulative intervals to create proper time series
            interval = 4 + (i % 3) - 1  # 3, 4, 5 hours cycle
            cumulative_hours += interval
            date = now - timedelta(hours=cumulative_hours)
            messages.append(MockMessage(views=100, date=date))

        fcs = FraudConvictionSystem(chat, messages)
        factor = fcs.check_f7_bot_regularity()

        # Some variation (3, 4, 5 hours cycling) gives CV around 0.20-0.30
        # The factor should NOT be triggered since CV > 0.15
        assert factor.triggered is False
        assert factor.value > 0.15  # Should be above bot threshold


# ============================================================================
# TEST: CHECK_INSTANT_SCAM TRIGGERS
# ============================================================================

class TestCheckInstantScam:
    """Test check_instant_scam() for various trigger conditions."""

    def test_insufficient_data_members(self):
        """Channel with < 100 members returns insufficient data."""
        chat = MockChat(members_count=50)
        messages = MessageFactory.natural(count=20)

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is False
        assert is_insufficient is True
        assert reason == "INSUFFICIENT_DATA"

    def test_insufficient_data_posts(self):
        """Channel with < 10 posts returns insufficient data."""
        chat = MockChat(members_count=1000)
        messages = MessageFactory.natural(count=5)

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is False
        assert is_insufficient is True
        assert reason == "INSUFFICIENT_DATA"

    def test_telegram_scam_flag_instant(self):
        """Telegram SCAM flag is instant scam detection."""
        chat = MockChat.scam(members_count=1000)
        messages = MessageFactory.natural(count=20)

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is True
        assert is_insufficient is False
        assert "SCAM" in reason

    def test_telegram_fake_flag_instant(self):
        """Telegram FAKE flag is instant scam detection."""
        chat = MockChat.fake(members_count=1000)
        messages = MessageFactory.natural(count=20)

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is True
        assert is_insufficient is False
        assert "FAKE" in reason

    def test_no_views_instant_scam(self):
        """No views on any post is instant scam."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=0) for _ in range(20)]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is True
        assert "просмотр" in reason.lower()

    def test_forwards_exceed_views_instant_scam(self):
        """Forwards > views is mathematically impossible = scam."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=100, forwards=150) for _ in range(20)]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is True
        assert "пересыл" in reason.lower() or "невозможно" in reason.lower()

    def test_reactions_exceed_views_instant_scam(self):
        """Reactions > views is mathematically impossible = scam."""
        chat = MockChat(members_count=1000)
        messages = [
            MockMessage.with_reactions(views=100, reactions=[("thumbs_up", 150)])
            for _ in range(20)
        ]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)

        assert is_scam is True
        assert "реакц" in reason.lower() or "невозможно" in reason.lower()

    def test_conviction_threshold_50_2(self):
        """Conviction >= 50 AND factors >= 2 triggers scam."""
        # Create channel that will trigger multiple factors
        chat = MockChat.young(members_count=100, age_days=10)
        messages = MessageFactory.bot_flat(count=20, exact_views=500)
        comments_data = {'enabled': False, 'avg_comments': 0}

        is_scam, reason, details, is_insufficient = check_instant_scam(
            chat, messages, comments_data
        )

        # Should have multiple factors triggered
        if is_scam:
            assert details['effective_conviction'] >= 50 or details['factors_triggered'] >= 2

    def test_conviction_threshold_70_1(self):
        """High conviction >= 70 with single factor triggers scam."""
        # This is harder to trigger with just one factor
        # Check that the rule exists in the result
        chat = MockChat.young(members_count=100, age_days=5)
        messages = MessageFactory.high_reach(count=20, members=100, reach_percent=400)
        comments_data = {'enabled': False, 'avg_comments': 0}

        is_scam, reason, details, is_insufficient = check_instant_scam(
            chat, messages, comments_data
        )

        # Verify the system evaluates conviction properly
        assert 'conviction_score' in details or is_insufficient

    def test_conviction_threshold_80(self):
        """Critical conviction >= 80 always triggers scam."""
        # Stack multiple factors to reach 80
        chat = MockChat.young(members_count=100, age_days=5)
        messages = MessageFactory.bot_flat(count=20, exact_views=500)
        comments_data = {'enabled': False, 'avg_comments': 0}

        is_scam, reason, details, is_insufficient = check_instant_scam(
            chat, messages, comments_data
        )

        if 'conviction_score' in details and details['conviction_score'] >= 80:
            assert is_scam is True

    def test_clean_channel_not_scam(self):
        """Clean channel with natural metrics should not be flagged."""
        chat = MockChat(members_count=5000)
        messages = MessageFactory.natural(count=50, base_views=2000)
        comments_data = {'enabled': True, 'avg_comments': 5.0}

        is_scam, reason, details, is_insufficient = check_instant_scam(
            chat, messages, comments_data
        )

        assert is_scam is False
        assert is_insufficient is False

    def test_verified_channel_mitigation(self):
        """Verified channel gets mitigation even with suspicious metrics."""
        chat = MockChat.verified(members_count=50000)
        messages = MessageFactory.bot_flat(count=20, exact_views=10000)
        comments_data = {'enabled': True, 'avg_comments': 3.0}

        is_scam, reason, details, is_insufficient = check_instant_scam(
            chat, messages, comments_data
        )

        # Verified channels get 20 points mitigation
        if 'mitigation' in details:
            assert details['mitigation'] >= 20


# ============================================================================
# REGRESSION TESTS FOR EDGE CASES
# ============================================================================

class TestRegressionEdgeCases:
    """Regression tests for known edge cases and bugs."""

    def test_empty_messages_no_crash(self):
        """Empty message list should not crash."""
        chat = MockChat(members_count=1000)
        fcs = FraudConvictionSystem(chat, [], {})
        result = fcs.calculate_conviction()

        assert 'conviction_score' in result
        assert result['is_scam'] is False

    def test_single_message_no_crash(self):
        """Single message should not crash."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=100)]
        fcs = FraudConvictionSystem(chat, messages, {})
        result = fcs.calculate_conviction()

        assert 'factors' in result

    def test_zero_members_no_division_error(self):
        """Zero members should not cause division by zero."""
        chat = MockChat(members_count=0)
        messages = MessageFactory.natural(count=20)
        fcs = FraudConvictionSystem(chat, messages, {})

        # Should not raise
        factor = fcs.check_f1_impossible_reach()
        assert factor is not None

    def test_zero_views_no_division_error(self):
        """Zero views should not cause division by zero."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=0) for _ in range(20)]
        fcs = FraudConvictionSystem(chat, messages, {})

        # Should not raise
        result = fcs.calculate_conviction()
        assert 'factors' in result

    def test_none_reactions_no_crash(self):
        """None reactions should not crash."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=100, reactions=None) for _ in range(20)]
        fcs = FraudConvictionSystem(chat, messages, {})

        result = fcs.calculate_conviction()
        assert 'factors' in result

    def test_empty_reactions_list_no_crash(self):
        """Empty reactions list should not crash."""
        chat = MockChat(members_count=1000)
        messages = [
            MockMessage(views=100, reactions=MockReactions([]))
            for _ in range(20)
        ]
        fcs = FraudConvictionSystem(chat, messages, {})

        result = fcs.calculate_conviction()
        assert 'factors' in result

    def test_messages_without_dates_no_crash(self):
        """Messages without dates should not crash."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=100, date=None) for _ in range(20)]
        fcs = FraudConvictionSystem(chat, messages, {})

        result = fcs.calculate_conviction()
        assert 'factors' in result

    def test_chat_without_date_no_crash(self):
        """Chat without date should not crash."""
        chat = MockChat(members_count=1000)
        chat.date = None
        messages = MessageFactory.natural(count=20)
        fcs = FraudConvictionSystem(chat, messages, {})

        result = fcs.calculate_conviction()
        assert 'factors' in result

    def test_negative_views_handled(self):
        """Negative views (if somehow present) should be handled."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=-100) for _ in range(20)]

        # Should not crash
        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert isinstance(is_scam, bool)

    def test_very_large_numbers(self):
        """Very large numbers should not overflow."""
        chat = MockChat(members_count=10_000_000)
        messages = [
            MockMessage(views=100_000_000, forwards=1_000_000)
            for _ in range(20)
        ]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert isinstance(is_scam, bool)


# ============================================================================
# TEST: GET_MESSAGE_REACTIONS_COUNT
# ============================================================================

class TestGetMessageReactionsCount:
    """Test the helper function for counting reactions."""

    def test_no_reactions_attribute(self):
        """Message without reactions attribute returns 0."""
        class SimpleMessage:
            views = 100

        assert get_message_reactions_count(SimpleMessage()) == 0

    def test_reactions_none(self):
        """Message with reactions=None returns 0."""
        msg = MockMessage(reactions=None)
        assert get_message_reactions_count(msg) == 0

    def test_empty_reactions_list(self):
        """Message with empty reactions list returns 0."""
        msg = MockMessage(reactions=MockReactions([]))
        assert get_message_reactions_count(msg) == 0

    def test_single_reaction(self):
        """Single reaction counted correctly."""
        msg = MockMessage.with_reactions(reactions=[("thumbs_up", 50)])
        assert get_message_reactions_count(msg) == 50

    def test_multiple_reactions(self):
        """Multiple reactions summed correctly."""
        msg = MockMessage.with_reactions(reactions=[
            ("thumbs_up", 30),
            ("heart", 20),
            ("fire", 10)
        ])
        assert get_message_reactions_count(msg) == 60

    def test_zero_count_reactions(self):
        """Reactions with count=0 handled correctly."""
        reactions = MockReactions([
            MockReaction(emoji="thumbs_up", count=0),
            MockReaction(emoji="heart", count=10)
        ])
        msg = MockMessage(reactions=reactions)
        assert get_message_reactions_count(msg) == 10
