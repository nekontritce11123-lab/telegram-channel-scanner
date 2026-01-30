"""
Smart Rescan CLI v80.0
Usage: python -m rescan --status
"""
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description='Smart Rescan System - Metric completeness analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m rescan --status              Show database completeness
  python -m rescan --fill llm            Fill missing LLM metrics
  python -m rescan --fill llm --dry-run  Preview what would be filled
  python -m rescan --metric ai_summary   Check specific metric
"""
    )
    parser.add_argument('--status', action='store_true', help='Show database completeness report')
    parser.add_argument('--fill', choices=['llm', 'forensics', 'photo', 'telegram'], help='Fill missing metrics')
    parser.add_argument('--metric', type=str, help='Check specific metric')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--limit', type=int, help='Limit channels to process')
    parser.add_argument('--db', default='crawler.db', help='Database path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.status:
        show_status(args.db)
    elif args.fill:
        fill_metrics(args.fill, args.db, args.dry_run, args.limit)
    elif args.metric:
        check_metric(args.metric, args.db)
    else:
        parser.print_help()
        sys.exit(1)

def show_status(db_path: str):
    """Show database completeness report."""
    from .domain.metric_checker import analyze_database_completeness

    print("[*] Analyzing database completeness...")
    report = analyze_database_completeness(db_path)

    print(f"\n{'='*50}")
    print(f"DATABASE COMPLETENESS REPORT")
    print(f"{'='*50}")
    print(f"Total channels: {report.total_channels}")
    pct = report.complete_channels / report.total_channels * 100 if report.total_channels > 0 else 0
    print(f"Complete channels: {report.complete_channels} ({pct:.1f}%)")

    print(f"\n--- By Source ---")
    for source, data in report.by_source.items():
        print(f"  {source}: {data['avg_pct']:.1f}% complete")

    print(f"\n--- Missing Metrics (Top 10) ---")
    sorted_metrics = sorted(report.by_metric.items(), key=lambda x: x[1]['missing'], reverse=True)
    for name, counts in sorted_metrics[:10]:
        if counts['missing'] > 0:
            print(f"  {name}: {counts['missing']} missing ({counts['pct']:.1f}% present)")

    if report.recommendations:
        print(f"\n--- Recommended Actions ---")
        for rec in report.recommendations:
            print(f"  {rec}")

def fill_metrics(filler: str, db_path: str, dry_run: bool, limit: int):
    """Fill missing metrics using specified filler."""
    print(f"[*] Fill mode: {filler}")
    print(f"    Database: {db_path}")
    print(f"    Dry run: {dry_run}")
    if limit:
        print(f"    Limit: {limit}")
    print()

    if filler == 'llm':
        from .fillers.llm_filler import fill_llm_metrics
        fill_llm_metrics(db_path, dry_run, limit)
    elif filler == 'forensics':
        from .fillers.forensics_filler import fill_forensics_metrics
        fill_forensics_metrics(db_path, dry_run, limit)
    elif filler == 'photo':
        from .fillers.photo_filler import fill_photo_metrics
        fill_photo_metrics(db_path, dry_run, limit)
    elif filler == 'telegram':
        print("[!] Telegram filler not yet implemented")
        print("    Use: python crawler.py --rescan")

def check_metric(metric_name: str, db_path: str):
    """Check specific metric across all channels."""
    from .domain.metric_registry import METRIC_REGISTRY

    if metric_name not in METRIC_REGISTRY:
        print(f"[!] Unknown metric: {metric_name}")
        print(f"    Available: {', '.join(sorted(METRIC_REGISTRY.keys()))}")
        return

    metric = METRIC_REGISTRY[metric_name]
    print(f"[*] Checking metric: {metric_name}")
    print(f"    Source: {metric.source.name}")
    print(f"    DB Column: {metric.db_column or 'N/A'}")
    print(f"    JSON Path: {metric.json_path or 'N/A'}")
    print(f"    Required: {metric.required}")
    print(f"    Filler: {metric.filler_module or 'N/A'}")

    # TODO: Count channels with/without this metric

if __name__ == '__main__':
    main()
