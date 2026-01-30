"""
Forensics Filler v80.0
Fill missing forensics metrics from user_ids_json.
"""
import sqlite3
import json
from typing import Optional

def get_channels_missing_forensics(db_path: str, limit: int = None) -> list[dict]:
    """Get channels missing forensics but have user_ids."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT username, user_ids_json
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
          AND user_ids_json IS NOT NULL
          AND user_ids_json != '[]'
          AND (forensics_json IS NULL OR forensics_json = '')
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    channels = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return channels

def parse_user_ids(user_ids_json: str) -> list[int]:
    """Parse user_ids_json to list of integers."""
    if not user_ids_json:
        return []
    try:
        return json.loads(user_ids_json)
    except:
        return []

def update_forensics(db_path: str, username: str, forensics: dict):
    """Update forensics_json in database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE channels
        SET forensics_json = ?
        WHERE username = ?
    """, (json.dumps(forensics), username))
    conn.commit()
    conn.close()

def fill_forensics_metrics(db_path: str, dry_run: bool = False, limit: int = None) -> dict:
    """Fill missing forensics metrics."""
    channels = get_channels_missing_forensics(db_path, limit)
    print(f"Found {len(channels)} channels missing forensics")

    if dry_run:
        print("\n[DRY RUN] Would process:")
        for ch in channels[:10]:
            print(f"  @{ch['username']}")
        if len(channels) > 10:
            print(f"  ... and {len(channels) - 10} more")
        return {'would_process': len(channels)}

    # Import forensics analyzer
    try:
        from scanner.forensics import UserForensics
    except ImportError:
        print("[!] UserForensics not available")
        return {'error': 'UserForensics not available'}

    success = 0
    errors = 0

    for i, ch in enumerate(channels, 1):
        try:
            user_ids = parse_user_ids(ch['user_ids_json'])
            if not user_ids:
                continue

            # Analyze
            forensics = UserForensics()
            result = forensics.analyze_local(user_ids)

            # Update DB
            update_forensics(db_path, ch['username'], result)
            success += 1

            if i % 50 == 0:
                print(f"  Processed {i}/{len(channels)}...")

        except Exception as e:
            errors += 1
            print(f"  [!] Error on @{ch['username']}: {e}")

    print(f"\nDone: {success} success, {errors} errors")
    return {'success': success, 'errors': errors}
