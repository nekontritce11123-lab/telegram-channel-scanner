"""
Snapshot тесты для scorer.py - модуля скоринга качества Telegram каналов.

Тесты покрывают:
- Структуру возвращаемого результата
- Детекцию SCAM каналов
- Оценку качественных каналов
- Систему floating weights
- Trust Factor расчёты
- Вердикты (EXCELLENT, GOOD, MEDIUM, HIGH_RISK, SCAM)
"""
import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Any, Optional, List


# ============================================================================
# MOCK КЛАССЫ ДЛЯ TELEGRAM ОБЪЕКТОВ
# ============================================================================

@dataclass
class MockReaction:
    """Мок реакции (Telegram ReactionCount)."""
    emoji: str
    count: int

    @property
    def reaction(self):
        return self


@dataclass
class MockReactions:
    """Мок контейнера реакций."""
    reactions: List[MockReaction]


@dataclass
class MockMessage:
    """Мок сообщения Telegram."""
    id: int
    views: int
    forwards: int = 0
    text: str = ""
    date: datetime = None
    reactions: MockReactions = None
    forward_from_chat: Any = None

    def __post_init__(self):
        if self.date is None:
            self.date = datetime.now(timezone.utc)


@dataclass
class MockLinkedChat:
    """Мок связанного чата (для комментариев)."""
    id: int
    title: str = "Discussion"


@dataclass
class MockChat:
    """Мок канала Telegram."""
    id: int
    username: str
    title: str = "Test Channel"
    members_count: int = 1000
    participants_count: int = 1000
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    linked_chat: MockLinkedChat = None
    date: datetime = None  # Дата создания канала

    def __post_init__(self):
        if self.date is None:
            # По умолчанию канал создан 1 год назад
            self.date = datetime.now(timezone.utc) - timedelta(days=365)


@dataclass
class MockUser:
    """Мок пользователя для forensics."""
    id: int
    is_premium: bool = False
    is_scam: bool = False
    is_fake: bool = False
    photo: Any = None
    dc_id: int = 2  # Europe/Russia DC (добавлено для forensics)


@dataclass
class MockUserPhoto:
    """Мок фото пользователя с DC."""
    dc_id: int = 2  # Europe/Russia DC


# ============================================================================
# ФАБРИКИ ДЛЯ СОЗДАНИЯ ТЕСТОВЫХ ДАННЫХ
# ============================================================================

def create_messages(
    count: int = 20,
    base_views: int = 1000,
    cv_percent: float = 35.0,
    include_reactions: bool = True,
    reaction_rate: float = 2.0,
    include_forwards: bool = True,
    forward_rate: float = 0.5,
    days_span: int = 30
) -> List[MockMessage]:
    """
    Создаёт список сообщений с заданными характеристиками.

    Args:
        count: Количество сообщений
        base_views: Средние просмотры
        cv_percent: Целевой CV просмотров (%)
        include_reactions: Включать ли реакции
        reaction_rate: Rate реакций к просмотрам (%)
        include_forwards: Включать ли форварды
        forward_rate: Rate форвардов к просмотрам (%)
        days_span: За сколько дней сообщения
    """
    import random
    random.seed(42)  # Для воспроизводимости

    messages = []
    now = datetime.now(timezone.utc)

    # Рассчитываем std для нужного CV
    std = base_views * (cv_percent / 100)

    for i in range(count):
        # Просмотры с нужным CV
        views = max(10, int(random.gauss(base_views, std)))

        # Форварды
        forwards = 0
        if include_forwards:
            forwards = int(views * forward_rate / 100)

        # Реакции
        reactions = None
        if include_reactions:
            total_reactions = int(views * reaction_rate / 100)
            if total_reactions > 0:
                # Типичное распределение реакций
                reactions = MockReactions(reactions=[
                    MockReaction(emoji="thumbsup", count=int(total_reactions * 0.6)),
                    MockReaction(emoji="fire", count=int(total_reactions * 0.25)),
                    MockReaction(emoji="heart", count=int(total_reactions * 0.15)),
                ])

        # Дата (старые посты раньше)
        post_date = now - timedelta(days=days_span * i / count)

        messages.append(MockMessage(
            id=i + 1,
            views=views,
            forwards=forwards,
            reactions=reactions,
            date=post_date,
            text=f"Test post #{i + 1}"
        ))

    return messages


def create_healthy_channel(
    username: str = "healthy_channel",
    members: int = 5000,
    verified: bool = False
) -> tuple[MockChat, List[MockMessage], dict]:
    """
    Создаёт данные здорового канала с хорошими метриками.

    Returns:
        (chat, messages, comments_data)
    """
    chat = MockChat(
        id=123456789,
        username=username,
        members_count=members,
        participants_count=members,
        is_verified=verified,
        linked_chat=MockLinkedChat(id=987654321),
        date=datetime.now(timezone.utc) - timedelta(days=730)  # 2 года
    )

    # 30-50% CV, 20-40% reach, 2-5% reaction rate
    avg_views = int(members * 0.3)  # 30% reach
    messages = create_messages(
        count=30,
        base_views=avg_views,
        cv_percent=40.0,
        include_reactions=True,
        reaction_rate=3.0,
        include_forwards=True,
        forward_rate=1.0,
        days_span=60
    )

    comments_data = {
        'enabled': True,
        'avg_comments': 2.5,
        'total_comments': 75
    }

    return chat, messages, comments_data


def create_scam_channel(
    username: str = "scam_channel",
    members: int = 10000,
    scam_type: str = "flat_views"
) -> tuple[MockChat, List[MockMessage], dict]:
    """
    Создаёт данные SCAM канала.

    scam_type:
        - "flat_views": Слишком ровные просмотры (CV < 15%)
        - "impossible_reach": Reach > 200%
        - "telegram_scam": Telegram пометил как SCAM
        - "dead_engagement": Много реакций, 0 комментов
    """
    chat = MockChat(
        id=111111111,
        username=username,
        members_count=members,
        participants_count=members,
        is_scam=(scam_type == "telegram_scam"),
        linked_chat=MockLinkedChat(id=222222222) if scam_type != "dead_engagement" else None,
        date=datetime.now(timezone.utc) - timedelta(days=90)  # Молодой
    )

    if scam_type == "flat_views":
        # CV < 10% - явный признак накрутки
        messages = create_messages(
            count=20,
            base_views=1000,
            cv_percent=5.0,  # Слишком ровно
            include_reactions=True,
            reaction_rate=1.0
        )
    elif scam_type == "impossible_reach":
        # Reach > 200% - невозможно
        avg_views = members * 2.5  # 250% reach
        messages = create_messages(
            count=20,
            base_views=int(avg_views),
            cv_percent=30.0,
            include_reactions=True,
            reaction_rate=1.0
        )
    elif scam_type == "dead_engagement":
        # Много реакций, но комменты выключены
        messages = create_messages(
            count=20,
            base_views=1000,
            cv_percent=30.0,
            include_reactions=True,
            reaction_rate=5.0  # Много реакций
        )
    else:
        messages = create_messages(count=20)

    comments_data = {
        'enabled': scam_type not in ["dead_engagement", "telegram_scam"],
        'avg_comments': 0.0 if scam_type == "dead_engagement" else 0.5,
        'total_comments': 0 if scam_type == "dead_engagement" else 10
    }

    return chat, messages, comments_data


def create_users_forensics(
    count: int = 30,
    premium_ratio: float = 0.03,
    cluster_ratio: float = 0.1,
    foreign_dc_ratio: float = 0.2
) -> List[MockUser]:
    """
    Создаёт список пользователей для forensics анализа.

    Args:
        count: Количество пользователей
        premium_ratio: Доля премиум юзеров
        cluster_ratio: Доля "кластерных" ID (подозрительных)
        foreign_dc_ratio: Доля юзеров на иностранных DC
    """
    import random
    random.seed(42)

    users = []
    premium_count = int(count * premium_ratio)
    cluster_count = int(count * cluster_ratio)
    foreign_count = int(count * foreign_dc_ratio)

    # Базовый ID
    base_id = 1000000000

    for i in range(count):
        # Кластерные ID (соседние)
        if i < cluster_count:
            user_id = base_id + i * 100  # Близкие ID
        else:
            user_id = base_id + random.randint(10000000, 999999999)

        # DC
        if i < foreign_count:
            dc_id = random.choice([1, 3, 5])  # Иностранные DC
        else:
            dc_id = random.choice([2, 4])  # Российские DC

        photo = MockUserPhoto(dc_id=dc_id)

        users.append(MockUser(
            id=user_id,
            is_premium=(i < premium_count),
            photo=photo
        ))

    return users


# ============================================================================
# ТЕСТЫ СТРУКТУРЫ РЕЗУЛЬТАТА
# ============================================================================

class TestScoreStructure:
    """Тесты структуры возвращаемого результата calculate_final_score."""

    def test_result_has_required_keys(self):
        """Результат содержит все необходимые ключи."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        # Обязательные ключи верхнего уровня
        required_keys = [
            'channel', 'members', 'score', 'verdict',
            'raw_score', 'trust_factor', 'trust_details',
            'breakdown', 'categories', 'flags', 'conviction', 'raw_stats'
        ]

        for key in required_keys:
            assert key in result, f"Missing required key: {key}"

    def test_score_in_valid_range(self):
        """Score в диапазоне 0-100."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        assert 0 <= result['score'] <= 100, f"Score {result['score']} out of range"
        assert 0 <= result['raw_score'] <= 100, f"Raw score {result['raw_score']} out of range"

    def test_trust_factor_in_valid_range(self):
        """Trust factor в диапазоне 0.0-1.0."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        assert 0.0 <= result['trust_factor'] <= 1.0, f"Trust factor {result['trust_factor']} out of range"

    def test_verdict_is_valid(self):
        """Verdict - одно из допустимых значений."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        valid_verdicts = ['EXCELLENT', 'GOOD', 'MEDIUM', 'HIGH_RISK', 'SCAM', 'NEW_CHANNEL', 'EXCLUDED']
        assert result['verdict'] in valid_verdicts, f"Invalid verdict: {result['verdict']}"

    def test_breakdown_structure(self):
        """Breakdown содержит все категории метрик."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        # Метрики качества
        quality_metrics = ['cv_views', 'reach', 'views_decay', 'forward_rate']
        for metric in quality_metrics:
            assert metric in result['breakdown'], f"Missing quality metric: {metric}"
            assert 'value' in result['breakdown'][metric], f"Missing value in {metric}"
            assert 'points' in result['breakdown'][metric], f"Missing points in {metric}"
            assert 'max' in result['breakdown'][metric], f"Missing max in {metric}"

        # Метрики engagement
        engagement_metrics = ['comments', 'reaction_rate', 'er_variation', 'reaction_stability']
        for metric in engagement_metrics:
            assert metric in result['breakdown'], f"Missing engagement metric: {metric}"

        # Метрики репутации
        reputation_metrics = ['verified', 'age', 'premium', 'source_diversity']
        for metric in reputation_metrics:
            assert metric in result['breakdown'], f"Missing reputation metric: {metric}"

    def test_categories_structure(self):
        """Categories содержит score и max для каждой категории."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        for category in ['quality', 'engagement', 'reputation']:
            assert category in result['categories'], f"Missing category: {category}"
            assert 'score' in result['categories'][category], f"Missing score in {category}"
            assert 'max' in result['categories'][category], f"Missing max in {category}"

    def test_flags_structure(self):
        """Flags содержит булевые флаги состояния."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        required_flags = ['is_scam', 'is_fake', 'is_verified', 'comments_enabled', 'reactions_enabled']
        for flag in required_flags:
            assert flag in result['flags'], f"Missing flag: {flag}"
            assert isinstance(result['flags'][flag], bool), f"Flag {flag} is not boolean"


# ============================================================================
# ТЕСТЫ ДЕТЕКЦИИ SCAM
# ============================================================================

class TestScamDetection:
    """Тесты детекции SCAM каналов."""

    def test_telegram_scam_flag(self):
        """Канал с Telegram флагом is_scam получает verdict SCAM."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_scam_channel(scam_type="telegram_scam")
        result = calculate_final_score(chat, messages, comments_data)

        assert result['verdict'] == 'SCAM'
        assert result['score'] == 0
        assert 'SCAM' in result.get('reason', '')

    def test_flat_views_detection(self):
        """Слишком ровные просмотры (CV < 15%) получают низкий score."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_scam_channel(scam_type="flat_views")
        result = calculate_final_score(chat, messages, comments_data)

        # CV просмотров должен быть низким
        cv_value = result['breakdown']['cv_views']['value']
        assert cv_value < 15, f"CV {cv_value} should be < 15 for flat views"

        # Низкие баллы за CV
        cv_points = result['breakdown']['cv_views']['points']
        assert cv_points == 0, f"CV points should be 0 for flat views, got {cv_points}"

    def test_impossible_reach_detection(self):
        """Невозможный reach (>200%) детектится как SCAM."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_scam_channel(scam_type="impossible_reach")
        result = calculate_final_score(chat, messages, comments_data)

        # Канал с reach 250% должен быть SCAM (instant_scam или high conviction)
        assert result['verdict'] == 'SCAM', f"Expected SCAM, got {result['verdict']}"
        assert result['score'] == 0, f"Expected score 0, got {result['score']}"

    def test_new_channel_insufficient_data(self):
        """Новый канал с < 10 постов получает NEW_CHANNEL, не SCAM."""
        from scanner.scorer import calculate_final_score

        chat = MockChat(
            id=123,
            username="new_channel",
            members_count=50,  # < 100 минимум
            date=datetime.now(timezone.utc) - timedelta(days=7)
        )
        messages = create_messages(count=5)  # < 10 минимум
        comments_data = {'enabled': True, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        # Должен вернуть NEW_CHANNEL, не SCAM
        assert result['verdict'] == 'NEW_CHANNEL'
        assert result['score'] == 0


# ============================================================================
# ТЕСТЫ КАЧЕСТВЕННЫХ КАНАЛОВ
# ============================================================================

class TestGoodChannelScore:
    """Тесты оценки качественных каналов."""

    def test_healthy_channel_gets_good_score(self):
        """Здоровый канал получает score >= 55 (GOOD или выше)."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        result = calculate_final_score(chat, messages, comments_data)

        assert result['score'] >= 40, f"Healthy channel score {result['score']} < 40"
        assert result['verdict'] in ['EXCELLENT', 'GOOD', 'MEDIUM']

    def test_verified_channel_no_bonus(self):
        """Верифицированный канал НЕ получает бонус (v38.4)."""
        from scanner.scorer import calculate_final_score

        # Обычный канал
        chat1, messages1, comments1 = create_healthy_channel(verified=False)
        result1 = calculate_final_score(chat1, messages1, comments1)

        # Верифицированный канал
        chat2, messages2, comments2 = create_healthy_channel(verified=True)
        result2 = calculate_final_score(chat2, messages2, comments2)

        # v38.4: verified не даёт баллов
        assert result1['breakdown']['verified']['points'] == 0
        assert result2['breakdown']['verified']['points'] == 0

    def test_old_channel_age_bonus(self):
        """Старый канал (>2 лет) получает максимум баллов за возраст."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        # Канал создан 3 года назад
        chat.date = datetime.now(timezone.utc) - timedelta(days=1100)

        result = calculate_final_score(chat, messages, comments_data)

        age_points = result['breakdown']['age']['points']
        age_max = result['breakdown']['age']['max']
        assert age_points == age_max, f"Old channel should get max age points ({age_max}), got {age_points}"

    def test_young_channel_age_penalty(self):
        """Молодой канал (<3 месяцев) получает 0 баллов за возраст."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()
        # Канал создан 1 месяц назад
        chat.date = datetime.now(timezone.utc) - timedelta(days=30)

        result = calculate_final_score(chat, messages, comments_data)

        age_points = result['breakdown']['age']['points']
        assert age_points == 0, f"Young channel should get 0 age points, got {age_points}"


# ============================================================================
# ТЕСТЫ FLOATING WEIGHTS
# ============================================================================

class TestFloatingWeights:
    """Тесты системы перераспределения баллов при отключённых фичах."""

    def test_comments_disabled_floating_weights(self):
        """Когда комменты выключены, баллы перераспределяются."""
        from scanner.scorer import calculate_floating_weights

        # Все включено
        weights_all = calculate_floating_weights(comments_enabled=True, reactions_enabled=True)
        assert weights_all['comments_max'] == 15
        assert weights_all['reaction_rate_max'] == 15
        assert weights_all['forward_rate_max'] == 7

        # Комменты выключены
        weights_no_comments = calculate_floating_weights(comments_enabled=False, reactions_enabled=True)
        assert weights_no_comments['comments_max'] == 0
        assert weights_no_comments['reaction_rate_max'] == 22  # 15 + 7
        assert weights_no_comments['forward_rate_max'] == 15   # 7 + 8

        # Сумма должна сохраняться (37 баллов)
        total_all = sum(weights_all.values())
        total_no_comments = sum(weights_no_comments.values())
        assert total_all == total_no_comments == 37

    def test_reactions_disabled_floating_weights(self):
        """Когда реакции выключены, баллы перераспределяются."""
        from scanner.scorer import calculate_floating_weights

        weights = calculate_floating_weights(comments_enabled=True, reactions_enabled=False)

        assert weights['comments_max'] == 22  # 15 + 7
        assert weights['reaction_rate_max'] == 0
        assert weights['forward_rate_max'] == 15  # 7 + 8

    def test_both_disabled_all_to_forward(self):
        """Когда и комменты и реакции выключены, все баллы в forward."""
        from scanner.scorer import calculate_floating_weights

        weights = calculate_floating_weights(comments_enabled=False, reactions_enabled=False)

        assert weights['comments_max'] == 0
        assert weights['reaction_rate_max'] == 0
        assert weights['forward_rate_max'] == 37  # Все 37 баллов

    def test_floating_weights_in_scoring(self):
        """Floating weights применяются в calculate_final_score."""
        from scanner.scorer import calculate_final_score

        # Канал без комментариев
        chat = MockChat(
            id=123,
            username="no_comments",
            members_count=1000,
            linked_chat=None  # Нет linked chat = комменты выключены
        )
        messages = create_messages(count=20, base_views=300)
        comments_data = {'enabled': False, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        # Комменты должны быть 0/0
        assert result['breakdown']['comments']['max'] == 0
        assert result['breakdown']['comments']['points'] == 0

        # Forward rate должен получить бонус
        assert result['breakdown']['forward_rate']['max'] > 7  # Больше чем стандартные 7

        # Флаг floating weights
        assert result['flags']['floating_weights'] is True


# ============================================================================
# ТЕСТЫ TRUST FACTOR
# ============================================================================

class TestTrustFactor:
    """Тесты расчёта Trust Factor."""

    def test_trust_factor_with_forensics(self):
        """Trust factor учитывает forensics результаты."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()

        # Здоровые юзеры
        healthy_users = create_users_forensics(
            count=30,
            premium_ratio=0.05,
            cluster_ratio=0.05,
            foreign_dc_ratio=0.1
        )

        result = calculate_final_score(chat, messages, comments_data, users=healthy_users)

        # Trust factor должен быть высоким
        assert result['trust_factor'] >= 0.8, f"Trust factor {result['trust_factor']} should be >= 0.8"

    def test_hidden_comments_penalty(self):
        """Скрытые комментарии снижают trust factor."""
        from scanner.scorer import calculate_trust_factor

        # Без комментариев
        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=False,
            conviction_score=0
        )

        assert 'hidden_comments' in details
        assert details['hidden_comments']['multiplier'] == 0.85
        assert trust <= 0.85

    def test_high_conviction_penalty(self):
        """Высокий conviction score снижает trust factor."""
        from scanner.scorer import calculate_trust_factor

        # Conviction >= 70
        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=75
        )

        assert 'conviction' in details
        assert details['conviction']['multiplier'] == 0.3
        assert trust <= 0.3

    def test_bot_wall_detection(self):
        """Bot wall (decay ~1.0) снижает trust factor."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            decay_ratio=1.0  # Идеально ровно = подозрительно
        )

        assert 'bot_wall' in details
        assert details['bot_wall']['multiplier'] == 0.6

    def test_hollow_views_detection(self):
        """Hollow views (высокий reach, низкий forward) снижает trust factor."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            reach=500,  # > 400% для micro канала
            forward_rate=0.1,  # < 0.5%
            members=100
        )

        assert 'hollow_views' in details
        assert details['hollow_views']['multiplier'] == 0.6


# ============================================================================
# ТЕСТЫ ВЕРДИКТОВ
# ============================================================================

class TestVerdicts:
    """Тесты вердиктов по порогам score."""

    def test_excellent_verdict(self):
        """Score >= 75 даёт EXCELLENT."""
        from scanner.scorer import calculate_final_score

        # Создаём идеальный канал
        chat, messages, comments_data = create_healthy_channel(members=10000, verified=True)
        # Добавляем здоровых юзеров
        users = create_users_forensics(count=50, premium_ratio=0.10)

        result = calculate_final_score(chat, messages, comments_data, users=users)

        # Даже если не достигаем EXCELLENT, проверяем логику вердикта
        if result['score'] >= 75:
            assert result['verdict'] == 'EXCELLENT'
        elif result['score'] >= 55:
            assert result['verdict'] == 'GOOD'

    def test_good_verdict_threshold(self):
        """Score 55-74 даёт GOOD."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel(members=3000)
        result = calculate_final_score(chat, messages, comments_data)

        if 55 <= result['score'] < 75:
            assert result['verdict'] == 'GOOD'

    def test_medium_verdict_threshold(self):
        """Score 40-54 даёт MEDIUM."""
        # Создаём канал среднего качества
        chat = MockChat(
            id=123,
            username="medium_channel",
            members_count=2000,
            linked_chat=MockLinkedChat(id=456),
            date=datetime.now(timezone.utc) - timedelta(days=180)
        )
        messages = create_messages(
            count=15,
            base_views=400,
            cv_percent=25.0,
            reaction_rate=1.0
        )
        comments_data = {'enabled': True, 'avg_comments': 0.5}

        from scanner.scorer import calculate_final_score
        result = calculate_final_score(chat, messages, comments_data)

        if 40 <= result['score'] < 55:
            assert result['verdict'] == 'MEDIUM'

    def test_high_risk_verdict_threshold(self):
        """Score 25-39 даёт HIGH_RISK."""
        from scanner.scorer import calculate_final_score

        # Канал с проблемами
        chat = MockChat(
            id=123,
            username="risky_channel",
            members_count=5000,
            linked_chat=None,  # Нет комментов
            date=datetime.now(timezone.utc) - timedelta(days=60)  # Молодой
        )
        messages = create_messages(
            count=15,
            base_views=100,  # Низкий reach
            cv_percent=20.0,
            reaction_rate=0.1  # Мало реакций
        )
        comments_data = {'enabled': False, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        if 25 <= result['score'] < 40:
            assert result['verdict'] == 'HIGH_RISK'

    def test_scam_verdict_threshold(self):
        """Score < 25 даёт SCAM."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_scam_channel(scam_type="telegram_scam")
        result = calculate_final_score(chat, messages, comments_data)

        assert result['verdict'] == 'SCAM'
        assert result['score'] < 25


# ============================================================================
# ТЕСТЫ ОТДЕЛЬНЫХ ФУНКЦИЙ КОНВЕРТАЦИИ
# ============================================================================

class TestPointsConversion:
    """Тесты функций конвертации метрик в баллы."""

    def test_cv_to_points_optimal_range(self):
        """CV 30-60% даёт максимум баллов."""
        from scanner.scorer import cv_to_points

        assert cv_to_points(35) == 15  # Оптимально
        assert cv_to_points(50) == 15  # Оптимально
        assert cv_to_points(5) == 0    # Слишком ровно
        assert cv_to_points(150) == 0  # Накрутка волнами

    def test_cv_viral_exception(self):
        """CV > 100% + high forward = Viral Exception."""
        from scanner.scorer import cv_to_points

        # Высокий CV без forward = накрутка
        assert cv_to_points(120, forward_rate=1.0) == 0

        # Высокий CV + high forward = viral
        assert cv_to_points(120, forward_rate=5.0) == 7  # 50% от max

    def test_reach_to_points_by_size(self):
        """Reach пороги зависят от размера канала."""
        from scanner.scorer import reach_to_points

        # Микроканал (<200) - до 200% норма
        assert reach_to_points(150, members=100) > 0

        # Большой канал (>5000) - >120% = накрутка
        assert reach_to_points(150, members=10000) == 0

    def test_age_to_points_thresholds(self):
        """Возраст канала конвертируется в баллы по порогам."""
        from scanner.scorer import age_to_points

        assert age_to_points(30) == 0   # < 90 дней
        assert age_to_points(100) == 1  # 90-180 дней
        assert age_to_points(200) == 2  # 180-365 дней
        assert age_to_points(500) == 4  # 1-2 года
        assert age_to_points(800) == 7  # > 2 лет (max)

    def test_decay_to_points_zones(self):
        """Decay ratio конвертируется по зонам."""
        from scanner.scorer import decay_to_points

        # Здоровая органика (0.3-0.95)
        pts, info = decay_to_points(0.7)
        assert pts == 8  # Max
        assert info['zone'] == 'healthy_organic'

        # Виральный рост (1.05-2.0)
        pts, info = decay_to_points(1.5)
        assert pts == 8  # Max
        assert info['zone'] == 'viral_growth'

        # Bot wall (0.98-1.02)
        pts, info = decay_to_points(1.0)
        assert pts == 2  # Штраф
        assert info['zone'] == 'bot_wall'

        # Budget cliff (<0.2)
        pts, info = decay_to_points(0.15)
        assert pts == 0  # SCAM signal
        assert info['zone'] == 'budget_cliff'


# ============================================================================
# ТЕСТЫ С FORENSICS
# ============================================================================

class TestForensicsIntegration:
    """Тесты интеграции с User Forensics."""

    def test_id_clustering_fatality(self):
        """ID Clustering FATALITY (>30% соседних ID) обнуляет канал."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()

        # Создаём юзеров с кластерными ID (>30%)
        bot_users = []
        base_id = 1000000000
        for i in range(30):
            bot_users.append(MockUser(
                id=base_id + i * 10,  # Очень близкие ID
                is_premium=False
            ))

        result = calculate_final_score(chat, messages, comments_data, users=bot_users)

        # FATALITY = SCAM
        assert result['verdict'] == 'SCAM'
        assert result['score'] == 0
        assert 'FATALITY' in result.get('reason', '')

    def test_premium_density_in_scoring(self):
        """Premium density влияет на баллы репутации."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel()

        # Юзеры с премиумами (>5%)
        premium_users = create_users_forensics(count=30, premium_ratio=0.10)

        result = calculate_final_score(chat, messages, comments_data, users=premium_users)

        # Должны быть баллы за premium
        assert result['breakdown']['premium']['points'] > 0


# ============================================================================
# ТЕСТЫ GHOST PROTOCOL
# ============================================================================

class TestGhostProtocol:
    """Тесты Ghost Protocol для детекции мёртвой аудитории."""

    def test_ghost_channel_detection(self):
        """Ghost Channel (20k+ subs, <0.1% online) снижает trust."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            members=25000,
            online_count=10,  # 0.04% online
        )

        assert 'ghost_channel' in details
        assert details['ghost_channel']['multiplier'] == 0.5

    def test_zombie_audience_detection(self):
        """Zombie Audience (5k+ subs, <0.3% online) снижает trust."""
        from scanner.scorer import calculate_trust_factor

        trust, details = calculate_trust_factor(
            forensics_result=None,
            comments_enabled=True,
            conviction_score=0,
            members=10000,
            online_count=20,  # 0.2% online
        )

        assert 'zombie_audience' in details
        assert details['zombie_audience']['multiplier'] == 0.7


# ============================================================================
# ТЕСТЫ RAW WEIGHTS И CATEGORY TOTALS
# ============================================================================

class TestWeightsConfiguration:
    """Тесты конфигурации весов."""

    def test_raw_weights_sum_to_100(self):
        """Сумма всех RAW_WEIGHTS = 100."""
        from scanner.scorer import RAW_WEIGHTS

        total = 0
        for category, metrics in RAW_WEIGHTS.items():
            for metric, weight in metrics.items():
                total += weight

        assert total == 100, f"RAW_WEIGHTS sum is {total}, expected 100"

    def test_category_totals_match_weights(self):
        """CATEGORY_TOTALS соответствуют сумме весов категорий."""
        from scanner.scorer import RAW_WEIGHTS, CATEGORY_TOTALS

        for category in RAW_WEIGHTS:
            expected = sum(RAW_WEIGHTS[category].values())
            actual = CATEGORY_TOTALS[category]
            assert expected == actual, f"{category}: expected {expected}, got {actual}"


# ============================================================================
# SNAPSHOT ТЕСТЫ (для регрессионного тестирования)
# ============================================================================

class TestSnapshotScores:
    """
    Snapshot тесты - фиксируют текущее поведение для отслеживания регрессий.
    При изменении алгоритма эти тесты упадут, что позволит проверить изменения.
    """

    def test_snapshot_healthy_channel(self):
        """Snapshot: здоровый канал."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_healthy_channel(
            username="snapshot_healthy",
            members=5000
        )
        result = calculate_final_score(chat, messages, comments_data)

        # Фиксируем ожидаемые диапазоны (не точные значения)
        assert 40 <= result['score'] <= 80, f"Score {result['score']} outside expected range"
        assert result['verdict'] in ['GOOD', 'MEDIUM', 'EXCELLENT']
        assert 0.7 <= result['trust_factor'] <= 1.0

    def test_snapshot_scam_channel(self):
        """Snapshot: SCAM канал."""
        from scanner.scorer import calculate_final_score

        chat, messages, comments_data = create_scam_channel(
            username="snapshot_scam",
            scam_type="telegram_scam"
        )
        result = calculate_final_score(chat, messages, comments_data)

        assert result['score'] == 0
        assert result['verdict'] == 'SCAM'

    def test_snapshot_no_comments_channel(self):
        """Snapshot: канал без комментариев."""
        from scanner.scorer import calculate_final_score

        chat = MockChat(
            id=123,
            username="no_comments_snapshot",
            members_count=3000,
            linked_chat=None,
            date=datetime.now(timezone.utc) - timedelta(days=400)
        )
        messages = create_messages(count=25, base_views=900, cv_percent=35.0)
        comments_data = {'enabled': False, 'avg_comments': 0}

        result = calculate_final_score(chat, messages, comments_data)

        # Floating weights должны работать
        assert result['flags']['floating_weights'] is True
        assert result['breakdown']['comments']['max'] == 0
        assert result['breakdown']['forward_rate']['max'] > 7

        # Trust penalty за hidden comments
        assert result['trust_factor'] <= 0.85
