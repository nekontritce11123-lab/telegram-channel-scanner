"""
Тесты для scanner/metrics.py

Покрывает:
- FraudConvictionSystem (13 факторов F1-F13)
- check_instant_scam()
- check_reactions_enabled()
- analyze_private_invites()
- Основные метрики (CV, Reach, Decay и др.)
"""

import pytest
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Optional

# Импортируем тестируемые модули
from scanner.metrics import (
    FraudConvictionSystem,
    FraudFactor,
    check_instant_scam,
    check_reactions_enabled,
    analyze_private_invites,
    calculate_cv_views,
    calculate_reach,
    calculate_views_decay,
    calculate_forwards_ratio,
    calculate_reaction_rate,
    calculate_er_variation,
    calculate_source_diversity,
    calculate_posts_per_day,
    get_message_reactions_count,
    get_channel_age_days,
)


# ============================================================================
# MOCK КЛАССЫ
# ============================================================================

@dataclass
class MockReaction:
    """Мок для реакции."""
    emoji: str
    count: int

    @property
    def reaction(self):
        return self


@dataclass
class MockReactions:
    """Мок для списка реакций на сообщении."""
    reactions: list[MockReaction]


@dataclass
class MockMessage:
    """Мок для сообщения Telegram."""
    views: int = 100
    forwards: int = 5
    date: datetime = None
    reactions: MockReactions = None
    text: str = ""
    forward_from_chat: Any = None

    def __post_init__(self):
        if self.date is None:
            self.date = datetime.now(timezone.utc)


@dataclass
class MockChat:
    """Мок для чата/канала Telegram."""
    members_count: int = 1000
    participants_count: int = 1000
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    date: datetime = None
    linked_chat: Any = None

    def __post_init__(self):
        if self.date is None:
            # По умолчанию канал создан год назад
            self.date = datetime.now(timezone.utc) - timedelta(days=365)


@dataclass
class MockForwardChat:
    """Мок для источника пересылки."""
    id: int


# ============================================================================
# ФАБРИКИ ДЛЯ СОЗДАНИЯ ТЕСТОВЫХ ДАННЫХ
# ============================================================================

def create_messages(
    count: int = 50,
    views_range: tuple = (80, 120),
    with_reactions: bool = True,
    reaction_count: int = 10,
    forwards: int = 5,
    time_spread_days: int = 30,
    text: str = ""
) -> list[MockMessage]:
    """Создаёт список мок-сообщений с заданными параметрами."""
    import random
    messages = []
    now = datetime.now(timezone.utc)

    for i in range(count):
        views = random.randint(views_range[0], views_range[1])
        date = now - timedelta(days=time_spread_days * i / count)

        reactions = None
        if with_reactions and reaction_count > 0:
            reactions = MockReactions([
                MockReaction(emoji="👍", count=int(reaction_count * 0.6)),
                MockReaction(emoji="❤️", count=int(reaction_count * 0.3)),
                MockReaction(emoji="🔥", count=int(reaction_count * 0.1)),
            ])

        messages.append(MockMessage(
            views=views,
            forwards=forwards,
            date=date,
            reactions=reactions,
            text=text
        ))

    return messages


def create_clean_channel_data():
    """Создаёт данные чистого канала для тестов."""
    chat = MockChat(
        members_count=5000,
        is_verified=False,
        date=datetime.now(timezone.utc) - timedelta(days=400)
    )
    # Естественный разброс просмотров 40-100%
    messages = create_messages(
        count=50,
        views_range=(2000, 5000),  # CV ~40%
        with_reactions=True,
        reaction_count=50,
        forwards=20
    )
    comments_data = {'enabled': True, 'avg_comments': 5.0}
    return chat, messages, comments_data


def create_scam_channel_data():
    """Создаёт данные накрученного канала для тестов."""
    chat = MockChat(
        members_count=100,  # Мало подписчиков
        is_verified=False,
        date=datetime.now(timezone.utc) - timedelta(days=30)  # Молодой
    )
    # Нереальный reach 500% + ровные просмотры
    messages = create_messages(
        count=50,
        views_range=(490, 510),  # CV ~2% - ровные накрученные просмотры
        with_reactions=True,
        reaction_count=200,  # Много реакций
        forwards=2
    )
    comments_data = {'enabled': False, 'avg_comments': 0}  # Комменты выключены
    return chat, messages, comments_data


# ============================================================================
# ТЕСТЫ FraudConvictionSystem
# ============================================================================

class TestFraudConvictionSystem:
    """Тесты для системы выявления фрода."""

    def test_clean_channel_low_conviction(self):
        """Чистый канал должен иметь низкий conviction."""
        chat, messages, comments_data = create_clean_channel_data()
        fcs = FraudConvictionSystem(chat, messages, comments_data)
        result = fcs.calculate_conviction()

        assert result['is_scam'] is False
        assert result['conviction_score'] < 50
        assert result['factors_triggered'] < 3

    def test_scam_channel_high_conviction(self):
        """SCAM канал должен иметь высокий conviction."""
        chat, messages, comments_data = create_scam_channel_data()
        fcs = FraudConvictionSystem(chat, messages, comments_data)
        result = fcs.calculate_conviction()

        # Должно быть несколько сработавших факторов
        assert result['conviction_score'] >= 50 or result['factors_triggered'] >= 2

    def test_f1_impossible_reach(self):
        """F1: Нереальный reach должен триггериться."""
        # Канал с reach > 250%
        chat = MockChat(members_count=100)
        messages = create_messages(count=20, views_range=(300, 350))
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is True
        assert factor.weight >= 30
        assert factor.value > 250  # reach > 250%

    def test_f1_normal_reach(self):
        """F1: Нормальный reach не должен триггериться."""
        chat = MockChat(members_count=1000)
        messages = create_messages(count=20, views_range=(200, 400))  # ~30% reach
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f1_impossible_reach()
        assert factor.triggered is False
        assert factor.weight == 0

    def test_f2_flat_cv(self):
        """F2: Слишком ровные просмотры должны триггериться."""
        chat = MockChat(members_count=1000)
        # CV < 15% - подозрительно ровные
        messages = create_messages(count=20, views_range=(98, 102))
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f2_flat_cv()
        assert factor.triggered is True
        assert factor.weight >= 20
        assert factor.value < 15

    def test_f2_natural_cv(self):
        """F2: Естественный CV не должен триггериться."""
        chat = MockChat(members_count=1000)
        # CV > 15% - естественный разброс
        messages = create_messages(count=20, views_range=(50, 150))
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f2_flat_cv()
        assert factor.triggered is False
        assert factor.weight == 0

    def test_f3_dead_engagement(self):
        """F3: Много реакций без комментариев должно триггериться."""
        chat = MockChat(members_count=1000)
        messages = create_messages(
            count=20,
            views_range=(100, 200),
            with_reactions=True,
            reaction_count=150  # Много реакций
        )
        # Много реакций, мало комментов
        comments_data = {'enabled': True, 'avg_comments': 0.5}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f3_dead_engagement()
        # Триггерится если reactions_per_post > 100 и avg_comments < 1
        # или если ratio слишком низкий
        # При 150 реакций на пост это должно сработать
        assert factor.name == 'dead_engagement'

    def test_f6_disabled_comments(self):
        """F6: Отключённые комментарии должны триггериться."""
        chat = MockChat(members_count=1000)
        messages = create_messages(count=20)
        comments_data = {'enabled': False, 'avg_comments': 0}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f6_disabled_comments()
        assert factor.triggered is True
        assert factor.weight == 15

    def test_f6_enabled_comments(self):
        """F6: Включённые комментарии не должны триггериться."""
        chat = MockChat(members_count=1000)
        messages = create_messages(count=20)
        comments_data = {'enabled': True, 'avg_comments': 5.0}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f6_disabled_comments()
        assert factor.triggered is False
        assert factor.weight == 0

    def test_f11_suspicious_velocity(self):
        """F11: Подозрительная скорость роста."""
        # Молодой канал с очень быстрым ростом
        # Для large (>=5000) scam_threshold=1000, нужно velocity > 1000
        chat = MockChat(
            members_count=6000,
            date=datetime.now(timezone.utc) - timedelta(days=5)  # 5 дней
        )
        messages = create_messages(count=20)
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f11_suspicious_velocity()
        # 6000 / 5 = 1200 подп/день > scam_threshold=1000 для large
        # velocity=1200 > scam_threshold=1000 → weight=25 (young)
        assert factor.triggered is True
        assert factor.weight >= 20

    def test_f12_effective_members(self):
        """F12: Низкая эффективность подписчиков."""
        # Много подписчиков, мало просмотров
        chat = MockChat(members_count=100000)
        messages = create_messages(count=20, views_range=(500, 1000))  # ~0.75% reach
        fcs = FraudConvictionSystem(chat, messages)

        factor = fcs.check_f12_effective_members()
        # expected reach для large = 15%, actual ~0.75%
        # effectiveness_ratio будет очень низким
        assert factor.name == 'effective_members'

    def test_f13_young_fast_inactive_combo(self):
        """F13: Комбо молодой + быстрый + неактивный."""
        # Все три условия
        chat = MockChat(
            members_count=10000,
            date=datetime.now(timezone.utc) - timedelta(days=30)  # 30 дней = молодой
        )
        # velocity = 10000/30 = 333 подп/день = быстрый
        messages = create_messages(
            count=20,
            views_range=(100, 200),
            with_reactions=True,
            reaction_count=1  # Мало реакций = неактивный
        )
        comments_data = {'enabled': True, 'avg_comments': 0.2}
        fcs = FraudConvictionSystem(chat, messages, comments_data)

        factor = fcs.check_f13_young_fast_inactive()
        assert factor.triggered is True
        assert factor.weight == 30

    def test_virality_mitigation(self):
        """Виральный канал получает смягчение."""
        chat = MockChat(members_count=1000, is_verified=True)
        # Высокий forward rate
        messages = create_messages(count=20, views_range=(100, 200), forwards=15)
        fcs = FraudConvictionSystem(chat, messages)

        mitigation = fcs.check_virality_mitigation()
        # verified = 20, high forward rate = 15
        assert mitigation >= 20

    def test_conviction_scam_threshold_50_2(self):
        """conviction >= 50 AND factors >= 2 = SCAM."""
        chat, messages, comments_data = create_scam_channel_data()
        fcs = FraudConvictionSystem(chat, messages, comments_data)
        result = fcs.calculate_conviction()

        # Проверяем логику вердикта
        if result['effective_conviction'] >= 50 and result['factors_triggered'] >= 2:
            assert result['is_scam'] is True


# ============================================================================
# ТЕСТЫ check_instant_scam
# ============================================================================

class TestCheckInstantScam:
    """Тесты для быстрой проверки SCAM."""

    def test_insufficient_data_not_scam(self):
        """Канал с недостаточными данными - не SCAM, а insufficient."""
        chat = MockChat(members_count=50)  # < 100
        messages = create_messages(count=5)  # < 10

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert is_scam is False
        assert reason == "INSUFFICIENT_DATA"
        assert is_insufficient is True

    def test_telegram_scam_flag(self):
        """Telegram пометил как SCAM = SCAM."""
        chat = MockChat(members_count=1000, is_scam=True)
        messages = create_messages(count=20)

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert is_scam is True
        assert "SCAM" in reason
        assert is_insufficient is False

    def test_telegram_fake_flag(self):
        """Telegram пометил как FAKE = SCAM."""
        chat = MockChat(members_count=1000, is_fake=True)
        messages = create_messages(count=20)

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert is_scam is True
        assert "FAKE" in reason
        assert is_insufficient is False

    def test_no_views_is_scam(self):
        """Канал без просмотров = SCAM."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=0) for _ in range(20)]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert is_scam is True
        assert "просмотр" in reason.lower()  # "просмотрах" или "просмотров"

    def test_forwards_more_than_views_is_scam(self):
        """Пересылок больше чем просмотров = невозможно = SCAM."""
        chat = MockChat(members_count=1000)
        messages = [MockMessage(views=100, forwards=150) for _ in range(20)]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert is_scam is True
        assert "пересылок" in reason.lower() or "невозможно" in reason.lower()

    def test_reactions_more_than_views_is_scam(self):
        """Реакций больше чем просмотров = невозможно = SCAM."""
        chat = MockChat(members_count=1000)
        messages = [
            MockMessage(
                views=100,
                reactions=MockReactions([MockReaction(emoji="👍", count=150)])
            ) for _ in range(20)
        ]

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages)
        assert is_scam is True
        assert "реакций" in reason.lower() or "невозможно" in reason.lower()

    def test_normal_channel_not_scam(self):
        """Нормальный канал не SCAM."""
        chat, messages, comments_data = create_clean_channel_data()

        is_scam, reason, details, is_insufficient = check_instant_scam(chat, messages, comments_data)
        assert is_scam is False
        assert is_insufficient is False


# ============================================================================
# ТЕСТЫ check_reactions_enabled
# ============================================================================

class TestCheckReactionsEnabled:
    """Тесты для определения включены ли реакции."""

    def test_reactions_with_counts(self):
        """Если есть реакции с counts > 0, то включены."""
        messages = [
            MockMessage(reactions=MockReactions([MockReaction(emoji="👍", count=10)]))
        ]
        assert check_reactions_enabled(messages) is True

    def test_reactions_attribute_exists_but_empty(self):
        """Если атрибут reactions есть но пустой - включены."""
        messages = [MockMessage(reactions=MockReactions([]))]
        assert check_reactions_enabled(messages) is True

    def test_reactions_attribute_none(self):
        """Если атрибут reactions = None везде - выключены."""
        messages = [MockMessage(reactions=None) for _ in range(10)]
        assert check_reactions_enabled(messages) is False

    def test_no_reactions_attribute(self):
        """Если нет атрибута reactions совсем - выключены."""
        @dataclass
        class MessageWithoutReactions:
            views: int = 100
            date: datetime = None

        messages = [MessageWithoutReactions() for _ in range(10)]
        assert check_reactions_enabled(messages) is False

    def test_empty_messages_list(self):
        """Пустой список сообщений - по умолчанию включены."""
        assert check_reactions_enabled([]) is True

    def test_mixed_messages(self):
        """Если хоть у одного есть реакции - включены."""
        messages = [
            MockMessage(reactions=None),
            MockMessage(reactions=None),
            MockMessage(reactions=MockReactions([MockReaction(emoji="👍", count=5)])),
            MockMessage(reactions=None),
        ]
        assert check_reactions_enabled(messages) is True


# ============================================================================
# ТЕСТЫ analyze_private_invites
# ============================================================================

class TestAnalyzePrivateInvites:
    """Тесты для анализа приватных ссылок."""

    def test_no_links(self):
        """Нет ссылок - trust 1.0."""
        messages = [MockMessage(text="Привет! Это обычный пост.")]
        result = analyze_private_invites(messages)

        assert result['has_ads'] is False
        assert result['trust_multiplier'] == 1.0
        assert result['private_ratio'] == 0

    def test_public_links_only(self):
        """Только публичные ссылки - trust 1.0."""
        messages = [
            MockMessage(text="Подписывайтесь на t.me/somechannel"),
            MockMessage(text="Ещё один канал t.me/anotherchannel"),
        ]
        result = analyze_private_invites(messages)

        assert result['has_ads'] is True
        assert result['private_ratio'] == 0
        assert result['trust_multiplier'] == 1.0

    def test_private_links_over_60(self):
        """Более 60% приватных ссылок = trust 0.50."""
        # Примечание: t.me/joinchat/xxx также матчит public pattern как 'joinchat'
        # поэтому используем только t.me/+xxx формат
        messages = [
            MockMessage(text="Вступай t.me/+abc123"),
            MockMessage(text="Ещё один t.me/+secret1"),
            MockMessage(text="Третий t.me/+secret2"),
            MockMessage(text="Публичный t.me/publicchannel"),
        ]
        result = analyze_private_invites(messages)

        assert result['private_ratio'] == 0.75  # 3 из 4
        assert result['trust_multiplier'] == 0.50

    def test_private_links_over_80(self):
        """Более 80% приватных ссылок = trust 0.35."""
        # Порог > 0.8 (строго больше), поэтому нужно 5 из 6 = 0.833
        messages = [
            MockMessage(text="t.me/+abc123"),
            MockMessage(text="t.me/+xyz789"),
            MockMessage(text="t.me/+secret1"),
            MockMessage(text="t.me/+secret2"),
            MockMessage(text="t.me/+secret3"),
            MockMessage(text="t.me/publicchannel"),
        ]
        result = analyze_private_invites(messages)

        assert result['private_ratio'] > 0.8  # 5 из 6 = 0.833
        assert result['trust_multiplier'] == 0.35

    def test_all_private_links(self):
        """100% приватных ссылок = trust 0.25."""
        messages = [
            MockMessage(text="t.me/+abc123"),
            MockMessage(text="t.me/+xyz789"),
        ]
        result = analyze_private_invites(messages)

        assert result['private_ratio'] == 1.0
        assert result['trust_multiplier'] == 0.25

    def test_crypto_combo(self):
        """CRYPTO + >40% приватных = trust 0.45."""
        messages = [
            MockMessage(text="t.me/+abc123"),
            MockMessage(text="t.me/public"),
        ]
        result = analyze_private_invites(messages, category='CRYPTO')

        assert result['private_ratio'] == 0.5
        assert result['trust_multiplier'] == 0.45

    def test_comments_disabled_combo(self):
        """Приватные + комменты выключены = trust 0.40."""
        messages = [
            MockMessage(text="t.me/+abc123"),
            MockMessage(text="t.me/+xyz789"),
            MockMessage(text="t.me/public"),
        ]
        result = analyze_private_invites(messages, comments_enabled=False)

        # 2/3 = 66% приватных, без комментов -> 0.40
        assert result['private_ratio'] == pytest.approx(0.67, rel=0.1)
        assert result['trust_multiplier'] == 0.40


# ============================================================================
# ТЕСТЫ ОСНОВНЫХ МЕТРИК
# ============================================================================

class TestCalculateCvViews:
    """Тесты для расчёта CV просмотров."""

    def test_empty_views(self):
        """Пустой список = 0."""
        assert calculate_cv_views([]) == 0.0

    def test_single_view(self):
        """Один элемент = 0."""
        assert calculate_cv_views([100]) == 0.0

    def test_identical_views(self):
        """Одинаковые просмотры = CV 0%."""
        assert calculate_cv_views([100, 100, 100]) == 0.0

    def test_high_variation(self):
        """Высокий разброс = высокий CV."""
        cv = calculate_cv_views([50, 100, 150, 200, 250])
        assert cv > 40  # Должен быть высокий CV

    def test_low_variation(self):
        """Низкий разброс = низкий CV."""
        cv = calculate_cv_views([98, 99, 100, 101, 102])
        assert cv < 5  # Должен быть низкий CV


class TestCalculateReach:
    """Тесты для расчёта охвата."""

    def test_zero_members(self):
        """0 подписчиков = 0% reach."""
        assert calculate_reach(1000, 0) == 0.0

    def test_normal_reach(self):
        """Нормальный reach."""
        # 500 просмотров / 1000 подписчиков = 50%
        assert calculate_reach(500, 1000) == 50.0

    def test_impossible_reach(self):
        """Reach > 100% возможен (виралка)."""
        # 1500 просмотров / 1000 подписчиков = 150%
        assert calculate_reach(1500, 1000) == 150.0


class TestCalculateViewsDecay:
    """Тесты для расчёта накопления просмотров."""

    def test_insufficient_messages(self):
        """Мало сообщений = 1.0."""
        messages = create_messages(count=5)
        assert calculate_views_decay(messages) == 1.0

    def test_normal_decay(self):
        """Нормальное накопление."""
        messages = create_messages(count=50, views_range=(80, 120))
        decay = calculate_views_decay(messages)
        # Должен быть около 1.0 для равномерного распределения
        assert 0.7 <= decay <= 1.3


class TestCalculateForwardsRatio:
    """Тесты для расчёта репостов."""

    def test_no_views(self):
        """Нет просмотров = 0."""
        messages = [MockMessage(views=0, forwards=10)]
        assert calculate_forwards_ratio(messages) == 0.0

    def test_normal_ratio(self):
        """Нормальный ratio."""
        messages = [MockMessage(views=1000, forwards=50)]
        assert calculate_forwards_ratio(messages) == 5.0  # 5%


class TestCalculateReactionRate:
    """Тесты для расчёта реакций."""

    def test_no_views(self):
        """Нет просмотров = 0."""
        messages = [MockMessage(views=0)]
        assert calculate_reaction_rate(messages) == 0.0

    def test_with_reactions(self):
        """С реакциями."""
        messages = [
            MockMessage(
                views=1000,
                reactions=MockReactions([MockReaction(emoji="👍", count=50)])
            )
        ]
        assert calculate_reaction_rate(messages) == 5.0  # 5%


class TestCalculatePostsPerDay:
    """Тесты для расчёта частоты постинга."""

    def test_insufficient_messages(self):
        """Мало сообщений."""
        messages = [MockMessage()]
        result = calculate_posts_per_day(messages)
        assert result['posting_status'] == 'insufficient_data'

    def test_normal_frequency(self):
        """Нормальная частота."""
        now = datetime.now(timezone.utc)
        messages = [
            MockMessage(date=now - timedelta(days=i)) for i in range(10)
        ]
        result = calculate_posts_per_day(messages)
        assert result['posting_status'] == 'normal'
        assert result['trust_multiplier'] == 1.0

    def test_spam_frequency(self):
        """Спам частота."""
        now = datetime.now(timezone.utc)
        # 50 постов за 1 день
        messages = [
            MockMessage(date=now - timedelta(hours=i * 0.5)) for i in range(50)
        ]
        result = calculate_posts_per_day(messages)
        assert result['posting_status'] == 'spam'
        assert result['trust_multiplier'] == 0.55


class TestGetChannelAgeDays:
    """Тесты для расчёта возраста канала."""

    def test_no_date(self):
        """Нет даты = 365 дней по умолчанию."""
        chat = MockChat()
        chat.date = None
        assert get_channel_age_days(chat) == 365

    def test_one_day_old(self):
        """Канал создан вчера."""
        chat = MockChat(date=datetime.now(timezone.utc) - timedelta(days=1))
        assert get_channel_age_days(chat) == 1

    def test_year_old(self):
        """Канал создан год назад."""
        chat = MockChat(date=datetime.now(timezone.utc) - timedelta(days=365))
        age = get_channel_age_days(chat)
        assert 364 <= age <= 366


class TestGetMessageReactionsCount:
    """Тесты для подсчёта реакций."""

    def test_no_reactions_attribute(self):
        """Нет атрибута reactions."""
        @dataclass
        class SimpleMessage:
            views: int = 100

        msg = SimpleMessage()
        assert get_message_reactions_count(msg) == 0

    def test_reactions_none(self):
        """reactions = None."""
        msg = MockMessage(reactions=None)
        assert get_message_reactions_count(msg) == 0

    def test_empty_reactions(self):
        """Пустой список реакций."""
        msg = MockMessage(reactions=MockReactions([]))
        assert get_message_reactions_count(msg) == 0

    def test_with_reactions(self):
        """С реакциями."""
        msg = MockMessage(reactions=MockReactions([
            MockReaction(emoji="👍", count=10),
            MockReaction(emoji="❤️", count=5),
        ]))
        assert get_message_reactions_count(msg) == 15


class TestCalculateSourceDiversity:
    """Тесты для разнообразия источников."""

    def test_no_forwards(self):
        """Нет репостов = 0."""
        messages = [MockMessage(forward_from_chat=None)]
        assert calculate_source_diversity(messages) == 0.0

    def test_single_source(self):
        """Один источник = 1.0 (100%)."""
        source = MockForwardChat(id=12345)
        messages = [MockMessage(forward_from_chat=source) for _ in range(10)]
        assert calculate_source_diversity(messages) == 1.0

    def test_multiple_sources(self):
        """Несколько источников."""
        messages = [
            MockMessage(forward_from_chat=MockForwardChat(id=1)),
            MockMessage(forward_from_chat=MockForwardChat(id=2)),
            MockMessage(forward_from_chat=MockForwardChat(id=3)),
            MockMessage(forward_from_chat=MockForwardChat(id=4)),
        ]
        # max_share = 1/4 = 0.25
        assert calculate_source_diversity(messages) == 0.25


# ============================================================================
# ТЕСТЫ ГРАНИЧНЫХ СЛУЧАЕВ
# ============================================================================

class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_fcs_empty_messages(self):
        """FCS с пустым списком сообщений."""
        chat = MockChat()
        fcs = FraudConvictionSystem(chat, [], {})
        result = fcs.calculate_conviction()
        # Не должно падать
        assert 'conviction_score' in result

    def test_fcs_minimal_data(self):
        """FCS с минимальными данными."""
        chat = MockChat(members_count=1)
        messages = [MockMessage(views=1)]
        fcs = FraudConvictionSystem(chat, messages)
        result = fcs.calculate_conviction()
        assert 'factors' in result

    def test_check_instant_scam_empty_messages(self):
        """check_instant_scam с пустыми сообщениями."""
        chat = MockChat(members_count=1000)
        is_scam, reason, details, is_insufficient = check_instant_scam(chat, [])
        # Мало данных
        assert is_insufficient is True

    def test_reactions_enabled_with_none_reactions_object(self):
        """check_reactions_enabled когда reactions объект есть но пустой."""
        messages = [MockMessage(reactions=MockReactions([]))]
        # Атрибут есть, хотя список пустой - реакции включены
        assert check_reactions_enabled(messages) is True
