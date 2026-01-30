"""
Verdict Determination v79.0
Thresholds and verdict assignment.
"""
from dataclasses import dataclass
from enum import Enum


class Verdict(Enum):
    """Channel quality verdict."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    MEDIUM = "MEDIUM"
    HIGH_RISK = "HIGH_RISK"
    SCAM = "SCAM"


@dataclass
class VerdictThresholds:
    """Score thresholds for verdicts."""
    EXCELLENT: int = 75
    GOOD: int = 55
    MEDIUM: int = 40
    HIGH_RISK: int = 25
    # Below HIGH_RISK = SCAM


def get_verdict(final_score: int) -> Verdict:
    """
    Determine verdict based on final score.

    Args:
        final_score: Score after trust_factor applied (0-100)

    Returns:
        Verdict enum value
    """
    if final_score >= VerdictThresholds.EXCELLENT:
        return Verdict.EXCELLENT
    elif final_score >= VerdictThresholds.GOOD:
        return Verdict.GOOD
    elif final_score >= VerdictThresholds.MEDIUM:
        return Verdict.MEDIUM
    elif final_score >= VerdictThresholds.HIGH_RISK:
        return Verdict.HIGH_RISK
    else:
        return Verdict.SCAM


def get_verdict_color(verdict: Verdict) -> str:
    """
    Get ANSI color code for terminal output.

    Args:
        verdict: Verdict enum value

    Returns:
        ANSI escape code string
    """
    colors = {
        Verdict.EXCELLENT: "\033[92m",  # Bright Green
        Verdict.GOOD: "\033[94m",       # Bright Blue
        Verdict.MEDIUM: "\033[93m",     # Yellow
        Verdict.HIGH_RISK: "\033[91m",  # Red
        Verdict.SCAM: "\033[95m",       # Magenta
    }
    return colors.get(verdict, "\033[0m")


def get_verdict_emoji(verdict: Verdict) -> str:
    """
    Get emoji for verdict (for logs/reports).
    """
    emojis = {
        Verdict.EXCELLENT: "🟢",
        Verdict.GOOD: "🔵",
        Verdict.MEDIUM: "🟡",
        Verdict.HIGH_RISK: "🟠",
        Verdict.SCAM: "🔴",
    }
    return emojis.get(verdict, "⚪")


def get_status_from_verdict(verdict: Verdict) -> str:
    """
    Convert verdict to database status.
    GOOD/EXCELLENT → 'GOOD', others → 'BAD'
    """
    if verdict in (Verdict.EXCELLENT, Verdict.GOOD):
        return 'GOOD'
    return 'BAD'


# Convenience function for direct score → verdict string
def score_to_verdict(final_score: int) -> str:
    """Get verdict string from score."""
    return get_verdict(final_score).value
