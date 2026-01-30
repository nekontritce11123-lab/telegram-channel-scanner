"""
Full Mode v79.0
Full rescan via Telegram API.
Slowest mode - calls smart_scan() for each channel.
"""
from dataclasses import dataclass
from typing import Optional

from ..infrastructure.batch_processor import BatchResult


def recalculate_full_mode(
    db_path: str = 'crawler.db',
    dry_run: bool = False,
    limit: int = None,
    verbose: bool = False,
) -> BatchResult:
    """
    Full rescan via Telegram API.

    This mode:
    1. Calls smart_scan() for each channel
    2. Gets fresh messages, users, online_count
    3. Runs full forensics analysis
    4. Runs LLM analysis
    5. Calculates new scores

    Rate limited to ~0.5 channels/second.

    Args:
        db_path: Path to database
        dry_run: Don't write changes
        limit: Max channels to process (recommended: 50)
        verbose: Print details

    Returns:
        BatchResult with statistics
    """
    print(f"🔄 Full Rescan Mode")
    print(f"   Database: {db_path}")
    print(f"   Dry run: {dry_run}")
    print(f"   Limit: {limit or 'none'}")
    print()

    if limit is None or limit > 100:
        print("⚠️  Warning: Full mode is slow (~0.5 ch/sec due to Telegram rate limits)")
        print("   Consider using --limit 50 to process in batches")
        print()

    # TODO: Implement full rescan
    print("⚠️  Full mode is not yet implemented")
    print("   Use python crawler.py to rescan channels")
    print("   Or use --mode local/forensics for recalculation from saved data")

    return BatchResult(
        processed=0,
        changed=0,
        errors=0,
        elapsed_seconds=0
    )
