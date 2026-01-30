"""
Metric Checker v80.0

Analyzes database completeness - which metrics are present/missing.

Usage:
    from rescan.domain.metric_checker import analyze_database_completeness

    report = analyze_database_completeness("crawler.db")
    print(f"Complete channels: {report.complete_channels}/{report.total_channels}")
    for rec in report.recommendations:
        print(f"  {rec}")
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

from .metric_registry import (
    METRIC_REGISTRY,
    MetricDefinition,
    MetricSource,
    get_metrics_by_source,
    get_metrics_by_filler,
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ChannelCompleteness:
    """Completeness analysis for a single channel."""
    username: str
    present: list[str] = field(default_factory=list)  # Metrics that have values
    missing: list[str] = field(default_factory=list)  # Metrics that are missing

    @property
    def completeness_pct(self) -> float:
        """Percentage of present metrics."""
        total = len(self.present) + len(self.missing)
        if total == 0:
            return 0.0
        return (len(self.present) / total) * 100

    @property
    def is_complete(self) -> bool:
        """Are all required metrics present?"""
        return len(self.missing) == 0


@dataclass
class GlobalCompleteness:
    """Completeness analysis for the entire database."""
    total_channels: int
    complete_channels: int
    by_metric: dict[str, dict] = field(default_factory=dict)  # metric -> {present, missing, pct}
    by_source: dict[str, dict] = field(default_factory=dict)  # source -> {metrics, avg_pct}
    recommendations: list[str] = field(default_factory=list)  # Commands to run


# =============================================================================
# METRIC VALUE EXTRACTION
# =============================================================================

def _extract_metric_value(row: dict, metric: MetricDefinition) -> Optional[Any]:
    """
    Extract metric value from a database row.

    Handles:
    - Direct DB columns (db_column)
    - JSON paths (json_path) like "breakdown_json.breakdown.cv_views"

    Returns None if metric is missing or empty.
    """
    # Direct DB column
    if metric.db_column:
        value = row.get(metric.db_column)

        # Handle None and empty strings
        if value is None or value == "":
            return None

        # Handle JSON columns that might contain null
        if metric.db_column.endswith("_json") and isinstance(value, str):
            try:
                parsed = json.loads(value)
                if parsed is None or parsed == {}:
                    return None
                return parsed
            except (json.JSONDecodeError, TypeError):
                return None

        return value

    # JSON path (e.g., "breakdown_json.breakdown.cv_views")
    if metric.json_path:
        parts = metric.json_path.split(".")
        if len(parts) < 2:
            return None

        # First part is the DB column containing JSON
        json_column = parts[0]
        json_str = row.get(json_column)

        if not json_str:
            return None

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None

        # Navigate the JSON path
        current = data
        for part in parts[1:]:
            if current is None:
                return None
            # Use null-safe access pattern
            current = (current.get(part) if isinstance(current, dict) else None) or None
            if current is None:
                return None

        return current

    return None


# =============================================================================
# CHANNEL COMPLETENESS
# =============================================================================

def check_channel_completeness(row: dict) -> ChannelCompleteness:
    """
    Check which metrics are present/missing for a channel.

    Args:
        row: Database row as dict (from sqlite3.Row or similar)

    Returns:
        ChannelCompleteness with lists of present and missing metrics
    """
    username = row.get("username", "unknown")
    present = []
    missing = []

    for name, metric in METRIC_REGISTRY.items():
        value = _extract_metric_value(row, metric)

        if value is not None:
            present.append(name)
        else:
            # Only count as missing if it's a required metric or has a filler
            if metric.required or metric.filler_module:
                missing.append(name)

    return ChannelCompleteness(
        username=username,
        present=present,
        missing=missing
    )


# =============================================================================
# GLOBAL ANALYSIS
# =============================================================================

def analyze_database_completeness(db_path: str) -> GlobalCompleteness:
    """
    Analyze completeness of all channels in the database.

    Args:
        db_path: Path to SQLite database

    Returns:
        GlobalCompleteness with aggregate statistics
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all scanned channels (GOOD or BAD status)
    cursor.execute("""
        SELECT * FROM channels
        WHERE status IN ('GOOD', 'BAD')
    """)

    rows = cursor.fetchall()
    conn.close()

    total_channels = len(rows)
    complete_channels = 0

    # Initialize metric counters
    by_metric: dict[str, dict] = {}
    for name in METRIC_REGISTRY:
        by_metric[name] = {"present": 0, "missing": 0, "pct": 0.0}

    # Analyze each channel
    for row in rows:
        row_dict = dict(row)
        completeness = check_channel_completeness(row_dict)

        if completeness.is_complete:
            complete_channels += 1

        for metric_name in completeness.present:
            if metric_name in by_metric:
                by_metric[metric_name]["present"] += 1

        for metric_name in completeness.missing:
            if metric_name in by_metric:
                by_metric[metric_name]["missing"] += 1

    # Calculate percentages
    for name, counts in by_metric.items():
        total = counts["present"] + counts["missing"]
        if total > 0:
            counts["pct"] = (counts["present"] / total) * 100

    # Group by source
    by_source: dict[str, dict] = {}
    for source in MetricSource:
        source_metrics = get_metrics_by_source(source)
        if not source_metrics:
            continue

        metric_names = [m.name for m in source_metrics]
        avg_pct = 0.0
        counted = 0

        for name in metric_names:
            if name in by_metric and by_metric[name]["present"] + by_metric[name]["missing"] > 0:
                avg_pct += by_metric[name]["pct"]
                counted += 1

        if counted > 0:
            avg_pct /= counted

        by_source[source.name] = {
            "metrics": metric_names,
            "avg_pct": avg_pct
        }

    # Generate recommendations
    recommendations = _generate_recommendations(by_metric, total_channels)

    return GlobalCompleteness(
        total_channels=total_channels,
        complete_channels=complete_channels,
        by_metric=by_metric,
        by_source=by_source,
        recommendations=recommendations
    )


def _generate_recommendations(by_metric: dict[str, dict], total: int) -> list[str]:
    """
    Generate recommendations based on missing metrics.

    Args:
        by_metric: Metric statistics {name: {present, missing, pct}}
        total: Total number of channels

    Returns:
        List of recommended commands to run
    """
    if total == 0:
        return ["No channels to analyze. Run crawler first."]

    recommendations = []

    # Group missing metrics by filler
    filler_missing: dict[str, list[tuple[str, int]]] = {}

    for name, counts in by_metric.items():
        if counts["missing"] == 0:
            continue

        metric = METRIC_REGISTRY.get(name)
        if not metric or not metric.filler_module:
            continue

        filler = metric.filler_module
        if filler not in filler_missing:
            filler_missing[filler] = []

        filler_missing[filler].append((name, counts["missing"]))

    # Generate recommendation per filler
    for filler, metrics in sorted(filler_missing.items()):
        total_missing = sum(m[1] for m in metrics)
        metric_names = [m[0] for m in metrics[:3]]  # Show top 3

        if len(metrics) > 3:
            metric_names.append(f"+{len(metrics) - 3} more")

        pct_missing = (total_missing / (total * len(metrics))) * 100 if total > 0 else 0

        # Use short filler names: "forensics_filler" → "forensics"
        short_filler = filler.replace("_filler", "")

        recommendations.append(
            f"python -m rescan --fill {short_filler}  # {', '.join(metric_names)} ({pct_missing:.0f}% missing)"
        )

    if not recommendations:
        recommendations.append("All fillable metrics are complete!")

    return recommendations
