"""
LLM Filler v80.0
Fill missing LLM metrics: bot_percentage, ad_percentage, ai_summary
"""
import sqlite3
import gzip
import json
from typing import Optional

def get_channels_missing_llm(db_path: str, limit: int = None) -> list[dict]:
    """Get channels missing LLM metrics."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Use content_json (has posts text) instead of posts_text_gz (empty in DB)
    query = """
        SELECT username, content_json, posts_text_gz, comments_text_gz
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
          AND (ai_summary IS NULL OR ai_summary = '')
          AND (content_json IS NOT NULL OR posts_text_gz IS NOT NULL)
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    channels = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return channels

def extract_posts(channel: dict) -> list[str]:
    """Extract post texts from channel data.

    Tries content_json first (has posts text), falls back to posts_text_gz.
    """
    # Try content_json first (contains {"posts": [text1, text2, ...]})
    content_json = channel.get('content_json')
    if content_json:
        try:
            data = json.loads(content_json)
            if isinstance(data, dict) and 'posts' in data:
                return data['posts']
        except:
            pass

    # Fallback to posts_text_gz (gzipped JSON list)
    posts_gz = channel.get('posts_text_gz')
    if posts_gz:
        try:
            data = gzip.decompress(posts_gz)
            return json.loads(data)
        except:
            pass

    return []

def update_llm_metrics(db_path: str, username: str, result: dict):
    """Update LLM metrics in database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE channels
        SET bot_percentage = ?,
            ad_percentage = ?,
            ai_summary = ?
        WHERE username = ?
    """, (
        result.get('bot_percentage'),
        result.get('ad_percentage'),
        result.get('ai_summary'),
        username
    ))
    conn.commit()
    conn.close()

def fill_llm_metrics(db_path: str, dry_run: bool = False, limit: int = None) -> dict:
    """Fill missing LLM metrics."""
    channels = get_channels_missing_llm(db_path, limit)
    print(f"Found {len(channels)} channels missing LLM metrics")

    if dry_run:
        print("\n[DRY RUN] Would process:")
        for ch in channels[:10]:
            print(f"  @{ch['username']}")
        if len(channels) > 10:
            print(f"  ... and {len(channels) - 10} more")
        return {'would_process': len(channels)}

    # Import LLM analyzer
    try:
        from scanner.llm_analyzer import LLMAnalyzer
        analyzer = LLMAnalyzer()
    except ImportError:
        print("[!] LLMAnalyzer not available")
        return {'error': 'LLMAnalyzer not available'}

    success = 0
    errors = 0

    for i, ch in enumerate(channels, 1):
        try:
            posts = extract_posts(ch)
            if not posts:
                continue

            # Analyze
            result = analyzer.analyze(posts)

            # Update DB
            update_llm_metrics(db_path, ch['username'], result)
            success += 1

            if i % 10 == 0:
                print(f"  Processed {i}/{len(channels)}...")

        except Exception as e:
            errors += 1
            print(f"  [!] Error on @{ch['username']}: {e}")

    print(f"\nDone: {success} success, {errors} errors")
    return {'success': success, 'errors': errors}
