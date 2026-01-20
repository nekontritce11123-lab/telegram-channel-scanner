"""
Pytest fixtures для тестов Рекламщик.

Содержит mock-данные для:
- Каналов (chat objects)
- Сообщений (RawMessageWrapper compatible)
- Пользователей (RawUserWrapper compatible)
- Результатов сканирования (ScanResult)
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any, Optional

# Добавить корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# MOCK КЛАССЫ ДЛЯ TELEGRAM ОБЪЕКТОВ
# =============================================================================

@dataclass
class MockChat:
    """Mock объект канала Telegram."""
    id: int = 123456789
    title: str = "Test Channel"
    username: str = "testchannel"
    members_count: int = 5000
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    linked_chat: Any = None

    # Дата создания канала (для age calculation)
    # По умолчанию: канал создан 400 дней назад
    @property
    def date(self):
        return datetime.now(timezone.utc) - timedelta(days=400)


@dataclass
class MockLinkedChat:
    """Mock объект связанного чата (для комментариев)."""
    id: int = 987654321
    title: str = "Test Channel Chat"


@dataclass
class MockReplies:
    """Mock объект replies (комментарии к посту)."""
    replies: int = 5
    comments: bool = True
    channel_id: Optional[int] = None


@dataclass
class MockReactionCount:
    """Mock счетчик одной реакции."""
    count: int = 10
    emoji: str = "👍"
    reaction: Any = None


@dataclass
class MockReactions:
    """Mock объект реакций поста."""
    reactions: list = field(default_factory=list)

    def __post_init__(self):
        if not self.reactions:
            # По умолчанию: 3 типа реакций
            self.reactions = [
                MockReactionCount(count=15, emoji="👍"),
                MockReactionCount(count=8, emoji="❤️"),
                MockReactionCount(count=3, emoji="🔥"),
            ]


@dataclass
class MockForwardFromChat:
    """Mock объект источника репоста."""
    id: int = 111222333
    type: str = "channel"
    username: Optional[str] = "source_channel"


@dataclass
class MockMessage:
    """
    Mock объект сообщения, совместимый с RawMessageWrapper.
    Содержит все поля, используемые в metrics.py и scorer.py.
    """
    id: int = 1
    date: datetime = field(default_factory=lambda: datetime.now(timezone.utc) - timedelta(hours=12))
    message: str = "Test message content"
    views: int = 1000
    forwards: int = 10
    edit_date: Optional[datetime] = None
    media_group_id: Optional[int] = None
    replies: Optional[MockReplies] = None
    reactions: Optional[MockReactions] = None
    forward_from_chat: Optional[MockForwardFromChat] = None


@dataclass
class MockUser:
    """
    Mock объект пользователя, совместимый с RawUserWrapper.
    Содержит все поля для UserForensics анализа.
    """
    id: int = 100000001
    username: Optional[str] = "testuser"
    first_name: Optional[str] = "Test"
    last_name: Optional[str] = "User"
    is_scam: bool = False
    is_fake: bool = False
    is_restricted: bool = False
    is_deleted: bool = False
    is_bot: bool = False
    is_premium: bool = False
    dc_id: Optional[int] = 2  # DC 2 = Europe/Russia


# =============================================================================
# FIXTURES: БАЗОВЫЕ ДАННЫЕ
# =============================================================================

@pytest.fixture
def sample_channel_data():
    """Mock данные канала для тестов (dict format)."""
    return {
        'id': 123456789,
        'title': 'Test Channel',
        'username': 'testchannel',
        'members_count': 5000,
        'is_verified': False,
        'is_scam': False,
        'is_fake': False,
    }


@pytest.fixture
def sample_chat():
    """Mock объект чата (MockChat instance)."""
    return MockChat()


@pytest.fixture
def sample_chat_with_comments():
    """Mock чат с включёнными комментариями."""
    chat = MockChat()
    chat.linked_chat = MockLinkedChat()
    return chat


@pytest.fixture
def sample_chat_verified():
    """Mock верифицированный канал."""
    return MockChat(
        is_verified=True,
        members_count=50000,
        title="Verified Channel"
    )


@pytest.fixture
def sample_chat_scam():
    """Mock SCAM канал (помечен Telegram)."""
    return MockChat(
        is_scam=True,
        title="Scam Channel"
    )


# =============================================================================
# FIXTURES: СООБЩЕНИЯ
# =============================================================================

@pytest.fixture
def sample_messages():
    """
    Mock список из 50 сообщений для тестов.
    Имитирует реальное распределение просмотров и реакций.
    """
    messages = []
    base_time = datetime.now(timezone.utc)

    for i in range(50):
        # Views: убывают от новых к старым (накопительный эффект)
        # Новые посты: ~800-1200, старые: ~1500-2500
        age_factor = i / 50  # 0 для нового, ~1 для старого
        base_views = 1000 + int(age_factor * 1200)
        # Добавляем случайность через детерминированную функцию
        views = base_views + (i * 17 % 400) - 200

        # Reactions: ~2-5% от views
        reaction_count = max(1, int(views * 0.03))

        # Forwards: ~0.5-2% от views
        forwards = max(0, int(views * 0.01))

        msg = MockMessage(
            id=i + 1,
            date=base_time - timedelta(hours=i * 4),  # Посты каждые 4 часа
            message=f"Test post #{i + 1}" + " with content" * (i % 5),
            views=views,
            forwards=forwards,
            replies=MockReplies(replies=i % 10 + 1),
            reactions=MockReactions(reactions=[
                MockReactionCount(count=reaction_count, emoji="👍"),
                MockReactionCount(count=reaction_count // 2, emoji="❤️"),
            ]),
        )
        messages.append(msg)

    return messages


@pytest.fixture
def sample_messages_no_reactions():
    """Сообщения без реакций (reactions отключены)."""
    messages = []
    base_time = datetime.now(timezone.utc)

    for i in range(20):
        msg = MockMessage(
            id=i + 1,
            date=base_time - timedelta(hours=i * 6),
            views=1000 + i * 50,
            forwards=5 + i,
            replies=MockReplies(replies=i + 1),
            reactions=None,  # Реакции отключены
        )
        messages.append(msg)

    return messages


@pytest.fixture
def sample_messages_bot_wall():
    """
    Сообщения с признаками накрутки (Bot Wall).
    Все посты имеют практически одинаковые просмотры.
    """
    messages = []
    base_time = datetime.now(timezone.utc)

    for i in range(30):
        # Bot Wall: views почти одинаковые (CV < 5%)
        views = 1000 + (i % 3) * 10  # 1000, 1010, 1020, 1000, ...

        msg = MockMessage(
            id=i + 1,
            date=base_time - timedelta(hours=i * 3),
            views=views,
            forwards=1,
            replies=MockReplies(replies=0),
            reactions=MockReactions(reactions=[
                MockReactionCount(count=100, emoji="👍"),  # Ровно 100 на всех
            ]),
        )
        messages.append(msg)

    return messages


@pytest.fixture
def sample_messages_viral():
    """Сообщения с виральным контентом (высокий forward rate)."""
    messages = []
    base_time = datetime.now(timezone.utc)

    for i in range(20):
        views = 5000 + i * 200

        msg = MockMessage(
            id=i + 1,
            date=base_time - timedelta(hours=i * 5),
            views=views,
            forwards=int(views * 0.05),  # 5% forwards = viral
            replies=MockReplies(replies=20 + i * 2),
            reactions=MockReactions(reactions=[
                MockReactionCount(count=int(views * 0.03), emoji="👍"),
                MockReactionCount(count=int(views * 0.02), emoji="🔥"),
            ]),
        )
        messages.append(msg)

    return messages


# =============================================================================
# FIXTURES: ПОЛЬЗОВАТЕЛИ (ДЛЯ FORENSICS)
# =============================================================================

@pytest.fixture
def sample_users():
    """
    Mock список пользователей для forensics анализа.
    Нормальное распределение ID (не ферма).
    """
    users = []

    for i in range(30):
        # ID разбросаны (не кластеризованы)
        user_id = 100000000 + i * 50000 + (i * 7919 % 10000)

        user = MockUser(
            id=user_id,
            username=f"user_{i}" if i % 3 == 0 else None,
            first_name=f"Name{i}",
            is_premium=(i % 15 == 0),  # ~7% премиумов
            dc_id=2 if i % 4 != 0 else 4,  # 75% DC2, 25% DC4 (оба Russian)
        )
        users.append(user)

    return users


@pytest.fixture
def sample_users_bot_farm():
    """
    Пользователи с признаками фермы ботов.
    ID кластеризованы (соседние).
    """
    users = []
    base_id = 500000000

    for i in range(30):
        # ID соседние (кластеризация > 30%)
        user_id = base_id + i * 50  # Разница 50 < 500 = соседи

        user = MockUser(
            id=user_id,
            username=None,  # Боты часто без username
            first_name=f"Bot{i}",
            is_premium=False,  # 0% премиумов
            dc_id=1,  # DC1 = USA (чужой для RU)
        )
        users.append(user)

    return users


@pytest.fixture
def sample_users_quality():
    """
    Пользователи высокого качества.
    Много премиумов, родные DC.
    """
    users = []

    for i in range(25):
        user_id = 200000000 + i * 100000

        user = MockUser(
            id=user_id,
            username=f"premium_user_{i}",
            first_name=f"Premium{i}",
            is_premium=(i % 5 != 0),  # ~80% премиумов
            dc_id=2,  # DC2 = Europe/Russia
        )
        users.append(user)

    return users


# =============================================================================
# FIXTURES: COMMENTS DATA
# =============================================================================

@pytest.fixture
def sample_comments_data():
    """Mock данные о комментариях (enabled)."""
    return {
        'enabled': True,
        'linked_chat': 'Test Channel Chat',
        'comments_counts': [5, 8, 3, 12, 7, 4, 9, 2, 6, 11],
        'total_comments': 67,
        'avg_comments': 6.7,
    }


@pytest.fixture
def sample_comments_data_disabled():
    """Mock данные о комментариях (disabled)."""
    return {
        'enabled': False,
        'linked_chat': None,
        'comments_counts': [],
        'total_comments': 0,
        'avg_comments': 0.0,
    }


# =============================================================================
# FIXTURES: CHANNEL HEALTH (GHOST PROTOCOL)
# =============================================================================

@pytest.fixture
def sample_channel_health():
    """Mock данные о здоровье канала (нормальный)."""
    return {
        'online_count': 150,  # 3% от 5000 = хорошо
        'participants_count': 5000,
        'admins_count': 3,
        'banned_count': 10,
        'kicked_count': 5,
        'status': 'complete',
    }


@pytest.fixture
def sample_channel_health_ghost():
    """Mock данные Ghost Channel (мёртвая аудитория)."""
    return {
        'online_count': 5,  # 0.025% от 20000 = ghost
        'participants_count': 20000,
        'admins_count': 1,
        'banned_count': 0,
        'kicked_count': 0,
        'status': 'complete',
    }


# =============================================================================
# FIXTURES: SCAN RESULT
# =============================================================================

@pytest.fixture
def sample_scan_result(sample_chat, sample_messages, sample_comments_data,
                       sample_users, sample_channel_health):
    """
    Полный mock ScanResult для integration тестов.
    """
    # Импортируем ScanResult если доступен
    try:
        from scanner.client import ScanResult
        return ScanResult(
            chat=sample_chat,
            messages=sample_messages,
            comments_data=sample_comments_data,
            users=sample_users,
            channel_health=sample_channel_health,
            api_requests=3,
        )
    except ImportError:
        # Fallback на dict если ScanResult недоступен
        return {
            'chat': sample_chat,
            'messages': sample_messages,
            'comments_data': sample_comments_data,
            'users': sample_users,
            'channel_health': sample_channel_health,
            'api_requests': 3,
        }


# =============================================================================
# FIXTURES: EDGE CASES
# =============================================================================

@pytest.fixture
def empty_messages():
    """Пустой список сообщений."""
    return []


@pytest.fixture
def empty_users():
    """Пустой список пользователей."""
    return []


@pytest.fixture
def sample_chat_micro():
    """Микроканал (< 200 подписчиков)."""
    return MockChat(
        members_count=150,
        title="Micro Channel"
    )


@pytest.fixture
def sample_chat_large():
    """Большой канал (> 50000 подписчиков)."""
    return MockChat(
        members_count=100000,
        title="Large Channel"
    )
