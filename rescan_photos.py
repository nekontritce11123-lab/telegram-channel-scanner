"""
rescan_photos.py - Загрузка аватарок для существующих каналов

v68.0: Миграция существующих каналов на новую систему хранения фото.
       Запускать ОДИН РАЗ после деплоя.

Использование:
    python rescan_photos.py              # Загрузить фото для всех без photo_blob
    python rescan_photos.py --limit 100  # Загрузить только 100 каналов
    python rescan_photos.py --check      # Только проверить статистику
"""

import os
import sys
import asyncio
import argparse
import sqlite3

from dotenv import load_dotenv

# Добавляем scanner в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()


async def rescan_photos(db_path: str = "crawler.db", limit: int = None, check_only: bool = False):
    """
    Загружает аватарки для каналов без photo_blob.

    Args:
        db_path: Путь к базе данных
        limit: Максимум каналов для обработки (None = все)
        check_only: Только показать статистику, не загружать
    """
    # Подключаемся к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Проверяем что колонка photo_blob существует
    cursor.execute("PRAGMA table_info(channels)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'photo_blob' not in columns:
        print("[ERROR] Колонка photo_blob не найдена!")
        print("Сначала запустите краулер или CLI для создания миграции.")
        conn.close()
        return

    # Получаем каналы без фото
    query = """
        SELECT username FROM channels
        WHERE status IN ('GOOD', 'BAD')
        AND (photo_blob IS NULL OR LENGTH(photo_blob) = 0)
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    channels = [row[0] for row in cursor.fetchall()]

    # Статистика
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN photo_blob IS NOT NULL AND LENGTH(photo_blob) > 0 THEN 1 ELSE 0 END) as with_photo
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
    """)
    stats = cursor.fetchone()
    total, with_photo = stats[0], stats[1] or 0

    print(f"\n{'='*50}")
    print(f"Photo Migration v68.0")
    print(f"{'='*50}")
    print(f"Всего каналов (GOOD/BAD): {total}")
    print(f"С фото:                   {with_photo}")
    print(f"Без фото:                 {total - with_photo}")
    print(f"Для обработки:            {len(channels)}")
    print(f"{'='*50}\n")

    if check_only:
        conn.close()
        return

    if not channels:
        print("Все каналы уже имеют фото!")
        conn.close()
        return

    # Импортируем Pyrogram
    try:
        from pyrogram import Client
    except ImportError:
        print("[ERROR] Pyrogram не установлен!")
        print("pip install pyrogram")
        conn.close()
        return

    # Создаём клиент
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")

    if not api_id or not api_hash:
        print("[ERROR] API_ID и API_HASH не настроены в .env!")
        conn.close()
        return

    print("Подключаюсь к Telegram...")

    async with Client("scanner_session", api_id=api_id, api_hash=api_hash) as client:
        print("Подключено!\n")

        success = 0
        failed = 0
        no_photo = 0

        for i, username in enumerate(channels, 1):
            try:
                # Получаем канал
                chat = await client.get_chat(f"@{username}")

                if not chat.photo:
                    print(f"[{i}/{len(channels)}] @{username}: нет аватарки")
                    no_photo += 1
                    continue

                # Скачиваем аватарку (small = 160x160, быстрее)
                file_id = chat.photo.small_file_id or chat.photo.big_file_id

                if not file_id:
                    print(f"[{i}/{len(channels)}] @{username}: нет file_id")
                    no_photo += 1
                    continue

                photo = await client.download_media(file_id, in_memory=True)

                if not photo:
                    print(f"[{i}/{len(channels)}] @{username}: не удалось скачать")
                    failed += 1
                    continue

                photo_blob = photo.getvalue()

                # Сохраняем в БД
                cursor.execute(
                    "UPDATE channels SET photo_blob = ? WHERE username = ?",
                    (photo_blob, username)
                )
                conn.commit()

                print(f"[{i}/{len(channels)}] @{username}: OK ({len(photo_blob):,} bytes)")
                success += 1

                # Rate limiting (0.5 сек между запросами)
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"[{i}/{len(channels)}] @{username}: ERROR - {type(e).__name__}: {e}")
                failed += 1
                # Больше ждём при ошибке
                await asyncio.sleep(2)

    conn.close()

    # Итоги
    print(f"\n{'='*50}")
    print(f"РЕЗУЛЬТАТ")
    print(f"{'='*50}")
    print(f"Успешно загружено: {success}")
    print(f"Без аватарки:      {no_photo}")
    print(f"Ошибки:            {failed}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Загрузка аватарок для существующих каналов")
    parser.add_argument("--db", default="crawler.db", help="Путь к БД")
    parser.add_argument("--limit", type=int, help="Максимум каналов")
    parser.add_argument("--check", action="store_true", help="Только проверить статистику")

    args = parser.parse_args()

    asyncio.run(rescan_photos(
        db_path=args.db,
        limit=args.limit,
        check_only=args.check
    ))


if __name__ == "__main__":
    main()
