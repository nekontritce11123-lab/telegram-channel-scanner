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
import random
import json
from datetime import datetime
from typing import Optional

from pyrogram import Client

from .database import CrawlerDB
from .client import get_client, smart_scan_safe
from .scorer import calculate_final_score
from .classifier import get_classifier, ChannelClassifier
from .llm_analyzer import LLMAnalyzer

# v43.0: Централизованная конфигурация
from .config import GOOD_THRESHOLD, COLLECT_THRESHOLD, ensure_ollama_running


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


# Настройки rate limiting
RATE_LIMIT = {
    'between_channels': 5,      # Секунд между каналами
    'batch_size': 100,          # Каналов до большой паузы
    'batch_pause': 300,         # 5 минут отдыха
}

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
        print(f"✓ LLM Analyzer готов")

    async def stop(self):
        """Останавливает клиент и классификатор."""
        if self.classifier:
            self.classifier.save_cache()
            self.classifier.unload()  # v33: Выгружаем модель из GPU

        if self.client:
            await self.client.stop()
            print("Отключено от Telegram")

    def add_seeds(self, channels: list):
        """Добавляет начальные каналы в очередь."""
        added = 0
        for channel in channels:
            channel = channel.lower().lstrip('@')
            if self.db.add_channel(channel, parent="[seed]"):
                added += 1
                print(f"  + @{channel} добавлен в очередь")
            else:
                print(f"  - @{channel} уже в базе")
        return added

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
            # Исключаем служебные и популярные слова которые ложно срабатывают
            skip_words = {
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
            for match in re.findall(r't\.me/([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in skip_words:
                    links.add(match)

            # telegram.me/username
            for match in re.findall(r'telegram\.me/([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in skip_words:
                    links.add(match)

            # @упоминания
            for match in re.findall(r'@([a-zA-Z0-9_]{5,32})', text):
                match = match.lower()
                if match != channel_username and match not in skip_words:
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
                return result

        # v22.1: Извлекаем контент для хранения и переклассификации
        # Включает 50 постов + 30 комментариев для AI анализа
        content = extract_content_for_classification(
            scan_result.chat,
            scan_result.messages,
            comments_data=scan_result.comments_data,
            users=scan_result.users
        )

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
                    messages=scan_result.messages
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
            except (AttributeError, KeyError, TypeError) as e:
                # LLM анализ опционален - не прерываем сканирование
                pass

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

            result['score'] = score
            result['verdict'] = verdict
            result['trust_factor'] = trust_factor
            result['members'] = members

        except (KeyError, TypeError, AttributeError, ValueError) as e:
            # v43.0: Ошибки при расчёте — помечаем как ERROR для записи
            error_msg = f"{type(e).__name__}: {e}"
            result['status'] = 'ERROR'
            result['verdict'] = error_msg
            return result

        # v43.0: Заполняем result данными для claim_and_complete()
        result['breakdown'] = score_result.get('breakdown')
        result['categories'] = score_result.get('categories')
        result['title'] = content['title']
        result['description'] = content['description']
        result['content_json'] = content['content_json']

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
                await asyncio.sleep(5)  # Пауза перед следующим

            await asyncio.sleep(3)

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

        print(f"\nЗапускаю краулер (v43.0 all-or-nothing)...")
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
                    await asyncio.sleep(2)
                    continue

                # v43.0: Атомарная запись результата
                if result.get('delete'):
                    # Удаляем невалидный канал
                    self.db.delete_if_waiting(username)
                    continue

                if result['status'] in ('GOOD', 'BAD', 'ERROR'):
                    # Атомарно записываем ВСЕ данные
                    success = self.db.claim_and_complete(
                        username=username,
                        status=result['status'],
                        score=result.get('score', 0),
                        verdict=result.get('verdict', ''),
                        trust_factor=result.get('trust_factor', 1.0),
                        members=result.get('members', 0),
                        ad_links=result.get('ad_links'),
                        category=result.get('category'),
                        breakdown=result.get('breakdown'),
                        categories=result.get('categories'),
                        llm_analysis=result.get('breakdown', {}).get('llm_analysis') if result.get('breakdown') else None,
                        title=result.get('title'),
                        description=result.get('description'),
                        content_json=result.get('content_json'),
                    )

                    if not success:
                        # v43.0: Канал уже обработан другим краулером
                        print(f"[SKIP] @{username} уже обработан")
                        continue

                # v42.0: Чистый компактный вывод (только GOOD и BAD)
                num = self.processed_count + 1
                cat = result.get('category') or ''
                ad = result.get('ad_pct')
                bot = result.get('bot_pct')

                # Форматируем None как "—"
                ad_str = f"{ad}%" if ad is not None else "—"
                bot_str = f"{bot}%" if bot is not None else "—"
                llm_info = f"ad:{ad_str} bot:{bot_str}"

                if result['status'] == 'GOOD':
                    cat_str = f" · {cat}" if cat else ""
                    new_str = f" +{result['new_channels']}" if result.get('new_channels') else ""
                    print(f"[{num}] @{username}{cat_str} · {llm_info} · {result['score']} ✓{new_str}")
                elif result['status'] == 'BAD':
                    cat_str = f" · {cat}" if cat else ""
                    print(f"[{num}] @{username}{cat_str} · {llm_info} · {result['score']} ✗")
                elif result['status'] == 'ERROR':
                    print(f"[{num}] @{username} · ERROR: {result.get('verdict', 'unknown')}")

                self.processed_count += 1
                self.new_links_count += result.get('new_channels', 0)

                # Пауза между каналами
                pause = RATE_LIMIT['between_channels'] + random.uniform(-1, 2)
                await asyncio.sleep(pause)

                # Большая пауза каждые N каналов
                if self.processed_count % RATE_LIMIT['batch_size'] == 0:
                    print(f"\nПауза {RATE_LIMIT['batch_pause'] // 60} минут (обработано {self.processed_count})...")
                    await asyncio.sleep(RATE_LIMIT['batch_pause'])
                    print("Продолжаю...\n")

        except KeyboardInterrupt:
            # v43.0: При Ctrl+C текущий канал остаётся WAITING — никаких потерь!
            print("\n\nОстановка по Ctrl+C (данные не потеряны)...")

        finally:
            await self.stop()

            # v41.1: Компактная финальная статистика
            stats = self.db.get_stats()
            print(f"\n{'─'*50}")
            print(f"Сессия: {self.processed_count} каналов | +{self.new_links_count} ссылок")
            print(f"База: {stats['good']} GOOD | {stats['bad']} BAD | {stats['waiting']} в очереди")

            # v41.1: Категории в одну строку
            cat_stats = self.db.get_category_stats()
            if cat_stats:
                cats = [f"{c}:{n}" for c, n in list(cat_stats.items())[:8]]
                print(f"Категории: {' | '.join(cats)}")

            # Закрываем базу
            self.db.close()
