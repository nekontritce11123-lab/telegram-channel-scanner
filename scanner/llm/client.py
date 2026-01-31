"""
Unified LLM client utilities v2.0 (OpenRouter + Ollama)

Extracted from llm_analyzer.py for reuse across scanner modules.

Contains:
- OllamaConfig: Dataclass for Ollama configuration
- OpenRouterConfig: Dataclass for OpenRouter configuration
- call_ollama(): Make requests to Ollama API with retry logic
- call_openrouter(): Make requests to OpenRouter API (Gemini/Qwen)
- encode_images_for_api(): Convert images to base64 for multimodal API
- safe_parse_json(): Multi-level JSON parsing with fallbacks
- fill_defaults(): Fill missing fields with default values
- regex_extract_fields(): Level 3 fallback for JSON extraction

Usage:
    from scanner.llm.client import call_ollama, call_openrouter, safe_parse_json

    # Local Ollama
    response = call_ollama(system_prompt, user_message)

    # OpenRouter (Gemini 2.0 Flash with Qwen fallback)
    response = call_openrouter(system_prompt, user_message, images=[img_bytes])

    data, warnings = safe_parse_json(response, default_values)
"""

import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple, List
from io import BytesIO

import requests

from scanner.config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    # OpenRouter config
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_PRIMARY_MODEL,
    OPENROUTER_FALLBACK_MODEL,
    OPENROUTER_TIMEOUT,
    LLM_FALLBACK_ENABLED,
    LLM_FALLBACK_THRESHOLD,
)


# === JSON REPAIR LIBRARY ===
try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    repair_json = None  # type: ignore


# === CONFIGURATION ===

@dataclass
class OllamaConfig:
    """
    Configuration for Ollama API requests.

    Useful for customizing behavior per-request while keeping defaults.
    """
    url: str = OLLAMA_URL
    model: str = OLLAMA_MODEL
    timeout: int = OLLAMA_TIMEOUT
    max_retries: int = MAX_RETRIES
    retry_delay: int = RETRY_DELAY
    temperature: float = 0.3
    num_predict: int = 500
    keep_alive: int = -1  # -1 = never unload model from memory
    think: bool = False   # Disable thinking for faster responses


@dataclass
class OpenRouterConfig:
    """
    Configuration for OpenRouter API requests (v88.0).

    Supports Gemini 2.0 Flash as primary, Qwen 2.5-VL as fallback.
    """
    api_key: str = OPENROUTER_API_KEY
    base_url: str = OPENROUTER_BASE_URL
    primary_model: str = OPENROUTER_PRIMARY_MODEL
    fallback_model: str = OPENROUTER_FALLBACK_MODEL
    timeout: int = OPENROUTER_TIMEOUT
    max_retries: int = MAX_RETRIES
    retry_delay: int = RETRY_DELAY
    temperature: float = 0.3
    max_tokens: int = 2048
    fallback_enabled: bool = LLM_FALLBACK_ENABLED
    fallback_threshold: int = LLM_FALLBACK_THRESHOLD


# === OLLAMA API ===

def call_ollama(
    system_prompt: str,
    user_message: str,
    retry_count: int = 0,
    config: Optional[OllamaConfig] = None
) -> Optional[str]:
    """
    Make a request to Ollama API with retry logic.

    Args:
        system_prompt: System message defining the assistant's behavior
        user_message: User's input message
        retry_count: Current retry attempt (internal use)
        config: Optional OllamaConfig for custom settings

    Returns:
        str: Response content from Ollama, or None on failure

    Example:
        response = call_ollama(
            "You are a helpful assistant.",
            "What is 2+2?"
        )
    """
    if config is None:
        config = OllamaConfig()

    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "stream": False,
        "think": config.think,
        "keep_alive": config.keep_alive,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.num_predict
        }
    }

    try:
        response = requests.post(config.url, json=payload, timeout=config.timeout)
        if response.status_code != 200:
            print(f"OLLAMA: HTTP {response.status_code}")
            return None

        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        return content

    except requests.exceptions.ConnectionError:
        print("OLLAMA: Not running! Start with: ollama serve")
        return None
    except requests.exceptions.Timeout:
        if retry_count < config.max_retries:
            wait = config.retry_delay * (retry_count + 1)
            print(f"OLLAMA: Timeout, retry {retry_count + 1}/{config.max_retries} in {wait}s...")
            time.sleep(wait)
            return call_ollama(system_prompt, user_message, retry_count + 1, config)
        print(f"OLLAMA: Timeout after {config.max_retries} attempts!")
        return None
    except (KeyError, TypeError, ValueError) as e:
        # KeyError: unexpected JSON response structure
        # TypeError/ValueError: data conversion errors
        print(f"OLLAMA: Response processing error - {e}")
        return None


# === OPENROUTER API (v88.0) ===

def detect_mime_type(img_bytes: bytes) -> str:
    """Detect image MIME type from bytes header."""
    if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if img_bytes[:2] == b'\xff\xd8':
        return "image/jpeg"
    if img_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    if img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"  # Default fallback


def compress_image(img_bytes: bytes, max_size: int = 1024, quality: int = 85) -> bytes:
    """
    Compress image to reduce API payload size.

    Args:
        img_bytes: Original image bytes
        max_size: Maximum dimension (width or height)
        quality: JPEG quality (1-100)

    Returns:
        Compressed image bytes
    """
    try:
        from PIL import Image

        img = Image.open(BytesIO(img_bytes))

        # Convert to RGB if needed (for JPEG compression)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Resize if too large
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # Compress to JPEG
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        return buffer.getvalue()

    except ImportError:
        # PIL not available, return original
        return img_bytes
    except Exception:
        # Any error, return original
        return img_bytes


def encode_images_for_api(images: List[bytes], compress: bool = True) -> List[Dict[str, Any]]:
    """
    Convert image bytes to OpenAI-compatible multimodal format.

    Args:
        images: List of image bytes
        compress: Whether to compress images (default True)

    Returns:
        List of content blocks for multimodal API

    Example:
        >>> images = [open("photo.jpg", "rb").read()]
        >>> content = encode_images_for_api(images)
        >>> # Returns: [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]
    """
    result = []
    for img_bytes in images:
        if compress:
            img_bytes = compress_image(img_bytes)

        mime_type = detect_mime_type(img_bytes)
        b64 = base64.b64encode(img_bytes).decode('utf-8')

        result.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{b64}"}
        })

    return result


# Track consecutive failures for fallback logic
_openrouter_failures: Dict[str, int] = {}


def call_openrouter(
    system_prompt: str,
    user_message: str,
    images: Optional[List[bytes]] = None,
    retry_count: int = 0,
    config: Optional[OpenRouterConfig] = None,
    _use_fallback: bool = False
) -> Optional[str]:
    """
    Make a request to OpenRouter API with automatic fallback.

    Supports multimodal input (text + images) for Gemini 2.0 Flash and Qwen 2.5-VL.
    Automatically falls back to secondary model after consecutive failures.

    Args:
        system_prompt: System message defining the assistant's behavior
        user_message: User's input message
        images: Optional list of image bytes for vision analysis
        retry_count: Current retry attempt (internal use)
        config: Optional OpenRouterConfig for custom settings
        _use_fallback: Internal flag to use fallback model

    Returns:
        str: Response content from API, or None on failure

    Example:
        # Text only
        response = call_openrouter(
            "You are a helpful assistant.",
            "What is 2+2?"
        )

        # With images (vision)
        with open("chart.png", "rb") as f:
            img = f.read()
        response = call_openrouter(
            "Analyze this trading chart.",
            "What patterns do you see?",
            images=[img]
        )
    """
    if config is None:
        config = OpenRouterConfig()

    if not config.api_key:
        print("OPENROUTER: API key not configured! Set OPENROUTER_API_KEY env var.")
        return None

    # Select model (primary or fallback)
    model = config.fallback_model if _use_fallback else config.primary_model

    # Build messages with multimodal content
    user_content: List[Any] = [{"type": "text", "text": user_message}]

    if images:
        image_content = encode_images_for_api(images)
        user_content.extend(image_content)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/scanner",  # Required by OpenRouter
        "X-Title": "TelegramScanner"
    }

    try:
        response = requests.post(
            f"{config.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.timeout
        )

        # Handle rate limiting
        if response.status_code == 429:
            if retry_count < config.max_retries:
                wait = config.retry_delay * (retry_count + 1)
                print(f"OPENROUTER: Rate limited, retry {retry_count + 1}/{config.max_retries} in {wait}s...")
                time.sleep(wait)
                return call_openrouter(system_prompt, user_message, images, retry_count + 1, config, _use_fallback)

            # Try fallback model
            if config.fallback_enabled and not _use_fallback:
                print(f"OPENROUTER: Switching to fallback model: {config.fallback_model}")
                return call_openrouter(system_prompt, user_message, images, 0, config, _use_fallback=True)

            print(f"OPENROUTER: Rate limited after {config.max_retries} attempts!")
            return None

        if response.status_code != 200:
            error_msg = response.text[:200] if response.text else "Unknown error"
            print(f"OPENROUTER: HTTP {response.status_code} - {error_msg}")

            # Try fallback on server errors
            if response.status_code >= 500 and config.fallback_enabled and not _use_fallback:
                print(f"OPENROUTER: Server error, trying fallback model...")
                return call_openrouter(system_prompt, user_message, images, 0, config, _use_fallback=True)

            return None

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        # Reset failure counter on success
        _openrouter_failures[model] = 0

        return content

    except requests.exceptions.ConnectionError:
        print("OPENROUTER: Connection error! Check internet connectivity.")
        return None
    except requests.exceptions.Timeout:
        _openrouter_failures[model] = _openrouter_failures.get(model, 0) + 1

        if retry_count < config.max_retries:
            wait = config.retry_delay * (retry_count + 1)
            print(f"OPENROUTER: Timeout, retry {retry_count + 1}/{config.max_retries} in {wait}s...")
            time.sleep(wait)
            return call_openrouter(system_prompt, user_message, images, retry_count + 1, config, _use_fallback)

        # Try fallback after threshold failures
        if (config.fallback_enabled and not _use_fallback and
            _openrouter_failures.get(model, 0) >= config.fallback_threshold):
            print(f"OPENROUTER: {config.fallback_threshold} consecutive failures, switching to fallback...")
            return call_openrouter(system_prompt, user_message, images, 0, config, _use_fallback=True)

        print(f"OPENROUTER: Timeout after {config.max_retries} attempts!")
        return None
    except (KeyError, TypeError, ValueError) as e:
        print(f"OPENROUTER: Response processing error - {e}")
        return None


# === JSON PARSING ===

def safe_parse_json(response: str, default_values: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[str]]:
    """
    Multi-level JSON parsing with fallbacks for LLM responses.

    Levels:
    1. Direct json.loads (find JSON object in text)
    2. json_repair library (fix trailing commas, etc.)
    3. Regex extraction of known fields

    Args:
        response: Raw text response from LLM
        default_values: Default values for missing fields

    Returns:
        Tuple of (parsed_data, warnings_list)

    Example:
        data, warnings = safe_parse_json(
            '{"score": 85, "verdict": "GOOD"}',
            {"score": 0, "verdict": "UNKNOWN"}
        )
    """
    warnings: List[str] = []

    if not response or not response.strip():
        warnings.append("Empty response from LLM")
        return default_values or {}, warnings

    # Level 1: Find and parse JSON object
    try:
        # Find balanced braces
        start_idx = response.find('{')
        if start_idx != -1:
            depth = 0
            end_idx = start_idx
            for i, char in enumerate(response[start_idx:], start_idx):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break

            json_candidate = response[start_idx:end_idx]
            data = json.loads(json_candidate)
            warnings.append("L1: Direct JSON parse succeeded")
            return fill_defaults(data, default_values), warnings
    except json.JSONDecodeError as e:
        warnings.append(f"L1: JSON decode error - {e.msg}")
    except (IndexError, KeyError) as e:
        # IndexError: when working with response indices
        # KeyError: when accessing dict keys
        warnings.append(f"L1: Parse error - {e}")

    # Level 2: json_repair library
    if HAS_JSON_REPAIR and repair_json is not None:
        try:
            repaired = repair_json(response)
            if repaired:
                data = json.loads(repaired)
                warnings.append("L2: json_repair succeeded")
                return fill_defaults(data, default_values), warnings
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # json_repair may return invalid JSON or crash
            warnings.append(f"L2: json_repair failed - {e}")
    else:
        warnings.append("L2: json_repair not installed, skipping")

    # Level 3: Regex extraction
    try:
        data = regex_extract_fields(response)
        if data:
            warnings.append(f"L3: Regex extracted {len(data)} fields")
            return fill_defaults(data, default_values), warnings
    except (re.error, TypeError, AttributeError) as e:
        # re.error: regex error, TypeError/AttributeError: wrong data type
        warnings.append(f"L3: Regex extraction failed - {e}")

    warnings.append("FAILED: All parsing levels exhausted")
    return default_values or {}, warnings


def fill_defaults(data: Dict[str, Any], default_values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fill missing fields with default values.

    Args:
        data: Parsed data dictionary
        default_values: Default values to fill in

    Returns:
        Data dictionary with defaults filled in
    """
    if not default_values:
        return data

    for key, default in default_values.items():
        if key not in data or data[key] is None:
            data[key] = default

    return data


def regex_extract_fields(response: str) -> Optional[Dict[str, Any]]:
    """
    Level 3 fallback: Extract fields via regex patterns.

    Used when JSON parsing fails completely.
    Supports common LLM response fields.

    Args:
        response: Raw text response

    Returns:
        Extracted fields as dict, or None if nothing found
    """
    patterns = {
        "toxicity": r'"?toxicity"?\s*[:\s]+(\d+)',
        "violence": r'"?violence"?\s*[:\s]+(\d+)',
        "military_conflict": r'"?military_conflict"?\s*[:\s]+(\d+)',
        "political_quantity": r'"?political_quantity"?\s*[:\s]+(\d+)',
        "political_risk": r'"?political_risk"?\s*[:\s]+(\d+)',
        "misinformation": r'"?misinformation"?\s*[:\s]+(\d+)',
        "ad_percentage": r'"?ad_percentage"?\s*[:\s]+(\d+)',
        "bot_percentage": r'"?bot_percentage"?\s*[:\s]+(\d+)',
        "trust_score": r'"?trust_score"?\s*[:\s]+(\d+)',
        "score": r'"?score"?\s*[:\s]+(\d+)',
        "confidence": r'"?confidence"?\s*[:\s]+(\d+)',
    }

    data: Dict[str, Any] = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            try:
                data[field] = int(match.group(1))
            except ValueError:
                pass

    # Extract red_flags array
    flags_match = re.search(r'"?red_flags"?\s*:\s*\[(.*?)\]', response, re.DOTALL)
    if flags_match:
        content = flags_match.group(1).strip()
        data["red_flags"] = re.findall(r'"([^"]+)"', content) if content else []

    # Extract evidence array
    evidence_match = re.search(r'"?evidence"?\s*:\s*\[(.*?)\]', response, re.DOTALL)
    if evidence_match:
        content = evidence_match.group(1).strip()
        data["evidence"] = re.findall(r'"([^"]+)"', content) if content else []

    # Extract string fields
    string_patterns = {
        "verdict": r'"?verdict"?\s*[:\s]+"?([A-Z_]+)"?',
        "severity": r'"?severity"?\s*[:\s]+"?([A-Z_]+)"?',
        "severity_label": r'"?severity_label"?\s*[:\s]+"?([A-Z_]+)"?',
        "toxic_category": r'"?toxic_category"?\s*[:\s]+"?([A-Z_]+)"?',
        "category": r'"?category"?\s*[:\s]+"?([A-Z_]+)"?',
    }

    for field, pattern in string_patterns.items():
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            value = match.group(1).upper()
            if value not in ('NULL', 'NONE', 'UNDEFINED'):
                data[field] = value

    return data if data else None
