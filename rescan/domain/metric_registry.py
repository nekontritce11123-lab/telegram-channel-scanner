"""
Metric Registry v80.0
Single source of truth for all scanner metrics.

This module defines all metrics used in the scoring system, their sources,
and how they are stored in the database.

Architecture:
- MetricSource: Enum defining where metrics come from (API calls, LLM, etc.)
- MetricDefinition: Dataclass describing a single metric
- METRIC_REGISTRY: Dict of all core metrics with their definitions
- Helper functions: get_metrics_by_source(), get_required_metrics(), etc.

Scoring Flow:
1. TELEGRAM_API_1: GetChat + GetHistory (50 messages) -> basic channel info
2. TELEGRAM_API_2: GetHistory linked_chat -> comments/reactions data
3. TELEGRAM_API_3: GetFullChannel -> online_count, premium ratio
4. LLM: Ollama/Groq analysis -> bot_percentage, ad_percentage, ai_summary
5. FORENSICS: User ID analysis -> clustering, geo/DC, premium density
6. CALCULATED: Derived from other metrics
7. EXTERNAL: Photo download, etc.

Usage:
    from .metric_registry import METRIC_REGISTRY, MetricSource, get_metrics_by_source

    # Get all LLM metrics
    llm_metrics = get_metrics_by_source(MetricSource.LLM)

    # Check specific metric
    if 'ai_summary' in METRIC_REGISTRY:
        metric = METRIC_REGISTRY['ai_summary']
        print(f"Source: {metric.source}, Filler: {metric.filler_module}")
"""
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class MetricSource(Enum):
    """Where the metric comes from."""
    TELEGRAM_API_1 = auto()  # GetChat + GetHistory (50 messages)
    TELEGRAM_API_2 = auto()  # GetHistory linked_chat (comments/reactions)
    TELEGRAM_API_3 = auto()  # GetFullChannel (online_count)
    LLM = auto()             # Ollama/Groq analysis
    CALCULATED = auto()      # Derived from other metrics
    FORENSICS = auto()       # From user_ids analysis
    EXTERNAL = auto()        # External sources (photo download)


@dataclass
class MetricDefinition:
    """
    Definition of a single metric.

    Attributes:
        name: Unique metric identifier
        source: MetricSource enum value
        db_column: Direct column name in channels table (if stored directly)
        json_path: Path in JSON field (e.g., 'breakdown_json.breakdown.cv_views')
        required: Whether this metric is required for scoring
        filler_module: Which filler module handles this metric
        dependencies: List of metric names this one depends on
        description: Human-readable description
    """
    name: str
    source: MetricSource
    db_column: Optional[str] = None     # Direct column in channels table
    json_path: Optional[str] = None     # Path in JSON field (breakdown_json, forensics_json)
    required: bool = True               # Required for scoring?
    filler_module: Optional[str] = None # Which filler handles this
    dependencies: list[str] = field(default_factory=list)
    description: str = ""


# =============================================================================
# METRIC REGISTRY - Single Source of Truth (~25 CORE metrics)
# =============================================================================

METRIC_REGISTRY: dict[str, MetricDefinition] = {
    # =========================================================================
    # TELEGRAM_API_1: GetChat + GetHistory (50 messages)
    # Basic channel info and message statistics
    # =========================================================================

    "members": MetricDefinition(
        name="members",
        source=MetricSource.TELEGRAM_API_1,
        db_column="members",
        required=True,
        filler_module="telegram_filler",
        description="Total subscriber count from chat.members_count"
    ),

    "title": MetricDefinition(
        name="title",
        source=MetricSource.TELEGRAM_API_1,
        db_column="title",
        required=False,
        filler_module="telegram_filler",
        description="Channel title"
    ),

    "channel_age_days": MetricDefinition(
        name="channel_age_days",
        source=MetricSource.TELEGRAM_API_1,
        db_column="channel_age_days",
        required=True,
        filler_module="telegram_filler",
        description="Days since first message (channel age)"
    ),

    "cv_views": MetricDefinition(
        name="cv_views",
        source=MetricSource.TELEGRAM_API_1,
        json_path="breakdown_json.breakdown.cv_views.value",
        required=True,
        filler_module="telegram_filler",
        description="Coefficient of Variation of views (natural variance indicator)"
    ),

    "reach": MetricDefinition(
        name="reach",
        source=MetricSource.TELEGRAM_API_1,
        db_column="reach_percent",
        json_path="breakdown_json.breakdown.reach.value",
        required=True,
        filler_module="telegram_filler",
        dependencies=["members"],
        description="Reach % (avg_views / members * 100)"
    ),

    "forward_rate": MetricDefinition(
        name="forward_rate",
        source=MetricSource.TELEGRAM_API_1,
        db_column="forward_rate",
        json_path="breakdown_json.breakdown.forward_rate.value",
        required=True,
        filler_module="telegram_filler",
        description="Forward rate % (avg_forwards / avg_views * 100)"
    ),

    "reaction_rate": MetricDefinition(
        name="reaction_rate",
        source=MetricSource.TELEGRAM_API_1,
        db_column="reaction_rate",
        json_path="breakdown_json.breakdown.reaction_rate.value",
        required=True,
        filler_module="telegram_filler",
        description="Reaction rate % (avg_reactions / avg_views * 100)"
    ),

    "views_decay_ratio": MetricDefinition(
        name="views_decay_ratio",
        source=MetricSource.TELEGRAM_API_1,
        db_column="decay_ratio",
        json_path="breakdown_json.breakdown.views_decay.value",
        required=True,
        filler_module="telegram_filler",
        description="Views decay ratio (new/old posts) - bot detection signal"
    ),

    "posts_per_day": MetricDefinition(
        name="posts_per_day",
        source=MetricSource.TELEGRAM_API_1,
        json_path="breakdown_json.breakdown.regularity.value",
        required=True,
        filler_module="telegram_filler",
        description="Average posts per day (regularity metric)"
    ),

    "er_trend_status": MetricDefinition(
        name="er_trend_status",
        source=MetricSource.TELEGRAM_API_1,
        db_column="er_trend_status",
        json_path="breakdown_json.breakdown.er_trend.status",
        required=True,
        filler_module="telegram_filler",
        description="ER trend status (growing/stable/declining/dying)"
    ),

    # =========================================================================
    # TELEGRAM_API_2: GetHistory linked_chat (comments/reactions)
    # =========================================================================

    "avg_comments": MetricDefinition(
        name="avg_comments",
        source=MetricSource.TELEGRAM_API_2,
        db_column="avg_comments",
        json_path="breakdown_json.breakdown.comments.avg",
        required=True,
        filler_module="telegram_filler",
        description="Average comments per post"
    ),

    # =========================================================================
    # TELEGRAM_API_3: GetFullChannel (online_count, premium data)
    # =========================================================================

    "online_count": MetricDefinition(
        name="online_count",
        source=MetricSource.TELEGRAM_API_3,
        db_column="online_count",
        required=True,
        filler_module="telegram_filler",
        description="Currently online users from GetFullChannel"
    ),

    "premium_ratio": MetricDefinition(
        name="premium_ratio",
        source=MetricSource.TELEGRAM_API_3,
        json_path="forensics_json.premium_density.premium_ratio",
        required=True,
        filler_module="forensics_filler",
        description="Premium users ratio (quality indicator)"
    ),

    "premium_count": MetricDefinition(
        name="premium_count",
        source=MetricSource.TELEGRAM_API_3,
        json_path="forensics_json.premium_density.premium_count",
        required=True,
        filler_module="forensics_filler",
        description="Number of premium users in sample"
    ),

    # =========================================================================
    # LLM: Ollama/Groq analysis
    # =========================================================================

    "bot_percentage": MetricDefinition(
        name="bot_percentage",
        source=MetricSource.LLM,
        db_column="bot_percentage",
        required=True,
        filler_module="llm_filler",
        description="Estimated bot percentage from LLM comment analysis"
    ),

    "ad_percentage": MetricDefinition(
        name="ad_percentage",
        source=MetricSource.LLM,
        db_column="ad_percentage",
        required=True,
        filler_module="llm_filler",
        description="Estimated ad percentage from LLM post analysis"
    ),

    "ai_summary": MetricDefinition(
        name="ai_summary",
        source=MetricSource.LLM,
        db_column="ai_summary",
        required=False,
        filler_module="llm_filler",
        description="AI-generated channel description (500+ chars)"
    ),

    # =========================================================================
    # FORENSICS: User ID analysis
    # =========================================================================

    "id_clustering": MetricDefinition(
        name="id_clustering",
        source=MetricSource.FORENSICS,
        json_path="forensics_json.id_clustering",
        required=True,
        filler_module="forensics_filler",
        description="ID clustering analysis (bot farm detection)"
    ),

    "geo_dc_analysis": MetricDefinition(
        name="geo_dc_analysis",
        source=MetricSource.FORENSICS,
        json_path="forensics_json.geo_dc_check",
        required=True,
        filler_module="forensics_filler",
        description="Geo/DC mismatch analysis (foreign bot detection)"
    ),

    "premium_density": MetricDefinition(
        name="premium_density",
        source=MetricSource.FORENSICS,
        json_path="forensics_json.premium_density",
        required=True,
        filler_module="forensics_filler",
        dependencies=["premium_ratio", "premium_count"],
        description="Premium density analysis from forensics"
    ),

    # =========================================================================
    # EXTERNAL: Photo and other external resources
    # =========================================================================

    "photo_path": MetricDefinition(
        name="photo_path",
        source=MetricSource.EXTERNAL,
        db_column="photo_blob",
        required=False,
        filler_module="photo_filler",
        description="Channel avatar photo (stored as BLOB)"
    ),

    # =========================================================================
    # CALCULATED: Derived metrics (depend on other metrics)
    # =========================================================================

    "raw_score": MetricDefinition(
        name="raw_score",
        source=MetricSource.CALCULATED,
        db_column="raw_score",
        required=True,
        filler_module="scoring_filler",
        dependencies=["cv_views", "reach", "forward_rate", "reaction_rate",
                      "posts_per_day", "avg_comments", "er_trend_status",
                      "channel_age_days", "premium_ratio"],
        description="Raw score before trust factor (0-100)"
    ),

    "trust_factor": MetricDefinition(
        name="trust_factor",
        source=MetricSource.CALCULATED,
        db_column="trust_factor",
        required=True,
        filler_module="scoring_filler",
        dependencies=["id_clustering", "geo_dc_analysis", "premium_density",
                      "bot_percentage", "ad_percentage", "online_count"],
        description="Trust factor multiplier (0.0-1.0)"
    ),

    "final_score": MetricDefinition(
        name="final_score",
        source=MetricSource.CALCULATED,
        db_column="score",
        required=True,
        filler_module="scoring_filler",
        dependencies=["raw_score", "trust_factor"],
        description="Final score = raw_score * trust_factor"
    ),

    "verdict": MetricDefinition(
        name="verdict",
        source=MetricSource.CALCULATED,
        db_column="verdict",
        required=True,
        filler_module="scoring_filler",
        dependencies=["final_score"],
        description="Final verdict (EXCELLENT/GOOD/MEDIUM/HIGH_RISK/SCAM)"
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_metrics_by_source(source: MetricSource) -> list[MetricDefinition]:
    """
    Get all metrics from a specific source.

    Args:
        source: MetricSource enum value

    Returns:
        List of MetricDefinition objects from that source

    Example:
        >>> api1_metrics = get_metrics_by_source(MetricSource.TELEGRAM_API_1)
        >>> [m.name for m in api1_metrics]
        ['members', 'title', 'cv_views', ...]
    """
    return [m for m in METRIC_REGISTRY.values() if m.source == source]


def get_required_metrics() -> list[MetricDefinition]:
    """
    Get all metrics that are required for scoring.

    Returns:
        List of MetricDefinition objects where required=True

    Example:
        >>> required = get_required_metrics()
        >>> len(required)
        21
    """
    return [m for m in METRIC_REGISTRY.values() if m.required]


def get_metrics_by_filler(filler_name: str) -> list[MetricDefinition]:
    """
    Get all metrics handled by a specific filler module.

    Args:
        filler_name: Name of the filler module (e.g., 'telegram_filler')

    Returns:
        List of MetricDefinition objects for that filler

    Example:
        >>> telegram_metrics = get_metrics_by_filler('telegram_filler')
        >>> [m.name for m in telegram_metrics]
        ['members', 'title', 'cv_views', 'reach', ...]
    """
    return [m for m in METRIC_REGISTRY.values() if m.filler_module == filler_name]


def get_metric(name: str) -> Optional[MetricDefinition]:
    """
    Get a specific metric by name.

    Args:
        name: Metric name

    Returns:
        MetricDefinition or None if not found
    """
    return METRIC_REGISTRY.get(name)


def get_db_columns() -> dict[str, str]:
    """
    Get mapping of metric names to their database columns.

    Returns:
        Dict mapping metric name -> db_column for metrics with direct columns

    Example:
        >>> columns = get_db_columns()
        >>> columns['members']
        'members'
        >>> columns['trust_factor']
        'trust_factor'
    """
    return {
        m.name: m.db_column
        for m in METRIC_REGISTRY.values()
        if m.db_column is not None
    }


def get_json_paths() -> dict[str, str]:
    """
    Get mapping of metric names to their JSON paths.

    Returns:
        Dict mapping metric name -> json_path for metrics stored in JSON fields

    Example:
        >>> paths = get_json_paths()
        >>> paths['cv_views']
        'breakdown_json.breakdown.cv_views.value'
    """
    return {
        m.name: m.json_path
        for m in METRIC_REGISTRY.values()
        if m.json_path is not None
    }


def get_metric_dependencies(name: str) -> list[str]:
    """
    Get all dependencies for a metric (recursive).

    Args:
        name: Metric name

    Returns:
        List of all dependency metric names (flattened, no duplicates)
    """
    metric = METRIC_REGISTRY.get(name)
    if not metric:
        return []

    all_deps = set()
    stack = list(metric.dependencies)

    while stack:
        dep_name = stack.pop()
        if dep_name not in all_deps:
            all_deps.add(dep_name)
            dep_metric = METRIC_REGISTRY.get(dep_name)
            if dep_metric:
                stack.extend(dep_metric.dependencies)

    return list(all_deps)


def get_fillable_metrics() -> list[MetricDefinition]:
    """Get all metrics that have a filler module."""
    return [m for m in METRIC_REGISTRY.values() if m.filler_module is not None]


def validate_registry() -> list[str]:
    """
    Validate the metric registry for consistency.

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    for name, metric in METRIC_REGISTRY.items():
        # Check name matches key
        if metric.name != name:
            errors.append(f"Metric '{name}' has mismatched name: '{metric.name}'")

        # Check dependencies exist
        for dep in metric.dependencies:
            if dep not in METRIC_REGISTRY:
                errors.append(f"Metric '{name}' has unknown dependency: '{dep}'")

        # Check storage location defined for non-calculated metrics
        if metric.db_column is None and metric.json_path is None:
            if metric.source not in (MetricSource.CALCULATED, MetricSource.FORENSICS):
                errors.append(f"Metric '{name}' has no storage location (db_column or json_path)")

    return errors


# =============================================================================
# MODULE INITIALIZATION - Validate on import
# =============================================================================

_validation_errors = validate_registry()
if _validation_errors:
    import warnings
    for error in _validation_errors:
        warnings.warn(f"MetricRegistry validation error: {error}")
