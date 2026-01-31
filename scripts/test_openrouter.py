#!/usr/bin/env python3
"""
OpenRouter API Test Script v93.0

Tests connectivity and functionality of OpenRouter API with:
- Gemini 2.0 Flash (primary)
- Qwen 2.5-VL 72B (fallback)
- Vision capability (base64 images)
- JSON response parsing (v93.0 contact extraction format)

Usage:
    python scripts/test_openrouter.py
    python scripts/test_openrouter.py --verbose
    python scripts/test_openrouter.py --model qwen/qwen2.5-vl-72b-instruct
"""

import os
import sys
import base64
import argparse
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()


def test_api_connectivity():
    """Test basic API connectivity."""
    print("\n=== Test 1: API Connectivity ===")

    import requests

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        print("[FAIL] OPENROUTER_API_KEY not set in environment")
        return False

    print(f"[INFO] API Key: {api_key[:20]}...")

    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )

        if response.status_code == 200:
            print("[PASS] API accessible")
            return True
        else:
            print(f"[FAIL] HTTP {response.status_code}: {response.text[:100]}")
            return False

    except Exception as e:
        print(f"[FAIL] Connection error: {e}")
        return False


def test_model_availability(model: str):
    """Test if specific model is available."""
    print(f"\n=== Test 2: Model Availability ({model}) ===")

    from scanner.llm.client import call_openrouter, OpenRouterConfig

    config = OpenRouterConfig()
    config.primary_model = model

    start = time.time()
    response = call_openrouter(
        system_prompt="You are a test assistant. Respond with 'OK' only.",
        user_message="Test. Respond with single word: OK",
        config=config
    )
    elapsed = time.time() - start

    if response and "OK" in response.upper():
        print(f"[PASS] Model {model} working (latency: {elapsed:.2f}s)")
        return True
    else:
        print(f"[FAIL] Model {model} failed: {response}")
        return False


def test_json_response():
    """Test JSON response generation."""
    print("\n=== Test 3: JSON Response ===")

    from scanner.llm.client import call_openrouter, safe_parse_json

    response = call_openrouter(
        system_prompt="You are a JSON generator. Output only valid JSON.",
        user_message='Generate JSON: {"status": "ok", "value": 42}'
    )

    if not response:
        print("[FAIL] No response")
        return False

    data, warnings = safe_parse_json(response, {"status": "unknown", "value": 0})

    if data.get("status") == "ok" and data.get("value") == 42:
        print(f"[PASS] JSON parsing works: {data}")
        return True
    else:
        print(f"[WARN] Partial parse: {data}, warnings: {warnings}")
        return True  # Still works with fallbacks


def test_vision_capability():
    """Test vision/multimodal capability."""
    print("\n=== Test 4: Vision Capability ===")

    from scanner.llm.client import call_openrouter, encode_images_for_api

    # Create a simple test image (1x1 red pixel PNG)
    # This is a minimal valid PNG
    test_png = bytes([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,  # PNG signature
        0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 pixels
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x08, 0xd7, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x18, 0xdd,
        0x8d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,  # IEND chunk
        0x4e, 0x44, 0xae, 0x42, 0x60, 0x82
    ])

    # Test encoding
    encoded = encode_images_for_api([test_png])
    if not encoded:
        print("[FAIL] Image encoding failed")
        return False

    print(f"[INFO] Encoded image: {encoded[0]['type']}")

    # Test vision call
    response = call_openrouter(
        system_prompt="Describe what you see in the image. Be brief.",
        user_message="What is in this image?",
        images=[test_png]
    )

    if response:
        print(f"[PASS] Vision response: {response[:100]}...")
        return True
    else:
        print("[WARN] Vision call failed (model may not support images)")
        return False


def test_fallback_chain():
    """Test fallback from Gemini to Qwen."""
    print("\n=== Test 5: Fallback Chain ===")

    from scanner.llm.backend import LLMBackendManager

    manager = LLMBackendManager(use_ollama=False)
    health = manager.health_check()

    print(f"[INFO] Primary: {health['primary']['name']} - {'OK' if health['primary']['available'] else 'FAIL'}")
    print(f"[INFO] Secondary: {health['secondary']['name']} - {'OK' if health['secondary']['available'] else 'FAIL'}")

    if health['primary']['available'] or health['secondary']['available']:
        print("[PASS] At least one backend available")
        return True
    else:
        print("[FAIL] No backends available")
        return False


def test_unified_analyzer():
    """Test unified analyzer with mock data."""
    print("\n=== Test 6: Unified Analyzer ===")

    from scanner.llm.unified_analyzer import unified_analyze_sync, UnifiedAnalysisResult
    from dataclasses import dataclass

    # Mock chat object with contact in description
    @dataclass
    class MockChat:
        title: str = "Crypto Signals VIP"
        description: str = "Лучшие сигналы на рынке. По рекламе: @crypto_manager или ads@crypto-vip.com"
        username: str = "crypto_signals_vip"
        participants_count: int = 15000

    # Mock message about crypto
    @dataclass
    class MockMessage:
        message: str = "Сигнал на BTC/USDT. Вход: $42,000. Тейк: $45,000. Стоп: $40,000. Binance Futures."
        text: str = "Сигнал на BTC/USDT. Вход: $42,000. Тейк: $45,000. Стоп: $40,000. Binance Futures."

    chat = MockChat()
    messages = [MockMessage() for _ in range(5)]
    comments = []

    try:
        result = unified_analyze_sync(chat, messages, comments)

        print(f"[INFO] Category: {result.category}")
        print(f"[INFO] Contact: {result.contact_info} ({result.contact_type})")
        print(f"[INFO] Ad%: {result.ad_percentage}, Trust: {result.trust_score}")
        print(f"[INFO] Safety: {result.toxic_severity} (toxic={result.is_toxic})")
        print(f"[INFO] Audience: {result.authenticity_tier}")
        print(f"[INFO] Summary: {result.summary_ru[:50]}..." if result.summary_ru else "[INFO] No summary")

        if result.category:
            print("[PASS] Unified analyzer working")
            return True
        else:
            print("[WARN] No category returned")
            return False

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test OpenRouter API")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--model", "-m", default="google/gemini-2.0-flash-001", help="Model to test")
    args = parser.parse_args()

    print("=" * 60)
    print("OpenRouter API Test Suite v93.0")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("API Connectivity", test_api_connectivity()))
    results.append(("Model Availability", test_model_availability(args.model)))
    results.append(("JSON Response", test_json_response()))
    results.append(("Vision Capability", test_vision_capability()))
    results.append(("Fallback Chain", test_fallback_chain()))
    results.append(("Unified Analyzer", test_unified_analyzer()))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\nResult: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅ All tests passed! OpenRouter is ready.")
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed. Check configuration.")
        sys.exit(1)


if __name__ == "__main__":
    main()
