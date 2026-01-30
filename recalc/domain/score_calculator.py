"""
Score Calculator v79.0
Recalculate raw_score from saved breakdown metrics.
NO division - direct calculation from metrics.
"""
from dataclasses import dataclass, field
from typing import Optional

# Add parent directory to path (works from any location)
import os
import sys
_parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from scanner.scorer import (
    cv_to_points,
    reach_to_points,
    regularity_to_points,
    forward_rate_to_points,
    reaction_rate_to_points,
    decay_to_points,
    er_trend_to_points,
    age_to_points,
    premium_to_points,
    source_to_points,
    comments_to_points,
    calculate_floating_weights,
    stability_to_points,
)
from scanner.scorer_constants import ScoringWeights


@dataclass
class ScoreInput:
    """Input data for score calculation."""
    # Quality metrics
    cv_views: float = 0.0
    reach: float = 0.0
    members: int = 0
    posts_per_day: float = 0.0
    forward_rate: float = 0.0
    views_decay_ratio: float = 1.0

    # Engagement metrics
    reaction_rate: float = 0.0
    avg_comments: float = 0.0
    er_trend_status: str = 'critical_decline'  # FIX: Was 'insufficient_data' (gives 5 pts)
    stability_cv: float = 100.0  # FIX: Was 50.0 - High CV = unstable = 0 pts
    stability_points: int = 0    # Use stored points if can't recalculate

    # Reputation metrics
    channel_age_days: int = 0
    premium_ratio: float = 0.0
    premium_count: int = 0
    is_verified: bool = False
    source_max_share: float = 1.0  # FIX: Was 0.0 - Max share = single source = 0 pts
    repost_ratio: float = 1.0  # FIX: Was 0.0 - All reposts = 0 pts

    # Flags
    comments_enabled: bool = True
    reactions_enabled: bool = True


@dataclass
class ScoreResult:
    """Result of score calculation."""
    raw_score: int
    quality_score: int = 0
    engagement_score: int = 0
    reputation_score: int = 0
    breakdown: dict = field(default_factory=dict)

    def __post_init__(self):
        # Safety cap at 100
        self.raw_score = min(100, max(0, self.raw_score))


def calculate_raw_score(input: ScoreInput) -> ScoreResult:
    """
    Recalculate raw_score from breakdown metrics.
    Uses the same functions as original scorer.py.
    """
    breakdown = {}

    # Calculate floating weights if needed
    floating = calculate_floating_weights(
        input.comments_enabled,
        input.reactions_enabled
    )

    # ========== QUALITY (max ~42) ==========
    quality_score = 0

    # CV Views (max 12)
    cv_pts = cv_to_points(input.cv_views, input.forward_rate)
    quality_score += cv_pts
    breakdown['cv_views'] = {'value': input.cv_views, 'points': cv_pts}

    # Reach (max 8)
    reach_pts = reach_to_points(input.reach, input.members)
    quality_score += reach_pts
    breakdown['reach'] = {'value': input.reach, 'points': reach_pts}

    # Regularity (max 7)
    regularity_pts = regularity_to_points(input.posts_per_day)
    quality_score += regularity_pts
    breakdown['regularity'] = {'value': input.posts_per_day, 'points': regularity_pts}

    # Forward Rate (max 15, can increase with floating weights)
    # FIX: Use correct key names from calculate_floating_weights
    forward_max = floating.get('forward_rate_max', 15)
    forward_pts = forward_rate_to_points(input.forward_rate, input.members, forward_max)
    quality_score += forward_pts
    breakdown['forward_rate'] = {'value': input.forward_rate, 'points': forward_pts, 'max': forward_max}

    # ========== ENGAGEMENT (max ~38) ==========
    engagement_score = 0

    # Reaction Rate (max 8, can increase to 13 with floating weights)
    # FIX: Use correct key names from calculate_floating_weights
    reaction_max = floating.get('reaction_rate_max', 8)
    reaction_pts = reaction_rate_to_points(input.reaction_rate, input.members, reaction_max)
    engagement_score += reaction_pts
    breakdown['reaction_rate'] = {'value': input.reaction_rate, 'points': reaction_pts, 'max': reaction_max}

    # Comments (max 15, can increase to 20 with floating weights)
    # FIX: Use correct key names from calculate_floating_weights
    comments_max = floating.get('comments_max', 15)
    comments_data = {
        'enabled': input.comments_enabled,
        'avg_comments': input.avg_comments
    }
    comments_pts, comments_status = comments_to_points(comments_data, input.members, comments_max)
    engagement_score += comments_pts
    breakdown['comments'] = {'avg': input.avg_comments, 'points': comments_pts, 'status': comments_status}

    # ER Trend (max 10)
    er_trend_data = {'status': input.er_trend_status}
    er_pts = er_trend_to_points(er_trend_data)
    engagement_score += er_pts
    breakdown['er_trend'] = {'status': input.er_trend_status, 'points': er_pts}

    # Reaction Stability (max 5) - v79.1: Use stored points or recalculate from CV
    # Can't fully recalculate without raw messages, so use stored points if available
    if input.stability_points > 0:
        stability_pts = input.stability_points
    else:
        # Fallback: calculate from stability_cv if available
        stability_data = {'stability_cv': input.stability_cv}
        stability_pts = stability_to_points(stability_data)
    engagement_score += stability_pts
    breakdown['reaction_stability'] = {'value': input.stability_cv, 'points': stability_pts}

    # Views Decay (INFO ONLY in v48.0, 0 points)
    decay_pts, decay_info = decay_to_points(input.views_decay_ratio, input.reaction_rate)
    # decay_pts is informational, not added to score
    breakdown['views_decay'] = {'value': input.views_decay_ratio, 'zone': decay_info.get('zone', 'unknown')}

    # ========== REPUTATION (max 20) ==========
    reputation_score = 0

    # Age (max 7)
    age_pts = age_to_points(input.channel_age_days)
    reputation_score += age_pts
    breakdown['age'] = {'value': input.channel_age_days, 'points': age_pts}

    # Premium (max 7)
    premium_pts = premium_to_points(input.premium_ratio, input.premium_count)
    reputation_score += premium_pts
    breakdown['premium'] = {'ratio': input.premium_ratio, 'count': input.premium_count, 'points': premium_pts}

    # Source Diversity (max 6)
    source_pts = source_to_points(input.source_max_share, input.repost_ratio)
    reputation_score += source_pts
    breakdown['source_diversity'] = {'value': 1 - input.source_max_share, 'points': source_pts}

    # Verified bonus (not in standard scoring but tracked)
    if input.is_verified:
        breakdown['verified'] = True

    # ========== TOTAL ==========
    raw_score = quality_score + engagement_score + reputation_score
    raw_score = min(100, max(0, raw_score))

    breakdown['categories'] = {
        'quality': {'score': quality_score, 'max': 42},
        'engagement': {'score': engagement_score, 'max': 38},
        'reputation': {'score': reputation_score, 'max': 20}
    }

    return ScoreResult(
        raw_score=raw_score,
        quality_score=quality_score,
        engagement_score=engagement_score,
        reputation_score=reputation_score,
        breakdown=breakdown
    )


def _extract_avg_comments(comments_data: dict) -> float:
    """
    Extract avg_comments from breakdown.
    Scanner stores: {'value': 'enabled (avg 10.3)', 'points': 15}
    or: {'avg': 10.3, 'points': 15}
    """
    if not comments_data:
        return 0.0

    # New format: direct 'avg' key
    if 'avg' in comments_data:
        return float(comments_data.get('avg', 0))

    # Old format: parse from 'value' string "enabled (avg X.X)"
    value = comments_data.get('value', '')
    if isinstance(value, str) and 'avg' in value:
        import re
        match = re.search(r'avg\s*([0-9.]+)', value)
        if match:
            return float(match.group(1))

    return 0.0


def extract_score_input_from_breakdown(breakdown_json: dict, members: int = 0) -> ScoreInput:
    """
    Extract ScoreInput from saved breakdown_json.
    Use this when recalculating from database.

    Args:
        breakdown_json: The breakdown_json from database
        members: Channel members count (pass from DB row, not stored in breakdown)
    """
    breakdown = breakdown_json.get('breakdown', breakdown_json)

    # Extract reaction stability data (use `or {}` to handle explicit null)
    stability_data = breakdown.get('reaction_stability') or {}
    stability_cv = stability_data.get('value', 100.0) if stability_data else 100.0  # FIX: Default 100 = unstable = 0 pts
    stability_points = stability_data.get('points', 0) if stability_data else 0

    # FIX: comments_enabled/reactions_enabled are in breakdown ROOT, not metadata
    comments_enabled = breakdown.get('comments_enabled', True)
    reactions_enabled = breakdown.get('reactions_enabled', True)

    # Fallback to metadata if present (for backwards compatibility)
    if 'metadata' in breakdown:
        metadata = breakdown['metadata']
        if 'comments_enabled' in metadata:
            comments_enabled = metadata['comments_enabled']
        if 'reactions_enabled' in metadata:
            reactions_enabled = metadata['reactions_enabled']
        if members == 0 and 'members' in metadata:
            members = metadata['members']

    return ScoreInput(
        # FIX: Use `or {}` pattern to handle explicit null values in JSON
        cv_views=(breakdown.get('cv_views') or {}).get('value', 0),
        reach=(breakdown.get('reach') or {}).get('value', 0),
        members=members,  # Pass from DB, not stored in breakdown
        posts_per_day=(breakdown.get('regularity') or {}).get('value', 0),
        forward_rate=(breakdown.get('forward_rate') or {}).get('value', 0),
        views_decay_ratio=(breakdown.get('views_decay') or {}).get('value', 1.0),
        reaction_rate=(breakdown.get('reaction_rate') or {}).get('value', 0),
        avg_comments=_extract_avg_comments(breakdown.get('comments') or {}),
        er_trend_status=(breakdown.get('er_trend') or {}).get('status', 'critical_decline'),  # FIX: Default 0 pts
        stability_cv=stability_cv,
        stability_points=stability_points,
        channel_age_days=(breakdown.get('age') or {}).get('value', 0),
        premium_ratio=(breakdown.get('premium') or {}).get('ratio', 0),
        premium_count=(breakdown.get('premium') or {}).get('count', 0),
        is_verified=breakdown.get('verified', False),
        source_max_share=1 - (breakdown.get('source_diversity') or {}).get('value', 0),  # FIX: Default value=0 -> max_share=1 = 0 pts
        repost_ratio=(breakdown.get('source_diversity') or {}).get('repost_ratio', 1.0),  # FIX: Default 1.0 = all reposts = 0 pts
        comments_enabled=comments_enabled,
        reactions_enabled=reactions_enabled,
    )
