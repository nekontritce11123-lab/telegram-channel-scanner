"""
Унифицированное кэширование для LLM результатов.

v23.0: Вынесено из llm_analyzer.py и classifier.py
v23.1: Унифицирован TTL через config.CACHE_TTL_DAYS
"""
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Any
import logging

from scanner.config import CACHE_TTL_DAYS

logger = logging.getLogger(__name__)


class JSONCache:
    """JSON-based кэш с TTL для LLM результатов."""

    def __init__(self, cache_dir: Path, ttl_days: int = None):
        """
        Args:
            cache_dir: Директория для кэш-файлов
            ttl_days: Время жизни кэша в днях (default: CACHE_TTL_DAYS from config)
        """
        if ttl_days is None:
            ttl_days = CACHE_TTL_DAYS
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(days=ttl_days)

    def _get_cache_path(self, key: str) -> Path:
        """Генерирует путь к файлу кэша по ключу."""
        # Используем hash для безопасных имён файлов
        key_hash = hashlib.md5(key.encode()).hexdigest()[:16]
        return self.cache_dir / f"{key_hash}.json"

    def get(self, key: str) -> Optional[dict]:
        """
        Получить значение из кэша.

        Args:
            key: Ключ (обычно username канала или hash контента)

        Returns:
            dict с данными или None если кэш устарел/не существует
        """
        cache_path = self._get_cache_path(key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Проверяем TTL
            cached_at = datetime.fromisoformat(data.get('_cached_at', '2000-01-01'))
            if datetime.now() - cached_at > self.ttl:
                logger.debug(f"Cache expired for {key}")
                cache_path.unlink()  # Удаляем устаревший
                return None

            return data.get('value')

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Cache read error for {key}: {e}")
            return None

    def set(self, key: str, value: Any) -> None:
        """
        Сохранить значение в кэш.

        Args:
            key: Ключ
            value: Значение (должно быть JSON-serializable)
        """
        cache_path = self._get_cache_path(key)

        data = {
            '_cached_at': datetime.now().isoformat(),
            'value': value
        }

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Cached {key}")
        except (IOError, TypeError) as e:
            logger.warning(f"Cache write error for {key}: {e}")

    def clear_expired(self) -> int:
        """
        Удалить все устаревшие записи.

        Returns:
            Количество удалённых файлов
        """
        removed = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                cached_at = datetime.fromisoformat(data.get('_cached_at', '2000-01-01'))
                if datetime.now() - cached_at > self.ttl:
                    cache_file.unlink()
                    removed += 1
            except Exception as e:
                logger.debug(f"Cache cleanup error for {cache_file}: {e}")

        if removed:
            logger.info(f"Cleared {removed} expired cache entries")
        return removed


# Глобальные экземпляры для удобства
_classification_cache: Optional[JSONCache] = None
_llm_cache: Optional[JSONCache] = None


def get_classification_cache(cache_dir: Path = None) -> JSONCache:
    """Получить кэш для классификации (uses CACHE_TTL_DAYS from config)."""
    global _classification_cache
    if _classification_cache is None:
        if cache_dir is None:
            cache_dir = Path(__file__).parent.parent / '.cache' / 'classification'
        _classification_cache = JSONCache(cache_dir)  # Uses CACHE_TTL_DAYS
    return _classification_cache


def get_llm_cache(cache_dir: Path = None) -> JSONCache:
    """Получить кэш для LLM анализа (uses CACHE_TTL_DAYS from config)."""
    global _llm_cache
    if _llm_cache is None:
        if cache_dir is None:
            cache_dir = Path(__file__).parent.parent / '.cache' / 'llm'
        _llm_cache = JSONCache(cache_dir)  # Uses CACHE_TTL_DAYS
    return _llm_cache
