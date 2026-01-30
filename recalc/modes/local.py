"""
Local Mode v79.0
Recalculate score and trust from saved breakdown_json.
No API calls - fastest mode.
"""
from dataclasses import dataclass
from typing import Optional

from ..domain.trust_calculator import TrustInput, calculate_trust_factor
from ..domain.score_calculator import ScoreInput, calculate_raw_score, extract_score_input_from_breakdown
from ..domain.verdict import get_verdict, get_status_from_verdict
from ..infrastructure.db_repository import ChannelRepository, ChannelRow, UpdateRow
from ..infrastructure.batch_processor import BatchProcessor, BatchResult


@dataclass
class LocalRecalcResult:
    """Result of local recalculation for one channel."""
    username: str
    raw_score: int
    old_score: int
    new_score: int
    old_trust: float
    new_trust: float
    old_verdict: str
    new_verdict: str
    changed: bool
    penalties: list


def extract_trust_input(row: ChannelRow) -> TrustInput:
    """Extract TrustInput from database row."""
    forensics = row.forensics_json or {}
    breakdown = row.breakdown_json or {}
    bd = breakdown.get('breakdown', breakdown)

    # ID Clustering
    id_data = forensics.get('id_clustering') or {}
    id_ratio = id_data.get('percentage', 0) / 100 if id_data.get('percentage') else 0
    id_fatality = id_data.get('fatality', False)

    # Geo/DC
    geo_data = forensics.get('geo_dc_analysis') or {}
    geo_ratio = geo_data.get('percentage', 0) / 100 if geo_data.get('percentage') else 0

    # Premium
    premium_data = forensics.get('premium_density') or {}
    premium_ratio = premium_data.get('premium_ratio', 0) or 0
    premium_count = premium_data.get('premium_count', 0) or 0
    users_analyzed = forensics.get('users_analyzed', 0) or premium_data.get('users_analyzed', 0) or 0

    # Conviction
    conviction_data = breakdown.get('conviction_details') or {}
    conviction_score = conviction_data.get('conviction_score', 0) or 0

    # Metrics from breakdown
    reach = (bd.get('reach') or {}).get('value', 0) or 0
    forward_rate = (bd.get('forward_rate') or {}).get('value', 0) or 0
    reaction_rate = (bd.get('reaction_rate') or {}).get('value', 0) or 0
    decay_ratio = (bd.get('views_decay') or {}).get('value', 1.0) or 1.0
    avg_comments = (bd.get('comments') or {}).get('avg', 0) or 0
    source_data = bd.get('source_diversity') or {}
    source_max_share = 1 - (source_data.get('value', 1) or 1)

    # ER Trend
    er_status = (bd.get('er_trend') or {}).get('status', 'insufficient_data')

    # Private links
    private_data = bd.get('private_links') or {}
    private_ratio = private_data.get('private_ratio', 0) or 0

    return TrustInput(
        id_clustering_ratio=id_ratio,
        id_clustering_fatality=id_fatality,
        geo_dc_foreign_ratio=geo_ratio,
        premium_ratio=premium_ratio,
        premium_count=premium_count,
        users_analyzed=users_analyzed,
        bot_percentage=row.bot_percentage or 0,
        ad_percentage=row.ad_percentage or 0,
        conviction_score=conviction_score,
        reach=reach,
        forward_rate=forward_rate,
        reaction_rate=reaction_rate,
        views_decay_ratio=decay_ratio,
        avg_comments=avg_comments,
        source_max_share=source_max_share,
        members=row.members or 0,
        online_count=row.online_count or 0,
        participants_count=row.participants_count or 0,
        posts_per_day=row.posts_per_day or 0,
        category=row.category,
        private_ratio=private_ratio,
        comments_enabled=row.comments_enabled,
        er_trend_status=er_status,
    )


def recalculate_channel(row: ChannelRow) -> LocalRecalcResult:
    """Recalculate single channel from breakdown."""
    # Validate data exists
    if not row.breakdown_json or 'breakdown' not in row.breakdown_json:
        return LocalRecalcResult(
            username=row.username,
            raw_score=0,
            old_score=row.score,
            new_score=row.score,  # Keep old score
            old_trust=row.trust_factor,
            new_trust=row.trust_factor,  # Keep old trust
            old_verdict=row.verdict,
            new_verdict=row.verdict,  # Keep old verdict
            changed=False,
            penalties=[],
        )

    # Extract inputs
    trust_input = extract_trust_input(row)
    # FIX: Pass members from DB row (not stored in breakdown_json)
    score_input = extract_score_input_from_breakdown(row.breakdown_json or {}, members=row.members)

    # Calculate new values
    trust_result = calculate_trust_factor(trust_input)
    score_result = calculate_raw_score(score_input)

    # Final score
    new_raw = score_result.raw_score
    new_trust = trust_result.trust_factor
    new_final = round(new_raw * new_trust)
    new_verdict = get_verdict(new_final)

    # Check if changed
    changed = (
        row.score != new_final or
        abs(row.trust_factor - new_trust) > 0.01 or
        row.verdict != new_verdict.value
    )

    return LocalRecalcResult(
        username=row.username,
        raw_score=new_raw,
        old_score=row.score,
        new_score=new_final,
        old_trust=row.trust_factor,
        new_trust=new_trust,
        old_verdict=row.verdict,
        new_verdict=new_verdict.value,
        changed=changed,
        penalties=trust_result.penalties,
    )


def recalculate_local_mode(
    db_path: str = 'crawler.db',
    dry_run: bool = False,
    filter_sql: str = None,
    limit: int = None,
    verbose: bool = False,
) -> BatchResult:
    """
    Recalculate all channels from saved breakdown.

    Args:
        db_path: Path to database
        dry_run: Don't write changes
        filter_sql: SQL filter (e.g., "category='CRYPTO'")
        limit: Max channels to process
        verbose: Print details for each channel

    Returns:
        BatchResult with statistics
    """
    print(f"[*] Local Recalculation Mode")
    print(f"   Database: {db_path}")
    print(f"   Dry run: {dry_run}")
    if filter_sql:
        print(f"   Filter: {filter_sql}")
    print()

    with ChannelRepository(db_path) as repo:
        # Get channels
        channels = repo.get_all_channels(limit=limit)
        print(f"Found {len(channels)} channels to process\n")

        # Process
        processor = BatchProcessor(
            items=channels,
            process_fn=recalculate_channel,
            show_progress=True,
        )
        results, stats = processor.run()

        # Collect updates
        updates = []
        changed_count = 0

        for result in results:
            if result and result.changed:
                changed_count += 1
                updates.append(UpdateRow(
                    username=result.username,
                    score=result.new_score,
                    raw_score=result.raw_score,
                    trust_factor=result.new_trust,
                    verdict=result.new_verdict,
                    status=get_status_from_verdict(get_verdict(result.new_score)),
                ))

                if verbose:
                    print(f"\n  @{result.username}:")
                    print(f"    Score: {result.old_score} -> {result.new_score}")
                    print(f"    Trust: {result.old_trust:.2f} -> {result.new_trust:.2f}")
                    print(f"    Verdict: {result.old_verdict} -> {result.new_verdict}")
                    if result.penalties:
                        print(f"    Penalties: {', '.join(result.penalties[:3])}")

        # Write updates
        if not dry_run and updates:
            print(f"\n[>] Writing {len(updates)} updates...")
            repo.batch_update(updates)
            print("[OK] Done")
        elif dry_run:
            print(f"\n[DRY] Dry run: {len(updates)} channels would be updated")

        # Update stats
        stats.changed = changed_count

        # Summary
        print(f"\n[=] Summary:")
        print(f"   Processed: {stats.processed}")
        print(f"   Changed: {stats.changed}")
        print(f"   Rate: {stats.rate:.1f}/sec")

        return stats
