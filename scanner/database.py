"""
База данных для Smart Crawler.
v18.0: SQLite хранилище для очереди каналов + AI категории с multi-label.

Статусы:
  WAITING    - В очереди на проверку
  PROCESSING - Сейчас проверяется
  GOOD       - Проверен, score >= 60
  BAD        - Проверен, score < 60
  PRIVATE    - Приватный канал
  ERROR      - Ошибка при проверке

Категории (AI) - 17 штук:
  Премиальные: CRYPTO, FINANCE, REAL_ESTATE, BUSINESS
  Технологии: TECH, AI_ML
  Образование: EDUCATION, BEAUTY, HEALTH, TRAVEL
  Коммерция: RETAIL
  Контент: ENTERTAINMENT, NEWS, LIFESTYLE
  Риск: GAMBLING, ADULT
  Fallback: OTHER

Multi-label: category + category_secondary (например TECH+ENTERTAINMENT)
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
    category: str = None  # v18.0: AI категория (основная)
    category_secondary: str = None  # v18.0: Вторичная категория (multi-label)
    category_percent: int = 100  # v20.0: Процент основной категории
    photo_url: str = None  # v19.0: URL аватарки канала
    breakdown_json: str = None  # v21.0: Детальный breakdown метрик (JSON)
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
                category TEXT DEFAULT NULL,
                scanned_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Индексы для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON channels(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_score ON channels(score)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_found_via ON channels(found_via)')

        # v17.0: Миграция - добавляем колонку category если её нет
        self._migrate_add_category()

        # v18.0: Миграция - добавляем колонку category_secondary для multi-label
        self._migrate_add_category_secondary()

        # v19.0: Миграция - добавляем колонку photo_url для аватарок
        self._migrate_add_photo_url()

        # v21.0: Миграция - добавляем колонку breakdown_json для реальных метрик
        self._migrate_add_breakdown()

        # Индексы для category (после миграции)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON channels(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category_secondary ON channels(category_secondary)')

        self.conn.commit()

    def _migrate_add_category(self):
        """Миграция: добавляет колонку category в существующую таблицу."""
        cursor = self.conn.cursor()
        try:
            # Проверяем есть ли колонка
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'category' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN category TEXT DEFAULT NULL")
                print("Миграция: добавлена колонка category")
        except sqlite3.Error:
            pass  # Колонка уже существует или другая ошибка

    def _migrate_add_category_secondary(self):
        """Миграция v18.0: добавляет колонку category_secondary для multi-label."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'category_secondary' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN category_secondary TEXT DEFAULT NULL")
                print("Миграция v18.0: добавлена колонка category_secondary")
        except sqlite3.Error:
            pass

    def _migrate_add_photo_url(self):
        """Миграция v19.0: добавляет колонку photo_url для аватарок каналов."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'photo_url' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN photo_url TEXT DEFAULT NULL")
                print("Миграция v19.0: добавлена колонка photo_url")
        except sqlite3.Error:
            pass

        # v20.0: category_percent для мульти-категорий с процентами
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'category_percent' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN category_percent INTEGER DEFAULT 100")
                print("Миграция v20.0: добавлена колонка category_percent")
        except sqlite3.Error:
            pass

    def _migrate_add_breakdown(self):
        """Миграция v21.0: добавляет колонку breakdown_json для реальных метрик."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'breakdown_json' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN breakdown_json TEXT DEFAULT NULL")
                print("Миграция v21.0: добавлена колонка breakdown_json")
        except sqlite3.Error:
            pass

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
        ad_links: list = None,
        category: str = None,
        category_secondary: str = None,
        photo_url: str = None,
        breakdown: dict = None,    # v21.0: детальный breakdown метрик
        categories: dict = None    # v21.0: итоги по категориям (quality/engagement/reputation)
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
            category: AI категория основная (CRYPTO, NEWS, TECH и т.д.)
            category_secondary: AI категория вторичная (для multi-label)
            photo_url: URL аватарки канала (Telegram CDN)
            breakdown: v21.0 - детальные метрики (cv_views, reach, verified, etc.)
            categories: v21.0 - итоги по категориям (quality, engagement, reputation)
        """
        username = username.lower().lstrip('@')
        ad_links_json = json.dumps(ad_links or [])

        # v21.0: Сериализуем breakdown в JSON
        breakdown_json = None
        if breakdown or categories:
            breakdown_json = json.dumps({
                'breakdown': breakdown,
                'categories': categories
            }, ensure_ascii=False)

        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE channels SET
                status = ?,
                score = ?,
                verdict = ?,
                trust_factor = ?,
                members = ?,
                ad_links = ?,
                category = ?,
                category_secondary = ?,
                photo_url = ?,
                breakdown_json = ?,
                scanned_at = ?
            WHERE username = ?
        ''', (status, score, verdict, trust_factor, members, ad_links_json, category, category_secondary, photo_url, breakdown_json, datetime.now(), username))
        self.conn.commit()

    def set_category(self, username: str, category: str, category_secondary: str = None, percent: int = 100):
        """
        Устанавливает категорию для канала (для догоняния).

        Args:
            username: имя канала
            category: основная категория
            category_secondary: вторичная категория (опционально, для multi-label)
            percent: процент основной категории (по умолчанию 100)
        """
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE channels SET category = ?, category_secondary = ?, category_percent = ? WHERE username = ?",
            (category, category_secondary, percent, username)
        )
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
            category=row['category'] if 'category' in row.keys() else None,
            category_secondary=row['category_secondary'] if 'category_secondary' in row.keys() else None,
            category_percent=row['category_percent'] if 'category_percent' in row.keys() else 100,
            photo_url=row['photo_url'] if 'photo_url' in row.keys() else None,
            breakdown_json=row['breakdown_json'] if 'breakdown_json' in row.keys() else None,  # v21.0
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
                category=row['category'] if 'category' in row.keys() else None,
                category_secondary=row['category_secondary'] if 'category_secondary' in row.keys() else None,
                photo_url=row['photo_url'] if 'photo_url' in row.keys() else None,
                scanned_at=row['scanned_at'],
                created_at=row['created_at']
            ))

        return channels

    def get_uncategorized(self, limit: int = 100) -> list:
        """Возвращает GOOD каналы без категории (для догоняния)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT username FROM channels WHERE status = 'GOOD' AND (category IS NULL OR category = '') ORDER BY score DESC LIMIT ?",
            (limit,)
        )
        return [row['username'] for row in cursor.fetchall()]

    def get_category_stats(self) -> dict:
        """Возвращает статистику по категориям."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                COALESCE(category, 'UNCATEGORIZED') as cat,
                COUNT(*) as cnt
            FROM channels
            WHERE status = 'GOOD'
            GROUP BY category
            ORDER BY cnt DESC
        """)

        stats = {}
        for row in cursor.fetchall():
            stats[row['cat']] = row['cnt']
        return stats

    def export_csv(self, filepath: str, status: str = "GOOD", category: str = None) -> int:
        """
        Экспортирует каналы в CSV.

        Args:
            filepath: путь к файлу
            status: фильтр по статусу (GOOD, BAD, etc.)
            category: фильтр по категории (опционально, ищет в category И category_secondary)
        """
        import csv

        cursor = self.conn.cursor()
        if category:
            # Поиск по основной ИЛИ вторичной категории
            cursor.execute(
                "SELECT username, score, verdict, members, category, category_secondary, found_via, scanned_at FROM channels WHERE status = ? AND (category = ? OR category_secondary = ?) ORDER BY score DESC",
                (status, category, category)
            )
        else:
            cursor.execute(
                "SELECT username, score, verdict, members, category, category_secondary, found_via, scanned_at FROM channels WHERE status = ? ORDER BY score DESC",
                (status,)
            )

        rows = cursor.fetchall()
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['username', 'score', 'verdict', 'members', 'category', 'category_secondary', 'found_via', 'scanned_at'])
            for row in rows:
                writer.writerow([
                    f"@{row['username']}",
                    row['score'],
                    row['verdict'],
                    row['members'],
                    row['category'] or '',
                    row['category_secondary'] or '',
                    row['found_via'],
                    row['scanned_at']
                ])

        return len(rows)

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
