"""
База данных для Smart Crawler.
v16.0: SQLite хранилище для очереди каналов.

Статусы:
  WAITING    - В очереди на проверку
  PROCESSING - Сейчас проверяется
  GOOD       - Проверен, score >= 60
  BAD        - Проверен, score < 60
  PRIVATE    - Приватный канал
  ERROR      - Ошибка при проверке
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class ChannelRecord:
    """Запись о канале в базе."""
    username: str
    status: str
    score: int = 0
    verdict: str = ""
    trust_factor: float = 1.0
    members: int = 0
    found_via: str = ""
    ad_links: list = None
    scanned_at: datetime = None
    created_at: datetime = None


class CrawlerDB:
    """
    Обёртка над SQLite для хранения очереди каналов.

    Использование:
        db = CrawlerDB("crawler.db")
        db.add_channel("oneeyesnake", parent="[seed]")

        channel = db.get_next()  # Следующий WAITING
        db.mark_processing(channel)
        # ... проверка ...
        db.mark_done(channel, "GOOD", score=72, ...)
    """

    def __init__(self, db_path: str = "crawler.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Создаёт таблицы если их нет."""
        cursor = self.conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                username TEXT PRIMARY KEY,
                status TEXT DEFAULT 'WAITING',
                score INTEGER DEFAULT 0,
                verdict TEXT DEFAULT '',
                trust_factor REAL DEFAULT 1.0,
                members INTEGER DEFAULT 0,
                found_via TEXT DEFAULT '',
                ad_links TEXT DEFAULT '[]',
                scanned_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Индексы для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON channels(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_score ON channels(score)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_found_via ON channels(found_via)')

        self.conn.commit()

    def add_channel(self, username: str, parent: str = "") -> bool:
        """
        Добавляет канал в очередь.

        Returns:
            True если добавлен новый, False если уже существует.
        """
        username = username.lower().lstrip('@')

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO channels (username, found_via) VALUES (?, ?)",
                (username, parent)
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            return False

    def add_channels(self, usernames: list, parent: str = "") -> int:
        """
        Добавляет несколько каналов за раз.

        Returns:
            Количество добавленных новых каналов.
        """
        added = 0
        for username in usernames:
            if self.add_channel(username, parent):
                added += 1
        return added

    def get_next(self) -> Optional[str]:
        """
        Возвращает следующий канал для проверки (WAITING).
        Самый старый по времени добавления.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT username FROM channels WHERE status = 'WAITING' ORDER BY created_at LIMIT 1"
        )
        row = cursor.fetchone()
        return row['username'] if row else None

    def mark_processing(self, username: str):
        """Помечает канал как обрабатываемый."""
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE channels SET status = 'PROCESSING' WHERE username = ?",
            (username,)
        )
        self.conn.commit()

    def mark_done(
        self,
        username: str,
        status: str,
        score: int = 0,
        verdict: str = "",
        trust_factor: float = 1.0,
        members: int = 0,
        ad_links: list = None
    ):
        """
        Помечает канал как проверенный.

        Args:
            status: GOOD, BAD, ERROR, PRIVATE
            score: 0-100
            verdict: Текстовый вердикт (EXCELLENT, SCAM, etc.)
            trust_factor: Trust Multiplier
            members: Количество подписчиков
            ad_links: Список найденных рекламных ссылок
        """
        username = username.lower().lstrip('@')
        ad_links_json = json.dumps(ad_links or [])

        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE channels SET
                status = ?,
                score = ?,
                verdict = ?,
                trust_factor = ?,
                members = ?,
                ad_links = ?,
                scanned_at = ?
            WHERE username = ?
        ''', (status, score, verdict, trust_factor, members, ad_links_json, datetime.now(), username))
        self.conn.commit()

    def is_known(self, username: str) -> bool:
        """Проверяет, есть ли канал в базе."""
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM channels WHERE username = ?", (username,))
        return cursor.fetchone() is not None

    def get_channel(self, username: str) -> Optional[ChannelRecord]:
        """Возвращает запись о канале."""
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM channels WHERE username = ?", (username,))
        row = cursor.fetchone()

        if not row:
            return None

        return ChannelRecord(
            username=row['username'],
            status=row['status'],
            score=row['score'],
            verdict=row['verdict'],
            trust_factor=row['trust_factor'],
            members=row['members'],
            found_via=row['found_via'],
            ad_links=json.loads(row['ad_links']) if row['ad_links'] else [],
            scanned_at=row['scanned_at'],
            created_at=row['created_at']
        )

    def get_stats(self) -> dict:
        """Возвращает статистику базы."""
        cursor = self.conn.cursor()

        stats = {
            'total': 0,
            'waiting': 0,
            'processing': 0,
            'good': 0,
            'bad': 0,
            'private': 0,
            'error': 0
        }

        cursor.execute("SELECT COUNT(*) as cnt FROM channels")
        stats['total'] = cursor.fetchone()['cnt']

        cursor.execute("SELECT status, COUNT(*) as cnt FROM channels GROUP BY status")
        for row in cursor.fetchall():
            status = row['status'].lower()
            if status in stats:
                stats[status] = row['cnt']

        return stats

    def get_good_channels(self, min_score: int = 60) -> list:
        """Возвращает список хороших каналов."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM channels WHERE status = 'GOOD' AND score >= ? ORDER BY score DESC",
            (min_score,)
        )

        channels = []
        for row in cursor.fetchall():
            channels.append(ChannelRecord(
                username=row['username'],
                status=row['status'],
                score=row['score'],
                verdict=row['verdict'],
                trust_factor=row['trust_factor'],
                members=row['members'],
                found_via=row['found_via'],
                ad_links=json.loads(row['ad_links']) if row['ad_links'] else [],
                scanned_at=row['scanned_at'],
                created_at=row['created_at']
            ))

        return channels

    def export_csv(self, filepath: str, status: str = "GOOD"):
        """Экспортирует каналы в CSV."""
        import csv

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT username, score, verdict, members, found_via, scanned_at FROM channels WHERE status = ? ORDER BY score DESC",
            (status,)
        )

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['username', 'score', 'verdict', 'members', 'found_via', 'scanned_at'])
            for row in cursor.fetchall():
                writer.writerow([
                    f"@{row['username']}",
                    row['score'],
                    row['verdict'],
                    row['members'],
                    row['found_via'],
                    row['scanned_at']
                ])

        return cursor.rowcount

    def reset_processing(self):
        """
        Сбрасывает все PROCESSING обратно в WAITING.
        Полезно при перезапуске после краша.
        """
        cursor = self.conn.cursor()
        cursor.execute("UPDATE channels SET status = 'WAITING' WHERE status = 'PROCESSING'")
        self.conn.commit()
        return cursor.rowcount

    def close(self):
        """Закрывает соединение."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
