"""
LLM Mode v79.0
Re-run LLM analysis on stored posts and comments.
Requires Ollama/Groq API.
"""
from dataclasses import dataclass
from typing import Optional

from ..domain.verdict import get_verdict, get_status_from_verdict
from ..infrastructure.db_repository import ChannelRepository, UpdateRow
from ..infrastructure.batch_processor import BatchResult


@dataclass
class LLMRecalcResult:
    """Result of LLM recalculation for one channel."""
    username: str
    old_bot_pct: int
    new_bot_pct: int
    old_ad_pct: int
    new_ad_pct: int
    old_score: int
    new_score: int
    changed: bool


def recalculate_llm_mode(
    db_path: str = 'crawler.db',
    dry_run: bool = False,
    limit: int = None,
    verbose: bool = False,
) -> BatchResult:
    """
    Re-run LLM analysis on stored posts/comments.

    This mode:
    1. Reads posts_text_gz and comments_text_gz from database
    2. Decompresses and sends to LLM for analysis
    3. Updates bot_percentage, ad_percentage, tier
    4. Recalculates trust_factor and final score

    Requires:
    - GROQ_API_KEY or Ollama running locally

    Args:
        db_path: Path to database
        dry_run: Don't write changes
        limit: Max channels to process
        verbose: Print details

    Returns:
        BatchResult with statistics
    """
    print(f"🤖 LLM Recalculation Mode")
    print(f"   Database: {db_path}")
    print(f"   Dry run: {dry_run}")
    print()

    # Check for LLM availability
    try:
        import sys
        sys.path.insert(0, 'f:/Code/Рекламщик')
        from scanner.llm_analyzer import LLMAnalyzer
        analyzer = LLMAnalyzer()
        print(f"   LLM: {analyzer.model}")
    except ImportError as e:
        print(f"❌ Error: Cannot import LLMAnalyzer: {e}")
        return BatchResult(processed=0, changed=0, errors=1, elapsed_seconds=0)
    except Exception as e:
        print(f"❌ Error: LLM not available: {e}")
        return BatchResult(processed=0, changed=0, errors=1, elapsed_seconds=0)

    with ChannelRepository(db_path) as repo:
        channels = repo.get_all_channels(limit=limit)
        print(f"Found {len(channels)} channels to process\n")

        # TODO: Implement full LLM recalculation
        # For now, this is a placeholder
        print("⚠️  LLM mode is not yet fully implemented")
        print("   Use --mode forensics for trust recalculation")
        print("   Use --mode local for full score recalculation")

        return BatchResult(
            processed=0,
            changed=0,
            errors=0,
            elapsed_seconds=0
        )
