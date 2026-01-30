"""
Unified Recalculation System v79.0
Single source of truth for score/trust recalculation.
"""
from .domain.trust_calculator import TrustInput, TrustResult, calculate_trust_factor
from .domain.score_calculator import ScoreInput, ScoreResult, calculate_raw_score
from .domain.verdict import Verdict, get_verdict

__all__ = [
    'TrustInput', 'TrustResult', 'calculate_trust_factor',
    'ScoreInput', 'ScoreResult', 'calculate_raw_score',
    'Verdict', 'get_verdict',
]
