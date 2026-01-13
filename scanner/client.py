"""
Pyrogram клиент для работы с Telegram API.
ОПТИМИЗИРОВАНО: 2 запроса вместо 7 (raw MTProto API)
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from pyrogram import Client
from pyrogram.raw import functions
from dotenv import load_dotenv

# Загружаем .env из корня проекта
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_client() -> Client:
    """
    Создаёт и возвращает Pyrogram клиент.
    Требует .env файл с API_ID, API_HASH, PHONE.
    """
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone = os.getenv("PHONE")

    if not api_id or not api_hash:
        raise ValueError(
            "Не найдены API_ID и API_HASH в .env файле.\n"
            "Получите их на https://my.telegram.org/apps"
        )

    # Сессия сохраняется в корне проекта
    session_path = PROJECT_ROOT / "scanner_session"

    return Client(
        name=str(session_path),
        api_id=int(api_id),
        api_hash=api_hash,
        phone_number=phone,
    )


async def get_channel_data(client: Client, channel: str) -> tuple:
    """
    Получает данные канала (2 запроса вместо 7).

    Args:
        client: Pyrogram клиент
        channel: username или ID канала

    Returns:
        (chat, messages, comments_data) - информация о канале, 50 сообщений и данные комментариев
    """
    # Убираем @ если есть
    channel = channel.lstrip('@')

    # Запрос 1: информация о канале (высокоуровневый API для удобства)
    chat = await client.get_chat(channel)

    # Запрос 2: Raw MTProto GetHistory - возвращает replies.replies!
    peer = await client.resolve_peer(channel)
    raw_result = await client.invoke(
        functions.messages.GetHistory(
            peer=peer,
            offset_id=0,
            offset_date=0,
            add_offset=0,
            limit=50,
            max_id=0,
            min_id=0,
            hash=0
        )
    )

    # Конвертируем raw messages в удобный формат
    messages = []
    comments_counts = []

    for raw_msg in raw_result.messages:
        # Пропускаем служебные сообщения (MessageService)
        if not hasattr(raw_msg, 'message'):
            continue

        # Создаём обёртку для совместимости с существующим кодом
        msg_wrapper = RawMessageWrapper(raw_msg)
        messages.append(msg_wrapper)

        # Извлекаем количество комментариев
        if hasattr(raw_msg, 'replies') and raw_msg.replies:
            comments_counts.append(raw_msg.replies.replies or 0)
        else:
            comments_counts.append(0)

    # Формируем данные о комментариях
    comments_data = {
        'enabled': chat.linked_chat is not None,
        'linked_chat': getattr(chat.linked_chat, 'title', None) if chat.linked_chat else None,
        'comments_counts': comments_counts,
        'total_comments': sum(comments_counts),
        'avg_comments': sum(comments_counts) / len(comments_counts) if comments_counts else 0.0
    }

    return chat, messages, comments_data


class RawMessageWrapper:
    """
    Обёртка для raw Message чтобы обеспечить совместимость с существующим кодом metrics.py.
    """
    def __init__(self, raw_msg):
        self._raw = raw_msg

        # Основные поля
        self.id = raw_msg.id

        # Конвертируем timestamp в datetime
        raw_date = raw_msg.date
        if isinstance(raw_date, int):
            self.date = datetime.fromtimestamp(raw_date, tz=timezone.utc)
        else:
            self.date = raw_date

        self.message = getattr(raw_msg, 'message', '')
        self.views = getattr(raw_msg, 'views', 0)
        self.forwards = getattr(raw_msg, 'forwards', 0)

        # Конвертируем edit_date если есть
        raw_edit = getattr(raw_msg, 'edit_date', None)
        if isinstance(raw_edit, int):
            self.edit_date = datetime.fromtimestamp(raw_edit, tz=timezone.utc)
        else:
            self.edit_date = raw_edit

        self.media_group_id = getattr(raw_msg, 'grouped_id', None)

        # Replies (комментарии)
        self.replies = None
        if hasattr(raw_msg, 'replies') and raw_msg.replies:
            self.replies = RawRepliesWrapper(raw_msg.replies)

        # Reactions
        self.reactions = None
        if hasattr(raw_msg, 'reactions') and raw_msg.reactions:
            self.reactions = RawReactionsWrapper(raw_msg.reactions)

        # Forward from chat
        self.forward_from_chat = None
        if hasattr(raw_msg, 'fwd_from') and raw_msg.fwd_from:
            fwd = raw_msg.fwd_from
            if hasattr(fwd, 'from_id') and fwd.from_id:
                self.forward_from_chat = RawForwardWrapper(fwd.from_id)


class RawRepliesWrapper:
    """Обёртка для MessageReplies"""
    def __init__(self, raw_replies):
        self.replies = raw_replies.replies or 0
        self.comments = getattr(raw_replies, 'comments', False)
        self.channel_id = getattr(raw_replies, 'channel_id', None)


class RawReactionsWrapper:
    """Обёртка для MessageReactions"""
    def __init__(self, raw_reactions):
        self.reactions = []
        if hasattr(raw_reactions, 'results') and raw_reactions.results:
            for r in raw_reactions.results:
                self.reactions.append(RawReactionCountWrapper(r))


class RawReactionCountWrapper:
    """Обёртка для ReactionCount"""
    def __init__(self, raw_reaction):
        self.count = raw_reaction.count or 0
        self.reaction = raw_reaction.reaction

        # Извлекаем emoji
        self.emoji = '?'
        if hasattr(raw_reaction.reaction, 'emoticon'):
            self.emoji = raw_reaction.reaction.emoticon
        elif hasattr(raw_reaction.reaction, 'document_id'):
            self.emoji = f"custom_{raw_reaction.reaction.document_id}"


class RawForwardWrapper:
    """Обёртка для forward_from_chat"""
    def __init__(self, from_id):
        self.id = None
        self.type = 'channel'

        if hasattr(from_id, 'channel_id'):
            self.id = from_id.channel_id
        elif hasattr(from_id, 'chat_id'):
            self.id = from_id.chat_id
        elif hasattr(from_id, 'user_id'):
            self.id = from_id.user_id
            self.type = 'user'
