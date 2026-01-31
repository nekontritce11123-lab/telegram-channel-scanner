"""
rescan_photos.py - Загрузка аватарок для существующих каналов

v68.1: Параллельная загрузка (5 одновременно).

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
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()


async def download_one(client, username: str, semaphore: asyncio.Semaphore) -> tuple:
    """Скачать фото одного канала. Возвращает (username, photo_blob, error)."""
    from pyrogram.errors import FloodWait

    async with semaphore:
        for attempt in range(3):  # 3 попытки
            try:
                chat = await client.get_chat(f"@{username}")

                if not chat.photo:
                    return (username, None, "no_photo")

                file_id = chat.photo.small_file_id or chat.photo.big_file_id
                if not file_id:
                    return (username, None, "no_file_id")

                photo = await client.download_media(file_id, in_memory=True)
                if not photo:
                    return (username, None, "download_failed")

                return (username, photo.getvalue(), None)

            except FloodWait as e:
                if attempt < 2:
                    await asyncio.sleep(e.value + 1)  # Ждём + 1 сек
                    continue
                return (username, None, f"FloodWait({e.value}s)")

            except Exception as e:
                return (username, None, f"{type(e).__name__}")


async def rescan_photos(db_path: str = "data/crawler.db", limit: int = None, check_only: bool = False):
    """Загружает аватарки для каналов без photo_blob."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Проверяем колонку
    cursor.execute("PRAGMA table_info(channels)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'photo_blob' not in columns:
        print("[ERROR] Колонка photo_blob не найдена!")
        conn.close()
        return

    # Каналы без фото
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
        SELECT COUNT(*), SUM(CASE WHEN photo_blob IS NOT NULL AND LENGTH(photo_blob) > 0 THEN 1 ELSE 0 END)
        FROM channels WHERE status IN ('GOOD', 'BAD')
    """)
    total, with_photo = cursor.fetchone()
    with_photo = with_photo or 0

    print(f"\n{'='*50}")
    print(f"Photo Migration v68.1 (parallel)")
    print(f"{'='*50}")
    print(f"Total (GOOD/BAD): {total}")
    print(f"With photo:       {with_photo}")
    print(f"Without photo:    {total - with_photo}")
    print(f"To process:       {len(channels)}")
    print(f"{'='*50}\n")

    if check_only or not channels:
        conn.close()
        return

    # Pyrogram
    try:
        from pyrogram import Client
    except ImportError:
        print("[ERROR] Pyrogram not installed!")
        conn.close()
        return

    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    if not api_id or not api_hash:
        print("[ERROR] API_ID/API_HASH not in .env!")
        conn.close()
        return

    print("Connecting...")

    session_path = str(Path(__file__).parent / "sessions" / "photo_session")
    async with Client(session_path, api_id=api_id, api_hash=api_hash) as client:
        print("Connected! Starting parallel download...\n")

        # Semaphore для 3 параллельных запросов (avoid FloodWait)
        semaphore = asyncio.Semaphore(3)

        # Запускаем все задачи параллельно
        tasks = [download_one(client, username, semaphore) for username in channels]
        results = await asyncio.gather(*tasks)

        # Обрабатываем результаты
        success = 0
        no_photo = 0
        failed = 0

        for i, (username, photo_blob, error) in enumerate(results, 1):
            if photo_blob:
                cursor.execute("UPDATE channels SET photo_blob = ? WHERE username = ?", (photo_blob, username))
                print(f"[{i}/{len(channels)}] @{username}: OK ({len(photo_blob):,} bytes)")
                success += 1
            elif error == "no_photo" or error == "no_file_id":
                print(f"[{i}/{len(channels)}] @{username}: no avatar")
                no_photo += 1
            else:
                print(f"[{i}/{len(channels)}] @{username}: ERROR - {error}")
                failed += 1

        conn.commit()

    conn.close()

    print(f"\n{'='*50}")
    print(f"RESULT")
    print(f"{'='*50}")
    print(f"Success:  {success}")
    print(f"No photo: {no_photo}")
    print(f"Errors:   {failed}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Download avatars for existing channels")
    parser.add_argument("--db", default="data/crawler.db", help="DB path")
    parser.add_argument("--limit", type=int, help="Max channels")
    parser.add_argument("--check", action="store_true", help="Only check stats")
    args = parser.parse_args()

    asyncio.run(rescan_photos(db_path=args.db, limit=args.limit, check_only=args.check))


if __name__ == "__main__":
    main()
