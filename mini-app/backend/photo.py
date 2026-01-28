"""
photo.py - Модуль для работы с аватарками каналов

v68.0: Упрощённая версия — только SELECT из БД.
       Аватарки загружаются при сканировании и хранятся в photo_blob.
       Telegram API больше не используется (0 внешних запросов).

Функционал:
- get_channel_photo(): Отдаёт фото из БД
- get_user_photo(): Deprecated (не используется)
"""

import re
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import Response

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$')


# ============================================================================
# ПУБЛИЧНЫЕ ФУНКЦИИ
# ============================================================================

async def get_channel_photo(username: str, db) -> Response:
    """
    Отдаёт аватарку канала из БД.

    v68.0: Telegram API больше не используется.
    Фото загружается при сканировании и хранится в photo_blob.

    Args:
        username: Username канала (без @)
        db: Объект БД с методом get_channel()

    Returns:
        Response с image/jpeg

    Raises:
        HTTPException 400: Неверный формат username
        HTTPException 404: Канал не найден или нет фото
    """
    username = username.lower().lstrip('@')

    # Валидация
    if not USERNAME_REGEX.match(username):
        raise HTTPException(status_code=400, detail="Invalid username format")

    # Получаем канал из БД
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    channel = db.get_channel(username)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Получаем photo_blob
    photo_blob = getattr(channel, 'photo_blob', None)
    if not photo_blob:
        raise HTTPException(status_code=404, detail="No photo available")

    return Response(content=photo_blob, media_type="image/jpeg")


async def get_user_photo(user_id: int) -> Response:
    """
    Deprecated: Аватарки пользователей не используются в mini-app.

    Оставлено для обратной совместимости.
    """
    raise HTTPException(status_code=501, detail="User photos not implemented")


def clear_cache(username: Optional[str] = None, user_id: Optional[int] = None) -> None:
    """
    Deprecated: Кэш больше не используется.

    v68.0: Фото хранятся в БД, кэш не нужен.
    Оставлено для обратной совместимости.
    """
    pass
