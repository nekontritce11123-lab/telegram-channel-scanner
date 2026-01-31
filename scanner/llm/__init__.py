"""
scanner.llm - LLM Analysis Subpackage v88.0

Unified module for LLM-based channel analysis.
Supports both local Ollama and cloud OpenRouter (Gemini/Qwen).
"""

# Client utilities
from .client import (
    call_ollama,
    call_openrouter,
    safe_parse_json,
    fill_defaults,
    regex_extract_fields,
    encode_images_for_api,
    OllamaConfig,
    OpenRouterConfig,
)

# Backend manager (v88.0)
from .backend import (
    get_backend,
    reset_backend,
    LLMBackendManager,
    LLMBackend,
    LLMResponse,
    OllamaBackend,
    OpenRouterBackend,
)

# Unified analyzer (v88.0)
from .unified_analyzer import (
    unified_analyze,
    unified_analyze_sync,
    UnifiedAnalysisResult,
)

# Legacy adapter (v88.0)
from .adapter import (
    adapt_unified_to_legacy,
    extract_category,
    extract_summary,
    format_analysis_report,
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
    # Client (v88.0: added OpenRouter)
    'call_ollama', 'call_openrouter', 'safe_parse_json', 'fill_defaults',
    'regex_extract_fields', 'encode_images_for_api', 'OllamaConfig', 'OpenRouterConfig',

    # Backend (v88.0: new)
    'get_backend', 'reset_backend', 'LLMBackendManager', 'LLMBackend',
    'LLMResponse', 'OllamaBackend', 'OpenRouterBackend',

    # Unified Analyzer (v88.0: new)
    'unified_analyze', 'unified_analyze_sync', 'UnifiedAnalysisResult',

    # Legacy Adapter (v88.0: new)
    'adapt_unified_to_legacy', 'extract_category', 'extract_summary', 'format_analysis_report',

    # Analyzer (legacy, kept for compatibility)
    'LLMAnalyzer', 'LLMAnalysisResult', 'PostAnalysisResult', 'CommentAnalysisResult',
    'analyze_brand_safety', 'analyze_comments', 'analyze_ad_percentage', 'infer_channel_type',

    # Classifier (legacy)
    'ChannelClassifier', 'get_classifier', 'parse_category_response',

    # Detector
    'detect_ad_status', 'detect_ad_status_llm', 'detect_ad_status_regex',
    'extract_ad_contacts', 'analyze_private_invites', 'get_ad_status_label',

    # Summarizer
    'generate_channel_summary',
]
