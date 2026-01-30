"""
Photo Filler v80.0
Fill missing channel photos (avatars).
"""
import sqlite3
import asyncio
from typing import Optional

def get_channels_missing_photo(db_path: str, limit: int = None) -> list[str]:
    """Get channels missing photo_blob."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
        SELECT username
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
          AND (photo_blob IS NULL OR photo_blob = '')
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    channels = [row[0] for row in cursor.fetchall()]
    conn.close()
    return channels

def update_photo(db_path: str, username: str, photo_blob: bytes):
    """Update photo_blob in database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE channels
        SET photo_blob = ?
        WHERE username = ?
    """, (photo_blob, username))
    conn.commit()
    conn.close()

async def download_photo(client, username: str, semaphore) -> tuple:
    """Download photo for one channel. Returns (username, photo_bytes, error)."""
    from pyrogram.errors import FloodWait

    async with semaphore:
        for attempt in range(3):
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
                    await asyncio.sleep(e.value + 1)
                    continue
                return (username, None, f"FloodWait({e.value}s)")

            except Exception as e:
                return (username, None, f"{type(e).__name__}")

def fill_photo_metrics(db_path: str, dry_run: bool = False, limit: int = None) -> dict:
    """Fill missing photo_blob."""
    channels = get_channels_missing_photo(db_path, limit)
    print(f"Found {len(channels)} channels missing photos")

    if dry_run:
        print("\n[DRY RUN] Would download photos for:")
        for ch in channels[:10]:
            print(f"  @{ch}")
        if len(channels) > 10:
            print(f"  ... and {len(channels) - 10} more")
        return {'would_process': len(channels)}

    print("\n[!] Photo download requires Pyrogram client")
    print("    Run: python rescan_photos.py")
    print("    (Uses existing implementation with proper rate limiting)")

    return {'channels': len(channels), 'note': 'Use rescan_photos.py'}
