"""
LLM Backend Manager v88.0

Unified abstraction for Ollama (local) and OpenRouter (cloud) backends.
Provides automatic fallback, health checks, and consistent interface.

Usage:
    from scanner.llm.backend import get_backend, LLMBackendManager

    # Auto-select based on USE_OLLAMA config
    backend = get_backend()
    response = backend.chat("You are helpful.", "Hello!", images=[img_bytes])

    # Force specific backend
    backend = get_backend(use_ollama=True)
"""

from dataclasses import dataclass
from typing import Optional, List, Any
from abc import ABC, abstractmethod

from scanner.config import (
    USE_OLLAMA,
    OLLAMA_MODEL,
    OPENROUTER_PRIMARY_MODEL,
    OPENROUTER_FALLBACK_MODEL,
    LLM_FALLBACK_ENABLED,
    LLM_FALLBACK_THRESHOLD,
)
from .client import (
    call_ollama,
    call_openrouter,
    OllamaConfig,
    OpenRouterConfig,
)


@dataclass
class LLMResponse:
    """Standardized response from any LLM backend."""
    content: Optional[str]
    model: str
    backend: str  # "ollama" or "openrouter"
    success: bool
    error: Optional[str] = None


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""
        pass

    @property
    @abstractmethod
    def model(self) -> str:
        """Current model name."""
        pass

    @abstractmethod
    def chat(
        self,
        system_prompt: str,
        user_message: str,
        images: Optional[List[bytes]] = None
    ) -> LLMResponse:
        """Send a chat request to the backend."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available."""
        pass


class OllamaBackend(LLMBackend):
    """Ollama local backend."""

    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self.config.model

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        images: Optional[List[bytes]] = None
    ) -> LLMResponse:
        # Note: Ollama vision requires different API, simplified here
        # For now, ignore images with Ollama (use OpenRouter for vision)
        if images:
            print("OLLAMA: Vision not supported, ignoring images")

        content = call_ollama(system_prompt, user_message, config=self.config)

        return LLMResponse(
            content=content,
            model=self.model,
            backend=self.name,
            success=content is not None,
            error=None if content else "Ollama request failed"
        )

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


class OpenRouterBackend(LLMBackend):
    """OpenRouter cloud backend with Gemini/Qwen support."""

    def __init__(self, config: Optional[OpenRouterConfig] = None):
        self.config = config or OpenRouterConfig()
        self._current_model = self.config.primary_model

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def model(self) -> str:
        return self._current_model

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        images: Optional[List[bytes]] = None
    ) -> LLMResponse:
        content = call_openrouter(
            system_prompt,
            user_message,
            images=images,
            config=self.config
        )

        return LLMResponse(
            content=content,
            model=self.model,
            backend=self.name,
            success=content is not None,
            error=None if content else "OpenRouter request failed"
        )

    def is_available(self) -> bool:
        """Check if OpenRouter API is accessible."""
        if not self.config.api_key:
            return False
        try:
            import requests
            response = requests.get(
                f"{self.config.base_url}/models",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=10
            )
            return response.status_code == 200
        except Exception:
            return False


class LLMBackendManager:
    """
    Manages LLM backends with automatic fallback.

    Primary backend is determined by USE_OLLAMA config:
    - USE_OLLAMA=true: Ollama primary, OpenRouter fallback
    - USE_OLLAMA=false: OpenRouter primary, Ollama fallback

    Automatically switches to secondary backend after consecutive failures.
    """

    def __init__(
        self,
        use_ollama: Optional[bool] = None,
        fallback_enabled: bool = LLM_FALLBACK_ENABLED,
        fallback_threshold: int = LLM_FALLBACK_THRESHOLD
    ):
        if use_ollama is None:
            use_ollama = USE_OLLAMA

        self._use_ollama = use_ollama
        self._fallback_enabled = fallback_enabled
        self._fallback_threshold = fallback_threshold

        # Initialize backends
        if use_ollama:
            self._primary = OllamaBackend()
            self._secondary = OpenRouterBackend()
        else:
            self._primary = OpenRouterBackend()
            self._secondary = OllamaBackend()

        self._consecutive_failures = 0
        self._in_fallback_mode = False

    @property
    def current_backend(self) -> LLMBackend:
        """Get the currently active backend."""
        if self._in_fallback_mode:
            return self._secondary
        return self._primary

    @property
    def backend_name(self) -> str:
        """Get the name of the current backend."""
        return self.current_backend.name

    @property
    def model_name(self) -> str:
        """Get the current model name."""
        return self.current_backend.model

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        images: Optional[List[bytes]] = None
    ) -> LLMResponse:
        """
        Send a chat request with automatic fallback.

        Args:
            system_prompt: System message
            user_message: User message
            images: Optional images for vision analysis

        Returns:
            LLMResponse with content and metadata
        """
        # Try current backend
        backend = self.current_backend
        response = backend.chat(system_prompt, user_message, images)

        if response.success:
            self._consecutive_failures = 0
            return response

        # Handle failure
        self._consecutive_failures += 1

        # Check if we should fallback
        if (self._fallback_enabled and
            not self._in_fallback_mode and
            self._consecutive_failures >= self._fallback_threshold):

            print(f"LLM: {self._consecutive_failures} failures, switching to {self._secondary.name}")
            self._in_fallback_mode = True
            self._consecutive_failures = 0

            # Try secondary backend
            response = self._secondary.chat(system_prompt, user_message, images)
            if response.success:
                return response

        return response

    def reset_fallback(self):
        """Reset to primary backend."""
        self._in_fallback_mode = False
        self._consecutive_failures = 0

    def health_check(self) -> dict:
        """Check health of all backends."""
        return {
            "primary": {
                "name": self._primary.name,
                "model": self._primary.model,
                "available": self._primary.is_available()
            },
            "secondary": {
                "name": self._secondary.name,
                "model": self._secondary.model,
                "available": self._secondary.is_available()
            },
            "current": self.backend_name,
            "in_fallback": self._in_fallback_mode,
            "consecutive_failures": self._consecutive_failures
        }


# === MODULE-LEVEL SINGLETON ===

_backend_manager: Optional[LLMBackendManager] = None


def get_backend(use_ollama: Optional[bool] = None) -> LLMBackendManager:
    """
    Get or create the global backend manager.

    Args:
        use_ollama: Force Ollama (True) or OpenRouter (False).
                   If None, uses USE_OLLAMA config.

    Returns:
        LLMBackendManager instance
    """
    global _backend_manager

    # If forcing a specific backend, create new manager
    if use_ollama is not None:
        return LLMBackendManager(use_ollama=use_ollama)

    # Return singleton
    if _backend_manager is None:
        _backend_manager = LLMBackendManager()

    return _backend_manager


def reset_backend():
    """Reset the global backend manager."""
    global _backend_manager
    _backend_manager = None
