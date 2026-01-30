"""
scanner.llm - LLM Analysis Subpackage

Unified module for all Ollama-based AI analysis.
"""

# Client utilities
from .client import (
    call_ollama,
    safe_parse_json,
    fill_defaults,
    regex_extract_fields,
    OllamaConfig,
)

# Analyzer (post/comment analysis)
from .analyzer import (
    LLMAnalyzer,
    LLMAnalysisResult,
    PostAnalysisResult,
    CommentAnalysisResult,
    analyze_brand_safety,
    analyze_comments,
    analyze_ad_percentage,
    infer_channel_type,
)

# Classifier (channel categorization)
from .classifier import (
    ChannelClassifier,
    get_classifier,
    parse_category_response,
)

# Detector (ad detection)
from .detector import (
    detect_ad_status,
    detect_ad_status_llm,
    detect_ad_status_regex,
    extract_ad_contacts,
    analyze_private_invites,
    get_ad_status_label,
)

# Summarizer (channel description)
from .summarizer import (
    generate_channel_summary,
)

__all__ = [
    # Client
    'call_ollama', 'safe_parse_json', 'fill_defaults', 'regex_extract_fields', 'OllamaConfig',
    # Analyzer
    'LLMAnalyzer', 'LLMAnalysisResult', 'PostAnalysisResult', 'CommentAnalysisResult',
    'analyze_brand_safety', 'analyze_comments', 'analyze_ad_percentage', 'infer_channel_type',
    # Classifier
    'ChannelClassifier', 'get_classifier', 'parse_category_response',
    # Detector
    'detect_ad_status', 'detect_ad_status_llm', 'detect_ad_status_regex',
    'extract_ad_contacts', 'analyze_private_invites', 'get_ad_status_label',
    # Summarizer
    'generate_channel_summary',
]
