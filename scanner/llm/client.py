"""
Unified Ollama client utilities v1.0

Extracted from llm_analyzer.py for reuse across scanner modules.

Contains:
- OllamaConfig: Dataclass for Ollama configuration
- call_ollama(): Make requests to Ollama API with retry logic
- safe_parse_json(): Multi-level JSON parsing with fallbacks
- fill_defaults(): Fill missing fields with default values
- regex_extract_fields(): Level 3 fallback for JSON extraction

Usage:
    from scanner.llm.client import call_ollama, safe_parse_json

    response = call_ollama(system_prompt, user_message)
    data, warnings = safe_parse_json(response, default_values)
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, List

import requests

from scanner.config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
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
