"""Domain models for Smart Rescan System."""

from .metric_registry import (
    METRIC_REGISTRY,
    MetricDefinition,
    MetricSource,
    get_metrics_by_source,
    get_metrics_by_filler,
    get_required_metrics,
    get_fillable_metrics,
)

from .metric_checker import (
    ChannelCompleteness,
    GlobalCompleteness,
    check_channel_completeness,
    analyze_database_completeness,
)

__all__ = [
    # Registry
    "METRIC_REGISTRY",
    "MetricDefinition",
    "MetricSource",
    "get_metrics_by_source",
    "get_metrics_by_filler",
    "get_required_metrics",
    "get_fillable_metrics",
    # Checker
    "ChannelCompleteness",
    "GlobalCompleteness",
    "check_channel_completeness",
    "analyze_database_completeness",
]
