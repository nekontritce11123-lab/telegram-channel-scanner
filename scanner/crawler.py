"""
Smart Crawler - автоматический сбор базы каналов.
v18.0: Алгоритм "Чистого Дерева" + 17 категорий + multi-label

Логика:
  1. Берём канал из очереди
  2. Проверяем через scanner
  3. Если score >= 60 (GOOD) → собираем рекламные ссылки
  4. Добавляем новые каналы в очередь
  5. AI классификатор работает ПАРАЛЛЕЛЬНО (не блокирует)
  6. Пауза → повторяем

Защита аккаунта:
  - Пауза 5 сек между каналами
  - Большая пауза каждые 100 каналов
  - Автоматическая обработка FloodWait

AI классификация v18.0:
  - Groq API + Llama 3.3 70B (бесплатно)
  - 17 категорий + multi-label (CAT+CAT2)
  - Фоновый worker (не тормозит краулер)
  - Fallback на ключевые слова
"""

import asyncio
import re
import json
# v61.0: httpx удалён - используем SCP синхронизацию через sync.py
from datetime import datetime
from typing import Optional

from loguru import logger
from pyrogram import Client

from .database import CrawlerDB
from .client import get_client, smart_scan_safe, download_photos_from_messages, download_channel_avatar
from .scorer import calculate_final_score
from .vision import analyze_images_batch, format_for_prompt, unload_model as unload_vision
from .classifier import get_classifier, ChannelClassifier
from .llm_analyzer import LLMAnalyzer
from .metrics import get_message_reactions_count  # v56.0: для posts_raw
from .json_compression import (
    compress_breakdown, compress_posts_raw, compress_user_ids
)  # v23.0: JSON compression
from .sync import fetch_requests, push_database, sync_channel  # v61.2: + HTTP sync
from .ad_detector import detect_ad_status  # v69.0: 3-уровневая детекция рекламы
from .summarizer import generate_channel_summary  # v69.0: AI описание канала
# v46.0: Brand Safety теперь в LLM Analyzer, стоп-слова deprecated

# v43.0: Централизованная конфигурация
from .config import GOOD_THRESHOLD, COLLECT_THRESHOLD, ensure_ollama_running

# v66.0: Константа на уровне модуля (DRY — не создаётся при каждом вызове)
SKIP_WORDS = {
    # Telegram служебные
    'addstickers', 'share', 'proxy', 'joinchat', 'stickerpack',
    # Короткие/зарезервированные
    's', 'c', 'iv', 'msg', 'vote', 'boost', 'premium', 'emoji',
    # Python методы/библиотеки
    'fetchall', 'fetchone', 'fetchmany', 'execute', 'commit', 'cursor',
    'pytest', 'unittest', 'numpy', 'pandas', 'scipy', 'matplotlib',
    'torch', 'keras', 'flask', 'django', 'fastapi', 'requests',
    'asyncio', 'aiohttp', 'httpx', 'redis', 'celery', 'sqlalchemy',
    # JavaScript/фреймворки
    'react', 'redux', 'vuejs', 'angular', 'nextjs', 'nodejs',
    'webpack', 'eslint', 'prettier', 'typescript', 'javascript',
    # Служебные слова программирования
    'async', 'await', 'import', 'export', 'const', 'class', 'state',
    'return', 'function', 'lambda', 'yield', 'static', 'public',
    'private', 'protected', 'interface', 'abstract', 'override',
    'binding', 'observable', 'subscribe', 'dispatch', 'middleware',
    # Переменные окружения
    'environment', 'production', 'development', 'staging', 'testing',
    'config', 'settings', 'options', 'params', 'arguments',
    # Платформы (не Telegram)
    'google', 'github', 'gitlab', 'bitbucket', 'stackoverflow',
    'youtube', 'twitter', 'instagram', 'facebook', 'linkedin',
    'discord', 'slack', 'medium', 'notion', 'figma', 'linux',
    # Языки программирования
    'python', 'kotlin', 'swift', 'rustlang', 'golang', 'clojure',
    'haskell', 'elixir', 'erlang', 'scala', 'groovy',
    # Прочие технические
    'admin', 'support', 'helper', 'utils', 'tools', 'service',
    'handler', 'controller', 'model', 'schema', 'migration',
    'dockerfile', 'makefile', 'readme', 'changelog', 'license',
    'tetrad', 'string', 'array', 'object', 'integer', 'boolean',
}


def extract_content_for_classification(
    chat,
    messages: list,
    comments_data: dict = None,
    users: dict = None,
    max_posts: int = 50,
    max_comments: int = 30
) -> dict:
    """
    v22.1: Извлекает контент канала для хранения и переклассификации.

    Хранит ВСЕ данные нужные для AI анализа:
    - 50 постов (тексты)
    - 30 комментариев (текст + user_id + is_premium для bot detection)

    Args:
        chat: Объект канала (scan_result.chat)
        messages: Список постов (scan_result.messages)
        comments_data: Данные комментариев (scan_result.comments_data)
        users: Данные пользователей (scan_result.users)
        max_posts: Максимум постов (по умолчанию 50)
        max_comments: Максимум комментариев (по умолчанию 30)

    Returns:
        dict с title, description, content_json
    """
    # Title и description из chat
    title = getattr(chat, 'title', '') or ''
    description = getattr(chat, 'description', '') or ''

    # === ПОСТЫ (50 штук × 300 символов) ===
    posts = []
    for m in messages[:max_posts]:
        text = ''
        if hasattr(m, 'message') and m.message:
            text = m.message
        elif hasattr(m, 'text') and m.text:
            text = m.text
        elif hasattr(m, 'caption') and m.caption:
            text = m.caption

        if text:
            posts.append(text[:300])  # 300 символов достаточно для классификации

    # === КОММЕНТАРИИ (30 штук для bot detection) ===
    # Формат: {"t": text, "p": is_premium, "id": user_id}
    # Короткие ключи для экономии места
    comments = []
    if comments_data:
        raw_comments = comments_data.get('comments', [])
        users_dict = users or {}

        for c in raw_comments[:max_comments]:
            # Извлекаем текст комментария
            text = ''
            if hasattr(c, 'message') and c.message:
                text = c.message
            elif hasattr(c, 'text') and c.text:
                text = c.text
            elif isinstance(c, dict):
                text = c.get('message', '') or c.get('text', '')

            if not text:
                continue

            # Извлекаем user_id
            user_id = None
            if hasattr(c, 'from_user') and c.from_user:
                user_id = getattr(c.from_user, 'id', None)
            elif hasattr(c, 'from_id'):
                from_id = c.from_id
                if hasattr(from_id, 'user_id'):
                    user_id = from_id.user_id
            elif isinstance(c, dict):
                user_id = c.get('user_id') or c.get('from_id')

            # Проверяем is_premium из users dict
            is_premium = False
            if user_id and user_id in users_dict:
                user = users_dict[user_id]
                if hasattr(user, 'is_premium'):
                    is_premium = bool(user.is_premium)
                elif isinstance(user, dict):
                    is_premium = bool(user.get('is_premium', False))

            comments.append({
                't': text[:150],  # 150 символов достаточно для паттернов
                'p': is_premium,
                'id': user_id
            })

    # Формируем JSON
    content = {'posts': posts}
    if comments:
        content['comments'] = comments

    content_json = json.dumps(content, ensure_ascii=False, separators=(',', ':'))

    return {
        'title': title,
        'description': description,
        'content_json': content_json
    }


# v50.0: Rate limiting отключён (бесполезен для локального сканирования)

# v43.0: GOOD_THRESHOLD, COLLECT_THRESHOLD импортируются из scanner.config


class SmartCrawler:
    """
    Краулер для автоматического сбора базы каналов.

    Использование:
        crawler = SmartCrawler()
        await crawler.run(["@channel1", "@channel2"])

    v18.0: AI классификация с 17 категориями и multi-label поддержкой.
    """

    def __init__(self, db_path: str = "crawler.db"):
        self.db = CrawlerDB(db_path)
        self.client: Optional[Client] = None
        self.processed_count = 0
        self.running = True
        self.classifier: Optional[ChannelClassifier] = None
        self.classified_count = 0  # Счётчик классифицированных
        self.new_links_count = 0   # v41.1: Счётчик новых ссылок
        self.llm_analyzer: Optional[LLMAnalyzer] = None  # v38.0: LLM анализ

    async def start(self):
        """Запускает Pyrogram клиент и AI классификатор."""
        # v43.1: Проверяем и запускаем Ollama ПЕРВЫМ делом
        # Без Ollama краулер не может работать (классификация + LLM анализ)
        ensure_ollama_running()  # Выбросит RuntimeError если не удалось

        self.client = get_client()
        await self.client.start()
        print("Подключено к Telegram")

        # v29: Классификатор без фонового worker — всё синхронно
        self.classifier = get_classifier()

        # v38.0: LLM Analyzer для ad_percentage и bot detection
        self.llm_analyzer = LLMAnalyzer()
        print("[OK] LLM Analyzer готов")

    async def stop(self):
        """Останавливает клиент и классификатор."""
        if self.classifier:
            self.classifier.save_cache()
            self.classifier.unload()  # v33: Выгружаем модель из GPU

        # v63.0: Выгружаем Vision модель
        try:
            unload_vision()
        except Exception as e:
            logger.debug(f"Vision unload warning: {e}")

        if self.client:
            await self.client.stop()
            print("Отключено от Telegram")

    def add_seeds(self, channels: list):
        """Добавляет начальные каналы в очередь (batch mode)."""
        try:
            channel_tuples = [
                (ch.lower().lstrip('@'), "[seed]")
                for ch in channels
            ]
            added = self.db.add_channels_batch(channel_tuples)
            print(f"  + {added} каналов добавлено (из {len(channels)})")
            return added
        except Exception as e:
            logger.error(f"Failed to add seeds: {e}")
            return 0

    # v61.0: Старые HTTP sync функции удалены
    # Используем SCP синхронизацию через scanner/sync.py

    def extract_links(self, messages: list, channel_username: str) -> set:
        """
        Извлекает все внешние Telegram ссылки из постов.

        Returns:
            set[str] — множество username'ов
        """
        links = set()
        channel_username = channel_username.lower()

        for msg in messages:
            # Получаем текст (RawMessageWrapper использует 'message', не 'text')
            text = ""
            if hasattr(msg, 'message') and msg.message:
                text = msg.message.lower()
            elif hasattr(msg, 'text') and msg.text:
                text = msg.text.lower()
            elif hasattr(msg, 'caption') and msg.caption:
                text = msg.caption.lower()

            # Репосты проверяем даже без текста
            if msg.forward_from_chat:
                fwd = msg.forward_from_chat
                fwd_username = getattr(fwd, 'username', None)
                if fwd_username and fwd_username != channel_username:
                    links.add(fwd_username)

            if not text:
                continue

            # Приватные инвайты (t.me/+XXX) — пропускаем, резолвим отдельно
            # Их обработаем через resolve_invite_link

            # Публичные каналы: t.me/username (минимум 5 символов как в Telegram)
            # v66.0: SKIP_WORDS вынесен на уровень модуля (DRY)
            for match in re.findall(r't\.me/([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in SKIP_WORDS:
                    links.add(match)

            # telegram.me/username
            for match in re.findall(r'telegram\.me/([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in SKIP_WORDS:
                    links.add(match)

            # @упоминания
            for match in re.findall(r'@([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in SKIP_WORDS:
                    if not match.endswith('bot'):
                        links.add(match)

        return links

    async def process_channel(self, username: str) -> Optional[dict]:
        """
        v43.0: Обрабатывает один канал в памяти (all-or-nothing).

        НЕ записывает в БД! Возвращает dict с данными для записи в run().
        При любой ошибке или прерывании — канал остаётся WAITING.

        Returns:
            dict с результатами для claim_and_complete(), или
            dict с delete=True для удаления, или
            None для retry (канал остаётся WAITING)
        """
        # v50.0: Тайминг обработки
        import time as _time
        _start_time = _time.time()

        result = {
            'username': username,
            'status': 'ERROR',
            'score': 0,
            'verdict': '',
            'new_channels': 0,
            'category': None,
            'ad_pct': None,
            'bot_pct': None,
            # v43.0: Данные для claim_and_complete()
            'trust_factor': 1.0,
            'members': 0,
            'breakdown': None,
            'categories': None,
            'llm_analysis': None,
            'title': None,
            'description': None,
            'content_json': None,
            'ad_links': None,
            'delete': False,  # v43.0: флаг для удаления
            'safety': None,   # v45.0: Brand Safety
            'elapsed': 0,     # v50.0: время обработки
        }

        # Сканируем
        scan_result = await smart_scan_safe(self.client, username)

        # v43.0: Проверяем на ошибку
        if scan_result.chat is None:
            error_reason = scan_result.channel_health.get('reason', 'Unknown error')

            # Только сетевые ошибки → retry (возвращаем None, канал остаётся WAITING)
            network_errors = ['timeout', 'connection', 'network', 'connectionerror']
            is_network = any(err in error_reason.lower() for err in network_errors)

            if is_network:
                # Временная ошибка — вернём None, канал останется WAITING для retry
                return None
            else:
                # Постоянные ошибки — помечаем для удаления
                result['delete'] = True
                result['elapsed'] = _time.time() - _start_time
                return result

        # v68.0: Загружаем аватарку канала для сохранения в БД
        photo_blob = await download_channel_avatar(self.client, scan_result.chat)
        result['photo_blob'] = photo_blob

        # v22.1: Извлекаем контент для хранения и переклассификации
        # Включает 50 постов + 30 комментариев для AI анализа
        content = extract_content_for_classification(
            scan_result.chat,
            scan_result.messages,
            comments_data=scan_result.comments_data,
            users=scan_result.users
        )

        # v46.0: Brand Safety теперь через LLM (см. ниже после llm_analyzer.analyze)
        # Старый стоп-слова фильтр удалён - LLM понимает контекст лучше

        # v63.0: Vision Analysis - анализ изображений с канала
        image_descriptions = ""
        try:
            photos = await download_photos_from_messages(
                self.client, scan_result.messages, max_photos=10, chat=scan_result.chat
            )
            if photos:
                print(f"  [VISION] {len(photos)} images...")
                analyses = analyze_images_batch(photos)
                image_descriptions = format_for_prompt(analyses)
                print(f"  [VISION] Done ({len(analyses)} analyzed)")
        except Exception as e:
            logger.warning(f"Vision analysis failed: {e}")

        # v43.2: Сначала классификация и LLM анализ, ПОТОМ score
        # (чтобы llm_trust_factor применился к score!)

        # v41.2: Классификация для ВСЕХ каналов (не только GOOD)
        category = None
        if self.classifier:
            channel_id = getattr(scan_result.chat, 'id', None)
            if channel_id:
                category = await self.classifier.classify_sync(
                    channel_id=channel_id,
                    title=getattr(scan_result.chat, 'title', ''),
                    description=getattr(scan_result.chat, 'description', ''),
                    messages=scan_result.messages,
                    image_descriptions=image_descriptions  # v63.0
                )
                if category:
                    self.classified_count += 1
                    result['category'] = category

        # v43.2: LLM Analysis ПЕРЕД calculate_final_score (чтобы штрафы применились!)
        llm_result = None
        if self.llm_analyzer:
            try:
                comments = []
                if scan_result.comments_data:
                    comments = scan_result.comments_data.get('comments', [])

                llm_result = self.llm_analyzer.analyze(
                    channel_id=getattr(scan_result.chat, 'id', 0),
                    messages=scan_result.messages,
                    comments=comments,
                    category=category or "DEFAULT"
                )

                if llm_result:
                    llm_analysis = {
                        'ad_percentage': llm_result.posts.ad_percentage if llm_result.posts else None,
                        'bot_percentage': llm_result.comments.bot_percentage if llm_result.comments else None,
                        'trust_score': llm_result.comments.trust_score if llm_result.comments else None,
                        'llm_trust_factor': llm_result.llm_trust_factor,
                        'ad_mult': getattr(llm_result, '_ad_mult', 1.0),
                        'bot_mult': getattr(llm_result, '_comment_mult', 1.0),
                    }
                    result['ad_pct'] = llm_analysis.get('ad_percentage')
                    result['bot_pct'] = llm_analysis.get('bot_percentage')

                    # v46.0: Brand Safety из LLM (заменяет стоп-слова)
                    if llm_result.safety:
                        result['safety'] = {
                            'is_toxic': llm_result.safety.get('is_toxic', False),
                            'category': llm_result.safety.get('toxic_category'),
                            'ratio': llm_result.safety.get('toxic_ratio', 0.0),
                            'severity': llm_result.safety.get('severity', 'LOW'),
                            'evidence': llm_result.safety.get('evidence', []),
                            'confidence': llm_result.safety.get('confidence', 0),
                        }

                        # CRITICAL = сразу BAD без дальнейшего анализа
                        if llm_result.safety.get('severity') == 'CRITICAL':
                            toxic_cat = llm_result.safety.get('toxic_category', 'CONTENT')
                            result['status'] = 'BAD'
                            result['verdict'] = f"TOXIC_{toxic_cat}"
                            result['score'] = 0
                            result['title'] = content['title']
                            result['description'] = content['description']
                            result['content_json'] = content['content_json']
                            result['elapsed'] = _time.time() - _start_time
                            return result

            except (AttributeError, KeyError, TypeError) as e:
                # LLM анализ опционален - не прерываем сканирование
                logger.debug(f"LLM analysis optional error: {e}")

        # v43.2: Теперь считаем score С учётом llm_result (ad_percentage штраф!)
        try:
            score_result = calculate_final_score(
                scan_result.chat,
                scan_result.messages,
                scan_result.comments_data,
                scan_result.users,
                scan_result.channel_health,
                llm_result=llm_result  # v43.2: Передаём LLM для штрафов!
            )

            score = score_result.get('score', 0)
            verdict = score_result.get('verdict', '')
            trust_factor = score_result.get('trust_factor', 1.0)
            members = score_result.get('members', 0)

            # v22.5: Добавляем flags в breakdown для корректного отображения в UI
            breakdown = score_result.get('breakdown', {})
            flags = score_result.get('flags', {})
            if breakdown and flags:
                breakdown['reactions_enabled'] = flags.get('reactions_enabled', True)
                breakdown['comments_enabled'] = flags.get('comments_enabled', True)
                breakdown['floating_weights'] = flags.get('floating_weights', False)
                score_result['breakdown'] = breakdown

            # v43.2: Добавляем llm_analysis в breakdown
            if llm_result:
                breakdown['llm_analysis'] = {
                    'ad_percentage': llm_result.posts.ad_percentage if llm_result.posts else None,
                    'bot_percentage': llm_result.comments.bot_percentage if llm_result.comments else None,
                    'trust_score': llm_result.comments.trust_score if llm_result.comments else None,
                    'llm_trust_factor': llm_result.llm_trust_factor,
                    'ad_mult': getattr(llm_result, '_ad_mult', 1.0),
                    'bot_mult': getattr(llm_result, '_comment_mult', 1.0),
                }

            # v52.2: Добавляем trust_details в breakdown для отображения штрафов в UI
            trust_details = score_result.get('trust_details', {})
            if trust_details:
                breakdown['trust_details'] = trust_details

            result['score'] = score
            result['verdict'] = verdict
            result['trust_factor'] = trust_factor
            result['members'] = members

        except (KeyError, TypeError, AttributeError, ValueError) as e:
            # v43.0: Ошибки при расчёте — помечаем как ERROR для записи
            error_msg = f"{type(e).__name__}: {e}"
            result['status'] = 'ERROR'
            result['verdict'] = error_msg
            result['elapsed'] = _time.time() - _start_time
            return result

        # v43.0: Заполняем result данными для claim_and_complete()
        result['breakdown'] = score_result.get('breakdown')
        result['categories'] = score_result.get('categories')
        result['title'] = content['title']
        result['description'] = content['description']
        result['content_json'] = content['content_json']

        # v69.0: Детекция продажи рекламы (0=нельзя, 1=возможно, 2=можно)
        result['ad_status'] = detect_ad_status(content['description'])

        # v69.0: AI описание канала (500+ символов)
        try:
            # Извлекаем тексты постов для анализа
            post_texts = []
            for m in scan_result.messages[:15]:  # Берём больше постов для контекста
                text = None
                if hasattr(m, 'message') and m.message:
                    text = m.message
                elif hasattr(m, 'text') and m.text:
                    text = m.text
                elif hasattr(m, 'caption') and m.caption:
                    text = m.caption
                if text and len(text.strip()) > 30:
                    post_texts.append(text.strip())

            # Генерируем описание только для GOOD каналов (экономим API)
            if score >= GOOD_THRESHOLD and post_texts:
                result['ai_summary'] = generate_channel_summary(
                    title=content['title'] or username,
                    description=content['description'],
                    posts=post_texts
                )
            else:
                result['ai_summary'] = None
        except Exception as e:
            logger.warning(f"[{username}] AI summary error: {e}")
            result['ai_summary'] = None

        # v56.0: Собираем posts_raw — сырые данные 50 постов для пересчёта
        posts_raw = [{
            'id': m.id if hasattr(m, 'id') else None,
            'date': m.date.isoformat() if hasattr(m, 'date') and m.date else None,
            'views': getattr(m, 'views', 0) or 0,
            'forwards': getattr(m, 'forwards', 0) or 0,
            'reactions': get_message_reactions_count(m) if hasattr(m, 'reactions') else 0,
        } for m in scan_result.messages[:50]]
        posts_raw = compress_posts_raw(posts_raw)  # v23.0: compress for storage
        result['posts_raw'] = posts_raw

        # v56.0: Собираем user_ids — для пересчёта forensics
        user_ids = None
        if scan_result.users:
            users_list = scan_result.users
            # users может быть dict или list
            if isinstance(users_list, dict):
                users_list = list(users_list.values())
            user_ids = {
                'ids': [u.id for u in users_list if hasattr(u, 'id') and u.id],
                'premium_ids': [u.id for u in users_list if hasattr(u, 'id') and u.id and getattr(u, 'is_premium', False)],
            }
            user_ids = compress_user_ids(user_ids)  # v23.0: compress for storage
        result['user_ids'] = user_ids

        # v56.0: Добавляем все данные из score_result
        result['raw_score'] = score_result.get('raw_score')
        result['is_scam'] = score_result.get('is_scam', False)
        result['scam_reason'] = score_result.get('scam_reason')
        result['tier'] = score_result.get('tier')
        result['trust_penalties'] = score_result.get('trust_details')
        result['conviction'] = score_result.get('conviction', {})
        result['forensics'] = score_result.get('forensics')
        result['channel_health'] = score_result.get('channel_health', {})
        result['flags'] = score_result.get('flags', {})
        result['raw_stats'] = score_result.get('raw_stats', {})

        # v56.0: linked_chat данные
        chat = scan_result.chat
        result['linked_chat_id'] = chat.linked_chat.id if hasattr(chat, 'linked_chat') and chat.linked_chat else None
        result['linked_chat_title'] = chat.linked_chat.title if hasattr(chat, 'linked_chat') and chat.linked_chat and hasattr(chat.linked_chat, 'title') else None

        # v45.0: Добавляем safety в breakdown для сохранения в БД
        if result['breakdown'] and result.get('safety'):
            result['breakdown']['safety'] = result['safety']

        # Определяем статус (GOOD если score >= 60)
        if score >= GOOD_THRESHOLD:
            status = 'GOOD'

            # v41.2: Для GOOD категория обязательна
            if not category:
                result['verdict'] = 'NO_CATEGORY'
                return None  # v43.0: Retry — категория получится при следующей попытке

            # Собираем ссылки только с ОЧЕНЬ хороших каналов (score >= 72)
            if score >= COLLECT_THRESHOLD:
                links = self.extract_links(scan_result.messages, username)
                result['ad_links'] = list(links)
                # v43.0: Добавляем новые каналы сразу (это безопасно, INSERT OR IGNORE)
                new_count = 0
                for link in links:
                    if self.db.add_channel(link, parent=username):
                        new_count += 1
                result['new_channels'] = new_count

        else:
            status = 'BAD'

        result['status'] = status
        result['elapsed'] = _time.time() - _start_time
        return result

    async def reclassify_uncategorized(self, limit: int = 50):
        """
        v31: Переклассифицирует GOOD каналы без категории.
        Вызывается в начале сессии для "догоняния".
        """
        if not self.classifier:
            return

        uncategorized = self.db.get_uncategorized(limit=limit)
        if not uncategorized:
            return

        print(f"\nРеклассификация {len(uncategorized)} каналов без категории...")

        reclassified = 0
        for i, username in enumerate(uncategorized, 1):
            if not self.running:
                break

            print(f"  [{i}/{len(uncategorized)}] @{username}...", end=" ", flush=True)

            scan_result = await smart_scan_safe(self.client, username)
            if scan_result.chat is None:
                print("ERROR (scan)")
                continue

            channel_id = getattr(scan_result.chat, 'id', None)
            if not channel_id:
                print("ERROR (no id)")
                continue

            category = await self.classifier.classify_sync(
                channel_id=channel_id,
                title=getattr(scan_result.chat, 'title', ''),
                description=getattr(scan_result.chat, 'description', ''),
                messages=scan_result.messages
            )

            if category:
                self.db.set_category(username, category)
                reclassified += 1
                self.classified_count += 1
                print(category)
            else:
                # v33: НЕ останавливаем — пропускаем и продолжаем
                print("SKIP (retry later)")

        print(f"Реклассификация завершена: {reclassified} категорий\n")

    async def run(
        self,
        seeds: list = None,
        max_channels: int = None,
        verbose: bool = True
    ):
        """
        v43.0: Основной цикл краулера с all-or-nothing семантикой.

        Args:
            seeds: начальные каналы (опционально)
            max_channels: максимум каналов для обработки (None = бесконечно)
            verbose: выводить ли подробный лог
        """
        # v43.0: Одноразовый сброс PROCESSING для миграции со старых версий
        # После миграции этот код ничего не делает (нет PROCESSING каналов)
        reset = self.db.reset_processing()
        if reset > 0:
            print(f"Миграция v43.0: сброшено {reset} PROCESSING → WAITING")

        # Добавляем seed каналы
        if seeds:
            print("\nДобавляю seed каналы:")
            self.add_seeds(seeds)

        # v61.0: SCP синхронизация - забираем запросы с сервера
        try:
            requests = fetch_requests()
            if requests:
                added = 0
                for username in requests:
                    if self.db.add_channel(username, parent="user_request"):
                        added += 1
                print(f"[OK] Синхронизация: {len(requests)} запросов с сервера, {added} добавлено")
            else:
                print("[OK] Синхронизация: нет новых запросов")
        except Exception as e:
            print(f"[!] Синхронизация: {e}")

        # Статистика
        stats = self.db.get_stats()
        print(f"\nБаза данных:")
        print(f"  Всего: {stats['total']}")
        print(f"  В очереди: {stats['waiting']}")
        print(f"  GOOD: {stats['good']}")
        print(f"  BAD: {stats['bad']}")

        if stats['waiting'] == 0:
            print("\nОчередь пуста! Добавьте seed каналы.")
            return

        print(f"\nЗапускаю краулер v50.0...")
        print("Нажми Ctrl+C для остановки\n")

        try:
            await self.start()

            # v30: Сначала доклассифицировать GOOD каналы без категории
            await self.reclassify_uncategorized(limit=50)

            print("Начинаю основной цикл обработки...")

            while self.running:
                # v43.0: peek_next() БЕЗ изменения статуса
                username = self.db.peek_next()

                if not username:
                    print("\nОчередь пуста! Краулер завершён.")
                    break

                # Проверяем лимит
                if max_channels and self.processed_count >= max_channels:
                    print(f"\nДостигнут лимит {max_channels} каналов.")
                    break

                # v43.0: Обрабатываем в памяти (может быть прервано без последствий)
                result = await self.process_channel(username)

                # v43.0: None = retry (сетевая ошибка или NO_CATEGORY)
                # Перемещаем в конец очереди чтобы не застрять в бесконечном цикле
                if result is None:
                    self.db.requeue_channel(username)
                    continue

                # v43.0: Атомарная запись результата
                if result.get('delete'):
                    # Удаляем невалидный канал
                    self.db.delete_if_waiting(username)
                    continue

                if result['status'] in ('GOOD', 'BAD', 'ERROR'):
                    # v56.0: Атомарно записываем ВСЕ данные включая новые поля
                    breakdown = result.get('breakdown', {}) or {}
                    flags = result.get('flags', {}) or {}
                    channel_health = result.get('channel_health', {}) or {}
                    conviction = result.get('conviction', {}) or {}
                    raw_stats = result.get('raw_stats', {}) or {}

                    # v23.0: Compress breakdown for storage (after extracting values below)
                    breakdown_compressed = compress_breakdown(breakdown)

                    success = self.db.claim_and_complete(
                        username=username,
                        status=result['status'],
                        score=result.get('score', 0),
                        verdict=result.get('verdict', ''),
                        trust_factor=result.get('trust_factor', 1.0),
                        members=result.get('members', 0),
                        ad_links=result.get('ad_links'),
                        category=result.get('category'),
                        breakdown=breakdown_compressed,
                        categories=result.get('categories'),
                        llm_analysis=breakdown.get('llm_analysis') if breakdown else None,
                        title=result.get('title'),
                        description=result.get('description'),
                        content_json=result.get('content_json'),
                        # v56.0: Новые поля для полного хранения данных
                        raw_score=result.get('raw_score'),
                        is_scam=result.get('is_scam', False),
                        scam_reason=result.get('scam_reason'),
                        tier=result.get('tier'),
                        trust_penalties=result.get('trust_penalties'),
                        conviction_score=conviction.get('effective_conviction'),
                        conviction_factors=conviction if conviction else None,
                        forensics=result.get('forensics'),
                        online_count=channel_health.get('online_count'),
                        participants_count=channel_health.get('participants_count'),
                        channel_age_days=breakdown.get('age', {}).get('value') if breakdown.get('age') else None,
                        avg_views=raw_stats.get('avg_views'),
                        reach_percent=breakdown.get('reach', {}).get('value') if breakdown.get('reach') else None,
                        forward_rate=breakdown.get('forward_rate', {}).get('value') if breakdown.get('forward_rate') else None,
                        reaction_rate=breakdown.get('reaction_rate', {}).get('value') if breakdown.get('reaction_rate') else None,
                        avg_comments=breakdown.get('comments', {}).get('avg') if breakdown.get('comments') else None,
                        comments_enabled=flags.get('comments_enabled', True),
                        reactions_enabled=flags.get('reactions_enabled', True),
                        decay_ratio=breakdown.get('views_decay', {}).get('value') if breakdown.get('views_decay') else None,
                        decay_zone=breakdown.get('views_decay', {}).get('zone') if breakdown.get('views_decay') else None,
                        er_trend=breakdown.get('er_trend', {}).get('er_trend') if breakdown.get('er_trend') else None,
                        er_trend_status=breakdown.get('er_trend', {}).get('status') if breakdown.get('er_trend') else None,
                        ad_percentage=breakdown.get('llm_analysis', {}).get('ad_percentage') if breakdown.get('llm_analysis') else None,
                        bot_percentage=breakdown.get('llm_analysis', {}).get('bot_percentage') if breakdown.get('llm_analysis') else None,
                        comment_trust=breakdown.get('llm_analysis', {}).get('trust_score') if breakdown.get('llm_analysis') else None,
                        safety=result.get('safety'),
                        posts_raw=result.get('posts_raw'),
                        user_ids=result.get('user_ids'),
                        linked_chat_id=result.get('linked_chat_id'),
                        linked_chat_title=result.get('linked_chat_title'),
                        # v68.0: Аватарка канала
                        photo_blob=result.get('photo_blob'),
                        # v69.0: Индикатор рекламы и AI описание
                        ad_status=result.get('ad_status'),
                        ai_summary=result.get('ai_summary'),
                    )

                    if not success:
                        # v43.0: Канал уже обработан другим краулером
                        print(f"[SKIP] @{username} уже обработан")
                        continue

                # v42.0: Чистый компактный вывод (только GOOD и BAD)
                # v50.0: Улучшенный вывод с таймингами и подробностями
                num = self.processed_count + 1
                cat = result.get('category') or ''
                ad = result.get('ad_pct')
                bot = result.get('bot_pct')
                members = result.get('members', 0)
                trust = result.get('trust_factor', 1.0)
                elapsed = result.get('elapsed', 0)
                score = result.get('score', 0)

                # Форматируем подписчиков (1.2K, 15K, 1.2M)
                if members >= 1_000_000:
                    members_str = f"{members/1_000_000:.1f}M"
                elif members >= 1_000:
                    members_str = f"{members/1_000:.1f}K"
                else:
                    members_str = str(members)

                # Форматируем ad/bot
                ad_str = f"{ad}%" if ad is not None else "—"
                bot_str = f"{bot}%" if bot is not None else "—"

                # v45.0: Brand Safety плашка
                safety = result.get('safety')
                toxic_str = ""
                if safety and safety.get('is_toxic'):
                    toxic_cat = safety.get('category', 'TOXIC')
                    toxic_str = f" [{toxic_cat}]"

                # Trust penalty indicator
                trust_str = "" if trust >= 0.95 else f" T:{trust:.2f}"

                if result['status'] == 'GOOD':
                    new_str = f" +{result['new_channels']}" if result.get('new_channels') else ""
                    print(f"[{num}] OK @{username} | {cat} | {members_str} | {score}pt{trust_str} | ad:{ad_str} bot:{bot_str} | {elapsed:.1f}s{new_str}")
                elif result['status'] == 'BAD':
                    print(f"[{num}] NO @{username} | {cat or 'BAD'} | {members_str} | {score}pt{trust_str} | ad:{ad_str} bot:{bot_str} | {elapsed:.1f}s{toxic_str}")
                elif result['status'] == 'ERROR':
                    print(f"[{num}] ER @{username} | ERROR: {result.get('verdict', 'unknown')} | {elapsed:.1f}s")

                self.processed_count += 1
                self.new_links_count += result.get('new_channels', 0)

                # v61.2: Real-time sync через HTTP API (не копирует БД, отправляет JSON)
                if result['status'] in ('GOOD', 'BAD'):
                    try:
                        # Формируем JSON для UI (с categories)
                        breakdown_json_str = json.dumps({
                            'breakdown': breakdown_compressed,
                            'categories': result.get('categories', {}),
                            'flags': flags
                        }, ensure_ascii=False) if breakdown_compressed else None

                        sync_data = {
                            "username": username,
                            "status": result['status'],
                            "score": result.get('score'),
                            "verdict": result.get('verdict'),
                            "trust_factor": result.get('trust_factor'),
                            "members": result.get('members'),
                            "category": result.get('category'),
                            "breakdown_json": breakdown_json_str,
                            "title": result.get('title'),
                            "description": result.get('description'),
                        }
                        sync_channel(sync_data)
                    except Exception as e:
                        logger.warning(f"Sync error for {result.get('username')}: {e}")

        except KeyboardInterrupt:
            # v43.0: При Ctrl+C текущий канал остаётся WAITING — никаких потерь!
            print("\n\nОстановка по Ctrl+C (данные не потеряны)...")

        finally:
            await self.stop()

            # v61.0: Отправляем БД на сервер после завершения
            try:
                push_database()
            except Exception as e:
                print(f"[!] Ошибка отправки БД: {e}")

            # v41.1: Компактная финальная статистика
            stats = self.db.get_stats()
            print(f"\n{'-'*50}")
            print(f"Сессия: {self.processed_count} каналов | +{self.new_links_count} ссылок")
            print(f"База: {stats['good']} GOOD | {stats['bad']} BAD | {stats['waiting']} в очереди")

            # v41.1: Категории в одну строку
            cat_stats = self.db.get_category_stats()
            if cat_stats:
                cats = [f"{c}:{n}" for c, n in list(cat_stats.items())[:8]]
                print(f"Категории: {' | '.join(cats)}")

            # Закрываем базу
            self.db.close()
