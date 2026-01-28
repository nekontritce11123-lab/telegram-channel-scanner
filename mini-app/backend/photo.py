"""
photo.py - Изолированный модуль для работы с аватарками Telegram

v67.0: Вынесен из main.py для стабильности.
       Не зависит от других модулей проекта.

Функционал:
- Загрузка аватарок каналов через Bot API
- Загрузка аватарок пользователей через Bot API
- In-memory кэширование с TTL
- Fallback на base64 из БД (legacy)
"""

import os
import re
import time
import base64
from typing import Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$')

# Кэш настройки
_PHOTO_CACHE_MAX = 1000
_PHOTO_CACHE_TTL = 3600  # 1 час

# Кэши (изолированные от main.py)
_channel_photo_cache: dict = {}  # {username: (bytes, timestamp)}
_user_photo_cache: dict = {}     # {user_id: (bytes, timestamp)}


# ============================================================================
# ВНУТРЕННИЕ ФУНКЦИИ
# ============================================================================

def _cache_cleanup(cache: dict) -> None:
    """Удаляет записи старше TTL."""
    now = time.time()
    expired = [k for k, (_, ts) in cache.items() if now - ts > _PHOTO_CACHE_TTL]
    for k in expired:
        del cache[k]


def _get_bot_token() -> str:
    """Получает BOT_TOKEN из окружения."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="BOT_TOKEN not configured")
    return token


async def _download_telegram_file(client: httpx.AsyncClient, bot_token: str, file_id: str) -> bytes:
    """
    Скачивает файл из Telegram по file_id.

    1. getFile -> file_path
    2. Скачиваем по file_path
    """
    # Получаем file_path
    file_resp = await client.get(
        f"https://api.telegram.org/bot{bot_token}/getFile",
        params={"file_id": file_id},
        timeout=10.0
    )
    file_data = file_resp.json()

    if not file_data.get("ok"):
        raise HTTPException(status_code=404, detail="Cannot get file info")

    file_path = file_data.get("result", {}).get("file_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="No file_path")

    # Скачиваем файл
    photo_resp = await client.get(
        f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
        timeout=30.0
    )

    if photo_resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Cannot download photo")

    return photo_resp.content


# ============================================================================
# ПУБЛИЧНЫЕ ФУНКЦИИ (endpoints)
# ============================================================================

async def get_channel_photo(username: str, db=None) -> Response:
    """
    Загружает аватарку канала из Telegram.

    Порядок:
    1. Проверяем кэш
    2. Пробуем из БД (legacy base64)
    3. Загружаем через Bot API

    Args:
        username: Username канала (без @)
        db: Опциональный объект БД для legacy fallback

    Returns:
        Response с image/jpeg
    """
    username = username.lower().lstrip('@')

    # Валидация
    if not USERNAME_REGEX.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format")

    # Очищаем старые записи
    _cache_cleanup(_channel_photo_cache)

    # 1. Проверяем кэш
    if username in _channel_photo_cache:
        photo_bytes, ts = _channel_photo_cache[username]
        if time.time() - ts < _PHOTO_CACHE_TTL:
            return Response(content=photo_bytes, media_type="image/jpeg")

    # 2. Пробуем из БД (legacy)
    if db is not None:
        try:
            channel = db.get_channel(username)
            if channel and hasattr(channel, 'photo_url') and channel.photo_url:
                if channel.photo_url.startswith('data:image'):
                    b64_data = channel.photo_url.split(',')[1]
                    photo_bytes = base64.b64decode(b64_data)

                    # Кэшируем
                    if len(_channel_photo_cache) < _PHOTO_CACHE_MAX:
                        _channel_photo_cache[username] = (photo_bytes, time.time())

                    return Response(content=photo_bytes, media_type="image/jpeg")
        except Exception:
            pass  # Игнорируем ошибки БД

    # 3. Загружаем через Bot API
    bot_token = _get_bot_token()

    try:
        async with httpx.AsyncClient() as client:
            # Получаем информацию о канале
            chat_resp = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getChat",
                params={"chat_id": f"@{username}"},
                timeout=10.0
            )
            chat_data = chat_resp.json()

            if not chat_data.get("ok"):
                raise HTTPException(status_code=404, detail="Channel not found")

            chat = chat_data.get("result", {})
            photo = chat.get("photo")

            if not photo:
                raise HTTPException(status_code=404, detail="Channel has no photo")

            big_file_id = photo.get("big_file_id")
            if not big_file_id:
                raise HTTPException(status_code=404, detail="No photo file_id")

            # Скачиваем
            photo_bytes = await _download_telegram_file(client, bot_token, big_file_id)

            # Кэшируем
            if len(_channel_photo_cache) < _PHOTO_CACHE_MAX:
                _channel_photo_cache[username] = (photo_bytes, time.time())

            return Response(content=photo_bytes, media_type="image/jpeg")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[PHOTO ERROR] {username}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


async def get_user_photo(user_id: int) -> Response:
    """
    Загружает аватарку пользователя из Telegram.

    Args:
        user_id: Telegram user ID

    Returns:
        Response с image/jpeg
    """
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    # Очищаем старые записи
    _cache_cleanup(_user_photo_cache)

    # Проверяем кэш
    if user_id in _user_photo_cache:
        photo_bytes, ts = _user_photo_cache[user_id]
        if time.time() - ts < _PHOTO_CACHE_TTL:
            return Response(content=photo_bytes, media_type="image/jpeg")

    # Загружаем через Bot API
    bot_token = _get_bot_token()

    try:
        async with httpx.AsyncClient() as client:
            # Получаем список фото пользователя
            photos_resp = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos",
                params={"user_id": user_id, "limit": 1},
                timeout=10.0
            )
            photos_data = photos_resp.json()

            if not photos_data.get("ok"):
                raise HTTPException(status_code=404, detail="Cannot get user photos")

            photos = photos_data.get("result", {}).get("photos", [])
            if not photos:
                raise HTTPException(status_code=404, detail="User has no photo")

            # Берём самое большое фото
            photo_sizes = photos[0]
            if not photo_sizes:
                raise HTTPException(status_code=404, detail="No photo sizes")

            big_photo = max(photo_sizes, key=lambda x: x.get("width", 0) * x.get("height", 0))
            file_id = big_photo.get("file_id")

            if not file_id:
                raise HTTPException(status_code=404, detail="No file_id")

            # Скачиваем
            photo_bytes = await _download_telegram_file(client, bot_token, file_id)

            # Кэшируем
            if len(_user_photo_cache) < _PHOTO_CACHE_MAX:
                _user_photo_cache[user_id] = (photo_bytes, time.time())

            return Response(content=photo_bytes, media_type="image/jpeg")

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal error")


def clear_cache(username: Optional[str] = None, user_id: Optional[int] = None) -> None:
    """
    Очищает кэш фото.

    Args:
        username: Если указан, очищает только для этого канала
        user_id: Если указан, очищает только для этого пользователя
        Если ничего не указано, очищает весь кэш
    """
    if username:
        username = username.lower().lstrip('@')
        _channel_photo_cache.pop(username, None)
    elif user_id:
        _user_photo_cache.pop(user_id, None)
    else:
        _channel_photo_cache.clear()
        _user_photo_cache.clear()
