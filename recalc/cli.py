"""
CLI Interface v79.0
Unified recalculation command line interface.

Usage:
    python -m recalc --mode local
    python -m recalc --mode forensics
    python -m recalc --mode llm
    python -m recalc --mode full --limit 50
    python -m recalc --status
"""
import argparse
import sys
from pathlib import Path

from .modes.local import recalculate_local_mode
from .modes.forensics import recalculate_forensics_mode
from .modes.llm import recalculate_llm_mode
from .modes.full import recalculate_full_mode
from .infrastructure.db_repository import ChannelRepository


def print_status(db_path: str):
    """Print database statistics."""
    print(f"[*] Database Status: {db_path}")
    print("=" * 50)

    try:
        with ChannelRepository(db_path) as repo:
            stats = repo.get_statistics()

            print(f"\nTotal channels: {stats['total']}")

            print(f"\nBy Status:")
            for status, count in sorted(stats['by_status'].items()):
                pct = count / stats['total'] * 100 if stats['total'] > 0 else 0
                print(f"  {status:15} {count:5} ({pct:5.1f}%)")

            print(f"\nBy Verdict (scanned only):")
            for verdict, count in sorted(stats['by_verdict'].items(), key=lambda x: -x[1]):
                print(f"  {verdict:15} {count:5}")

    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='recalc',
        description='Unified Recalculation System v79.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m recalc --status              # Show database statistics
  python -m recalc --mode local          # Recalculate from saved breakdown
  python -m recalc --mode forensics      # Recalculate trust_factor only
  python -m recalc --mode local --dry-run  # Preview changes without saving
  python -m recalc --mode local -v       # Verbose output

Modes:
  local      - Recalculate score + trust from breakdown_json (fastest)
  forensics  - Recalculate trust_factor only, uses ALL 20+ multipliers
  llm        - Re-run LLM analysis (requires Ollama/Groq)
  full       - Full rescan via Telegram API (slowest)
        """
    )

    # Mode selection
    parser.add_argument(
        '--mode', '-m',
        choices=['local', 'forensics', 'llm', 'full'],
        help='Recalculation mode'
    )

    # Status
    parser.add_argument(
        '--status', '-s',
        action='store_true',
        help='Show database statistics'
    )

    # Options
    parser.add_argument(
        '--db',
        default='crawler.db',
        help='Path to database (default: crawler.db)'
    )

    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Preview changes without saving'
    )

    parser.add_argument(
        '--limit', '-l',
        type=int,
        help='Max channels to process'
    )

    parser.add_argument(
        '--filter', '-f',
        help='SQL filter (e.g., "category=\'CRYPTO\'")'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    # Check database exists
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}")
        sys.exit(1)

    # Handle --status
    if args.status:
        print_status(str(db_path))
        return

    # Require --mode
    if not args.mode:
        parser.print_help()
        print("\n[ERROR] --mode is required (or use --status)")
        sys.exit(1)

    # Run selected mode
    if args.mode == 'local':
        result = recalculate_local_mode(
            db_path=str(db_path),
            dry_run=args.dry_run,
            filter_sql=args.filter,
            limit=args.limit,
            verbose=args.verbose,
        )
    elif args.mode == 'forensics':
        result = recalculate_forensics_mode(
            db_path=str(db_path),
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
        )
    elif args.mode == 'llm':
        result = recalculate_llm_mode(
            db_path=str(db_path),
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
        )
    elif args.mode == 'full':
        result = recalculate_full_mode(
            db_path=str(db_path),
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
        )

    # Exit code
    if result.errors > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
