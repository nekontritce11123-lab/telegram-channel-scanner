"""
Unified Channel Analyzer v93.0 (Contact Extraction Edition)

Single-prompt analysis combining all LLM tasks:
1. Contact extraction (username, email, bot link from bio/posts)
2. Category classification (16 categories, strict priority rules)
3. Brand safety & toxicity audit (multi-modal, 4-tier risk)
4. Ad detection (post ID extraction)
5. Audience authenticity check (trust score, bot detection)
6. Russian channel summary (marketplace insight style)
7. Image/visual content analysis (native Gemini vision)

Advantages:
- 1 API call instead of 4-5 (cost savings, latency reduction)
- Gemini's 1M context window handles all data at once
- Native vision eliminates Florence-2 dependency
- Consistent analysis across all dimensions

Usage:
    from scanner.llm.unified_analyzer import unified_analyze, UnifiedAnalysisResult

    result = await unified_analyze(
        chat=chat_info,
        messages=messages,
        comments=comments,
        images=[img_bytes1, img_bytes2]
    )

    print(result.category)      # "CRYPTO"
    print(result.summary_ru)    # "Агрегатор сигналов для криптотрейдинга..."
    print(result.ad_percentage) # 15
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from scanner.utils import clean_text
from scanner.config import MAX_POSTS_FOR_AI, MAX_CHARS_PER_POST, CATEGORIES

from .backend import get_backend, LLMBackendManager
from .client import safe_parse_json

logger = logging.getLogger(__name__)

# Debug flag
DEBUG_UNIFIED = False


# === UNIFIED RESULT DATACLASS ===

@dataclass
class UnifiedAnalysisResult:
    """
    Complete result from unified channel analysis (v93.0).

    All fields have sensible defaults for graceful degradation.
    """
    # v93.0: Contact extraction
    contact_info: Optional[str] = None  # @username, email, or bot link
    contact_type: str = "UNKNOWN"  # USERNAME, EMAIL, BOT, UNKNOWN

    # Category classification
    category: str = "LIFESTYLE"
    category_confidence: int = 80
    category_reasoning: str = ""

    # Brand safety
    is_toxic: bool = False
    toxic_category: Optional[str] = None  # GAMBLING, ADULT, SCAM
    toxic_severity: str = "SAFE"  # CRITICAL, HIGH, MEDIUM, SAFE
    toxic_evidence: List[str] = field(default_factory=list)

    # Ad analysis
    ad_percentage: int = 0
    ad_post_ids: List[int] = field(default_factory=list)

    # Comment analysis
    bot_percentage: int = 0
    trust_score: int = 70
    authenticity_tier: str = "MEDIUM"  # HIGH_QUALITY, MIXED, BOT_FARM → HIGH, MEDIUM, LOW
    comment_signals: List[str] = field(default_factory=list)

    # Channel summary
    summary_ru: str = ""

    # Visual context from images
    image_insights: str = ""
    detected_elements: List[str] = field(default_factory=list)

    # Metadata
    raw_response: str = ""
    parse_warnings: List[str] = field(default_factory=list)

    # Computed fields (set by calculate_impact)
    llm_trust_factor: float = 1.0
    tier: str = "STANDARD"
    tier_cap: int = 85


# === UNIFIED SYSTEM PROMPT ===

UNIFIED_SYSTEM_PROMPT = """You are an Expert Telegram Analyst & Data Miner (v93.0).
Your task is to analyze the provided INPUT DATA (Metadata, Posts, Comments, Images) and return a JSON database record.

## 1. CONTACT EXTRACTION (Crucial)
Scan the "Bio/Description" and "Recent Posts" sections for ANY contact method.
Look for:
- Usernames (@admin, @manager, @..._bot)
- Emails (gmail, proton, mail.ru, yandex)
- Links to contact bots (t.me/SupportBot)
- Direct phone numbers

OUTPUT RULES for `contact_info`:
- If found multiple, prioritize the one marked as "Commercial/Ads/Реклама/Сотрудничество".
- If found email -> return email string.
- If found bot link -> return bot link.
- If found @username -> return @username.
- Return `null` ONLY if absolutely no contact is found.

## 2. CATEGORY CLASSIFICATION
Pick ONE based on Posts content:
[CRYPTO, AI_ML, FINANCE, BUSINESS, TECH, NEWS, LIFESTYLE, ENTERTAINMENT, EDUCATION, HEALTH, BEAUTY, TRAVEL, RETAIL, REAL_ESTATE, GAMBLING, ADULT]

OVERRIDES:
- Mentions of Bybit/Binance/Futures/Tokens/Airdrop = CRYPTO.
- Mentions of ChatGPT/Claude/Midjourney/Neural = AI_ML.
- Personal diary of a founder = LIFESTYLE (not BUSINESS).
- "Buy this gadget/dress" reviews = RETAIL (not TECH).

## 3. SAFETY & SCAM AUDIT (Content + Images)
Analyze Text AND Images. Scammers hide text in images.

RISK TIERS:
- **CRITICAL**: Pure spam, scam, darknet, drugs, hard 18+.
- **HIGH**: Casino ads (1win, Vavada), "Easy Money", Pump & Dump signals.
- **MEDIUM**: Occasional swear words, controversial politics, gray ads.
- **SAFE**: Clean content suitable for top-tier brands.

SAFE CONTEXTS (Do NOT Flag):
- Legitimate Crypto Trading (Binance/Bybit analysis) = SAFE.
- Medical/Educational discussion of sensitive topics = SAFE.

## 4. AD POSTS DETECTION
Identify posts that are clearly paid promotions.

SIGNALS OF ADS:
- Tags: #реклама, #ad, erid, "партнерский пост".
- Sudden shift in tone, aggressive CTA to join another channel.
- Links to betting sites, weird exchanges, cross-promo.

NOT ADS:
- Self-promotion (my course, my other channel).
- Genuine personal recommendations.

## 5. AUDIENCE TRUST ANALYSIS
Analyze comments for "Dead Audience" symptoms.

BOT SIGNALS: Generic English on Russian channel ("Good project", "Sir"), repetitive stickers.
REAL SIGNALS: Arguments, questions, technical slang, negativity/debate.

## 6. SUMMARY GENERATION
Draft a concise Russian summary (max 300 chars).
Structure: "[Category context]. [Main value]. [Audience type]."
Example: "Авторский блог про DeFi и дропхантинг. Публикует гайды по тестнетам. Аудитория — опытные криптаны."

---
## OUTPUT FORMAT (JSON ONLY)
Return ONLY raw JSON. No markdown blocks.

{
  "meta_data": {
    "contact_info": "@manager_username",
    "contact_type": "USERNAME"
  },
  "classification": {
    "category": "CRYPTO",
    "category_reasoning": "Mentions Binance, futures trading"
  },
  "safety": {
    "status": "SAFE",
    "is_scam": false,
    "flags": []
  },
  "ad_analysis": {
    "ad_post_ids": [3, 7]
  },
  "audience": {
    "trust_score": 85,
    "verdict": "HIGH_QUALITY"
  },
  "ui_content": {
    "summary_ru": "Авторский блог про DeFi..."
  }
}"""


# === DATA PREPARATION ===

def _prepare_posts_text(messages: list, max_posts: int = MAX_POSTS_FOR_AI) -> tuple[str, int]:
    """
    Prepare posts text for analysis.

    Returns:
        Tuple of (formatted_text, post_count)
    """
    posts = []
    for i, msg in enumerate(messages[:max_posts]):
        text = ""
        if hasattr(msg, 'message') and msg.message:
            text = msg.message
        elif hasattr(msg, 'text') and msg.text:
            text = msg.text

        if text:
            clean = clean_text(text)[:MAX_CHARS_PER_POST]
            if clean and len(clean) > 20:
                posts.append(f"[Post {i+1}]: {clean}")

    return "\n\n".join(posts), len(posts)


def _prepare_comments_text(comments: list, max_comments: int = 100) -> tuple[str, int]:
    """
    Prepare comments text for analysis.

    Returns:
        Tuple of (formatted_text, comment_count)
    """
    texts = []
    for i, comment in enumerate(comments[:max_comments]):
        text = ""
        if hasattr(comment, 'message') and comment.message:
            text = comment.message
        elif hasattr(comment, 'text') and comment.text:
            text = comment.text
        elif isinstance(comment, str):
            text = comment

        if text:
            clean = clean_text(text)[:200]
            if clean and len(clean) > 5:
                texts.append(f"[{i+1}]: {clean}")

    return "\n".join(texts), len(texts)


def _build_user_message(
    chat: Any,
    messages: list,
    comments: list,
    has_images: bool = False
) -> str:
    """
    Build the user message with all channel data (v93.0 format).

    Structured format for reliable contact extraction.
    """
    parts = []

    # Channel info
    title = getattr(chat, 'title', '') or ''
    description = getattr(chat, 'description', '') or ''
    username = getattr(chat, 'username', '') or ''
    members = getattr(chat, 'participants_count', 0) or 0

    # v93.0: Structured metadata block
    parts.append("=== CHANNEL METADATA ===")
    parts.append(f"Title: {title}")
    parts.append(f"Username: @{username}" if username else "Username: N/A")
    parts.append(f"Bio/Description: {clean_text(description)[:600]}")  # <-- Contact extraction source
    parts.append(f"Members: {members:,}" if members else "Members: Unknown")

    # Posts with numbered indices for ad_post_ids
    posts_text, post_count = _prepare_posts_text(messages)
    if posts_text:
        parts.append(f"\n=== RECENT POSTS (Last {post_count}) ===")
        parts.append(posts_text[:12000])

    # Comments
    comments_text, comment_count = _prepare_comments_text(comments)
    if comments_text:
        parts.append(f"\n=== COMMENTS SAMPLE ({comment_count}) ===")
        parts.append(comments_text[:4000])
    else:
        parts.append("\n=== COMMENTS SAMPLE ===")
        parts.append("No comments available for analysis.")

    # Image note
    if has_images:
        parts.append("\n=== IMAGES ===")
        parts.append("Channel images attached. Analyze for scam text, casino logos, watermarks.")

    parts.append("\n=== INSTRUCTION ===")
    parts.append("Analyze the data above according to your System Prompt v93.0. Return JSON.")

    return "\n".join(parts)


# === RESPONSE PARSING ===

def _parse_unified_response(response: str, total_posts: int = 30) -> tuple[Dict[str, Any], List[str]]:
    """
    Parse the unified JSON response with fallbacks (v93.0 format).

    Args:
        response: Raw JSON response from LLM
        total_posts: Total number of posts (for ad_percentage calculation)

    Returns:
        Tuple of (parsed_data, warnings)
    """
    # v93.0: New nested structure
    default_values = {
        "meta_data": {
            "contact_info": None,
            "contact_type": "UNKNOWN"
        },
        "classification": {
            "category": "LIFESTYLE",
            "category_reasoning": ""
        },
        "safety": {
            "status": "SAFE",
            "is_scam": False,
            "flags": []
        },
        "ad_analysis": {
            "ad_post_ids": []
        },
        "audience": {
            "trust_score": 70,
            "verdict": "MIXED"
        },
        "ui_content": {
            "summary_ru": ""
        }
    }

    data, warnings = safe_parse_json(response, default_values)

    # v93.0: Extract category from nested structure
    classification = data.get("classification", {})
    category = classification.get("category", "LIFESTYLE")
    if category not in CATEGORIES:
        warnings.append(f"Invalid category '{category}', defaulting to LIFESTYLE")
        category = "LIFESTYLE"
    data["_category"] = category
    data["_category_reasoning"] = classification.get("category_reasoning", "")

    # v93.0: Extract contact info
    meta_data = data.get("meta_data", {})
    data["_contact_info"] = meta_data.get("contact_info")
    data["_contact_type"] = meta_data.get("contact_type", "UNKNOWN")

    # v93.0: Calculate ad_percentage from ad_post_ids
    ad_post_ids = data.get("ad_analysis", {}).get("ad_post_ids", [])
    if total_posts > 0 and ad_post_ids:
        data["_calculated_ad_percentage"] = int(len(ad_post_ids) / total_posts * 100)
    else:
        data["_calculated_ad_percentage"] = 0

    return data, warnings


def _result_from_parsed(data: Dict[str, Any], warnings: List[str], raw: str) -> UnifiedAnalysisResult:
    """Convert parsed data to UnifiedAnalysisResult (v93.0 format)."""
    safety = data.get("safety", {})
    ad_analysis = data.get("ad_analysis", {})
    audience = data.get("audience", {})
    ui_content = data.get("ui_content", {})

    # v93.0: Map safety status to is_toxic and severity
    status = safety.get("status", "SAFE")
    is_toxic = status in ("CRITICAL", "HIGH") or safety.get("is_scam", False)
    toxic_severity = status  # CRITICAL/HIGH/MEDIUM/SAFE

    # v93.0: Extract toxic_category from flags
    flags = safety.get("flags", [])
    toxic_category = None
    if flags:
        first_flag = flags[0].upper() if flags else ""
        if "CASINO" in first_flag or "GAMBLING" in first_flag or "1WIN" in first_flag or "VAVADA" in first_flag:
            toxic_category = "GAMBLING"
        elif "ADULT" in first_flag or "18+" in first_flag or "PORN" in first_flag or "NSFW" in first_flag:
            toxic_category = "ADULT"
        elif "SCAM" in first_flag or "DARKNET" in first_flag or "DRUG" in first_flag or "FAKE" in first_flag:
            toxic_category = "SCAM"

    # v93.0: Map trust_score to bot_percentage (inverted)
    trust_score = int(audience.get("trust_score", 70))
    bot_percentage = max(0, 100 - trust_score)

    # v93.0: Map verdict to authenticity_tier
    verdict = audience.get("verdict", "MIXED")
    tier_map = {"HIGH_QUALITY": "HIGH", "MIXED": "MEDIUM", "BOT_FARM": "LOW"}
    authenticity_tier = tier_map.get(verdict, "MEDIUM")

    # v93.0: Use calculated ad_percentage
    ad_percentage = data.get("_calculated_ad_percentage", 0)

    return UnifiedAnalysisResult(
        # v93.0: Contact extraction
        contact_info=data.get("_contact_info"),
        contact_type=data.get("_contact_type", "UNKNOWN"),

        # Category (from pre-processed fields)
        category=data.get("_category", "LIFESTYLE"),
        category_confidence=80,
        category_reasoning=data.get("_category_reasoning", ""),

        # Brand safety
        is_toxic=is_toxic,
        toxic_category=toxic_category,
        toxic_severity=toxic_severity,
        toxic_evidence=flags[:5],

        # Ad analysis
        ad_percentage=ad_percentage,
        ad_post_ids=ad_analysis.get("ad_post_ids", []),

        # Audience quality
        bot_percentage=bot_percentage,
        trust_score=trust_score,
        authenticity_tier=authenticity_tier,
        comment_signals=[],

        # Summary and images
        summary_ru=ui_content.get("summary_ru", ""),
        image_insights="",
        detected_elements=[],

        # Metadata
        raw_response=raw,
        parse_warnings=warnings
    )


# === MAIN ANALYSIS FUNCTION ===

async def unified_analyze(
    chat: Any,
    messages: list,
    comments: list,
    images: Optional[List[bytes]] = None,
    backend: Optional[LLMBackendManager] = None
) -> UnifiedAnalysisResult:
    """
    Perform unified channel analysis with single LLM call.

    Combines category classification, brand safety, ad detection,
    comment analysis, and summary generation in one request.

    Args:
        chat: Pyrogram Chat object with title, description, etc.
        messages: List of channel messages/posts
        comments: List of comments (can be empty)
        images: Optional list of image bytes for vision analysis
        backend: Optional LLMBackendManager (uses default if not provided)

    Returns:
        UnifiedAnalysisResult with all analysis data

    Example:
        result = await unified_analyze(chat, messages, comments, [img1, img2])
        print(f"Category: {result.category}")
        print(f"Ad%: {result.ad_percentage}")
        print(f"Summary: {result.summary_ru}")
    """
    if backend is None:
        backend = get_backend()

    # Build user message
    has_images = images is not None and len(images) > 0
    user_message = _build_user_message(chat, messages, comments, has_images)

    if DEBUG_UNIFIED:
        print(f"\n{'='*60}")
        print(f"UNIFIED ANALYZER - {len(messages)} posts, {len(comments)} comments")
        print(f"Backend: {backend.backend_name} ({backend.model_name})")
        print(f"Images: {len(images) if images else 0}")
        print(f"{'='*60}\n")

    # Call LLM
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: backend.chat(
            UNIFIED_SYSTEM_PROMPT,
            user_message,
            images=images
        )
    )

    if not response.success or not response.content:
        logger.warning(f"Unified analysis failed: {response.error}")
        return UnifiedAnalysisResult(
            parse_warnings=[f"LLM call failed: {response.error}"]
        )

    if DEBUG_UNIFIED:
        print(f"RESPONSE ({len(response.content)} chars):")
        print(response.content[:500])

    # Parse response (v90.0: pass total posts for ad_percentage calculation)
    total_posts = len(messages) if messages else 30
    data, warnings = _parse_unified_response(response.content, total_posts=total_posts)

    if DEBUG_UNIFIED and warnings:
        print(f"PARSE WARNINGS: {warnings}")

    result = _result_from_parsed(data, warnings, response.content)

    # Log summary
    logger.info(
        f"Unified analysis: {result.category} "
        f"(ad={result.ad_percentage}%, bot={result.bot_percentage}%, "
        f"toxic={result.is_toxic})"
    )

    return result


def unified_analyze_sync(
    chat: Any,
    messages: list,
    comments: list,
    images: Optional[List[bytes]] = None,
    backend: Optional[LLMBackendManager] = None
) -> UnifiedAnalysisResult:
    """
    Synchronous wrapper for unified_analyze.

    Use this when running outside of an async context.
    """
    return asyncio.run(unified_analyze(chat, messages, comments, images, backend))
