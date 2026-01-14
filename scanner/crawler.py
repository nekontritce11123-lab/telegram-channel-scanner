"""
Smart Crawler - автоматический сбор базы каналов.
v16.0: Алгоритм "Чистого Дерева"

Логика:
  1. Берём канал из очереди
  2. Проверяем через scanner
  3. Если score >= 60 (GOOD) → собираем рекламные ссылки
  4. Добавляем новые каналы в очередь
  5. Пауза → повторяем

Защита аккаунта:
  - Пауза 5 сек между каналами
  - Большая пауза каждые 100 каналов
  - Автоматическая обработка FloodWait
"""

import asyncio
import re
import random
from datetime import datetime
from typing import Optional

from pyrogram import Client

from .database import CrawlerDB
from .client import get_client, smart_scan_safe, resolve_invite_link
from .scorer import calculate_final_score


# Настройки rate limiting
RATE_LIMIT = {
    'between_channels': 5,      # Секунд между каналами
    'batch_size': 100,          # Каналов до большой паузы
    'batch_pause': 300,         # 5 минут отдыха
}

# Порог для GOOD каналов
GOOD_THRESHOLD = 60


class SmartCrawler:
    """
    Краулер для автоматического сбора базы каналов.

    Использование:
        crawler = SmartCrawler()
        await crawler.run(["@channel1", "@channel2"])
    """

    def __init__(self, db_path: str = "crawler.db"):
        self.db = CrawlerDB(db_path)
        self.client: Optional[Client] = None
        self.processed_count = 0
        self.running = True

    async def start(self):
        """Запускает Pyrogram клиент."""
        self.client = get_client()
        await self.client.start()
        print("Подключено к Telegram")

    async def stop(self):
        """Останавливает клиент."""
        if self.client:
            await self.client.stop()
            print("Отключено от Telegram")

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
            # Получаем текст
            text = ""
            if hasattr(msg, 'text') and msg.text:
                text = msg.text.lower()
            elif hasattr(msg, 'caption') and msg.caption:
                text = msg.caption.lower()

            if not text:
                continue

            # Приватные инвайты (t.me/+XXX) — пропускаем, резолвим отдельно
            # Их обработаем через resolve_invite_link

            # Публичные каналы: t.me/username
            for match in re.findall(r't\.me/([a-zA-Z0-9_]+)', text):
                match = match.lower()
                if match != channel_username:
                    if match not in ['addstickers', 'share', 'proxy', 's', 'iv', 'joinchat']:
                        links.add(match)

            # telegram.me/username
            for match in re.findall(r'telegram\.me/([a-zA-Z0-9_]+)', text):
                match = match.lower()
                if match != channel_username:
                    links.add(match)

            # @упоминания
            for match in re.findall(r'@([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username:
                    if not match.endswith('bot'):
                        links.add(match)

            # Репосты (v16.0: используем username из chats_map)
            if hasattr(msg, 'forward_from_chat') and msg.forward_from_chat:
                fwd = msg.forward_from_chat
                fwd_username = getattr(fwd, 'username', None)
                if fwd_username and fwd_username != channel_username:
                    links.add(fwd_username)

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

            result['score'] = score
            result['verdict'] = verdict

        except Exception as e:
            self.db.mark_done(username, 'ERROR', verdict=str(e))
            result['verdict'] = str(e)
            return result

        # Определяем статус
        if score >= GOOD_THRESHOLD:
            status = 'GOOD'

            # Собираем ссылки только с хороших каналов
            links = self.extract_links(scan_result.messages, username)

            # Добавляем новые каналы в очередь
            new_count = 0
            for link in links:
                if self.db.add_channel(link, parent=username):
                    new_count += 1

            result['new_channels'] = new_count

            self.db.mark_done(
                username, status, score, verdict, trust_factor, members,
                ad_links=list(links)
            )

        else:
            status = 'BAD'
            # Ссылки НЕ собираем с плохих каналов
            self.db.mark_done(username, status, score, verdict, trust_factor, members)

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
            print(f"  Всего в базе: {stats['total']}")
            print(f"  GOOD: {stats['good']}")
            print(f"  BAD: {stats['bad']}")
            print(f"  В очереди: {stats['waiting']}")

            # Закрываем базу
            self.db.close()

    def get_stats(self) -> dict:
        """Возвращает статистику базы."""
        return self.db.get_stats()

    def export_good(self, filepath: str) -> int:
        """Экспортирует GOOD каналы в CSV."""
        return self.db.export_csv(filepath, 'GOOD')
