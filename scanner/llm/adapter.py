"""
Legacy Adapter v88.0

Converts UnifiedAnalysisResult to LLMAnalysisResult for scorer.py compatibility.

The scorer.py expects LLMAnalysisResult with PostAnalysisResult and CommentAnalysisResult
dataclasses. This adapter translates the new unified format to the legacy format
without changing the scorer logic.

Usage:
    from scanner.llm.adapter import adapt_unified_to_legacy

    unified_result = await unified_analyze(chat, messages, comments, images)
    legacy_result = adapt_unified_to_legacy(unified_result)

    # Now use with scorer
    score = calculate_final_score(..., llm_result=legacy_result)
"""

from typing import Optional

from .unified_analyzer import UnifiedAnalysisResult
from .analyzer import (
    LLMAnalysisResult,
    PostAnalysisResult,
    CommentAnalysisResult,
)


def adapt_unified_to_legacy(
    unified: UnifiedAnalysisResult,
    category: Optional[str] = None
) -> LLMAnalysisResult:
    """
    Convert UnifiedAnalysisResult to LLMAnalysisResult.

    This adapter ensures backwards compatibility with the existing
    scorer.py which expects LLMAnalysisResult format.

    Args:
        unified: Result from unified_analyze()
        category: Optional category override (defaults to unified.category)

    Returns:
        LLMAnalysisResult compatible with scorer.py

    Example:
        unified = await unified_analyze(chat, messages, comments)
        legacy = adapt_unified_to_legacy(unified)
        legacy.calculate_impact_v2()  # Computes trust factors
    """
    # Use unified category if not overridden
    effective_category = category or unified.category

    # Create PostAnalysisResult from unified data
    posts = PostAnalysisResult(
        brand_safety=100 if not unified.is_toxic else 0,
        toxicity=0,
        violence=0,
        military_conflict=0,
        political_quantity=0,
        political_risk=0,
        misinformation=0,
        ad_percentage=unified.ad_percentage,
        red_flags=unified.toxic_evidence if unified.is_toxic else [],
        raw_response=""
    )

    # Create CommentAnalysisResult from unified data
    comments = None
    if unified.trust_score > 0 or unified.bot_percentage > 0:
        comments = CommentAnalysisResult(
            bot_percentage=unified.bot_percentage,
            bot_signals=unified.comment_signals,
            trust_score=unified.trust_score,
            trust_signals=[f"Tier: {unified.authenticity_tier}"],
            raw_response=""
        )

    # Create brand safety dict for LLMAnalysisResult.safety field
    safety_dict = None
    if unified.is_toxic or unified.toxic_severity != "SAFE":
        safety_dict = {
            'is_toxic': unified.is_toxic,
            'toxic_category': unified.toxic_category,
            'severity': unified.toxic_severity,
            'evidence': unified.toxic_evidence,
            'confidence': unified.category_confidence if unified.is_toxic else 0,
            'toxic_ratio': 0.0,  # Not computed in unified
            'reasoning': unified.category_reasoning
        }

    # Create LLMAnalysisResult
    result = LLMAnalysisResult(
        posts=posts,
        comments=comments,
        safety=safety_dict,
        category=effective_category
    )

    # Calculate impact (sets tier, tier_cap, llm_trust_factor, etc.)
    result.calculate_impact_v2()

    return result


def extract_category(unified: UnifiedAnalysisResult) -> str:
    """
    Extract category from UnifiedAnalysisResult.

    Simple helper for places that just need the category.

    Args:
        unified: Result from unified_analyze()

    Returns:
        Category string (e.g., "CRYPTO", "TECH")
    """
    return unified.category


def extract_summary(unified: UnifiedAnalysisResult) -> Optional[str]:
    """
    Extract Russian summary from UnifiedAnalysisResult.

    Returns None if summary is too short or missing.

    Args:
        unified: Result from unified_analyze()

    Returns:
        Summary string or None
    """
    summary = unified.summary_ru
    if summary and len(summary) >= 50:
        return summary
    return None


def format_analysis_report(unified: UnifiedAnalysisResult) -> str:
    """
    Format unified result as human-readable report.

    Useful for debugging and logging.

    Args:
        unified: Result from unified_analyze()

    Returns:
        Formatted multi-line report string
    """
    lines = [
        "=" * 50,
        "UNIFIED ANALYSIS REPORT",
        "=" * 50,
        "",
        f"Category: {unified.category} ({unified.category_confidence}%)",
        f"Reasoning: {unified.category_reasoning[:100]}..." if unified.category_reasoning else "",
        "",
        "--- Brand Safety ---",
        f"Toxic: {unified.is_toxic}",
        f"Category: {unified.toxic_category or 'None'}",
        f"Severity: {unified.toxic_severity}",
    ]

    if unified.toxic_evidence:
        lines.append(f"Evidence: {', '.join(unified.toxic_evidence[:3])}")

    lines.extend([
        "",
        "--- Ad Analysis ---",
        f"Ad Percentage: {unified.ad_percentage}%",
        f"Ad Post IDs: {unified.ad_post_ids[:5]}" if unified.ad_post_ids else "",
        "",
        "--- Comment Analysis ---",
        f"Bot Percentage: {unified.bot_percentage}%",
        f"Trust Score: {unified.trust_score}",
        f"Authenticity: {unified.authenticity_tier}",
    ])

    if unified.comment_signals:
        lines.append(f"Signals: {', '.join(unified.comment_signals[:3])}")

    lines.extend([
        "",
        "--- Summary ---",
        unified.summary_ru[:200] if unified.summary_ru else "(No summary)",
    ])

    if unified.image_insights:
        lines.extend([
            "",
            "--- Image Insights ---",
            unified.image_insights[:200]
        ])

    if unified.parse_warnings:
        lines.extend([
            "",
            "--- Warnings ---",
            *unified.parse_warnings[:5]
        ])

    lines.append("=" * 50)

    return "\n".join(lines)
