#!/usr/bin/env python3
"""
Smart Crawler - автоматический сбор базы Telegram каналов.
v16.0: Алгоритм "Чистого Дерева"

Использование:
    # Первый запуск с seed каналами
    python crawler.py @channel1 @channel2 @channel3

    # Продолжить работу
    python crawler.py

    # Посмотреть статистику
    python crawler.py --stats

    # Экспортировать GOOD каналы
    python crawler.py --export good.csv

    # Ограничить количество
    python crawler.py --max 100
"""

import sys
import asyncio
import argparse

from scanner.crawler import SmartCrawler


def print_banner():
    print("""
╔═══════════════════════════════════════════════════════════╗
║            SMART CRAWLER v16.0                            ║
║         Автоматический сбор базы каналов                  ║
╚═══════════════════════════════════════════════════════════╝
    """)


def main():
    parser = argparse.ArgumentParser(
        description="Smart Crawler - автоматический сбор базы Telegram каналов"
    )
    parser.add_argument(
        'channels',
        nargs='*',
        help='Seed каналы для начала (@channel1 @channel2)'
    )
    parser.add_argument(
        '--max',
        type=int,
        default=None,
        help='Максимум каналов для обработки'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Показать статистику базы'
    )
    parser.add_argument(
        '--export',
        type=str,
        metavar='FILE',
        help='Экспортировать GOOD каналы в CSV файл'
    )
    parser.add_argument(
        '--db',
        type=str,
        default='crawler.db',
        help='Путь к базе данных (по умолчанию: crawler.db)'
    )

    args = parser.parse_args()

    print_banner()

    crawler = SmartCrawler(db_path=args.db)

    # Показать статистику
    if args.stats:
        stats = crawler.get_stats()
        print("Статистика базы данных:")
        print(f"  Всего каналов:  {stats['total']}")
        print(f"  В очереди:      {stats['waiting']}")
        print(f"  Обрабатывается: {stats['processing']}")
        print(f"  GOOD (>=60):    {stats['good']}")
        print(f"  BAD (<60):      {stats['bad']}")
        print(f"  PRIVATE:        {stats['private']}")
        print(f"  ERROR:          {stats['error']}")
        return

    # Экспортировать
    if args.export:
        count = crawler.export_good(args.export)
        print(f"Экспортировано {count} GOOD каналов в {args.export}")
        return

    # Запустить краулер
    seeds = args.channels if args.channels else None

    try:
        asyncio.run(crawler.run(seeds=seeds, max_channels=args.max))
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(0)


if __name__ == "__main__":
    main()
