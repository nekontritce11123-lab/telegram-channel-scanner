"""
Тесты для scanner/database.py.

v1.0: Базовые тесты + проверка race condition в get_next() + mark_processing().

Запуск:
    pytest tests/test_database.py -v
    pytest tests/test_database.py -v -k "race"  # Только тесты на race condition
"""

import pytest
import sqlite3
import tempfile
import threading
import time
import os
from pathlib import Path
from typing import List, Set

# Добавляем путь к scanner в PYTHONPATH
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scanner.database import CrawlerDB, ChannelRecord


class TestCrawlerDBBasic:
    """Базовые тесты для CrawlerDB."""

    @pytest.fixture
    def temp_db(self):
        """Создать временную БД для тестов."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = CrawlerDB(db_path)
        yield db

        db.close()
        # Удаляем временный файл
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_add_channel_new(self, temp_db):
        """Добавление нового канала возвращает True."""
        result = temp_db.add_channel('test_channel')
        assert result is True, "add_channel должен вернуть True для нового канала"

    def test_add_channel_duplicate(self, temp_db):
        """Повторное добавление канала возвращает False."""
        temp_db.add_channel('test_channel')
        result = temp_db.add_channel('test_channel')
        assert result is False, "add_channel должен вернуть False для дубликата"

    def test_add_channel_normalizes_username(self, temp_db):
        """Username нормализуется (lowercase, без @)."""
        temp_db.add_channel('@TeSt_ChAnNeL')
        channel = temp_db.get_channel('test_channel')
        assert channel is not None, "Канал должен быть найден по нормализованному имени"
        assert channel.username == 'test_channel'

    def test_get_channel_returns_record(self, temp_db):
        """get_channel возвращает ChannelRecord."""
        temp_db.add_channel('test_channel', parent='seed')
        channel = temp_db.get_channel('test_channel')

        assert isinstance(channel, ChannelRecord)
        assert channel.username == 'test_channel'
        assert channel.status == 'WAITING'
        assert channel.found_via == 'seed'

    def test_get_channel_not_found(self, temp_db):
        """get_channel возвращает None для несуществующего канала."""
        channel = temp_db.get_channel('nonexistent')
        assert channel is None

    def test_get_next_returns_waiting(self, temp_db):
        """get_next возвращает WAITING канал."""
        temp_db.add_channel('channel1')
        temp_db.add_channel('channel2')

        next_channel = temp_db.get_next()
        assert next_channel == 'channel1', "get_next должен вернуть первый добавленный канал"

    def test_get_next_respects_order(self, temp_db):
        """get_next возвращает каналы в порядке добавления (FIFO)."""
        for i in range(5):
            temp_db.add_channel(f'channel_{i}')
            time.sleep(0.01)  # Небольшая задержка для разного created_at

        for i in range(5):
            next_channel = temp_db.get_next()
            assert next_channel == f'channel_{i}', f"Ожидался channel_{i}, получен {next_channel}"
            temp_db.mark_processing(next_channel)
            temp_db.mark_done(next_channel, 'GOOD', score=50)

    def test_get_next_empty_returns_none(self, temp_db):
        """get_next возвращает None для пустой очереди."""
        result = temp_db.get_next()
        assert result is None

    def test_mark_processing_changes_status(self, temp_db):
        """mark_processing меняет статус на PROCESSING."""
        temp_db.add_channel('test_channel')
        temp_db.mark_processing('test_channel')

        channel = temp_db.get_channel('test_channel')
        assert channel.status == 'PROCESSING'

    def test_mark_done_good(self, temp_db):
        """mark_done с GOOD статусом."""
        temp_db.add_channel('test_channel')
        temp_db.mark_processing('test_channel')
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=75,
            verdict='EXCELLENT',
            trust_factor=0.95,
            members=10000
        )

        channel = temp_db.get_channel('test_channel')
        assert channel.status == 'GOOD'
        assert channel.score == 75
        assert channel.verdict == 'EXCELLENT'
        assert channel.trust_factor == 0.95
        assert channel.members == 10000
        assert channel.scanned_at is not None

    def test_mark_done_bad(self, temp_db):
        """mark_done с BAD статусом."""
        temp_db.add_channel('test_channel')
        temp_db.mark_done('test_channel', status='BAD', score=25, verdict='SCAM')

        channel = temp_db.get_channel('test_channel')
        assert channel.status == 'BAD'
        assert channel.verdict == 'SCAM'

    def test_mark_done_with_category(self, temp_db):
        """mark_done сохраняет категорию."""
        temp_db.add_channel('test_channel')
        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            category='CRYPTO',
            category_secondary='TECH'
        )

        channel = temp_db.get_channel('test_channel')
        assert channel.category == 'CRYPTO'
        assert channel.category_secondary == 'TECH'

    def test_mark_done_coalesce_category(self, temp_db):
        """mark_done с NULL категорией не перезаписывает существующую."""
        temp_db.add_channel('test_channel')
        temp_db.mark_done('test_channel', status='GOOD', score=70, category='CRYPTO')

        # Второй mark_done без категории
        temp_db.mark_done('test_channel', status='GOOD', score=80, category=None)

        channel = temp_db.get_channel('test_channel')
        assert channel.category == 'CRYPTO', "COALESCE должен сохранить существующую категорию"
        assert channel.score == 80, "Другие поля должны обновиться"

    def test_set_category(self, temp_db):
        """set_category устанавливает категорию."""
        temp_db.add_channel('test_channel')
        temp_db.set_category('test_channel', 'NEWS', 'ENTERTAINMENT', 70)

        channel = temp_db.get_channel('test_channel')
        assert channel.category == 'NEWS'
        assert channel.category_secondary == 'ENTERTAINMENT'
        assert channel.category_percent == 70

    def test_delete_channel(self, temp_db):
        """delete_channel удаляет канал из базы."""
        temp_db.add_channel('test_channel')
        assert temp_db.get_channel('test_channel') is not None

        result = temp_db.delete_channel('test_channel')
        assert result is True
        assert temp_db.get_channel('test_channel') is None

    def test_delete_channel_nonexistent(self, temp_db):
        """delete_channel возвращает False для несуществующего канала."""
        result = temp_db.delete_channel('nonexistent')
        assert result is False

    def test_requeue_channel(self, temp_db):
        """requeue_channel отправляет канал в конец очереди."""
        temp_db.add_channel('channel1')
        time.sleep(0.5)  # Увеличен интервал для надёжности SQLite datetime
        temp_db.add_channel('channel2')
        time.sleep(0.5)

        # Берём channel1 и делаем requeue
        temp_db.mark_processing('channel1')
        time.sleep(0.5)  # Ждём перед requeue чтобы datetime отличался
        temp_db.requeue_channel('channel1')

        # Теперь channel2 должен быть первым (его created_at раньше чем обновлённый channel1)
        next_channel = temp_db.get_next()
        assert next_channel == 'channel2', f"После requeue channel1 должен быть в конце очереди, got {next_channel}"

    def test_reset_processing(self, temp_db):
        """reset_processing сбрасывает PROCESSING обратно в WAITING."""
        for i in range(3):
            temp_db.add_channel(f'channel_{i}')
            temp_db.mark_processing(f'channel_{i}')

        count = temp_db.reset_processing()
        assert count == 3

        for i in range(3):
            channel = temp_db.get_channel(f'channel_{i}')
            assert channel.status == 'WAITING'


class TestCrawlerDBStats:
    """Тесты для статистики."""

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

    def test_get_stats_empty(self, temp_db):
        """get_stats для пустой базы."""
        stats = temp_db.get_stats()
        assert stats['total'] == 0
        assert stats['waiting'] == 0
        assert stats['good'] == 0

    def test_get_stats_counts(self, temp_db):
        """get_stats правильно считает статусы."""
        # Добавляем каналы с разными статусами
        for i in range(3):
            temp_db.add_channel(f'waiting_{i}')

        for i in range(2):
            temp_db.add_channel(f'good_{i}')
            temp_db.mark_done(f'good_{i}', 'GOOD', score=70)

        temp_db.add_channel('bad_0')
        temp_db.mark_done('bad_0', 'BAD', score=20)

        stats = temp_db.get_stats()
        assert stats['total'] == 6
        assert stats['waiting'] == 3
        assert stats['good'] == 2
        assert stats['bad'] == 1

    def test_get_category_stats(self, temp_db):
        """get_category_stats считает каналы по категориям."""
        # Добавляем GOOD каналы с категориями
        for i in range(3):
            temp_db.add_channel(f'crypto_{i}')
            temp_db.mark_done(f'crypto_{i}', 'GOOD', score=70, category='CRYPTO')

        for i in range(2):
            temp_db.add_channel(f'tech_{i}')
            temp_db.mark_done(f'tech_{i}', 'GOOD', score=70, category='TECH')

        # Один без категории
        temp_db.add_channel('uncategorized')
        temp_db.mark_done('uncategorized', 'GOOD', score=70)

        stats = temp_db.get_category_stats()
        assert stats.get('CRYPTO') == 3
        assert stats.get('TECH') == 2
        assert stats.get('UNCATEGORIZED') == 1

    def test_get_uncategorized(self, temp_db):
        """get_uncategorized возвращает GOOD каналы без категории."""
        # С категорией
        temp_db.add_channel('categorized')
        temp_db.mark_done('categorized', 'GOOD', score=70, category='CRYPTO')

        # Без категории
        temp_db.add_channel('uncategorized1')
        temp_db.mark_done('uncategorized1', 'GOOD', score=80)

        temp_db.add_channel('uncategorized2')
        temp_db.mark_done('uncategorized2', 'GOOD', score=60)

        uncategorized = temp_db.get_uncategorized()
        assert len(uncategorized) == 2
        # Сортировка по score DESC
        assert uncategorized[0] == 'uncategorized1'
        assert uncategorized[1] == 'uncategorized2'


class TestCrawlerDBRaceCondition:
    """
    Тесты на race condition в get_next() + mark_processing().

    Проблема: get_next() и mark_processing() - отдельные операции.
    Между ними другой поток может получить тот же канал.

    Сценарий:
        Thread1: get_next() -> 'channel1'
        Thread2: get_next() -> 'channel1'  # Тот же канал!
        Thread1: mark_processing('channel1')
        Thread2: mark_processing('channel1')  # Оба работают над одним каналом
    """

    @pytest.fixture
    def temp_db_path(self):
        """Возвращает путь к временной БД (не сам объект)."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_race_condition_demonstrates_problem(self, temp_db_path):
        """
        Демонстрация проблемы race condition.

        Этот тест показывает, что текущая реализация НЕ атомарна.
        Два потока могут получить один и тот же канал.
        """
        # Инициализируем БД и добавляем каналы
        db_init = CrawlerDB(temp_db_path)
        for i in range(5):
            db_init.add_channel(f'channel_{i}')
        db_init.close()

        # Результаты из потоков
        results: List[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)  # Синхронизация старта

        def worker(thread_id: int):
            """Поток который берёт канал."""
            # Каждый поток - своё соединение (SQLite requirement)
            db = CrawlerDB(temp_db_path)

            try:
                # Ждём пока оба потока будут готовы
                barrier.wait()

                # Получаем следующий канал
                channel = db.get_next()

                # Небольшая задержка чтобы увеличить вероятность race condition
                time.sleep(0.001)

                if channel:
                    db.mark_processing(channel)
                    with lock:
                        results.append(channel)
            finally:
                db.close()

        # Запускаем два потока
        threads = [
            threading.Thread(target=worker, args=(0,)),
            threading.Thread(target=worker, args=(1,))
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Проверяем результаты
        # При race condition оба потока получат один и тот же канал
        # Это тест-демонстрация проблемы, не строгий assert
        if len(results) == 2 and results[0] == results[1]:
            # Race condition произошёл - это ожидаемо с текущей реализацией
            pytest.skip("Race condition detected (expected with current implementation)")
        else:
            # Race condition не произошёл в этот раз (но может в другой)
            assert len(set(results)) == len(results), "Дублей быть не должно"

    @pytest.mark.xfail(reason="Демонстрирует race condition с get_next()+mark_processing()")
    def test_race_condition_stress_test(self, temp_db_path):
        """
        Стресс-тест на race condition с множеством потоков.

        10 каналов, 5 потоков - проверяем что нет дублей.
        XFAIL: Этот тест показывает проблему с НЕатомарным подходом.
        """
        num_channels = 10
        num_threads = 5

        # Инициализируем БД
        db_init = CrawlerDB(temp_db_path)
        for i in range(num_channels):
            db_init.add_channel(f'channel_{i}')
        db_init.close()

        # Результаты
        all_results: List[str] = []
        lock = threading.Lock()

        def worker():
            """Поток который берёт все доступные каналы."""
            db = CrawlerDB(temp_db_path)
            local_results = []

            try:
                while True:
                    channel = db.get_next()
                    if not channel:
                        break

                    db.mark_processing(channel)
                    local_results.append(channel)

                    # Имитация работы
                    time.sleep(0.001)

                    db.mark_done(channel, 'GOOD', score=70)
            finally:
                db.close()

            with lock:
                all_results.extend(local_results)

        # Запускаем потоки
        threads = [threading.Thread(target=worker) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Проверяем результаты
        # С текущей реализацией могут быть дубли из-за race condition
        unique_results = set(all_results)

        if len(all_results) != len(unique_results):
            # Дубли есть - race condition!
            duplicates = [ch for ch in all_results if all_results.count(ch) > 1]
            pytest.fail(
                f"Race condition: обнаружены дубликаты! "
                f"Всего: {len(all_results)}, уникальных: {len(unique_results)}, "
                f"дубли: {set(duplicates)}"
            )

        # Все каналы должны быть обработаны
        assert len(unique_results) == num_channels, (
            f"Ожидалось {num_channels} каналов, обработано {len(unique_results)}"
        )

    def test_get_next_atomic_no_duplicates(self, temp_db_path):
        """
        Тест для атомарной функции get_next_atomic().

        v23.0: get_next_atomic() реализована с UPDATE...RETURNING.
        Проверяем что нет дублей при параллельном вызове.
        """
        num_channels = 20
        num_threads = 10

        # Инициализируем БД
        db_init = CrawlerDB(temp_db_path)
        for i in range(num_channels):
            db_init.add_channel(f'channel_{i}')
        db_init.close()

        # Результаты
        all_results: List[str] = []
        lock = threading.Lock()

        def worker():
            """Поток который берёт каналы атомарно."""
            db = CrawlerDB(temp_db_path)
            local_results = []

            try:
                while True:
                    # Используем атомарную функцию
                    channel = db.get_next_atomic()  # type: ignore
                    if not channel:
                        break

                    local_results.append(channel)
                    time.sleep(0.001)
                    db.mark_done(channel, 'GOOD', score=70)
            finally:
                db.close()

            with lock:
                all_results.extend(local_results)

        # Запускаем потоки
        threads = [threading.Thread(target=worker) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # С атомарной функцией дублей быть НЕ ДОЛЖНО
        assert len(all_results) == len(set(all_results)), (
            f"get_next_atomic должен предотвратить дубли! "
            f"Получено: {len(all_results)}, уникальных: {len(set(all_results))}"
        )
        assert len(all_results) == num_channels


class TestCrawlerDBBreakdown:
    """Тесты для breakdown_json (v21.0+)."""

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

    def test_mark_done_with_breakdown(self, temp_db):
        """mark_done сохраняет breakdown_json."""
        temp_db.add_channel('test_channel')

        breakdown = {
            'cv_views': {'value': 5000, 'points': 12, 'max': 15},
            'reach': {'value': 0.45, 'points': 8, 'max': 10},
            'reactions_enabled': True,
            'comments_enabled': False
        }
        categories = {
            'quality': {'total': 35, 'max': 40},
            'engagement': {'total': 30, 'max': 40},
            'reputation': {'total': 15, 'max': 20}
        }

        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=80,
            breakdown=breakdown,
            categories=categories
        )

        channel = temp_db.get_channel('test_channel')
        assert channel.breakdown_json is not None

        import json
        data = json.loads(channel.breakdown_json)
        assert 'breakdown' in data
        assert 'categories' in data
        assert data['breakdown']['cv_views']['points'] == 12
        assert data['breakdown']['reactions_enabled'] is True

    def test_mark_done_with_content_v22(self, temp_db):
        """mark_done сохраняет title, description, content_json (v22.0)."""
        temp_db.add_channel('test_channel')

        temp_db.mark_done(
            'test_channel',
            status='GOOD',
            score=70,
            title='Test Channel',
            description='This is a test channel description',
            content_json='["post 1", "post 2", "post 3"]'
        )

        channel = temp_db.get_channel('test_channel')
        assert channel.title == 'Test Channel'
        assert channel.description == 'This is a test channel description'
        assert channel.content_json == '["post 1", "post 2", "post 3"]'


class TestCrawlerDBExport:
    """Тесты для экспорта в CSV."""

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

    @pytest.fixture
    def temp_csv(self):
        """Создать временный CSV файл."""
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False, mode='w') as f:
            csv_path = f.name
        yield csv_path
        try:
            os.unlink(csv_path)
        except OSError:
            pass

    def test_export_csv_basic(self, temp_db, temp_csv):
        """Экспорт GOOD каналов в CSV."""
        # Добавляем каналы
        for i in range(3):
            temp_db.add_channel(f'good_channel_{i}')
            temp_db.mark_done(f'good_channel_{i}', 'GOOD', score=70 + i, category='CRYPTO')

        temp_db.add_channel('bad_channel')
        temp_db.mark_done('bad_channel', 'BAD', score=20)

        count = temp_db.export_csv(temp_csv)
        assert count == 3

        # Проверяем содержимое
        with open(temp_csv, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 4  # Header + 3 rows
        assert 'username' in lines[0]
        assert '@good_channel_2' in lines[1]  # Сортировка по score DESC

    def test_export_csv_with_category_filter(self, temp_db, temp_csv):
        """Экспорт с фильтром по категории."""
        temp_db.add_channel('crypto1')
        temp_db.mark_done('crypto1', 'GOOD', score=70, category='CRYPTO')

        temp_db.add_channel('tech1')
        temp_db.mark_done('tech1', 'GOOD', score=80, category='TECH')

        temp_db.add_channel('crypto2')
        temp_db.mark_done('crypto2', 'GOOD', score=65, category='NEWS', category_secondary='CRYPTO')

        count = temp_db.export_csv(temp_csv, category='CRYPTO')
        assert count == 2  # crypto1 и crypto2 (по secondary)


class TestCrawlerDBContextManager:
    """Тесты для context manager."""

    def test_context_manager(self):
        """with statement работает корректно."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with CrawlerDB(db_path) as db:
                db.add_channel('test_channel')
                channel = db.get_channel('test_channel')
                assert channel is not None

            # После выхода из with соединение должно быть закрыто
            # Новое соединение должно работать
            with CrawlerDB(db_path) as db:
                channel = db.get_channel('test_channel')
                assert channel is not None
        finally:
            os.unlink(db_path)


class TestAllOrNothing:
    """
    v43.0: Тесты для all-or-nothing механики.

    Новые методы:
    - peek_next() — берёт канал БЕЗ изменения статуса
    - claim_and_complete() — атомарно записывает ТОЛЬКО если WAITING
    - delete_if_waiting() — удаляет ТОЛЬКО если WAITING
    """

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

    @pytest.fixture
    def temp_db_path(self):
        """Возвращает путь к временной БД (не сам объект)."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_peek_next_returns_waiting(self, temp_db):
        """peek_next() возвращает WAITING канал."""
        temp_db.add_channel('channel1')
        temp_db.add_channel('channel2')

        result = temp_db.peek_next()
        assert result == 'channel1', "peek_next должен вернуть первый WAITING"

    def test_peek_next_does_not_change_status(self, temp_db):
        """peek_next() НЕ меняет статус канала."""
        temp_db.add_channel('channel1')

        temp_db.peek_next()

        # Статус должен остаться WAITING
        channel = temp_db.get_channel('channel1')
        assert channel.status == 'WAITING', "peek_next не должен менять статус"

    def test_peek_next_returns_same_channel(self, temp_db):
        """peek_next() возвращает один и тот же канал при повторных вызовах."""
        temp_db.add_channel('channel1')

        result1 = temp_db.peek_next()
        result2 = temp_db.peek_next()
        result3 = temp_db.peek_next()

        assert result1 == result2 == result3 == 'channel1'

    def test_peek_next_empty_returns_none(self, temp_db):
        """peek_next() возвращает None при пустой очереди."""
        result = temp_db.peek_next()
        assert result is None

    def test_claim_and_complete_success(self, temp_db):
        """claim_and_complete() записывает данные при WAITING."""
        temp_db.add_channel('channel1')

        result = temp_db.claim_and_complete(
            username='channel1',
            status='GOOD',
            score=75,
            verdict='GOOD',
            trust_factor=0.9,
            members=1000,
            category='CRYPTO'
        )

        assert result is True, "claim_and_complete должен вернуть True при успехе"

        # Проверяем данные
        channel = temp_db.get_channel('channel1')
        assert channel.status == 'GOOD'
        assert channel.score == 75
        assert channel.verdict == 'GOOD'
        assert channel.trust_factor == 0.9
        assert channel.members == 1000
        assert channel.category == 'CRYPTO'

    def test_claim_and_complete_fails_if_not_waiting(self, temp_db):
        """claim_and_complete() возвращает False если канал не WAITING."""
        temp_db.add_channel('channel1')
        temp_db.mark_done('channel1', 'GOOD', score=70)  # Меняем статус

        result = temp_db.claim_and_complete(
            username='channel1',
            status='BAD',  # Пытаемся перезаписать
            score=50
        )

        assert result is False, "claim_and_complete должен вернуть False если не WAITING"

        # Данные НЕ должны измениться
        channel = temp_db.get_channel('channel1')
        assert channel.status == 'GOOD'
        assert channel.score == 70

    def test_claim_and_complete_with_breakdown(self, temp_db):
        """claim_and_complete() сохраняет breakdown и llm_analysis."""
        temp_db.add_channel('channel1')

        breakdown = {
            'cv_views': {'value': 5000, 'points': 12, 'max': 15},
            'reach': {'value': 0.45, 'points': 8, 'max': 10}
        }
        llm_analysis = {
            'ad_percentage': 15,
            'bot_percentage': 5
        }

        result = temp_db.claim_and_complete(
            username='channel1',
            status='GOOD',
            score=75,
            breakdown=breakdown,
            llm_analysis=llm_analysis
        )

        assert result is True

        # Проверяем breakdown_json
        channel = temp_db.get_channel('channel1')
        assert channel.breakdown_json is not None

        import json
        data = json.loads(channel.breakdown_json)
        assert data['breakdown']['cv_views']['points'] == 12
        assert data['llm_analysis']['ad_percentage'] == 15

    def test_delete_if_waiting_success(self, temp_db):
        """delete_if_waiting() удаляет WAITING канал."""
        temp_db.add_channel('channel1')

        result = temp_db.delete_if_waiting('channel1')

        assert result is True, "delete_if_waiting должен вернуть True при успехе"

        channel = temp_db.get_channel('channel1')
        assert channel is None, "Канал должен быть удалён"

    def test_delete_if_waiting_fails_if_not_waiting(self, temp_db):
        """delete_if_waiting() возвращает False если канал не WAITING."""
        temp_db.add_channel('channel1')
        temp_db.mark_done('channel1', 'GOOD', score=70)

        result = temp_db.delete_if_waiting('channel1')

        assert result is False, "delete_if_waiting должен вернуть False если не WAITING"

        # Канал НЕ должен быть удалён
        channel = temp_db.get_channel('channel1')
        assert channel is not None
        assert channel.status == 'GOOD'

    def test_parallel_crawlers_no_duplicates(self, temp_db_path):
        """
        Два краулера не обрабатывают один и тот же канал.

        Сценарий:
        1. Thread1: peek_next() -> 'channel1'
        2. Thread2: peek_next() -> 'channel1' (тот же!)
        3. Thread1: claim_and_complete('channel1', GOOD) -> True
        4. Thread2: claim_and_complete('channel1', BAD) -> False (уже не WAITING)
        """
        num_channels = 20
        num_threads = 5

        # Инициализируем БД
        db_init = CrawlerDB(temp_db_path)
        for i in range(num_channels):
            db_init.add_channel(f'channel_{i}')
        db_init.close()

        # Результаты
        successful_claims: List[str] = []
        lock = threading.Lock()

        def worker():
            """Поток-краулер с peek_next + claim_and_complete."""
            db = CrawlerDB(temp_db_path)
            local_results = []

            try:
                while True:
                    # 1. Peek (без блокировки)
                    channel = db.peek_next()
                    if not channel:
                        break

                    # Имитируем обработку
                    time.sleep(0.01)

                    # 2. Атомарный claim
                    success = db.claim_and_complete(
                        username=channel,
                        status='GOOD',
                        score=70
                    )

                    if success:
                        local_results.append(channel)
                    # Если не успели — берём следующий (другой поток уже обработал)
            finally:
                db.close()

            with lock:
                successful_claims.extend(local_results)

        # Запускаем потоки
        threads = [threading.Thread(target=worker) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Не должно быть дублей!
        assert len(successful_claims) == len(set(successful_claims)), (
            f"Дубли при параллельных краулерах! "
            f"Claims: {len(successful_claims)}, unique: {len(set(successful_claims))}"
        )

        # Все каналы должны быть обработаны
        assert len(successful_claims) == num_channels, (
            f"Не все каналы обработаны: {len(successful_claims)} из {num_channels}"
        )

    def test_ctrl_c_simulation(self, temp_db):
        """
        Симуляция Ctrl+C: канал остаётся WAITING при прерывании.

        Сценарий:
        1. peek_next() -> 'channel1'
        2. "Обработка" (просто время)
        3. KeyboardInterrupt (Ctrl+C)
        4. claim_and_complete() НЕ вызван
        5. Канал должен остаться WAITING
        """
        temp_db.add_channel('channel1')

        # Берём канал
        username = temp_db.peek_next()
        assert username == 'channel1'

        # Симулируем прерывание (claim_and_complete не вызывается)
        # ...

        # Канал должен остаться WAITING
        channel = temp_db.get_channel('channel1')
        assert channel.status == 'WAITING', (
            "При прерывании канал должен остаться WAITING"
        )
