"""
v58.0: Worker для обработки очереди сканирования.

Запуск:
  python -m scanner.worker         # Один проход
  python -m scanner.worker --loop  # Бесконечный цикл

Worker читает pending запросы из scan_requests,
сканирует каналы и сохраняет результаты.
"""

import asyncio
import sys
import time
from pathlib import Path
from datetime import datetime

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scanner.database import Database
from scanner.client import smart_scan
from scanner.scorer import calculate_final_score
from scanner.classifier import get_classifier

# Configuration
BATCH_SIZE = 5  # Сколько запросов обрабатывать за раз
SLEEP_BETWEEN = 3  # Секунд между каналами (rate limit)
LOOP_INTERVAL = 30  # Секунд между проверками очереди


async def process_request(db: Database, request: dict) -> bool:
    """
    Обрабатывает один запрос на сканирование.

    Returns:
        True если успешно, False если ошибка
    """
    request_id = request['id']
    username = request['username']

    print(f"\n[{request_id}] Сканирую @{username}...")

    # Обновляем статус на processing
    db.update_scan_request(request_id, 'processing')

    try:
        # Сканируем канал
        scan_result = await smart_scan(username)

        if not scan_result or not scan_result.chat:
            print(f"  ❌ Канал не найден")
            db.update_scan_request(request_id, 'error', 'Channel not found')
            return False

        # Считаем скор
        score_result = calculate_final_score(
            chat=scan_result.chat,
            messages=scan_result.messages,
            comments_data=scan_result.comments,
            users=scan_result.users,
            channel_health=scan_result.channel_health
        )

        # Классифицируем
        classifier = get_classifier()
        category = await classifier.classify_sync(
            channel_id=getattr(scan_result.chat, 'id', 0),
            title=getattr(scan_result.chat, 'title', username),
            description=scan_result.full_chat.about if scan_result.full_chat else '',
            messages=scan_result.messages
        )
        if not category:
            category = "OTHER"

        # Сохраняем в БД каналов
        channel_id = getattr(scan_result.chat, 'id', None)
        title = getattr(scan_result.chat, 'title', username)
        members = getattr(scan_result.full_chat, 'participants_count', 0) if scan_result.full_chat else 0

        # Подготавливаем данные для сохранения
        score = score_result.get('final_score', 0)
        trust = score_result.get('trust_factor', 1.0)
        verdict = score_result.get('verdict', 'UNKNOWN')
        breakdown = score_result.get('breakdown', {})
        categories = score_result.get('categories', {})

        # Добавляем flags в breakdown
        flags = score_result.get('flags', {})
        if breakdown and flags:
            breakdown['reactions_enabled'] = flags.get('reactions_enabled', True)
            breakdown['comments_enabled'] = flags.get('comments_enabled', True)
            breakdown['floating_weights'] = flags.get('floating_weights', False)

        # Определяем статус
        status = 'GOOD' if score >= 55 else 'BAD'

        # Сохраняем результат через mark_done
        db.mark_done(
            username=username,
            status=status,
            score=int(score),
            verdict=verdict,
            trust_factor=trust,
            members=members,
            category=category,
            title=title,
            breakdown=breakdown,
            categories=categories,
            reactions_enabled=flags.get('reactions_enabled', True),
            comments_enabled=flags.get('comments_enabled', True)
        )

        print(f"  ✅ Score: {score:.1f}, Trust: {trust:.2f}, Verdict: {verdict}")
        print(f"     Category: {category}, Members: {members:,}")

        # Обновляем статус запроса
        db.update_scan_request(request_id, 'done')
        return True

    except Exception as e:
        error_msg = str(e)[:200]
        print(f"  ❌ Ошибка: {error_msg}")
        db.update_scan_request(request_id, 'error', error_msg)
        return False


async def process_queue(db: Database, batch_size: int = BATCH_SIZE) -> int:
    """
    Обрабатывает очередь запросов.

    Returns:
        Количество успешно обработанных
    """
    # Получаем pending запросы
    pending = db.get_pending_scan_requests(limit=batch_size)

    if not pending:
        return 0

    print(f"\n{'='*50}")
    print(f"Найдено {len(pending)} запросов в очереди")
    print(f"{'='*50}")

    success_count = 0

    for i, request in enumerate(pending):
        if i > 0:
            print(f"\n⏳ Пауза {SLEEP_BETWEEN} сек (rate limit)...")
            await asyncio.sleep(SLEEP_BETWEEN)

        try:
            if await process_request(db, request):
                success_count += 1
        except Exception as e:
            print(f"  ❌ Необработанная ошибка: {e}")

    return success_count


async def main():
    """Основная функция worker."""
    loop_mode = '--loop' in sys.argv

    print("="*50)
    print("v58.0: Scan Queue Worker")
    print(f"Mode: {'Loop' if loop_mode else 'Single pass'}")
    print("="*50)

    # Инициализируем БД
    db = Database()

    if loop_mode:
        # Бесконечный цикл
        print(f"\nWorker запущен. Проверка каждые {LOOP_INTERVAL} сек...")
        print("Нажмите Ctrl+C для остановки\n")

        while True:
            try:
                processed = await process_queue(db)

                if processed > 0:
                    print(f"\n✅ Обработано: {processed} каналов")
                else:
                    print(".", end="", flush=True)

                await asyncio.sleep(LOOP_INTERVAL)

            except KeyboardInterrupt:
                print("\n\n👋 Worker остановлен")
                break
    else:
        # Один проход
        processed = await process_queue(db)
        print(f"\n{'='*50}")
        print(f"Обработано: {processed} каналов")
        print("="*50)


if __name__ == "__main__":
    asyncio.run(main())
