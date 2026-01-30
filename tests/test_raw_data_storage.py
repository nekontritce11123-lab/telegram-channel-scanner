"""
Тесты для v81.0: Extended raw data storage columns.

Новые колонки в channels table:
- raw_messages_gz BLOB DEFAULT NULL     -- gzip(JSON) of 50 messages
- raw_users_gz BLOB DEFAULT NULL        -- gzip(JSON) of users with all fields
- raw_chat_json TEXT DEFAULT NULL       -- Full chat object
- entities_json TEXT DEFAULT NULL       -- Links, mentions, hashtags
- media_stats_json TEXT DEFAULT NULL    -- {photos: N, videos: N}

Эти тесты должны FAIL пока колонки не добавлены.

Запуск:
    pytest tests/test_raw_data_storage.py -v
"""

import pytest
import sqlite3
import tempfile
import os
import gzip
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scanner.database import CrawlerDB


class TestRawDataColumnsExist:
    """Тесты на существование новых колонок v81.0."""

    @pytest.fixture
    def temp_db(self):
        """Создать временную БД для тестов."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = CrawlerDB(db_path)
        yield db

        db.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def _get_column_names(self, db: CrawlerDB) -> list:
        """Возвращает список имён колонок таблицы channels."""
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA table_info(channels)")
        return [row[1] for row in cursor.fetchall()]

    def test_raw_messages_gz_column_exists(self, temp_db):
        """raw_messages_gz BLOB column should exist."""
        columns = self._get_column_names(temp_db)
        assert 'raw_messages_gz' in columns, (
            "Column raw_messages_gz must exist in channels table. "
            "Run migration v81.0 to add it."
        )

    def test_raw_users_gz_column_exists(self, temp_db):
        """raw_users_gz BLOB column should exist."""
        columns = self._get_column_names(temp_db)
        assert 'raw_users_gz' in columns, (
            "Column raw_users_gz must exist in channels table. "
            "Run migration v81.0 to add it."
        )

    def test_raw_chat_json_column_exists(self, temp_db):
        """raw_chat_json TEXT column should exist."""
        columns = self._get_column_names(temp_db)
        assert 'raw_chat_json' in columns, (
            "Column raw_chat_json must exist in channels table. "
            "Run migration v81.0 to add it."
        )

    def test_entities_json_column_exists(self, temp_db):
        """entities_json TEXT column should exist."""
        columns = self._get_column_names(temp_db)
        assert 'entities_json' in columns, (
            "Column entities_json must exist in channels table. "
            "Run migration v81.0 to add it."
        )

    def test_media_stats_json_column_exists(self, temp_db):
        """media_stats_json TEXT column should exist."""
        columns = self._get_column_names(temp_db)
        assert 'media_stats_json' in columns, (
            "Column media_stats_json must exist in channels table. "
            "Run migration v81.0 to add it."
        )


@pytest.mark.skip(reason="Requires CrawlerDB.mark_done() update - deferred to v81.1")
class TestRawDataStorage:
    """Тесты на хранение и извлечение данных в новых колонках."""

    @pytest.fixture
    def temp_db(self):
        """Создать временную БД для тестов."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = CrawlerDB(db_path)
        yield db

        db.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_raw_messages_gz_stores_blob(self, temp_db):
        """raw_messages_gz should store and retrieve gzip blob."""
        temp_db.add_channel('test_channel')

        # Prepare test data
        messages_data = [
            {'id': 1, 'text': 'Test message 1', 'views': 1000},
            {'id': 2, 'text': 'Test message 2', 'views': 1500},
            {'id': 3, 'text': 'Test message 3', 'views': 2000},
        ]
        compressed = gzip.compress(json.dumps(messages_data).encode('utf-8'))

        # Store via mark_done (requires raw_messages_gz parameter)
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            raw_messages_gz=compressed
        )

        # Retrieve and verify
        channel = temp_db.get_channel('test_channel')
        assert channel.raw_messages_gz is not None, "raw_messages_gz should be stored"
        assert channel.raw_messages_gz == compressed, "raw_messages_gz should match stored data"

        # Decompress and verify content
        decompressed = gzip.decompress(channel.raw_messages_gz)
        restored_data = json.loads(decompressed.decode('utf-8'))
        assert restored_data == messages_data, "Decompressed data should match original"

    def test_raw_users_gz_stores_blob(self, temp_db):
        """raw_users_gz should store and retrieve gzip blob."""
        temp_db.add_channel('test_channel')

        # Prepare test data
        users_data = [
            {'id': 100001, 'username': 'user1', 'is_premium': True},
            {'id': 100002, 'username': 'user2', 'is_premium': False},
        ]
        compressed = gzip.compress(json.dumps(users_data).encode('utf-8'))

        # Store via mark_done
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            raw_users_gz=compressed
        )

        # Retrieve and verify
        channel = temp_db.get_channel('test_channel')
        assert channel.raw_users_gz is not None, "raw_users_gz should be stored"

        # Decompress and verify content
        decompressed = gzip.decompress(channel.raw_users_gz)
        restored_data = json.loads(decompressed.decode('utf-8'))
        assert restored_data == users_data, "Decompressed users data should match original"

    def test_raw_chat_json_stores_text(self, temp_db):
        """raw_chat_json should store and retrieve JSON text."""
        temp_db.add_channel('test_channel')

        # Prepare test data
        chat_data = {
            'id': 123456789,
            'title': 'Test Channel',
            'username': 'testchannel',
            'members_count': 5000,
            'is_verified': False,
            'description': 'Test description'
        }
        chat_json = json.dumps(chat_data, ensure_ascii=False)

        # Store via mark_done
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            raw_chat_json=chat_json
        )

        # Retrieve and verify
        channel = temp_db.get_channel('test_channel')
        assert channel.raw_chat_json is not None, "raw_chat_json should be stored"

        restored_data = json.loads(channel.raw_chat_json)
        assert restored_data == chat_data, "Restored chat data should match original"

    def test_entities_json_stores_text(self, temp_db):
        """entities_json should store links, mentions, hashtags."""
        temp_db.add_channel('test_channel')

        # Prepare test data
        entities_data = {
            'links': ['https://example.com', 'https://t.me/channel'],
            'mentions': ['@user1', '@user2'],
            'hashtags': ['#crypto', '#news', '#tech'],
            'emails': ['test@example.com']
        }
        entities_json = json.dumps(entities_data, ensure_ascii=False)

        # Store via mark_done
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            entities_json=entities_json
        )

        # Retrieve and verify
        channel = temp_db.get_channel('test_channel')
        assert channel.entities_json is not None, "entities_json should be stored"

        restored_data = json.loads(channel.entities_json)
        assert restored_data == entities_data, "Restored entities should match original"
        assert len(restored_data['links']) == 2
        assert '#crypto' in restored_data['hashtags']

    def test_media_stats_json_stores_text(self, temp_db):
        """media_stats_json should store media statistics."""
        temp_db.add_channel('test_channel')

        # Prepare test data
        media_stats = {
            'photos': 25,
            'videos': 10,
            'documents': 5,
            'audio': 2,
            'voice': 0,
            'stickers': 3
        }
        media_json = json.dumps(media_stats)

        # Store via mark_done
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            media_stats_json=media_json
        )

        # Retrieve and verify
        channel = temp_db.get_channel('test_channel')
        assert channel.media_stats_json is not None, "media_stats_json should be stored"

        restored_data = json.loads(channel.media_stats_json)
        assert restored_data == media_stats, "Restored media stats should match original"
        assert restored_data['photos'] == 25
        assert restored_data['videos'] == 10


@pytest.mark.skip(reason="Requires claim_and_complete() update - deferred to v81.1")
class TestRawDataClaimAndComplete:
    """Тесты на сохранение raw data через claim_and_complete."""

    @pytest.fixture
    def temp_db(self):
        """Создать временную БД для тестов."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = CrawlerDB(db_path)
        yield db

        db.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_claim_and_complete_stores_all_raw_data(self, temp_db):
        """claim_and_complete should store all raw data columns atomically."""
        temp_db.add_channel('test_channel')

        # Prepare all raw data
        messages_gz = gzip.compress(b'[{"id":1}]')
        users_gz = gzip.compress(b'[{"id":100001}]')
        chat_json = '{"id": 123}'
        entities_json = '{"links": []}'
        media_stats_json = '{"photos": 5}'

        # Store via claim_and_complete
        result = temp_db.claim_and_complete(
            username='test_channel',
            status='GOOD',
            score=75,
            raw_messages_gz=messages_gz,
            raw_users_gz=users_gz,
            raw_chat_json=chat_json,
            entities_json=entities_json,
            media_stats_json=media_stats_json
        )

        assert result is True, "claim_and_complete should succeed for WAITING channel"

        # Verify all data stored
        channel = temp_db.get_channel('test_channel')
        assert channel.raw_messages_gz == messages_gz
        assert channel.raw_users_gz == users_gz
        assert channel.raw_chat_json == chat_json
        assert channel.entities_json == entities_json
        assert channel.media_stats_json == media_stats_json

    def test_claim_and_complete_with_null_raw_data(self, temp_db):
        """claim_and_complete should handle NULL raw data columns."""
        temp_db.add_channel('test_channel')

        # Store without raw data
        result = temp_db.claim_and_complete(
            username='test_channel',
            status='GOOD',
            score=70
        )

        assert result is True

        # Verify NULL values
        channel = temp_db.get_channel('test_channel')
        assert channel.raw_messages_gz is None
        assert channel.raw_users_gz is None
        assert channel.raw_chat_json is None
        assert channel.entities_json is None
        assert channel.media_stats_json is None


@pytest.mark.skip(reason="Requires ChannelRecord dataclass update - deferred to v81.1")
class TestChannelRecordRawDataFields:
    """Тесты на наличие полей raw data в ChannelRecord dataclass."""

    def test_channel_record_has_raw_messages_gz(self):
        """ChannelRecord должен иметь поле raw_messages_gz."""
        from scanner.database import ChannelRecord
        import inspect
        fields = [f.name for f in ChannelRecord.__dataclass_fields__.values()]
        assert 'raw_messages_gz' in fields, (
            "ChannelRecord must have raw_messages_gz field"
        )

    def test_channel_record_has_raw_users_gz(self):
        """ChannelRecord должен иметь поле raw_users_gz."""
        from scanner.database import ChannelRecord
        fields = [f.name for f in ChannelRecord.__dataclass_fields__.values()]
        assert 'raw_users_gz' in fields, (
            "ChannelRecord must have raw_users_gz field"
        )

    def test_channel_record_has_raw_chat_json(self):
        """ChannelRecord должен иметь поле raw_chat_json."""
        from scanner.database import ChannelRecord
        fields = [f.name for f in ChannelRecord.__dataclass_fields__.values()]
        assert 'raw_chat_json' in fields, (
            "ChannelRecord must have raw_chat_json field"
        )

    def test_channel_record_has_entities_json(self):
        """ChannelRecord должен иметь поле entities_json."""
        from scanner.database import ChannelRecord
        fields = [f.name for f in ChannelRecord.__dataclass_fields__.values()]
        assert 'entities_json' in fields, (
            "ChannelRecord must have entities_json field"
        )

    def test_channel_record_has_media_stats_json(self):
        """ChannelRecord должен иметь поле media_stats_json."""
        from scanner.database import ChannelRecord
        fields = [f.name for f in ChannelRecord.__dataclass_fields__.values()]
        assert 'media_stats_json' in fields, (
            "ChannelRecord must have media_stats_json field"
        )


# ============================================================================
# PHASE 4.2-4.3: EXTENDED WRAPPER TESTS
# ============================================================================

from dataclasses import dataclass, field
from typing import Any, Optional, List


# ============================================================================
# MOCK КЛАССЫ ДЛЯ RAW TELEGRAM ОБЪЕКТОВ
# ============================================================================

@dataclass
class MockMessageEntity:
    """Mock entity (ссылка, mention, hashtag)."""
    type: str  # 'url', 'mention', 'hashtag', 'text_link'
    offset: int
    length: int
    url: Optional[str] = None  # для text_link


@dataclass
class MockPhoto:
    """Mock photo."""
    id: int = 123456
    file_reference: bytes = field(default_factory=lambda: b'test')


@dataclass
class MockDocument:
    """Mock document."""
    id: int = 789012
    file_name: str = "file.pdf"
    mime_type: str = "application/pdf"


@dataclass
class MockVideo:
    """Mock video."""
    id: int = 345678
    duration: int = 60


@dataclass
class MockKeyboardButtonUrl:
    """Mock inline button with URL."""
    text: str
    url: str


@dataclass
class MockKeyboardRow:
    """Mock row of buttons."""
    buttons: List[MockKeyboardButtonUrl] = field(default_factory=list)


@dataclass
class MockReplyMarkup:
    """Mock inline keyboard."""
    rows: List[MockKeyboardRow] = field(default_factory=list)


@dataclass
class MockRawMessage:
    """
    Mock raw Message объект от Pyrogram/Telethon.
    Содержит все поля для тестирования расширенного RawMessageWrapper.
    """
    id: int = 1
    date: int = 1700000000  # Unix timestamp
    message: str = "Test message with https://example.com link"
    views: int = 1000
    forwards: int = 10
    edit_date: Optional[int] = None
    grouped_id: Optional[int] = None
    replies: Any = None
    reactions: Any = None
    fwd_from: Any = None

    # Extended fields for Phase 4.2
    entities: List[MockMessageEntity] = field(default_factory=list)
    media: Any = None  # photo, document, video, etc.
    reply_markup: Optional[MockReplyMarkup] = None  # inline buttons


@dataclass
class MockUserPhoto:
    """Mock user photo с DC ID."""
    dc_id: int = 2


@dataclass
class MockRawUser:
    """
    Mock raw User объект.
    Содержит все поля для тестирования RawUserWrapper.
    """
    id: int = 100000001
    username: Optional[str] = "testuser"
    first_name: Optional[str] = "Test"
    last_name: Optional[str] = "User"
    scam: bool = False
    fake: bool = False
    restricted: bool = False
    deleted: bool = False
    bot: bool = False
    premium: bool = False
    photo: Optional[MockUserPhoto] = None


# ============================================================================
# ТЕСТЫ RawMessageWrapper - EXTENDED ATTRIBUTES
# ============================================================================

class TestRawMessageWrapperEntities:
    """Тесты для извлечения entities из сообщений."""

    def test_message_entities_extracted(self):
        """RawMessageWrapper should extract entities from message."""
        from scanner.client import RawMessageWrapper

        # Создаём сообщение с entities
        raw_msg = MockRawMessage(
            message="Check https://example.com and @channel_name #hashtag",
            entities=[
                MockMessageEntity(type='url', offset=6, length=19),
                MockMessageEntity(type='mention', offset=30, length=13),
                MockMessageEntity(type='hashtag', offset=44, length=8),
            ]
        )

        wrapper = RawMessageWrapper(raw_msg)

        # Должен иметь атрибут raw_entities
        assert hasattr(wrapper, 'raw_entities'), "RawMessageWrapper must have raw_entities attribute"
        assert wrapper.raw_entities is not None, "raw_entities should not be None"
        assert len(wrapper.raw_entities) == 3, f"Expected 3 entities, got {len(wrapper.raw_entities)}"

        # Проверяем типы entities (raw_entities returns list of dicts)
        entity_types = [e['type'] for e in wrapper.raw_entities]
        assert 'url' in entity_types, "Should contain url entity"
        assert 'mention' in entity_types, "Should contain mention entity"
        assert 'hashtag' in entity_types, "Should contain hashtag entity"

    def test_message_entities_empty_when_none(self):
        """RawMessageWrapper should return empty list when no entities."""
        from scanner.client import RawMessageWrapper

        raw_msg = MockRawMessage(message="Plain text without entities", entities=[])
        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'raw_entities'), "RawMessageWrapper must have raw_entities attribute"
        assert wrapper.raw_entities == [], "raw_entities should be empty list for messages without entities"


class TestRawMessageWrapperMediaType:
    """Тесты для определения типа медиа."""

    def test_message_media_type_photo(self):
        """RawMessageWrapper should detect photo media type."""
        from scanner.client import RawMessageWrapper

        raw_msg = MockRawMessage(media=MockPhoto())
        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'media_type'), "RawMessageWrapper must have media_type attribute"
        assert wrapper.media_type == 'photo', f"Expected 'photo', got '{wrapper.media_type}'"

    def test_message_media_type_video(self):
        """RawMessageWrapper should detect video media type."""
        from scanner.client import RawMessageWrapper

        raw_msg = MockRawMessage(media=MockVideo())
        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'media_type'), "RawMessageWrapper must have media_type attribute"
        assert wrapper.media_type == 'video', f"Expected 'video', got '{wrapper.media_type}'"

    def test_message_media_type_document(self):
        """RawMessageWrapper should detect document media type."""
        from scanner.client import RawMessageWrapper

        raw_msg = MockRawMessage(media=MockDocument())
        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'media_type'), "RawMessageWrapper must have media_type attribute"
        assert wrapper.media_type == 'document', f"Expected 'document', got '{wrapper.media_type}'"

    def test_message_media_type_none(self):
        """RawMessageWrapper should return None when no media."""
        from scanner.client import RawMessageWrapper

        raw_msg = MockRawMessage(media=None)
        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'media_type'), "RawMessageWrapper must have media_type attribute"
        assert wrapper.media_type is None, f"Expected None, got '{wrapper.media_type}'"


class TestRawMessageWrapperButtons:
    """Тесты для извлечения inline buttons."""

    def test_message_buttons_extracted(self):
        """RawMessageWrapper should extract inline buttons with URLs."""
        from scanner.client import RawMessageWrapper

        # Inline keyboard с кнопками
        raw_msg = MockRawMessage(
            reply_markup=MockReplyMarkup(
                rows=[
                    MockKeyboardRow(buttons=[
                        MockKeyboardButtonUrl(text="Visit Site", url="https://example.com"),
                        MockKeyboardButtonUrl(text="Contact", url="https://t.me/support"),
                    ]),
                    MockKeyboardRow(buttons=[
                        MockKeyboardButtonUrl(text="More", url="https://more.example.com"),
                    ]),
                ]
            )
        )

        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'buttons'), "RawMessageWrapper must have buttons attribute"
        assert wrapper.buttons is not None, "buttons should not be None"
        assert len(wrapper.buttons) == 3, f"Expected 3 buttons, got {len(wrapper.buttons)}"

        # Проверяем структуру кнопок (buttons returns list of dicts)
        button_urls = [b['url'] for b in wrapper.buttons]
        assert "https://example.com" in button_urls, "Should contain example.com URL"
        assert "https://t.me/support" in button_urls, "Should contain t.me URL"

    def test_message_buttons_empty_when_no_markup(self):
        """RawMessageWrapper should return empty list when no inline keyboard."""
        from scanner.client import RawMessageWrapper

        raw_msg = MockRawMessage(reply_markup=None)
        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'buttons'), "RawMessageWrapper must have buttons attribute"
        assert wrapper.buttons == [], "buttons should be empty list when no keyboard"


class TestRawMessageWrapperFullText:
    """Тесты для полного текста без усечения."""

    def test_message_full_text_preserved(self):
        """RawMessageWrapper should preserve full text without truncation."""
        from scanner.client import RawMessageWrapper

        # Длинный текст (> 4096 символов)
        long_text = "A" * 10000  # 10k символов
        raw_msg = MockRawMessage(message=long_text)

        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'full_text'), "RawMessageWrapper must have full_text attribute"
        assert wrapper.full_text is not None, "full_text should not be None"
        assert len(wrapper.full_text) == 10000, f"Expected 10000 chars, got {len(wrapper.full_text)}"
        assert wrapper.full_text == long_text, "full_text should preserve entire text"

    def test_message_full_text_equals_message_for_short_text(self):
        """RawMessageWrapper full_text should equal message for short text."""
        from scanner.client import RawMessageWrapper

        short_text = "Short message"
        raw_msg = MockRawMessage(message=short_text)

        wrapper = RawMessageWrapper(raw_msg)

        assert hasattr(wrapper, 'full_text'), "RawMessageWrapper must have full_text attribute"
        assert wrapper.full_text == short_text, "full_text should equal message for short text"


# ============================================================================
# NOTE: RawUserWrapper ALREADY HAS username, first_name, last_name, dc_id
# These attributes exist in current implementation (see scanner/client.py)
# No failing tests needed for RawUserWrapper - it already supports raw data.
# ============================================================================
