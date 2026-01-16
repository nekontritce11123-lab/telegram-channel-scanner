"""
Smart Crawler - автоматический сбор базы каналов.
v18.0: Алгоритм "Чистого Дерева" + 17 категорий + multi-label

Логика:
  1. Берём канал из очереди
  2. Проверяем через scanner
  3. Если score >= 60 (GOOD) → собираем рекламные ссылки
  4. Добавляем новые каналы в очередь
  5. AI классификатор работает ПАРАЛЛЕЛЬНО (не блокирует)
  6. Пауза → повторяем

Защита аккаунта:
  - Пауза 5 сек между каналами
  - Большая пауза каждые 100 каналов
  - Автоматическая обработка FloodWait

AI классификация v18.0:
  - Groq API + Llama 3.3 70B (бесплатно)
  - 17 категорий + multi-label (CAT+CAT2)
  - Фоновый worker (не тормозит краулер)
  - Fallback на ключевые слова
"""

import asyncio
import re
import random
import base64
from datetime import datetime
from typing import Optional

from pyrogram import Client

from .database import CrawlerDB
from .client import get_client, smart_scan_safe
from .scorer import calculate_final_score
from .classifier import get_classifier, ChannelClassifier


# Настройки rate limiting
RATE_LIMIT = {
    'between_channels': 5,      # Секунд между каналами
    'batch_size': 100,          # Каналов до большой паузы
    'batch_pause': 300,         # 5 минут отдыха
}

# Пороги качества
GOOD_THRESHOLD = 60      # Минимум для статуса GOOD в базе
COLLECT_THRESHOLD = 66   # Минимум для сбора ссылок (размножения)


async def get_avatar_base64(client: Client, chat) -> str | None:
    """
    Скачивает аватарку канала и конвертирует в base64 data URL.

    v22.0: Аватарки хранятся в БД как data:image/jpeg;base64,...
    Размер ~10KB на канал, работает офлайн без proxy.

    Args:
        client: Pyrogram клиент
        chat: Объект канала из scan_result.chat

    Returns:
        str: data:image/jpeg;base64,... или None если нет аватарки
    """
    if not chat:
        return None

    # Проверяем наличие фото
    photo = getattr(chat, 'photo', None)
    if not photo:
        return None

    # Получаем file_id большой версии фото
    big_file_id = getattr(photo, 'big_file_id', None)
    if not big_file_id:
        return None

    try:
        # Скачиваем в память (BytesIO)
        photo_bytes = await client.download_media(
            big_file_id,
            in_memory=True
        )

        if photo_bytes:
            # Конвертируем BytesIO в base64
            b64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')
            return f"data:image/jpeg;base64,{b64}"

    except Exception as e:
        # Тихо игнорируем ошибки скачивания (канал может запретить)
        pass

    return None


class SmartCrawler:
    """
    Краулер для автоматического сбора базы каналов.

    Использование:
        crawler = SmartCrawler()
        await crawler.run(["@channel1", "@channel2"])

    v18.0: AI классификация с 17 категориями и multi-label поддержкой.
    """

    def __init__(self, db_path: str = "crawler.db"):
        self.db = CrawlerDB(db_path)
        self.client: Optional[Client] = None
        self.processed_count = 0
        self.running = True
        self.classifier: Optional[ChannelClassifier] = None
        self.classified_count = 0  # Счётчик классифицированных
        self._channel_id_to_username = {}  # Маппинг для callback

    async def start(self):
        """Запускает Pyrogram клиент и AI классификатор."""
        self.client = get_client()
        await self.client.start()
        print("Подключено к Telegram")

        # Запускаем AI классификатор в фоне
        self.classifier = get_classifier()
        await self.classifier.start_worker()
        print("AI классификатор запущен в фоне")

    async def stop(self):
        """Останавливает клиент и классификатор."""
        if self.classifier:
            await self.classifier.stop_worker()
            print(f"AI классификатор остановлен (классифицировано: {self.classified_count})")

        if self.client:
            await self.client.stop()
            print("Отключено от Telegram")

    def _on_category_ready(self, channel_id: int, category: str):
        """
        Callback когда категория готова - сохраняем в БД.
        v15.0: category - уже готовая строка (CRYPTO, TECH, и т.д.)
        """
        # Находим username по channel_id (храним маппинг)
        username = self._channel_id_to_username.get(channel_id)
        if username:
            # v15.0: category это строка, не нужно парсить
            self.db.set_category(username, category, None, 100)
            self.classified_count += 1

    def add_seeds(self, channels: list):
        """Добавляет начальные каналы в очередь."""
        added = 0
        for channel in channels:
            channel = channel.lower().lstrip('@')
            if self.db.add_channel(channel, parent="[seed]"):
                added += 1
                print(f"  + @{channel} добавлен в очередь")
            else:
                print(f"  - @{channel} уже в базе")
        return added

    def extract_links(self, messages: list, channel_username: str) -> set:
        """
        Извлекает все внешние Telegram ссылки из постов.

        Returns:
            set[str] — множество username'ов
        """
        links = set()
        channel_username = channel_username.lower()

        for msg in messages:
            # Получаем текст (RawMessageWrapper использует 'message', не 'text')
            text = ""
            if hasattr(msg, 'message') and msg.message:
                text = msg.message.lower()
            elif hasattr(msg, 'text') and msg.text:
                text = msg.text.lower()
            elif hasattr(msg, 'caption') and msg.caption:
                text = msg.caption.lower()

            # Репосты проверяем даже без текста
            if msg.forward_from_chat:
                fwd = msg.forward_from_chat
                fwd_username = getattr(fwd, 'username', None)
                if fwd_username and fwd_username != channel_username:
                    links.add(fwd_username)

            if not text:
                continue

            # Приватные инвайты (t.me/+XXX) — пропускаем, резолвим отдельно
            # Их обработаем через resolve_invite_link

            # Публичные каналы: t.me/username (минимум 5 символов как в Telegram)
            # Исключаем служебные и популярные слова которые ложно срабатывают
            skip_words = {
                # Telegram служебные
                'addstickers', 'share', 'proxy', 'joinchat', 'stickerpack',
                # Короткие/зарезервированные
                's', 'c', 'iv', 'msg', 'vote', 'boost', 'premium', 'emoji',
                # Python методы/библиотеки
                'fetchall', 'fetchone', 'fetchmany', 'execute', 'commit', 'cursor',
                'pytest', 'unittest', 'numpy', 'pandas', 'scipy', 'matplotlib',
                'torch', 'keras', 'flask', 'django', 'fastapi', 'requests',
                'asyncio', 'aiohttp', 'httpx', 'redis', 'celery', 'sqlalchemy',
                # JavaScript/фреймворки
                'react', 'redux', 'vuejs', 'angular', 'nextjs', 'nodejs',
                'webpack', 'eslint', 'prettier', 'typescript', 'javascript',
                # Служебные слова программирования
                'async', 'await', 'import', 'export', 'const', 'class', 'state',
                'return', 'function', 'lambda', 'yield', 'static', 'public',
                'private', 'protected', 'interface', 'abstract', 'override',
                'binding', 'observable', 'subscribe', 'dispatch', 'middleware',
                # Переменные окружения
                'environment', 'production', 'development', 'staging', 'testing',
                'config', 'settings', 'options', 'params', 'arguments',
                # Платформы (не Telegram)
                'google', 'github', 'gitlab', 'bitbucket', 'stackoverflow',
                'youtube', 'twitter', 'instagram', 'facebook', 'linkedin',
                'discord', 'slack', 'medium', 'notion', 'figma', 'linux',
                # Языки программирования
                'python', 'kotlin', 'swift', 'rustlang', 'golang', 'clojure',
                'haskell', 'elixir', 'erlang', 'scala', 'groovy',
                # Прочие технические
                'admin', 'support', 'helper', 'utils', 'tools', 'service',
                'handler', 'controller', 'model', 'schema', 'migration',
                'dockerfile', 'makefile', 'readme', 'changelog', 'license',
                'tetrad', 'string', 'array', 'object', 'integer', 'boolean',
            }
            for match in re.findall(r't\.me/([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in skip_words:
                    links.add(match)

            # telegram.me/username
            for match in re.findall(r'telegram\.me/([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in skip_words:
                    links.add(match)

            # @упоминания
            for match in re.findall(r'@([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in skip_words:
                    if not match.endswith('bot'):
                        links.add(match)

        return links

    async def process_channel(self, username: str) -> dict:
        """
        Обрабатывает один канал.

        Returns:
            dict с результатами: status, score, new_channels
        """
        result = {
            'username': username,
            'status': 'ERROR',
            'score': 0,
            'verdict': '',
            'new_channels': 0
        }

        # Помечаем как обрабатываемый
        self.db.mark_processing(username)

        # Сканируем
        scan_result = await smart_scan_safe(self.client, username)

        # Проверяем на ошибку
        if scan_result.chat is None:
            error_reason = scan_result.channel_health.get('reason', 'Unknown error')
            self.db.mark_done(username, 'ERROR', verdict=error_reason)
            result['verdict'] = error_reason
            return result

        # Считаем score
        try:
            score_result = calculate_final_score(
                scan_result.chat,
                scan_result.messages,
                scan_result.comments_data,
                scan_result.users,
                scan_result.channel_health
            )

            score = score_result.get('score', 0)
            verdict = score_result.get('verdict', '')
            trust_factor = score_result.get('trust_factor', 1.0)
            members = score_result.get('members', 0)

            # v22.5: Добавляем flags в breakdown для корректного отображения в UI
            # (reactions_enabled, comments_enabled, floating_weights)
            breakdown = score_result.get('breakdown', {})
            flags = score_result.get('flags', {})
            if breakdown and flags:
                breakdown['reactions_enabled'] = flags.get('reactions_enabled', True)
                breakdown['comments_enabled'] = flags.get('comments_enabled', True)
                breakdown['floating_weights'] = flags.get('floating_weights', False)
                score_result['breakdown'] = breakdown

            result['score'] = score
            result['verdict'] = verdict

        except Exception as e:
            self.db.mark_done(username, 'ERROR', verdict=str(e))
            result['verdict'] = str(e)
            return result

        # v22.0: Извлекаем аватарку для сохранения в БД
        photo_url = await get_avatar_base64(self.client, scan_result.chat)

        # Определяем статус (GOOD если score >= 60)
        if score >= GOOD_THRESHOLD:
            status = 'GOOD'

            # Добавляем в очередь AI классификации (асинхронно, не блокирует)
            if self.classifier:
                channel_id = getattr(scan_result.chat, 'id', None)
                if channel_id:
                    self._channel_id_to_username[channel_id] = username
                    self.classifier.add_to_queue(
                        channel_id=channel_id,
                        title=getattr(scan_result.chat, 'title', ''),
                        description=getattr(scan_result.chat, 'description', ''),
                        messages=scan_result.messages,
                        callback=self._on_category_ready
                    )

            # Собираем ссылки только с ОЧЕНЬ хороших каналов (score >= 66)
            if score >= COLLECT_THRESHOLD:
                links = self.extract_links(scan_result.messages, username)

                # Добавляем новые каналы в очередь
                new_count = 0
                for link in links:
                    if self.db.add_channel(link, parent=username):
                        new_count += 1

                result['new_channels'] = new_count

                # v21.0: Передаём реальный breakdown для сохранения в БД
                # v22.0: Добавляем photo_url (base64)
                self.db.mark_done(
                    username, status, score, verdict, trust_factor, members,
                    ad_links=list(links),
                    photo_url=photo_url,
                    breakdown=score_result.get('breakdown'),
                    categories=score_result.get('categories')
                )
            else:
                # 60-65: GOOD но ссылки не собираем (тупиковая ветка)
                # v21.0: Передаём реальный breakdown
                # v22.0: Добавляем photo_url (base64)
                self.db.mark_done(
                    username, status, score, verdict, trust_factor, members,
                    photo_url=photo_url,
                    breakdown=score_result.get('breakdown'),
                    categories=score_result.get('categories')
                )

        else:
            status = 'BAD'
            # Ссылки НЕ собираем с плохих каналов
            # v21.0: Передаём реальный breakdown
            # v22.0: Добавляем photo_url (base64)
            self.db.mark_done(
                username, status, score, verdict, trust_factor, members,
                photo_url=photo_url,
                breakdown=score_result.get('breakdown'),
                categories=score_result.get('categories')
            )

        result['status'] = status
        return result

    async def run(
        self,
        seeds: list = None,
        max_channels: int = None,
        verbose: bool = True
    ):
        """
        Основной цикл краулера.

        Args:
            seeds: начальные каналы (опционально)
            max_channels: максимум каналов для обработки (None = бесконечно)
            verbose: выводить ли подробный лог
        """
        # Сбрасываем зависшие PROCESSING
        reset = self.db.reset_processing()
        if reset > 0:
            print(f"Сброшено {reset} зависших каналов")

        # Добавляем seed каналы
        if seeds:
            print("\nДобавляю seed каналы:")
            self.add_seeds(seeds)

        # Статистика
        stats = self.db.get_stats()
        print(f"\nБаза данных:")
        print(f"  Всего: {stats['total']}")
        print(f"  В очереди: {stats['waiting']}")
        print(f"  GOOD: {stats['good']}")
        print(f"  BAD: {stats['bad']}")

        if stats['waiting'] == 0:
            print("\nОчередь пуста! Добавьте seed каналы.")
            return

        print(f"\nЗапускаю краулер...")
        print("Нажми Ctrl+C для остановки\n")

        try:
            await self.start()

            while self.running:
                # Берём следующий канал
                username = self.db.get_next()

                if not username:
                    print("\nОчередь пуста! Краулер завершён.")
                    break

                # Проверяем лимит
                if max_channels and self.processed_count >= max_channels:
                    print(f"\nДостигнут лимит {max_channels} каналов.")
                    break

                # Обрабатываем
                print(f"[{self.processed_count + 1}] @{username}...", end=" ", flush=True)

                result = await self.process_channel(username)

                # Выводим результат
                if result['status'] == 'GOOD':
                    print(f"GOOD {result['score']} (+{result['new_channels']} новых)")
                elif result['status'] == 'BAD':
                    print(f"BAD {result['score']}")
                else:
                    print(f"ERROR: {result['verdict']}")

                self.processed_count += 1

                # Пауза между каналами
                pause = RATE_LIMIT['between_channels'] + random.uniform(-1, 2)
                await asyncio.sleep(pause)

                # Большая пауза каждые N каналов
                if self.processed_count % RATE_LIMIT['batch_size'] == 0:
                    print(f"\nПауза {RATE_LIMIT['batch_pause'] // 60} минут (обработано {self.processed_count})...")
                    await asyncio.sleep(RATE_LIMIT['batch_pause'])
                    print("Продолжаю...\n")

        except KeyboardInterrupt:
            print("\n\nОстановка по Ctrl+C...")

        finally:
            await self.stop()

            # Финальная статистика
            stats = self.db.get_stats()
            print(f"\nИтого:")
            print(f"  Обработано за сессию: {self.processed_count}")
            print(f"  Классифицировано AI: {self.classified_count}")
            print(f"  Всего в базе: {stats['total']}")
            print(f"  GOOD: {stats['good']}")
            print(f"  BAD: {stats['bad']}")
            print(f"  В очереди: {stats['waiting']}")

            # Статистика по категориям
            cat_stats = self.db.get_category_stats()
            if cat_stats:
                print(f"\nПо категориям:")
                for cat, count in list(cat_stats.items())[:10]:
                    print(f"  {cat}: {count}")

            # Закрываем базу
            self.db.close()
