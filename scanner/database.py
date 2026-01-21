"""
База данных для Smart Crawler.
v22.0: Хранение контента для переклассификации (title, description, content_json).

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
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
    photo_url: str = None  # v19.0: deprecated, фото загружаются через /api/photo/{username}
    breakdown_json: str = None  # v21.0: Детальный breakdown метрик (JSON)
    title: str = None  # v22.0: Название канала
    description: str = None  # v22.0: Описание канала
    content_json: str = None  # v22.0: Тексты постов для переклассификации
    scanned_at: datetime = None
    created_at: datetime = None
    # v56.0: Полное хранение данных сканирования
    raw_score: int = None
    is_scam: bool = False
    scam_reason: str = None
    tier: str = None
    trust_penalties_json: str = None
    conviction_score: int = None
    conviction_factors_json: str = None
    forensics_json: str = None
    online_count: int = None
    participants_count: int = None
    channel_age_days: int = None
    avg_views: float = None
    reach_percent: float = None
    forward_rate: float = None
    reaction_rate: float = None
    avg_comments: float = None
    comments_enabled: bool = True
    reactions_enabled: bool = True
    decay_ratio: float = None
    decay_zone: str = None
    er_trend: float = None
    er_trend_status: str = None
    ad_percentage: int = None
    bot_percentage: int = None
    comment_trust: int = None
    safety_json: str = None
    posts_raw_json: str = None
    user_ids_json: str = None
    linked_chat_id: int = None
    linked_chat_title: str = None


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

        # v22.0: Миграция - добавляем колонки для переклассификации
        self._migrate_v22_content_storage()

        # v56.0: Миграция - полное хранение данных сканирования (30 новых колонок)
        self._migrate_v56_full_data()

        # v59.5: Миграция - приоритет для пользовательских запросов
        self._migrate_v59_priority()

        # Индексы для category (после миграции)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON channels(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category_secondary ON channels(category_secondary)')

        # v57.0: Composite индексы для ускорения запросов
        # get_next() + peek_next() — ORDER BY created_at WHERE status='WAITING'
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_created ON channels(status, created_at)')
        # API фильтрация — WHERE status IN (...) AND score >= X
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_score ON channels(status, score)')
        # Фильтрация с trust_factor
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_score_trust ON channels(status, score, trust_factor)')
        # Категории
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_category ON channels(status, category)')

        # v58.0: Таблица очереди запросов на сканирование
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                processed_at DATETIME DEFAULT NULL,
                error TEXT DEFAULT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_scan_requests_status ON scan_requests(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_scan_requests_created ON scan_requests(created_at)')

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
        except sqlite3.OperationalError as e:
            # Колонка уже существует (duplicate column name)
            logger.debug(f"Migration category: column already exists or table issue: {e}")
        except sqlite3.Error as e:
            logger.error(f"Migration category failed: {e}")

    def _migrate_add_category_secondary(self):
        """Миграция v18.0: добавляет колонку category_secondary для multi-label."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'category_secondary' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN category_secondary TEXT DEFAULT NULL")
                print("Миграция v18.0: добавлена колонка category_secondary")
        except sqlite3.OperationalError as e:
            logger.debug(f"Migration category_secondary: column already exists or table issue: {e}")
        except sqlite3.Error as e:
            logger.error(f"Migration category_secondary failed: {e}")

    def _migrate_add_photo_url(self):
        """Миграция v19.0: добавляет колонку photo_url для аватарок каналов."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'photo_url' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN photo_url TEXT DEFAULT NULL")
                print("Миграция v19.0: добавлена колонка photo_url")
        except sqlite3.OperationalError as e:
            logger.debug(f"Migration photo_url: column already exists or table issue: {e}")
        except sqlite3.Error as e:
            logger.error(f"Migration photo_url failed: {e}")

        # v20.0: category_percent для мульти-категорий с процентами
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'category_percent' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN category_percent INTEGER DEFAULT 100")
                print("Миграция v20.0: добавлена колонка category_percent")
        except sqlite3.OperationalError as e:
            logger.debug(f"Migration category_percent: column already exists or table issue: {e}")
        except sqlite3.Error as e:
            logger.error(f"Migration category_percent failed: {e}")

    def _migrate_add_breakdown(self):
        """Миграция v21.0: добавляет колонку breakdown_json для реальных метрик."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(channels)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'breakdown_json' not in columns:
                cursor.execute("ALTER TABLE channels ADD COLUMN breakdown_json TEXT DEFAULT NULL")
                print("Миграция v21.0: добавлена колонка breakdown_json")
        except sqlite3.OperationalError as e:
            logger.debug(f"Migration breakdown_json: column already exists or table issue: {e}")
        except sqlite3.Error as e:
            logger.error(f"Migration breakdown_json failed: {e}")

    def _migrate_v22_content_storage(self):
        """Миграция v22.0: добавляет колонки для хранения контента и переклассификации."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(channels)")
        columns = [row[1] for row in cursor.fetchall()]

        # Добавляем новые колонки
        new_columns = ['title', 'description', 'content_json']
        for col in new_columns:
            if col not in columns:
                try:
                    cursor.execute(f"ALTER TABLE channels ADD COLUMN {col} TEXT DEFAULT NULL")
                    print(f"Миграция v22.0: добавлена колонка {col}")
                except sqlite3.OperationalError as e:
                    logger.debug(f"Migration v22.0 {col}: column already exists or table issue: {e}")
                except sqlite3.Error as e:
                    logger.error(f"Migration v22.0 {col} failed: {e}")

        self.conn.commit()

    def _migrate_v56_full_data(self):
        """v56.0: Полное хранение данных сканирования (30 новых колонок)."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(channels)")
        columns = [row[1] for row in cursor.fetchall()]

        new_columns = [
            ('raw_score', 'INTEGER DEFAULT NULL'),
            ('is_scam', 'INTEGER DEFAULT 0'),
            ('scam_reason', 'TEXT DEFAULT NULL'),
            ('tier', 'TEXT DEFAULT NULL'),
            ('trust_penalties_json', 'TEXT DEFAULT NULL'),
            ('conviction_score', 'INTEGER DEFAULT NULL'),
            ('conviction_factors_json', 'TEXT DEFAULT NULL'),
            ('forensics_json', 'TEXT DEFAULT NULL'),
            ('online_count', 'INTEGER DEFAULT NULL'),
            ('participants_count', 'INTEGER DEFAULT NULL'),
            ('channel_age_days', 'INTEGER DEFAULT NULL'),
            ('avg_views', 'REAL DEFAULT NULL'),
            ('reach_percent', 'REAL DEFAULT NULL'),
            ('forward_rate', 'REAL DEFAULT NULL'),
            ('reaction_rate', 'REAL DEFAULT NULL'),
            ('avg_comments', 'REAL DEFAULT NULL'),
            ('comments_enabled', 'INTEGER DEFAULT 1'),
            ('reactions_enabled', 'INTEGER DEFAULT 1'),
            ('decay_ratio', 'REAL DEFAULT NULL'),
            ('decay_zone', 'TEXT DEFAULT NULL'),
            ('er_trend', 'REAL DEFAULT NULL'),
            ('er_trend_status', 'TEXT DEFAULT NULL'),
            ('ad_percentage', 'INTEGER DEFAULT NULL'),
            ('bot_percentage', 'INTEGER DEFAULT NULL'),
            ('comment_trust', 'INTEGER DEFAULT NULL'),
            ('safety_json', 'TEXT DEFAULT NULL'),
            ('posts_raw_json', 'TEXT DEFAULT NULL'),
            ('user_ids_json', 'TEXT DEFAULT NULL'),
            ('linked_chat_id', 'INTEGER DEFAULT NULL'),
            ('linked_chat_title', 'TEXT DEFAULT NULL'),
        ]

        added = []
        for col_name, col_def in new_columns:
            if col_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE channels ADD COLUMN {col_name} {col_def}")
                    added.append(col_name)
                except sqlite3.OperationalError as e:
                    logger.debug(f"Migration v56.0 {col_name}: column already exists or table issue: {e}")
                except sqlite3.Error as e:
                    logger.error(f"Migration v56.0 {col_name} failed: {e}")

        if added:
            print(f"Миграция v56.0: добавлено {len(added)} колонок: {', '.join(added[:5])}...")

        self.conn.commit()

    def _migrate_v59_priority(self):
        """v59.5: Приоритет для пользовательских запросов."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(channels)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'priority' not in columns:
            try:
                cursor.execute("ALTER TABLE channels ADD COLUMN priority INTEGER DEFAULT 0")
                # Индекс для быстрой сортировки по приоритету
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_priority_created ON channels(priority DESC, created_at ASC)")
                print("Миграция v59.5: добавлена колонка priority")
            except sqlite3.OperationalError as e:
                logger.debug(f"Migration v59.5 priority: {e}")

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
        except sqlite3.IntegrityError as e:
            # Ожидаемо: дубликат канала (UNIQUE constraint)
            logger.debug(f"Channel {username} already exists: {e}")
            return False
        except sqlite3.OperationalError as e:
            # Database locked, no such table, etc.
            logger.error(f"Database operational error adding channel {username}: {e}")
            return False
        except sqlite3.Error as e:
            logger.error(f"Database error adding channel {username}: {e}")
            return False

    def add_channels_batch(self, channels: list[tuple[str, str]]) -> int:
        """Batch добавление каналов в одной транзакции.

        Args:
            channels: List of (username, parent) tuples
        Returns:
            Количество добавленных (без дубликатов)
        """
        if not channels:
            return 0

        normalized = [
            (username.lower().lstrip('@'), parent)
            for username, parent in channels
        ]

        cursor = self.conn.cursor()
        try:
            cursor.executemany(
                "INSERT OR IGNORE INTO channels (username, found_via) VALUES (?, ?)",
                normalized
            )
            added = cursor.rowcount
            self.conn.commit()
            return added
        except sqlite3.Error as e:
            logger.error(f"Batch insert failed: {e}")
            self.conn.rollback()
            return 0

    def get_next(self) -> Optional[str]:
        """
        Возвращает следующий канал для проверки (WAITING).
        v59.5: Сначала приоритетные (от пользователей), потом по времени.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT username FROM channels WHERE status = 'WAITING' ORDER BY priority DESC, created_at ASC LIMIT 1"
        )
        row = cursor.fetchone()
        return row['username'] if row else None

    def mark_processing(self, username: str):
        """Помечает канал как обрабатываемый."""
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE channels SET status = 'PROCESSING' WHERE LOWER(username) = ?",
            (username,)
        )
        self.conn.commit()

    def get_next_atomic(self) -> Optional[str]:
        """
        Атомарно получить и заблокировать следующий канал.

        Использует UPDATE...RETURNING для атомарности.
        Избегает race condition при параллельных краулерах.

        Требует SQLite 3.35+ (Python 3.10+ обычно включает).

        Returns:
            username канала или None если очередь пуста
        """
        cursor = self.conn.cursor()
        # v59.5: Сначала приоритетные (от пользователей), потом по времени
        cursor.execute("""
            UPDATE channels
            SET status = 'PROCESSING', scanned_at = datetime('now')
            WHERE username = (
                SELECT username FROM channels
                WHERE status = 'WAITING'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            RETURNING username
        """)
        row = cursor.fetchone()
        self.conn.commit()
        return row['username'] if row else None

    # ========== v43.0: All-or-nothing механика ==========

    def peek_next(self) -> Optional[str]:
        """
        v43.0: Возвращает следующий канал БЕЗ изменения статуса.

        Используется для "всё или ничего" семантики:
        - Берём канал
        - Обрабатываем в памяти
        - Записываем атомарно через claim_and_complete()

        При Ctrl+C или краше канал остаётся WAITING.

        Returns:
            username канала или None если очередь пуста
        """
        cursor = self.conn.cursor()
        # v59.5: Сначала приоритетные (от пользователей), потом по времени
        cursor.execute("""
            SELECT username FROM channels
            WHERE status = 'WAITING'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return row['username'] if row else None

    def claim_and_complete(
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
        breakdown: dict = None,
        categories: dict = None,
        llm_analysis: dict = None,
        title: str = None,
        description: str = None,
        content_json: str = None,
        # v56.0: Новые поля для полного хранения данных
        raw_score: int = None,
        is_scam: bool = False,
        scam_reason: str = None,
        tier: str = None,
        trust_penalties: list = None,
        conviction_score: int = None,
        conviction_factors: list = None,
        forensics: dict = None,
        online_count: int = None,
        participants_count: int = None,
        channel_age_days: int = None,
        avg_views: float = None,
        reach_percent: float = None,
        forward_rate: float = None,
        reaction_rate: float = None,
        avg_comments: float = None,
        comments_enabled: bool = True,
        reactions_enabled: bool = True,
        decay_ratio: float = None,
        decay_zone: str = None,
        er_trend: float = None,
        er_trend_status: str = None,
        ad_percentage: int = None,
        bot_percentage: int = None,
        comment_trust: int = None,
        safety: dict = None,
        posts_raw: list = None,
        user_ids: list = None,
        linked_chat_id: int = None,
        linked_chat_title: str = None
    ) -> bool:
        """
        v43.0: Атомарно записывает результат ТОЛЬКО если канал в WAITING.
        v56.0: Расширено для полного хранения данных сканирования.

        Реализует "всё или ничего" семантику:
        - Если канал в WAITING → записываем ВСЕ данные, возвращаем True
        - Если канал в другом статусе → ничего не делаем, возвращаем False

        Защита параллельных краулеров (optimistic locking):
        - Только один краулер успешно запишет результат
        - Остальные получат False и возьмут следующий канал

        Returns:
            True если успешно записали, False если канал уже обработан
        """
        username = username.lower().lstrip('@')
        ad_links_json = json.dumps(ad_links or [], ensure_ascii=False)

        breakdown_json = None
        if breakdown or categories or llm_analysis:
            breakdown_json = json.dumps({
                'breakdown': breakdown,
                'categories': categories,
                'llm_analysis': llm_analysis
            }, ensure_ascii=False)

        # v56.0: Сериализуем новые JSON поля
        trust_penalties_json = json.dumps(trust_penalties, ensure_ascii=False) if trust_penalties else None
        conviction_factors_json = json.dumps(conviction_factors, ensure_ascii=False) if conviction_factors else None
        forensics_json = json.dumps(forensics, ensure_ascii=False) if forensics else None
        safety_json = json.dumps(safety, ensure_ascii=False) if safety else None
        posts_raw_json = json.dumps(posts_raw, ensure_ascii=False) if posts_raw else None
        user_ids_json = json.dumps(user_ids, ensure_ascii=False) if user_ids else None

        cursor = self.conn.cursor()
        # v57.0: username нормализован на входе (line 483), LOWER() не нужен
        cursor.execute("""
            UPDATE channels SET
                status = ?,
                score = ?,
                verdict = ?,
                trust_factor = ?,
                members = ?,
                ad_links = ?,
                category = COALESCE(?, category),
                category_secondary = COALESCE(?, category_secondary),
                breakdown_json = ?,
                title = ?,
                description = ?,
                content_json = ?,
                raw_score = ?,
                is_scam = ?,
                scam_reason = ?,
                tier = ?,
                trust_penalties_json = ?,
                conviction_score = ?,
                conviction_factors_json = ?,
                forensics_json = ?,
                online_count = ?,
                participants_count = ?,
                channel_age_days = ?,
                avg_views = ?,
                reach_percent = ?,
                forward_rate = ?,
                reaction_rate = ?,
                avg_comments = ?,
                comments_enabled = ?,
                reactions_enabled = ?,
                decay_ratio = ?,
                decay_zone = ?,
                er_trend = ?,
                er_trend_status = ?,
                ad_percentage = ?,
                bot_percentage = ?,
                comment_trust = ?,
                safety_json = ?,
                posts_raw_json = ?,
                user_ids_json = ?,
                linked_chat_id = ?,
                linked_chat_title = ?,
                scanned_at = datetime('now')
            WHERE LOWER(username) = ? AND status = 'WAITING'
            RETURNING username
        """, (status, score, verdict, trust_factor, members, ad_links_json,
              category, category_secondary, breakdown_json,
              title, description, content_json,
              raw_score, 1 if is_scam else 0, scam_reason, tier,
              trust_penalties_json, conviction_score, conviction_factors_json,
              forensics_json, online_count, participants_count, channel_age_days,
              avg_views, reach_percent, forward_rate, reaction_rate, avg_comments,
              1 if comments_enabled else 0, 1 if reactions_enabled else 0,
              decay_ratio, decay_zone, er_trend, er_trend_status,
              ad_percentage, bot_percentage, comment_trust,
              safety_json, posts_raw_json, user_ids_json,
              linked_chat_id, linked_chat_title, username))

        row = cursor.fetchone()
        self.conn.commit()
        return row is not None

    def delete_if_waiting(self, username: str) -> bool:
        """
        v43.0: Удаляет канал ТОЛЬКО если он в WAITING.

        Для "всё или ничего" семантики с невалидными каналами:
        - Если канал ещё WAITING → удаляем, возвращаем True
        - Если канал уже обработан другим краулером → возвращаем False

        Returns:
            True если удалили, False если канал уже не WAITING
        """
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        # v59.4: LOWER() для case-insensitive (legacy данные могут быть mixed case)
        cursor.execute("""
            DELETE FROM channels
            WHERE LOWER(username) = ? AND status = 'WAITING'
        """, (username,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ========== Старые методы (для обратной совместимости) ==========

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
        photo_url: str = None,  # v22.0: deprecated, не сохраняем (фото через /api/photo/)
        breakdown: dict = None,    # v21.0: детальный breakdown метрик
        categories: dict = None,   # v21.0: итоги по категориям (quality/engagement/reputation)
        llm_analysis: dict = None,  # v38.0: LLM анализ (tier, brand_safety, etc.)
        title: str = None,  # v22.0: название канала
        description: str = None,  # v22.0: описание канала
        content_json: str = None,  # v22.0: тексты постов (JSON)
        # v56.0: Новые поля для полного хранения данных
        raw_score: int = None,
        is_scam: bool = False,
        scam_reason: str = None,
        tier: str = None,
        trust_penalties: list = None,
        conviction_score: int = None,
        conviction_factors: list = None,
        forensics: dict = None,
        online_count: int = None,
        participants_count: int = None,
        channel_age_days: int = None,
        avg_views: float = None,
        reach_percent: float = None,
        forward_rate: float = None,
        reaction_rate: float = None,
        avg_comments: float = None,
        comments_enabled: bool = True,
        reactions_enabled: bool = True,
        decay_ratio: float = None,
        decay_zone: str = None,
        er_trend: float = None,
        er_trend_status: str = None,
        ad_percentage: int = None,
        bot_percentage: int = None,
        comment_trust: int = None,
        safety: dict = None,
        posts_raw: list = None,
        user_ids: list = None,
        linked_chat_id: int = None,
        linked_chat_title: str = None
    ):
        """
        Помечает канал как проверенный.
        v56.0: Расширено для полного хранения данных сканирования.

        Args:
            status: GOOD, BAD, ERROR, PRIVATE
            score: 0-100
            verdict: Текстовый вердикт (EXCELLENT, SCAM, etc.)
            trust_factor: Trust Multiplier
            members: Количество подписчиков
            ad_links: Список найденных рекламных ссылок
            category: AI категория основная (CRYPTO, NEWS, TECH и т.д.)
            category_secondary: AI категория вторичная (для multi-label)
            photo_url: deprecated v22.0 - не используется, фото загружаются через API
            breakdown: v21.0 - детальные метрики (cv_views, reach, verified, etc.)
            categories: v21.0 - итоги по категориям (quality, engagement, reputation)
            llm_analysis: v38.0 - LLM анализ (tier, tier_cap, posts, comments)
            title: v22.0 - название канала для переклассификации
            description: v22.0 - описание канала для переклассификации
            content_json: v22.0 - тексты постов (JSON) для переклассификации
            raw_score: v56.0 - сырой score до применения trust_factor
            is_scam: v56.0 - флаг SCAM
            scam_reason: v56.0 - причина SCAM вердикта
            tier: v56.0 - tier канала (от LLM)
            trust_penalties: v56.0 - список примененных штрафов trust
            conviction_score: v56.0 - score из FraudConvictionSystem
            conviction_factors: v56.0 - факторы fraud conviction
            forensics: v56.0 - результаты forensics анализа
            online_count: v56.0 - число онлайн участников
            participants_count: v56.0 - общее число участников
            channel_age_days: v56.0 - возраст канала в днях
            avg_views: v56.0 - среднее просмотров
            reach_percent: v56.0 - процент охвата
            forward_rate: v56.0 - процент пересылок
            reaction_rate: v56.0 - процент реакций
            avg_comments: v56.0 - среднее комментариев
            comments_enabled: v56.0 - флаг включенных комментариев
            reactions_enabled: v56.0 - флаг включенных реакций
            decay_ratio: v56.0 - коэффициент затухания просмотров
            decay_zone: v56.0 - зона затухания (ORGANIC/BOT_WALL/etc.)
            er_trend: v56.0 - тренд engagement rate
            er_trend_status: v56.0 - статус тренда (GROWING/STABLE/DECLINING)
            ad_percentage: v56.0 - процент рекламы
            bot_percentage: v56.0 - процент ботов
            comment_trust: v56.0 - trust score комментариев
            safety: v56.0 - brand safety данные
            posts_raw: v56.0 - сырые данные постов
            user_ids: v56.0 - IDs пользователей для forensics
            linked_chat_id: v56.0 - ID связанного чата
            linked_chat_title: v56.0 - название связанного чата
        """
        username = username.lower().lstrip('@')
        ad_links_json = json.dumps(ad_links or [])

        # v38.0: Сериализуем breakdown + llm_analysis в JSON
        breakdown_json = None
        if breakdown or categories or llm_analysis:
            breakdown_json = json.dumps({
                'breakdown': breakdown,
                'categories': categories,
                'llm_analysis': llm_analysis  # v38.0
            }, ensure_ascii=False)

        # v56.0: Сериализуем новые JSON поля
        trust_penalties_json = json.dumps(trust_penalties, ensure_ascii=False) if trust_penalties else None
        conviction_factors_json = json.dumps(conviction_factors, ensure_ascii=False) if conviction_factors else None
        forensics_json = json.dumps(forensics, ensure_ascii=False) if forensics else None
        safety_json = json.dumps(safety, ensure_ascii=False) if safety else None
        posts_raw_json = json.dumps(posts_raw, ensure_ascii=False) if posts_raw else None
        user_ids_json = json.dumps(user_ids, ensure_ascii=False) if user_ids else None

        cursor = self.conn.cursor()
        # v24.0: COALESCE чтобы не перезаписывать category/category_secondary если NULL
        # v22.0: photo_url больше не сохраняем, title/description/content_json добавлены
        # v56.0: Добавлены 30 новых колонок для полного хранения данных
        cursor.execute('''
            UPDATE channels SET
                status = ?,
                score = ?,
                verdict = ?,
                trust_factor = ?,
                members = ?,
                ad_links = ?,
                category = COALESCE(?, category),
                category_secondary = COALESCE(?, category_secondary),
                breakdown_json = ?,
                title = ?,
                description = ?,
                content_json = ?,
                raw_score = ?,
                is_scam = ?,
                scam_reason = ?,
                tier = ?,
                trust_penalties_json = ?,
                conviction_score = ?,
                conviction_factors_json = ?,
                forensics_json = ?,
                online_count = ?,
                participants_count = ?,
                channel_age_days = ?,
                avg_views = ?,
                reach_percent = ?,
                forward_rate = ?,
                reaction_rate = ?,
                avg_comments = ?,
                comments_enabled = ?,
                reactions_enabled = ?,
                decay_ratio = ?,
                decay_zone = ?,
                er_trend = ?,
                er_trend_status = ?,
                ad_percentage = ?,
                bot_percentage = ?,
                comment_trust = ?,
                safety_json = ?,
                posts_raw_json = ?,
                user_ids_json = ?,
                linked_chat_id = ?,
                linked_chat_title = ?,
                scanned_at = ?
            WHERE LOWER(username) = ?
        ''', (status, score, verdict, trust_factor, members, ad_links_json,
              category, category_secondary, breakdown_json,
              title, description, content_json,
              raw_score, 1 if is_scam else 0, scam_reason, tier,
              trust_penalties_json, conviction_score, conviction_factors_json,
              forensics_json, online_count, participants_count, channel_age_days,
              avg_views, reach_percent, forward_rate, reaction_rate, avg_comments,
              1 if comments_enabled else 0, 1 if reactions_enabled else 0,
              decay_ratio, decay_zone, er_trend, er_trend_status,
              ad_percentage, bot_percentage, comment_trust,
              safety_json, posts_raw_json, user_ids_json,
              linked_chat_id, linked_chat_title, datetime.now(), username))
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
            "UPDATE channels SET category = ?, category_secondary = ?, category_percent = ? WHERE LOWER(username) = ?",
            (category, category_secondary, percent, username)
        )
        self.conn.commit()

    def get_channel(self, username: str) -> Optional[ChannelRecord]:
        """Возвращает запись о канале."""
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM channels WHERE LOWER(username) = ?", (username,))
        row = cursor.fetchone()

        if not row:
            return None

        keys = row.keys()

        def get_col(name, default=None):
            """Безопасно получает значение колонки."""
            return row[name] if name in keys else default

        return ChannelRecord(
            username=row['username'],
            status=row['status'],
            score=row['score'],
            verdict=row['verdict'],
            trust_factor=row['trust_factor'],
            members=row['members'],
            found_via=row['found_via'],
            ad_links=json.loads(row['ad_links']) if row['ad_links'] else [],
            category=get_col('category'),
            category_secondary=get_col('category_secondary'),
            category_percent=get_col('category_percent', 100),
            photo_url=get_col('photo_url'),
            breakdown_json=get_col('breakdown_json'),
            title=get_col('title'),  # v22.0
            description=get_col('description'),  # v22.0
            content_json=get_col('content_json'),  # v22.0
            scanned_at=row['scanned_at'],
            created_at=row['created_at'],
            # v56.0: Новые поля для полного хранения данных
            raw_score=get_col('raw_score'),
            is_scam=bool(get_col('is_scam', 0)),
            scam_reason=get_col('scam_reason'),
            tier=get_col('tier'),
            trust_penalties_json=get_col('trust_penalties_json'),
            conviction_score=get_col('conviction_score'),
            conviction_factors_json=get_col('conviction_factors_json'),
            forensics_json=get_col('forensics_json'),
            online_count=get_col('online_count'),
            participants_count=get_col('participants_count'),
            channel_age_days=get_col('channel_age_days'),
            avg_views=get_col('avg_views'),
            reach_percent=get_col('reach_percent'),
            forward_rate=get_col('forward_rate'),
            reaction_rate=get_col('reaction_rate'),
            avg_comments=get_col('avg_comments'),
            comments_enabled=bool(get_col('comments_enabled', 1)),
            reactions_enabled=bool(get_col('reactions_enabled', 1)),
            decay_ratio=get_col('decay_ratio'),
            decay_zone=get_col('decay_zone'),
            er_trend=get_col('er_trend'),
            er_trend_status=get_col('er_trend_status'),
            ad_percentage=get_col('ad_percentage'),
            bot_percentage=get_col('bot_percentage'),
            comment_trust=get_col('comment_trust'),
            safety_json=get_col('safety_json'),
            posts_raw_json=get_col('posts_raw_json'),
            user_ids_json=get_col('user_ids_json'),
            linked_chat_id=get_col('linked_chat_id'),
            linked_chat_title=get_col('linked_chat_title'),
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

    def delete_channel(self, username: str) -> bool:
        """
        v42.0: Удаляет канал из базы (для невалидных).

        Используется для: ChannelInvalid, ChannelPrivate, NOT_CHANNEL,
        USERNAME_NOT_OCCUPIED, Max retries exceeded.
        """
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM channels WHERE LOWER(username) = ?", (username,))
        self.conn.commit()
        return cursor.rowcount > 0

    def requeue_channel(self, username: str) -> bool:
        """
        v42.0: Кидает канал в конец очереди (для временных ошибок).

        Обновляет created_at на NOW — канал будет обработан последним.
        Используется для: Timeout, Connection errors.
        """
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE channels
            SET status = 'WAITING', created_at = datetime('now')
            WHERE LOWER(username) = ?
        """, (username,))
        self.conn.commit()
        return cursor.rowcount > 0

    def reset_processing(self):
        """
        Сбрасывает все PROCESSING обратно в WAITING.
        Полезно при перезапуске после краша.
        """
        cursor = self.conn.cursor()
        cursor.execute("UPDATE channels SET status = 'WAITING' WHERE status = 'PROCESSING'")
        self.conn.commit()
        return cursor.rowcount

    # =========================================================================
    # v58.0: Scan Requests Queue
    # =========================================================================

    def add_scan_request(self, username: str) -> int:
        """
        v59.5: Добавляет запрос на сканирование в очередь.
        Также добавляет в channels с priority=1 для приоритетной обработки.
        Returns: ID созданного запроса (или существующего)
        """
        username = username.lower().lstrip('@')
        cursor = self.conn.cursor()

        # v59.5: СНАЧАЛА добавляем в channels с приоритетом
        # ON CONFLICT — если канал уже есть, повышаем priority
        cursor.execute("""
            INSERT INTO channels (username, status, priority, found_via)
            VALUES (?, 'WAITING', 1, 'user_request')
            ON CONFLICT(username) DO UPDATE SET
                priority = 1,
                status = CASE WHEN status IN ('GOOD', 'BAD') THEN status ELSE 'WAITING' END
        """, (username,))

        # Проверяем нет ли уже pending запроса на этот канал
        cursor.execute(
            "SELECT id FROM scan_requests WHERE LOWER(username) = ? AND status = 'pending'",
            (username,)
        )
        existing = cursor.fetchone()
        if existing:
            self.conn.commit()
            return existing[0]  # Возвращаем существующий ID

        # Добавляем в scan_requests для отслеживания
        cursor.execute(
            "INSERT INTO scan_requests (username, status) VALUES (?, 'pending')",
            (username,)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_scan_requests(self, limit: int = 5) -> list:
        """
        Возвращает последние запросы на сканирование.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, username, status, created_at, processed_at, error
            FROM scan_requests
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [
            {
                'id': r[0],
                'username': r[1],
                'status': r[2],
                'created_at': r[3],
                'processed_at': r[4],
                'error': r[5]
            }
            for r in rows
        ]

    def get_pending_scan_requests(self, limit: int = 10) -> list:
        """
        Возвращает pending запросы для обработки.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, username
            FROM scan_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
        return [{'id': r[0], 'username': r[1]} for r in cursor.fetchall()]

    def update_scan_request(self, request_id: int, status: str, error: str = None):
        """
        Обновляет статус запроса.
        """
        cursor = self.conn.cursor()
        if status in ('done', 'error'):
            cursor.execute("""
                UPDATE scan_requests
                SET status = ?, processed_at = datetime('now'), error = ?
                WHERE id = ?
            """, (status, error, request_id))
        else:
            cursor.execute(
                "UPDATE scan_requests SET status = ? WHERE id = ?",
                (status, request_id)
            )
        self.conn.commit()

    def close(self):
        """Закрывает соединение."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
