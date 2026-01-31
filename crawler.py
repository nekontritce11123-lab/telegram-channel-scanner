#!/usr/bin/env python3
"""
Smart Crawler - автоматический сбор базы Telegram каналов.
v31.0: Локальный LLM (Ollama + Qwen3-8B), 17 категорий

Использование:
    # Первый запуск с seed каналами
    python crawler.py @channel1 @channel2 @channel3

    # Продолжить работу
    python crawler.py

    # Посмотреть статистику
    python crawler.py --stats

    # Статистика по категориям
    python crawler.py --category-stats

    # Экспортировать GOOD каналы
    python crawler.py --export good.csv

    # Экспортировать только CRYPTO каналы (ищет в основной И вторичной категории)
    python crawler.py --export crypto.csv --category CRYPTO

    # Экспортировать AI_ML каналы
    python crawler.py --export ai.csv --category AI_ML

    # Классифицировать существующие GOOD каналы (догоняние)
    python crawler.py --classify

    # Ограничить количество
    python crawler.py --max 100

Категории v18.0:
    Премиальные: CRYPTO, FINANCE, REAL_ESTATE, BUSINESS
    Технологии:  TECH, AI_ML
    Образование: EDUCATION, BEAUTY, HEALTH, TRAVEL
    Коммерция:   RETAIL
    Контент:     ENTERTAINMENT, NEWS, LIFESTYLE
    Риск:        GAMBLING, ADULT
    Fallback:    OTHER
"""

import sys
import asyncio
import argparse

from scanner.crawler import SmartCrawler
from scanner.database import CrawlerDB
from scanner.classifier import get_classifier
from scanner.cli import scan_channel, print_result, save_to_database


def print_banner():
    print("""
+-----------------------------------------------------------+
|                    CRAWLER v51.0                          |
|         Telegram channel scanner - 17 categories         |
+-----------------------------------------------------------+
    """)


def parse_category_result(result: str) -> tuple:
    """
    Парсит результат классификации в формате "CAT" или "CAT+CAT2".

    Returns:
        (category, category_secondary) - вторая может быть None
    """
    if "+" in result:
        parts = result.split("+")
        primary = parts[0].strip()
        secondary = parts[1].strip() if len(parts) > 1 else None
        return (primary, secondary)
    return (result.strip(), None)


async def classify_existing(db: CrawlerDB, limit: int = 100):
    """
    Классифицирует существующие GOOD каналы без категории.
    v28.0: ТОЛЬКО AI классификация - без fallback!
    Если AI не ответил после retry - канал остаётся без категории.
    """
    from scanner.client import get_client, smart_scan_safe

    classifier = get_classifier()

    # Получаем каналы без категории
    uncategorized = db.get_uncategorized(limit=limit)

    if not uncategorized:
        print("Все GOOD каналы уже классифицированы!")
        return

    print(f"\nНайдено {len(uncategorized)} каналов без категории")
    print("Сканирую и классифицирую (пауза 3 сек между каналами)...\n")

    # Подключаемся к Telegram
    client = get_client()
    await client.start()
    print("Подключено к Telegram\n")

    classified = 0
    multi_label = 0
    errors = 0

    try:
        for i, username in enumerate(uncategorized, 1):
            try:
                # Сканируем канал для получения реальных данных
                scan_result = await smart_scan_safe(client, username)

                if scan_result.chat is None:
                    print(f"[{i}/{len(uncategorized)}] @{username} → ERROR")
                    errors += 1
                    await asyncio.sleep(1)
                    continue

                # Получаем данные для классификации
                title = getattr(scan_result.chat, 'title', '') or ''
                description = getattr(scan_result.chat, 'description', '') or ''
                messages = scan_result.messages

                # v31.0: Ollama классификация (локально)
                channel_id = getattr(scan_result.chat, 'id', None)
                if not channel_id:
                    print(f"[{i}/{len(uncategorized)}] @{username} → SKIP (no channel_id)")
                    errors += 1
                    await asyncio.sleep(1)
                    continue

                result = await classifier.classify_sync(
                    channel_id, title, description, messages
                )

                # v28.0: Если AI не ответил после retry - пропускаем
                if result is None:
                    print(f"[{i}/{len(uncategorized)}] @{username} → SKIP (AI не ответил)")
                    errors += 1
                    await asyncio.sleep(1)
                    continue

                # Парсим multi-label формат
                category, category_secondary = parse_category_result(result)

                # Сохраняем обе категории
                db.set_category(username, category, category_secondary)
                classified += 1

                # Форматируем вывод
                if category_secondary:
                    multi_label += 1
                    display = f"{category}+{category_secondary}"
                else:
                    display = category

                print(f"[{i}/{len(uncategorized)}] @{username} → {display}")

                # Пауза между запросами (защита от FloodWait)
                await asyncio.sleep(3)

            except Exception as e:
                print(f"[{i}/{len(uncategorized)}] @{username} → ERROR: {e}")
                errors += 1
                await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\nПрервано по Ctrl+C")

    finally:
        await client.stop()
        print("Отключено от Telegram")

    print(f"\nКлассифицировано: {classified}")
    print(f"Multi-label: {multi_label}")
    print(f"Ошибок: {errors}")
    classifier.save_cache()
    classifier.unload()  # v33: Выгружаем модель из GPU


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
        '--category-stats',
        action='store_true',
        help='Показать статистику по категориям'
    )
    parser.add_argument(
        '--classify',
        action='store_true',
        help='Классифицировать существующие GOOD каналы (догоняние)'
    )
    parser.add_argument(
        '--export',
        type=str,
        metavar='FILE',
        help='Экспортировать GOOD каналы в CSV файл'
    )
    parser.add_argument(
        '--category',
        type=str,
        metavar='CAT',
        help='Фильтр по категории для экспорта (CRYPTO, NEWS, TECH и т.д.)'
    )
    parser.add_argument(
        '--db',
        type=str,
        default='data/crawler.db',
        help='Путь к базе данных (по умолчанию: data/crawler.db)'
    )
    # v52.0: Флаги пересчёта метрик
    parser.add_argument(
        '--recalculate-local',
        action='store_true',
        help='Пересчитать scores из сохранённых breakdown (без Telegram/Ollama)'
    )
    parser.add_argument(
        '--recalculate-llm',
        action='store_true',
        help='Пересчитать LLM анализ из сохранённых текстов (требует Ollama)'
    )
    parser.add_argument(
        '--sync',
        action='store_true',
        help='Синхронизировать результаты на сервер после пересчёта'
    )

    args = parser.parse_args()

    print_banner()

    # Handle 'scan' subcommand: python crawler.py scan @channel
    if args.channels and args.channels[0] == 'scan':
        if len(args.channels) < 2:
            print("Usage: python crawler.py scan @channel")
            return
        channel = args.channels[1].lstrip('@')
        result = asyncio.run(scan_channel(channel))
        if result:
            print_result(result)
            save_to_database(result)
        return

    # v52.0: Пересчёт метрик
    if args.recalculate_local or args.recalculate_llm:
        from scanner.recalculator import recalculate_local, recalculate_llm, get_channels_without_texts

        db = CrawlerDB(db_path=args.db)

        if args.recalculate_local:
            print("\n=== ПЕРЕСЧЁТ SCORES (--recalculate-local) ===")
            print("Применяем НОВЫЕ формулы к сохранённым метрикам...\n")
            result = recalculate_local(db, verbose=True)

        if args.recalculate_llm:
            print("\n=== ПЕРЕСЧЁТ LLM (--recalculate-llm) ===")

            # Проверяем есть ли каналы без текстов
            missing = get_channels_without_texts(db)
            if missing:
                print(f"⚠️  {len(missing)} каналов без текстов (нужен ресканс):")
                for u in missing[:5]:
                    print(f"    @{u}")
                if len(missing) > 5:
                    print(f"    ... и ещё {len(missing) - 5}")
                print()

            print("Запускаем LLM анализ с новым промптом/моделью...\n")
            result = recalculate_llm(db, verbose=True)

        # v52.0: Синхронизация на сервер
        if args.sync:
            print("\n=== СИНХРОНИЗАЦИЯ НА СЕРВЕР ===")
            # TODO: Реализовать синхронизацию через API
            print("⚠️  --sync пока не реализован")
            print("Используй: cd mini-app/deploy && python sync_channels.py")

        db.close()
        return

    # Для некоторых команд нужна только БД
    if args.stats or args.category_stats or args.export or args.classify:
        db = CrawlerDB(db_path=args.db)

        # Показать статистику
        if args.stats:
            stats = db.get_stats()
            print("Статистика базы данных:")
            print(f"  Всего каналов:  {stats['total']}")
            print(f"  В очереди:      {stats['waiting']}")
            print(f"  Обрабатывается: {stats['processing']}")
            print(f"  GOOD (>=60):    {stats['good']}")
            print(f"  BAD (<60):      {stats['bad']}")
            print(f"  PRIVATE:        {stats['private']}")
            print(f"  ERROR:          {stats['error']}")
            db.close()
            return

        # Статистика по категориям
        if args.category_stats:
            cat_stats = db.get_category_stats()
            print("Статистика по категориям (GOOD каналы):")
            total = sum(cat_stats.values())
            for cat, count in cat_stats.items():
                pct = (count / total * 100) if total > 0 else 0
                print(f"  {cat:<15} {count:>5} ({pct:.1f}%)")
            print(f"\n  Всего: {total}")
            db.close()
            return

        # Классифицировать существующие
        if args.classify:
            try:
                asyncio.run(classify_existing(db, limit=args.max or 100))
            except KeyboardInterrupt:
                print("\nПрервано")
            db.close()
            return

        # Экспортировать
        if args.export:
            count = db.export_csv(args.export, status='GOOD', category=args.category)
            if args.category:
                print(f"Экспортировано {count} {args.category} каналов в {args.export}")
            else:
                print(f"Экспортировано {count} GOOD каналов в {args.export}")
            db.close()
            return

        db.close()

    # Запустить краулер
    crawler = SmartCrawler(db_path=args.db)
    seeds = args.channels if args.channels else None

    try:
        asyncio.run(crawler.run(seeds=seeds, max_channels=args.max))
    except KeyboardInterrupt:
        print("\nПрервано пользователем")


if __name__ == "__main__":
    main()
