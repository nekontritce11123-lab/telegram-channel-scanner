"""
Tests for Favorites feature.

TDD Phase 2.1: Database table tests (user_favorites)
TDD Phase 2.2-2.3: API endpoint tests (GET/POST/DELETE)

Expected table schema:
    CREATE TABLE IF NOT EXISTS user_favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        score INTEGER DEFAULT NULL,
        verdict TEXT DEFAULT NULL,
        members INTEGER DEFAULT NULL,
        category TEXT DEFAULT NULL,
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, username)
    )

Run:
    pytest tests/test_favorites_api.py -v
    pytest tests/test_favorites_api.py -v -k "table"  # Only table tests
"""

import pytest
import sqlite3
import tempfile
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add mini-app/backend to path for imports
backend_path = Path(__file__).parent.parent / "mini-app" / "backend"
sys.path.insert(0, str(backend_path))

from scanner.database import CrawlerDB


# =============================================================================
# PHASE 2.1: DATABASE TABLE TESTS
# =============================================================================

class TestFavoritesTable:
    """Tests for user_favorites table existence and schema."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = CrawlerDB(db_path)
        yield db, db_path

        db.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_favorites_table_exists(self, temp_db):
        """Table user_favorites should exist after CrawlerDB initialization."""
        db, db_path = temp_db

        # Connect directly to check table exists
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='user_favorites'
        """)
        result = cursor.fetchone()
        conn.close()

        assert result is not None, (
            "Table 'user_favorites' should exist after database initialization. "
            "Expected CREATE TABLE user_favorites(...)"
        )
        assert result[0] == 'user_favorites'

    def test_favorites_table_schema(self, temp_db):
        """Table should have: id, user_id, username, score, verdict, members, category, added_at."""
        db, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get table info
        cursor.execute("PRAGMA table_info(user_favorites)")
        columns = cursor.fetchall()
        conn.close()

        # Extract column names
        column_names = [col[1] for col in columns]

        # Expected columns
        expected_columns = [
            'id',
            'user_id',
            'username',
            'score',
            'verdict',
            'members',
            'category',
            'added_at'
        ]

        assert len(columns) == 8, (
            f"Table user_favorites should have exactly 8 columns, "
            f"got {len(columns)}: {column_names}"
        )

        for expected in expected_columns:
            assert expected in column_names, (
                f"Column '{expected}' missing from user_favorites table. "
                f"Existing columns: {column_names}"
            )

    def test_favorites_table_column_types(self, temp_db):
        """Verify column types match expected schema."""
        db, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(user_favorites)")
        columns = cursor.fetchall()
        conn.close()

        # columns format: (cid, name, type, notnull, dflt_value, pk)
        column_info = {col[1]: {'type': col[2], 'notnull': col[3], 'pk': col[5]} for col in columns}

        # Check primary key
        assert column_info.get('id', {}).get('pk') == 1, "id should be PRIMARY KEY"

        # Check NOT NULL constraints
        assert column_info.get('user_id', {}).get('notnull') == 1, "user_id should be NOT NULL"
        assert column_info.get('username', {}).get('notnull') == 1, "username should be NOT NULL"

        # Check types
        assert 'INTEGER' in column_info.get('id', {}).get('type', '').upper(), "id should be INTEGER"
        assert 'INTEGER' in column_info.get('user_id', {}).get('type', '').upper(), "user_id should be INTEGER"
        assert 'TEXT' in column_info.get('username', {}).get('type', '').upper(), "username should be TEXT"

    def test_favorites_unique_constraint(self, temp_db):
        """UNIQUE constraint on (user_id, username) should prevent duplicates."""
        db, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Insert first record
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username, score, verdict)
            VALUES (123456, 'testchannel', 75, 'GOOD')
        """)
        conn.commit()

        # Try to insert duplicate (same user_id + username)
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            cursor.execute("""
                INSERT INTO user_favorites (user_id, username, score, verdict)
                VALUES (123456, 'testchannel', 80, 'EXCELLENT')
            """)
            conn.commit()

        conn.close()

        assert 'UNIQUE constraint failed' in str(exc_info.value), (
            "UNIQUE(user_id, username) constraint should prevent duplicate favorites"
        )

    def test_favorites_different_users_same_channel(self, temp_db):
        """Different users can favorite the same channel."""
        db, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # User 1 favorites channel
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username, score)
            VALUES (111, 'channel1', 70)
        """)

        # User 2 favorites same channel - should work
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username, score)
            VALUES (222, 'channel1', 70)
        """)
        conn.commit()

        # Count records
        cursor.execute("SELECT COUNT(*) FROM user_favorites WHERE username = 'channel1'")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 2, "Different users should be able to favorite the same channel"

    def test_favorites_same_user_different_channels(self, temp_db):
        """Same user can favorite multiple channels."""
        db, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # User favorites multiple channels
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username, score)
            VALUES (123, 'channel1', 70)
        """)
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username, score)
            VALUES (123, 'channel2', 80)
        """)
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username, score)
            VALUES (123, 'channel3', 60)
        """)
        conn.commit()

        # Count records for user
        cursor.execute("SELECT COUNT(*) FROM user_favorites WHERE user_id = 123")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 3, "Same user should be able to favorite multiple channels"

    def test_favorites_added_at_default(self, temp_db):
        """added_at should default to CURRENT_TIMESTAMP."""
        db, db_path = temp_db

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Insert without specifying added_at
        cursor.execute("""
            INSERT INTO user_favorites (user_id, username)
            VALUES (999, 'testchannel')
        """)
        conn.commit()

        # Check added_at is populated
        cursor.execute("SELECT added_at FROM user_favorites WHERE user_id = 999")
        result = cursor.fetchone()
        conn.close()

        assert result is not None, "Record should be inserted"
        assert result[0] is not None, "added_at should have default value (CURRENT_TIMESTAMP)"


# =============================================================================
# PHASE 2.2-2.3: API ENDPOINT TESTS
# =============================================================================


@pytest.fixture(scope="module")
def test_client():
    """
    Create test client for FastAPI app.
    Uses TestClient which handles async internally.
    Patches verify_telegram_init_data to allow test auth.
    """
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from main import app

    def mock_verify(init_data, bot_token=None):
        """Mock verification that extracts user_id from init_data without HMAC check."""
        if not init_data:
            return None
        # Parse URL-encoded user data
        import urllib.parse
        params = dict(urllib.parse.parse_qsl(init_data))
        if 'user' in params:
            import json
            user = json.loads(params['user'])
            return {'user_id': user.get('id'), 'username': user.get('username')}
        return None

    with patch('main.verify_telegram_init_data', side_effect=mock_verify):
        with TestClient(app) as client:
            yield client


class TestGetFavorites:
    """Tests for GET /api/favorites endpoint."""

    def test_get_favorites_empty(self, test_client):
        """New user should have empty favorites."""
        # Use unique user_id that has no favorites
        response = test_client.get(
            "/api/favorites",
            headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A999999%7D&hash=test"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "favorites" in data
        assert data["favorites"] == []
        assert data["total"] == 0

    def test_get_favorites_unauthorized(self, test_client):
        """Without initData should return empty list, not error."""
        response = test_client.get("/api/favorites")

        # Should return 200 with empty list (graceful degradation)
        assert response.status_code == 200
        data = response.json()
        assert data["favorites"] == []

    def test_get_favorites_with_data(self, test_client):
        """User with favorites should get them sorted by added_at DESC."""
        # Use unique user_id to avoid conflict with other tests
        headers = {"X-Telegram-Init-Data": "user=%7B%22id%22%3A333444%7D&hash=test"}

        # First add some favorites with a delay to ensure different timestamps
        import time
        test_client.post(
            "/api/favorites",
            json={"username": "order_channel_first"},
            headers=headers
        )
        time.sleep(1.1)  # 1+ second delay to ensure different added_at in SQLite
        test_client.post(
            "/api/favorites",
            json={"username": "order_channel_second"},
            headers=headers
        )

        # Now get favorites
        response = test_client.get("/api/favorites", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data["favorites"]) == 2
        # Most recently added should be first (DESC order)
        assert data["favorites"][0]["username"] == "order_channel_second"
        assert data["favorites"][1]["username"] == "order_channel_first"


class TestAddFavorite:
    """Tests for POST /api/favorites endpoint."""

    def test_add_favorite_success(self, test_client):
        """POST /api/favorites should add channel."""
        response = test_client.post(
            "/api/favorites",
            json={"username": "test_channel"},
            headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A999%7D&hash=test"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["username"] == "test_channel"

    def test_add_favorite_duplicate(self, test_client):
        """Adding same channel twice should update, not duplicate."""
        headers = {"X-Telegram-Init-Data": "user=%7B%22id%22%3A888%7D&hash=test"}

        # Add first time
        response1 = test_client.post(
            "/api/favorites",
            json={"username": "dup_channel"},
            headers=headers
        )
        assert response1.status_code == 201

        # Add second time (same channel)
        response2 = test_client.post(
            "/api/favorites",
            json={"username": "dup_channel"},
            headers=headers
        )

        # Should succeed (upsert behavior)
        assert response2.status_code in (200, 201)

        # Check no duplicates in list
        list_response = test_client.get("/api/favorites", headers=headers)
        data = list_response.json()
        usernames = [f["username"] for f in data["favorites"]]
        assert usernames.count("dup_channel") == 1

    def test_add_favorite_unauthorized(self, test_client):
        """Adding favorite without auth should fail."""
        response = test_client.post(
            "/api/favorites",
            json={"username": "test_channel"}
        )

        # Should require authentication for write operations
        assert response.status_code == 401


class TestDeleteFavorite:
    """Tests for DELETE /api/favorites/{username} endpoint."""

    def test_delete_favorite_success(self, test_client):
        """DELETE /api/favorites/{username} should remove."""
        headers = {"X-Telegram-Init-Data": "user=%7B%22id%22%3A777%7D&hash=test"}

        # First add a favorite
        test_client.post(
            "/api/favorites",
            json={"username": "to_delete"},
            headers=headers
        )

        # Now delete it
        response = test_client.delete(
            "/api/favorites/to_delete",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["removed"] is True

    def test_delete_favorite_not_found(self, test_client):
        """Deleting non-existent should return removed: false."""
        response = test_client.delete(
            "/api/favorites/nonexistent_channel",
            headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A666%7D&hash=test"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["removed"] is False

    def test_delete_favorite_unauthorized(self, test_client):
        """Deleting without auth should fail."""
        response = test_client.delete("/api/favorites/some_channel")

        assert response.status_code == 401
