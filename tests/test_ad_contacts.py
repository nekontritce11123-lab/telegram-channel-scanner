"""
Тесты для извлечения рекламных контактов из описания канала.

Phase 5.1: Ad Contacts Extraction

Тестируемая функция: extract_ad_contacts(description, channel_username=None)
Возвращает список контактов с confidence score:
    [{'contact': '@admin', 'confidence': 80, 'type': 'username'}, ...]
"""
import pytest


class TestAdContactsExtraction:
    """Тесты извлечения контактов из описания канала."""

    def test_extract_admin_contacts_from_description(self):
        """Should extract @username from description."""
        from scanner.ad_detector import extract_ad_contacts

        description = "По вопросам рекламы: @admin_contact"
        contacts = extract_ad_contacts(description)

        assert len(contacts) >= 1
        assert any(c['contact'] == '@admin_contact' for c in contacts)

    def test_extract_multiple_contacts(self):
        """Should extract multiple @usernames."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Реклама @manager1 или @manager2"
        contacts = extract_ad_contacts(description)

        assert len(contacts) >= 2
        usernames = [c['contact'] for c in contacts]
        assert '@manager1' in usernames
        assert '@manager2' in usernames

    def test_extract_t_me_links(self):
        """Should extract t.me/username links."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Связь: t.me/ad_manager"
        contacts = extract_ad_contacts(description)

        assert len(contacts) >= 1
        assert any('ad_manager' in c['contact'] for c in contacts)

    def test_extract_telegram_me_links(self):
        """Should extract telegram.me/username links."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Contact: telegram.me/pr_manager"
        contacts = extract_ad_contacts(description)

        assert len(contacts) >= 1
        assert any('pr_manager' in c['contact'] for c in contacts)

    def test_no_false_positives_own_username(self):
        """Should not include channel's own username."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Канал @mychannel - реклама @manager"
        contacts = extract_ad_contacts(description, channel_username='mychannel')

        # Own channel username should be excluded
        assert not any(c['contact'] == '@mychannel' for c in contacts)
        # Manager contact should be included
        assert any(c['contact'] == '@manager' for c in contacts)

    def test_extract_near_ad_keywords_high_confidence(self):
        """Contacts near ad keywords should have higher confidence."""
        from scanner.ad_detector import extract_ad_contacts

        description = "По рекламе: @ad_contact"
        contacts = extract_ad_contacts(description)

        # Contact near 'реклам' keyword should have high confidence
        ad_contact = next((c for c in contacts if c['contact'] == '@ad_contact'), None)
        assert ad_contact is not None
        assert ad_contact['confidence'] > 50

    def test_extract_returns_contact_type(self):
        """Each contact should have a type field."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Реклама: @admin или t.me/prbot"
        contacts = extract_ad_contacts(description)

        # All contacts should have 'type' field
        for contact in contacts:
            assert 'type' in contact
            assert contact['type'] in ('telegram', 'telegram_link', 'bot')

    def test_detect_bot_contacts(self):
        """Should detect bot usernames (ending with 'bot')."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Заказать рекламу: @adsbot или @promo_bot"
        contacts = extract_ad_contacts(description)

        # Should detect bot usernames
        bot_contacts = [c for c in contacts if c['type'] == 'bot']
        assert len(bot_contacts) >= 1

    def test_empty_description_returns_empty_list(self):
        """Empty description should return empty list."""
        from scanner.ad_detector import extract_ad_contacts

        assert extract_ad_contacts("") == []
        assert extract_ad_contacts(None) == []
        assert extract_ad_contacts("   ") == []

    def test_no_contacts_returns_empty_list(self):
        """Description without contacts should return empty list."""
        from scanner.ad_detector import extract_ad_contacts

        description = "Лучший канал про технологии!"
        contacts = extract_ad_contacts(description)

        assert contacts == []

    def test_extract_only_valid_usernames(self):
        """Should only extract valid Telegram usernames (5+ chars)."""
        from scanner.ad_detector import extract_ad_contacts

        # @abc is too short (min 5 chars), @admin is valid
        description = "Contact @abc or @admin_contact"
        contacts = extract_ad_contacts(description)

        # Short username should be excluded
        assert not any(c['contact'] == '@abc' for c in contacts)
        # Valid username should be included
        assert any(c['contact'] == '@admin_contact' for c in contacts)

    def test_confidence_scoring_logic(self):
        """Contacts should have confidence based on context."""
        from scanner.ad_detector import extract_ad_contacts

        # High confidence: near ad keywords
        desc_high = "Реклама / PR: @prmanager"
        contacts_high = extract_ad_contacts(desc_high)

        # Low confidence: just a mention without ad context
        desc_low = "Основатель канала @founder"
        contacts_low = extract_ad_contacts(desc_low)

        # High-context contact should have higher confidence
        if contacts_high and contacts_low:
            high_conf = contacts_high[0]['confidence']
            low_conf = contacts_low[0]['confidence']
            assert high_conf > low_conf


class TestAdContactsDatabase:
    """Тесты для хранения контактов в базе данных."""

    def test_ad_contacts_json_column_exists(self, tmp_path):
        """ad_contacts_json column should exist in channels table."""
        import sqlite3
        from scanner.database import CrawlerDB

        db_path = tmp_path / "test_contacts.db"
        db = CrawlerDB(str(db_path))

        # Check that ad_contacts_json column exists
        cursor = db.conn.cursor()
        cursor.execute("PRAGMA table_info(channels)")
        columns = {row[1] for row in cursor.fetchall()}

        assert 'ad_contacts_json' in columns, \
            "Column ad_contacts_json must exist in channels table"

        db.conn.close()

    def test_save_and_load_ad_contacts(self, tmp_path):
        """Should be able to save and load ad_contacts_json."""
        import json
        from scanner.database import CrawlerDB

        db_path = tmp_path / "test_contacts_save.db"
        db = CrawlerDB(str(db_path))

        # Prepare test data
        contacts = [
            {'contact': '@manager', 'confidence': 85, 'type': 'username'},
            {'contact': 't.me/prbot', 'confidence': 70, 'type': 'bot'},
        ]
        contacts_json = json.dumps(contacts)

        # Add channel with ad_contacts_json
        db.add_channel("test_channel", parent="[test]")

        cursor = db.conn.cursor()
        cursor.execute(
            "UPDATE channels SET ad_contacts_json = ? WHERE username = ?",
            (contacts_json, "test_channel")
        )
        db.conn.commit()

        # Load and verify
        cursor.execute(
            "SELECT ad_contacts_json FROM channels WHERE username = ?",
            ("test_channel",)
        )
        row = cursor.fetchone()

        assert row is not None
        loaded = json.loads(row[0])
        assert len(loaded) == 2
        assert loaded[0]['contact'] == '@manager'

        db.conn.close()


class TestAdContactsIntegration:
    """Интеграционные тесты: extract_ad_contacts + scanner."""

    def test_contacts_extracted_during_scan(self):
        """Ad contacts should be extracted during channel scan."""
        # This test verifies the integration point exists
        # Implementation will be in scorer.py or client.py
        from scanner.ad_detector import extract_ad_contacts

        # Mock description that would come from scan
        description = "Канал о бизнесе\nРеклама: @business_ads\nt.me/ads_bot"

        contacts = extract_ad_contacts(description)

        # Should extract both contacts
        assert len(contacts) >= 2

        # Verify we can serialize to JSON (for database storage)
        import json
        json_str = json.dumps(contacts)
        assert json_str  # Should not raise
