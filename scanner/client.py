"""
Pyrogram клиент для работы с Telegram API.
v16.0: Ghost Protocol + Smart Crawler
- Математический анализ + User Forensics
- MTProto Vector Layers для минимизации запросов
- GetFullChannel для детекции мёртвой аудитории (online_count)
- chats_map для извлечения username из репостов
- FloodWait handling для безопасного краулинга
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import asyncio
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.raw import functions
from pyrogram.errors import ChannelPrivate, ChannelInvalid, FloodWait
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


class RawMessageWrapper:
    """
    Обёртка для raw Message чтобы обеспечить совместимость с существующим кодом metrics.py.
    """
    def __init__(self, raw_msg, chats_map: dict = None):
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

        # Forward from chat (v16.0: с username для краулера)
        self.forward_from_chat = None
        if hasattr(raw_msg, 'fwd_from') and raw_msg.fwd_from:
            fwd = raw_msg.fwd_from
            if hasattr(fwd, 'from_id') and fwd.from_id:
                self.forward_from_chat = RawForwardWrapper(fwd.from_id, chats_map)


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
    def __init__(self, from_id, chats_map: dict = None):
        self.id = None
        self.type = 'channel'
        self.username = None  # v16.0: username для краулера

        if hasattr(from_id, 'channel_id'):
            self.id = from_id.channel_id
        elif hasattr(from_id, 'chat_id'):
            self.id = from_id.chat_id
        elif hasattr(from_id, 'user_id'):
            self.id = from_id.user_id
            self.type = 'user'

        # v16.0: Получаем username из chats_map
        if self.id and chats_map and self.id in chats_map:
            self.username = chats_map[self.id]


class RawUserWrapper:
    """
    Обёртка для raw User объекта.
    Нормализует доступ к атрибутам для UserForensics.
    v11.0: Добавлены is_premium и dc_id для Executioner System.
    """
    def __init__(self, raw_user):
        self._raw = raw_user

        # ID юзера (критически важно для ID Clustering)
        self.id = getattr(raw_user, 'id', None)

        # Username и имя (для Username Entropy)
        self.username = getattr(raw_user, 'username', None)
        self.first_name = getattr(raw_user, 'first_name', None)
        self.last_name = getattr(raw_user, 'last_name', None)

        # Флаги Telegram (для Hidden Flags)
        self.is_scam = getattr(raw_user, 'scam', False)
        self.is_fake = getattr(raw_user, 'fake', False)
        self.is_restricted = getattr(raw_user, 'restricted', False)
        self.is_deleted = getattr(raw_user, 'deleted', False)
        self.is_bot = getattr(raw_user, 'bot', False)

        # v11.0: Premium статус (для Premium Density)
        self.is_premium = getattr(raw_user, 'premium', False)

        # v11.0: DC ID для Geo Check (только если есть фото)
        # dc_id находится в user.photo.dc_id
        self.dc_id = None
        if hasattr(raw_user, 'photo') and raw_user.photo:
            self.dc_id = getattr(raw_user.photo, 'dc_id', None)

    def __repr__(self):
        return f"<User id={self.id} username={self.username} premium={self.is_premium} dc={self.dc_id}>"


@dataclass
class ScanResult:
    """
    Результат сканирования канала v15.0.
    Содержит все данные для математического анализа, User Forensics и Ghost Protocol.
    """
    chat: Any                           # Информация о канале
    messages: list = field(default_factory=list)   # 50 сообщений
    comments_data: dict = field(default_factory=dict)  # Данные о комментариях
    users: list = field(default_factory=list)      # Юзеры для Forensics
    channel_health: dict = field(default_factory=dict)  # v15.0: Ghost Protocol данные
    api_requests: int = 3               # Количество API запросов (было 2)


# ============================================================================
# v15.0: GHOST PROTOCOL SMART SCAN
# ============================================================================

async def smart_scan(client: Client, channel: str) -> ScanResult:
    """
    Ghost Protocol сканирование канала v15.0.

    Всего 3 API запроса:
    - Запрос 1: get_chat + GetHistory (канал + посты)
    - Запрос 2: GetHistory linked_chat ИЛИ GetReactionsList (юзеры для Forensics)
    - Запрос 3: GetFullChannel (online_count для Ghost Detection)

    Args:
        client: Pyrogram клиент
        channel: username или ID канала

    Returns:
        ScanResult со всеми данными для анализа
    """
    # Убираем @ если есть
    channel = channel.lstrip('@')

    # =========================================================================
    # ЗАПРОС 1: Канал + сообщения
    # =========================================================================
    chat = await client.get_chat(channel)

    # Проверяем что это канал, а не профиль/группа/бот
    if chat.type != ChatType.CHANNEL:
        return ScanResult(
            chat=None,
            messages=[],
            comments_data={},
            users=[],
            channel_health={'status': 'error', 'reason': f'NOT_CHANNEL ({chat.type.name})'}
        )

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

    # v15.2: Пауза между запросами для снижения риска FloodWait
    await asyncio.sleep(0.5)

    # v16.0: Создаём маппинг channel_id → username для репостов
    chats_map = {}
    if hasattr(raw_result, 'chats') and raw_result.chats:
        for chat_obj in raw_result.chats:
            chat_id = getattr(chat_obj, 'id', None)
            chat_username = getattr(chat_obj, 'username', None)
            if chat_id and chat_username:
                chats_map[chat_id] = chat_username.lower()

    # Обрабатываем сообщения
    messages = []
    comments_counts = []

    for raw_msg in raw_result.messages:
        if not hasattr(raw_msg, 'message'):
            continue

        msg_wrapper = RawMessageWrapper(raw_msg, chats_map)
        messages.append(msg_wrapper)

        if hasattr(raw_msg, 'replies') and raw_msg.replies:
            comments_counts.append(raw_msg.replies.replies or 0)
        else:
            comments_counts.append(0)

    # Данные о комментариях
    comments_data = {
        'enabled': chat.linked_chat is not None,
        'linked_chat': getattr(chat.linked_chat, 'title', None) if chat.linked_chat else None,
        'comments_counts': comments_counts,
        'total_comments': sum(comments_counts),
        'avg_comments': sum(comments_counts) / len(comments_counts) if comments_counts else 0.0
    }

    # =========================================================================
    # ЗАПРОС 2: Юзеры для Forensics
    # =========================================================================
    users_for_forensics = []

    # ПУТЬ А: Комментарии включены → Linked Chat Dump (увеличенный лимит)
    if chat.linked_chat:
        try:
            linked_peer = await client.resolve_peer(chat.linked_chat.id)

            # v7.1: Увеличиваем лимит до 100 для большей выборки юзеров
            linked_result = await client.invoke(
                functions.messages.GetHistory(
                    peer=linked_peer,
                    offset_id=0,
                    offset_date=0,
                    add_offset=0,
                    limit=100,  # Было 50, увеличено для лучшей выборки
                    max_id=0,
                    min_id=0,
                    hash=0
                )
            )

            # Извлекаем юзеров из Vector Layer (users[] в ответе)
            if hasattr(linked_result, 'users') and linked_result.users:
                for raw_user in linked_result.users:
                    users_for_forensics.append(RawUserWrapper(raw_user))

            # v39.1: Извлекаем ТЕКСТЫ комментариев для LLM анализа
            comment_texts = []
            if hasattr(linked_result, 'messages') and linked_result.messages:
                for msg in linked_result.messages:
                    text = getattr(msg, 'message', None)
                    if text and len(text) > 2:  # Игнорируем пустые и однобуквенные
                        comment_texts.append(text)
            comments_data['comments'] = comment_texts

            # v7.1: Если юзеров всё ещё мало, дополняем из авторов сообщений
            if len(users_for_forensics) < 10 and hasattr(linked_result, 'messages'):
                for msg in linked_result.messages:
                    if hasattr(msg, 'from_id') and msg.from_id:
                        # from_id может быть PeerUser
                        if hasattr(msg.from_id, 'user_id'):
                            # Ищем юзера в users[] по ID
                            user_id = msg.from_id.user_id
                            for raw_user in (linked_result.users or []):
                                if getattr(raw_user, 'id', None) == user_id:
                                    users_for_forensics.append(RawUserWrapper(raw_user))
                                    break

        except (ChannelPrivate, ChannelInvalid):
            # Linked chat приватный → fallback на реакции
            users_for_forensics = await _get_users_from_reactions(
                client, peer, messages
            )

    # ПУТЬ Б: Комментарии отключены → Реакции последнего поста
    else:
        users_for_forensics = await _get_users_from_reactions(
            client, peer, messages
        )

    # Дедупликация юзеров
    users_for_forensics = _deduplicate_users(users_for_forensics)

    # v15.2: Пауза перед последним запросом
    await asyncio.sleep(0.5)

    # =========================================================================
    # ЗАПРОС 3: GetFullChannel - Ghost Protocol (online_count)
    # =========================================================================
    channel_health = {}
    api_requests = 3

    try:
        full_result = await client.invoke(
            functions.channels.GetFullChannel(channel=peer)
        )
        full_chat = full_result.full_chat

        channel_health = {
            'online_count': getattr(full_chat, 'online_count', 0) or 0,
            'participants_count': getattr(full_chat, 'participants_count', 0) or 0,
            'admins_count': getattr(full_chat, 'admins_count', 0) or 0,
            'banned_count': getattr(full_chat, 'banned_count', 0) or 0,
            'kicked_count': getattr(full_chat, 'kicked_count', 0) or 0,
            'status': 'complete'
        }
    except Exception:
        # Приватный канал или ошибка - пропускаем Ghost Protocol
        channel_health = {'status': 'unavailable'}

    return ScanResult(
        chat=chat,
        messages=messages,
        comments_data=comments_data,
        users=users_for_forensics,
        channel_health=channel_health,
        api_requests=api_requests
    )


async def _get_users_from_reactions(
    client: Client,
    peer: Any,
    messages: list
) -> list:
    """
    Получает юзеров из реакций последнего поста.
    Fallback когда комментарии отключены или linked_chat недоступен.
    """
    users = []

    if not messages:
        return users

    # Берём последний пост с реакциями
    target_msg = None
    for msg in messages[:5]:  # Проверяем первые 5 постов
        if msg.reactions and msg.reactions.reactions:
            target_msg = msg
            break

    if not target_msg:
        return users

    try:
        # GetMessageReactionsList возвращает список юзеров
        result = await client.invoke(
            functions.messages.GetMessageReactionsList(
                peer=peer,
                id=target_msg.id,
                limit=50
            )
        )

        # Извлекаем юзеров из Vector Layer
        if hasattr(result, 'users') and result.users:
            for raw_user in result.users:
                users.append(RawUserWrapper(raw_user))

    except Exception:
        # Реакции недоступны или ошибка API
        pass

    return users


def _deduplicate_users(users: list) -> list:
    """Убирает дубликаты юзеров по ID."""
    seen = set()
    unique = []

    for user in users:
        if user.id and user.id not in seen:
            seen.add(user.id)
            unique.append(user)

    return unique


# ============================================================================
# v16.0: SAFE SCAN С ОБРАБОТКОЙ FLOODWAIT
# ============================================================================

async def smart_scan_safe(client: Client, channel: str, max_retries: int = 3) -> ScanResult:
    """
    Безопасный вариант smart_scan с обработкой FloodWait.

    При получении FloodWait ждёт указанное время и повторяет запрос.
    При ошибке доступа возвращает ScanResult с пустыми данными.

    Args:
        client: Pyrogram клиент
        channel: username канала
        max_retries: максимум попыток при FloodWait

    Returns:
        ScanResult или ScanResult с error статусом
    """
    for attempt in range(max_retries):
        try:
            return await smart_scan(client, channel)

        except FloodWait as e:
            # v15.2: Экспоненциальный backoff - увеличиваем паузу с каждой попыткой
            backoff = (2 ** attempt) * 2  # 2, 4, 8 сек
            wait_time = e.value + 5 + backoff
            hours = wait_time // 3600
            mins = (wait_time % 3600) // 60
            secs = wait_time % 60

            # Всегда ждём FloodWait — никогда не пропускаем!
            if hours > 0:
                print(f"FloodWait: жду {hours}ч {mins}мин (попытка {attempt + 1}/{max_retries})")
            elif mins > 0:
                print(f"FloodWait: жду {mins}мин {secs}сек (попытка {attempt + 1}/{max_retries})")
            else:
                print(f"FloodWait: жду {secs} сек (попытка {attempt + 1}/{max_retries})")

            await asyncio.sleep(wait_time)

        except (ChannelPrivate, ChannelInvalid) as e:
            # Канал приватный или не существует
            return ScanResult(
                chat=None,
                messages=[],
                comments_data={},
                users=[],
                channel_health={'status': 'error', 'reason': str(type(e).__name__)}
            )

        except Exception as e:
            # Другие ошибки — reason передаётся наверх, краулер выводит
            return ScanResult(
                chat=None,
                messages=[],
                comments_data={},
                users=[],
                channel_health={'status': 'error', 'reason': str(e)}
            )

    # Все попытки исчерпаны
    return ScanResult(
        chat=None,
        messages=[],
        comments_data={},
        users=[],
        channel_health={'status': 'error', 'reason': 'Max retries exceeded'}
    )
