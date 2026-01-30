"""
Channel Repository v79.0
Batch database operations for recalculation.
"""
import json
import sqlite3
from dataclasses import dataclass
from typing import Iterator, Optional
from pathlib import Path


@dataclass
class ChannelRow:
    """Channel data from database."""
    username: str
    score: int
    raw_score: int
    trust_factor: float
    verdict: str
    status: str
    breakdown_json: dict
    forensics_json: dict
    llm_analysis: dict
    members: int
    online_count: int
    participants_count: int
    bot_percentage: int
    ad_percentage: int
    category: str
    posts_per_day: float
    comments_enabled: bool
    reactions_enabled: bool


@dataclass
class UpdateRow:
    """Update data for a channel."""
    username: str
    score: int
    raw_score: int
    trust_factor: float
    verdict: str
    status: str


class ChannelRepository:
    """
    Repository for channel database operations.
    Optimized for batch reads and writes.
    """

    def __init__(self, db_path: str = 'crawler.db'):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self):
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_all_channels(
        self,
        status_filter: list[str] = None,
        limit: int = None,
        offset: int = 0,
    ) -> list[ChannelRow]:
        """
        Get channels for recalculation.

        Args:
            status_filter: List of statuses to include (default: GOOD, BAD)
            limit: Max channels to return
            offset: Skip first N channels

        Returns:
            List of ChannelRow objects
        """
        if status_filter is None:
            status_filter = ['GOOD', 'BAD']

        placeholders = ','.join('?' * len(status_filter))

        query = f"""
            SELECT
                username, score, raw_score, trust_factor, verdict, status,
                breakdown_json, forensics_json,
                COALESCE(bot_percentage, 0) as bot_percentage,
                COALESCE(ad_percentage, 0) as ad_percentage,
                COALESCE(members, 0) as members,
                COALESCE(online_count, 0) as online_count,
                COALESCE(participants_count, 0) as participants_count,
                category,
                COALESCE(comments_enabled, 1) as comments_enabled,
                COALESCE(reactions_enabled, 1) as reactions_enabled
            FROM channels
            WHERE status IN ({placeholders})
              AND breakdown_json IS NOT NULL
              AND breakdown_json != ''
              AND json_extract(breakdown_json, '$.breakdown.cv_views') IS NOT NULL
            ORDER BY username
        """

        if limit:
            query += f" LIMIT {limit}"
        if offset:
            query += f" OFFSET {offset}"

        cursor = self._conn.cursor()
        cursor.execute(query, status_filter)

        rows = []
        for row in cursor.fetchall():
            # Parse JSON fields
            breakdown = {}
            if row['breakdown_json']:
                try:
                    breakdown = json.loads(row['breakdown_json'])
                except (json.JSONDecodeError, TypeError):
                    pass

            forensics = {}
            if row['forensics_json']:
                try:
                    forensics = json.loads(row['forensics_json'])
                except (json.JSONDecodeError, TypeError):
                    pass

            # Extract posts_per_day from breakdown
            posts_per_day = 0.0
            if breakdown:
                bd = breakdown.get('breakdown', breakdown)
                posts_per_day = bd.get('regularity', {}).get('value', 0)

            rows.append(ChannelRow(
                username=row['username'],
                score=row['score'] or 0,
                raw_score=row['raw_score'] or 0,
                trust_factor=row['trust_factor'] or 1.0,
                verdict=row['verdict'] or 'MEDIUM',
                status=row['status'],
                breakdown_json=breakdown,
                forensics_json=forensics,
                llm_analysis={},  # Will be loaded separately if needed
                members=row['members'],
                online_count=row['online_count'],
                participants_count=row['participants_count'],
                bot_percentage=row['bot_percentage'],
                ad_percentage=row['ad_percentage'],
                category=row['category'],
                posts_per_day=posts_per_day,
                comments_enabled=bool(row['comments_enabled']),
                reactions_enabled=bool(row['reactions_enabled']),
            ))

        return rows

    def count_channels(self, status_filter: list[str] = None) -> int:
        """Count channels matching filter."""
        if status_filter is None:
            status_filter = ['GOOD', 'BAD']

        placeholders = ','.join('?' * len(status_filter))
        cursor = self._conn.cursor()
        cursor.execute(
            f"SELECT COUNT(*) FROM channels WHERE status IN ({placeholders})",
            status_filter
        )
        return cursor.fetchone()[0]

    def batch_update(self, updates: list[UpdateRow]) -> int:
        """
        Batch update channels using executemany.
        Simple and reliable approach.

        Args:
            updates: List of UpdateRow objects

        Returns:
            Number of updated rows
        """
        if not updates:
            return 0

        # Prepare data as tuples (score, raw_score, trust_factor, verdict, status, username)
        data = [
            (u.score, u.raw_score, u.trust_factor, u.verdict, u.status, u.username)
            for u in updates
        ]

        cursor = self._conn.cursor()
        cursor.executemany('''
            UPDATE channels
            SET score = ?, raw_score = ?, trust_factor = ?, verdict = ?, status = ?
            WHERE username = ?
        ''', data)
        self._conn.commit()

        return len(updates)

    def get_statistics(self) -> dict:
        """Get database statistics."""
        cursor = self._conn.cursor()

        # Total counts
        cursor.execute("SELECT COUNT(*) FROM channels")
        total = cursor.fetchone()[0]

        # By status
        cursor.execute("""
            SELECT status, COUNT(*)
            FROM channels
            GROUP BY status
        """)
        by_status = dict(cursor.fetchall())

        # By verdict
        cursor.execute("""
            SELECT verdict, COUNT(*)
            FROM channels
            WHERE status IN ('GOOD', 'BAD')
            GROUP BY verdict
        """)
        by_verdict = dict(cursor.fetchall())

        return {
            'total': total,
            'by_status': by_status,
            'by_verdict': by_verdict,
        }
