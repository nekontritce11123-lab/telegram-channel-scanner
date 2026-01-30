# Telegram Channel Scanner
# v51.2: убрали cli для избежания torch зависимости на сервере
# v85.0: добавлен scanner.llm subpackage

from .scorer import calculate_final_score
from .client import get_client
# scan_channel доступен через: from scanner.cli import scan_channel

# =========================================================================
# v85.0 Backward Compatibility Shims
# Old imports continue to work, but new code should use scanner.llm.*
# =========================================================================

# LLM Analyzer (from scanner.llm_analyzer import X → from scanner.llm import X)
from .llm import (
    LLMAnalyzer,
    LLMAnalysisResult,
    PostAnalysisResult,
    CommentAnalysisResult,
)

# Classifier (from scanner.classifier import X → from scanner.llm import X)
from .llm import (
    ChannelClassifier,
    get_classifier,
)

# Ad Detector (from scanner.ad_detector import X → from scanner.llm import X)
from .llm import (
    detect_ad_status,
    extract_ad_contacts,
    analyze_private_invites,
)

# Summarizer (from scanner.summarizer import X → from scanner.llm import X)
from .llm import generate_channel_summary
