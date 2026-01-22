"""
CLI модуль для сканирования каналов.
v48.0: Business-Oriented Scoring System

Формула: Final Score = min((Raw Score + LLM Bonus) × Trust Factor × LLM Trust Factor, Tier Cap)

RAW SCORE (0-100) - "витрина":
- КАЧЕСТВО: 42 балла (cv_views 12, reach 8, regularity 7, forward_rate 15)
- ENGAGEMENT: 38 баллов (comments 15, er_trend 10, reactions 8, stability 5)
- РЕПУТАЦИЯ: 20 баллов (verified 0, age 7, premium 7, source 6)

TRUST FACTOR (0.0-1.0) - мультипликатор доверия:
- Forensics (ID Clustering, Geo/DC, Premium)
- Statistical Trust (Hollow Views, Zombie Engagement, Satellite)
- Ghost Protocol (Ghost Channel, Zombie Audience, Member Discrepancy)
- Decay Trust (Bot Wall ×0.6, Budget Cliff)

LLM ANALYSIS (v38.0):
- Tier система: PREMIUM/STANDARD/LIMITED/RESTRICTED/EXCLUDED
- Brand Safety: toxicity, violence, political_quantity, political_risk
- Comment Analysis: bot_percentage, trust_score (v41.0: authenticity removed)
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

import requests

# Фикс для Windows консоли - поддержка unicode
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from .client import get_client, smart_scan
from .scorer import calculate_final_score
from .llm_analyzer import LLMAnalyzer, LLMAnalysisResult, OLLAMA_URL, OLLAMA_MODEL
from .classifier import get_classifier
from .config import ensure_ollama_running, check_ollama_available
from .database import CrawlerDB
from .metrics import get_message_reactions_count  # v57.0: для posts_raw
from .json_compression import (
    compress_breakdown, compress_posts_raw, compress_user_ids
)  # v57.0: JSON compression


async def scan_channel(channel: str) -> dict:
    """
    Сканирует канал и возвращает результат анализа.
    v38.0: Интеграция LLM анализа (Ollama обязателен).

    Args:
        channel: username канала (с @ или без)

    Returns:
        dict с результатами анализа
    """
    # v43.1: Проверяем и запускаем Ollama если не работает
    try:
        ensure_ollama_running()
    except RuntimeError as e:
        print(f"\n❌ ОШИБКА: {e}")
        print("\nOllama обязателен для работы сканера!")
        print("Инструкция:")
        print("  1. Установи Ollama: https://ollama.ai")
        print("  2. Запусти сервер: ollama serve")
        print(f"  3. Установи модель: ollama pull {OLLAMA_MODEL}")
        sys.exit(1)

    async with get_client() as client:
        print(f"Подключение к Telegram...")

        # v15.0: smart_scan - 3 API запроса (включая GetFullChannel)
        scan_result = await smart_scan(client, channel)

        chat = scan_result.chat
        messages = scan_result.messages
        comments_data = scan_result.comments_data
        users = scan_result.users
        channel_health = scan_result.channel_health  # v15.0: Ghost Protocol

        print(f"Получено {len(messages)} сообщений из @{chat.username or chat.id}")
        if comments_data['enabled']:
            print(f"Комментарии: {comments_data['total_comments']} (avg {comments_data['avg_comments']:.1f})")

        # v7.0: Forensics данные
        print(f"User Forensics: {len(users)} юзеров для анализа")

        # v15.0: Ghost Protocol данные
        if channel_health.get('status') == 'complete':
            online = channel_health.get('online_count', 0)
            print(f"Ghost Protocol: {online:,} юзеров онлайн")

        # v38.0: LLM анализ
        print("\n--- LLM ANALYSIS ---")
        llm_analyzer = LLMAnalyzer()

        # Собираем комментарии из comments_data
        # v41.0: comments_data['comments'] — это список текстов комментариев (не dict)
        comments_list = []
        if comments_data.get('enabled'):
            comments_list = comments_data.get('comments', [])

        # v38.3: Получаем категорию из classifier для category-aware LLM анализа
        classifier = get_classifier()
        category = await classifier.classify_sync(
            channel_id=getattr(chat, 'id', 0),
            title=getattr(chat, 'title', ''),
            description=getattr(chat, 'description', ''),
            messages=messages
        )
        if not category:
            category = "DEFAULT"
        print(f"Category: {category}")

        llm_result = llm_analyzer.analyze(
            channel_id=getattr(chat, 'id', 0),
            messages=messages,
            comments=comments_list,
            category=category
        )

        # v38.0: передаём llm_result в scorer
        result = calculate_final_score(chat, messages, comments_data, users, channel_health, llm_result=llm_result)

        # v57.0: Собираем posts_raw для полного хранения
        posts_raw = [{
            'id': m.id if hasattr(m, 'id') else None,
            'date': m.date.isoformat() if hasattr(m, 'date') and m.date else None,
            'views': getattr(m, 'views', 0) or 0,
            'forwards': getattr(m, 'forwards', 0) or 0,
            'reactions': get_message_reactions_count(m) if hasattr(m, 'reactions') else 0,
        } for m in messages[:50]]
        result['posts_raw'] = compress_posts_raw(posts_raw)

        # v57.0: Собираем user_ids для пересчёта forensics
        user_ids = None
        if users:
            users_list = users if isinstance(users, list) else list(users.values())
            user_ids = {
                'ids': [u.id for u in users_list if hasattr(u, 'id') and u.id],
                'premium_ids': [u.id for u in users_list if hasattr(u, 'id') and u.id and getattr(u, 'is_premium', False)],
            }
            result['user_ids'] = compress_user_ids(user_ids)

        # v22.0: Аватарки загружаются через /api/photo/{username}, не храним base64
        result['photo_url'] = None

        # Добавляем метаданные
        result['scan_time'] = datetime.now().isoformat()
        result['title'] = getattr(chat, 'title', None)
        result['description'] = getattr(chat, 'description', None)

        # v57.0: Добавляем channel_health и scan_result для save_to_database
        result['channel_health'] = channel_health
        result['linked_chat_id'] = getattr(scan_result, 'linked_chat_id', None)
        result['linked_chat_title'] = getattr(scan_result, 'linked_chat_title', None)

        # v38.0: Сериализация LLM результата для сохранения в БД
        if llm_result:
            result['llm_analysis'] = {
                'tier': llm_result.tier,
                'tier_cap': llm_result.tier_cap,
                'exclusion_reason': llm_result.exclusion_reason,
                'llm_bonus': round(llm_result.llm_bonus, 2),
                'llm_trust_factor': round(llm_result.llm_trust_factor, 3),
                'posts': {
                    'brand_safety': llm_result.posts.brand_safety,
                    'toxicity': llm_result.posts.toxicity,
                    'violence': llm_result.posts.violence,
                    'military_conflict': llm_result.posts.military_conflict,  # V2.0
                    'political_quantity': llm_result.posts.political_quantity,
                    'political_risk': llm_result.posts.political_risk,
                    'misinformation': llm_result.posts.misinformation,
                    'ad_percentage': llm_result.posts.ad_percentage,
                    'red_flags': llm_result.posts.red_flags,
                } if llm_result.posts else None,
                'comments': {
                    # v41.0: authenticity REMOVED (duplicate of bot_percentage)
                    'bot_percentage': llm_result.comments.bot_percentage,
                    'bot_signals': llm_result.comments.bot_signals,
                    'trust_score': llm_result.comments.trust_score,
                    'trust_signals': llm_result.comments.trust_signals,
                } if llm_result.comments else None,
            }

            # v46.0: Brand Safety из LLM
            if llm_result.safety:
                result['safety'] = llm_result.safety

        return result


def print_result(result: dict) -> None:
    """v15.2: Красиво выводит результат с категориями и Floating Weights."""
    print("\n" + "=" * 60)
    print(f"КАНАЛ: @{result['channel']}")
    print(f"Название: {result.get('title', 'N/A')}")
    print(f"Подписчики: {result['members']:,}")
    print("=" * 60)

    # Цвета
    verdict_colors = {
        'EXCELLENT': '\033[92m',  # Зелёный
        'GOOD': '\033[94m',       # Синий
        'MEDIUM': '\033[93m',     # Жёлтый
        'HIGH_RISK': '\033[91m',  # Красный
        'SCAM': '\033[91m\033[1m', # Красный жирный
        'NEW_CHANNEL': '\033[96m' # v37.2: Голубой для новых каналов
    }
    reset = '\033[0m'
    red = '\033[91m'
    green = '\033[92m'
    cyan = '\033[96m'
    yellow = '\033[93m'

    verdict = result['verdict']
    color = verdict_colors.get(verdict, '')
    scoring_mode = result.get('scoring_mode', 'normal')
    mode_color = '\033[95m' if scoring_mode == 'hardcore' else cyan

    # v13.0: Trust Multiplier System
    raw_score = result.get('raw_score', result.get('score', 0))
    trust_factor = result.get('trust_factor', 1.0)
    final_score = result.get('score', 0)

    # Цвет для Trust Factor
    if trust_factor >= 0.9:
        trust_color = green
    elif trust_factor >= 0.6:
        trust_color = yellow
    else:
        trust_color = red

    print(f"\n{cyan}--- TRUST MULTIPLIER SYSTEM (v15.4) ---{reset}")
    print(f"  Raw Score:    {raw_score}/100 (витрина)")
    print(f"  Trust Factor: {trust_color}×{trust_factor:.2f}{reset}")
    print(f"  {color}Final Score:  {final_score}/100{reset}")

    print(f"\n{color}ВЕРДИКТ: {verdict}{reset}")
    print(f"РЕЖИМ: {mode_color}{scoring_mode.upper()}{reset}")

    if result.get('reason'):
        print(f"{red}ПРИЧИНА: {result['reason']}{reset}")

    # v13.0: Trust Penalties (если есть)
    trust_details = result.get('trust_details', {})
    if trust_details:
        print(f"\n{red}--- TRUST PENALTIES ---{reset}")
        for key, detail in trust_details.items():
            mult = detail.get('multiplier', 1.0)
            reason = detail.get('reason', '')
            print(f"  {key}: ×{mult:.1f} ({reason})")

    # v13.0: Категории (без reliability)
    categories = result.get('categories', {})
    if categories:
        print(f"\n{cyan}--- КАТЕГОРИИ ---{reset}")

        cat_names = {
            'quality': 'КАЧЕСТВО',
            'engagement': 'ENGAGEMENT',
            'reputation': 'РЕПУТАЦИЯ'
        }

        for cat_key, cat_name in cat_names.items():
            cat_data = categories.get(cat_key, {})
            score = cat_data.get('score', 0)
            max_pts = cat_data.get('max', 0)

            # Цвет по проценту заполнения
            if max_pts > 0:
                pct = score / max_pts * 100
                if pct >= 70:
                    cat_color = green
                elif pct >= 40:
                    cat_color = yellow
                else:
                    cat_color = red
            else:
                cat_color = reset

            print(f"  {cat_name}: {cat_color}{score}/{max_pts}{reset}")

    # Детальный breakdown
    breakdown = result.get('breakdown', {})
    if breakdown:
        print(f"\n--- BREAKDOWN (Raw Score) ---")

        # v48.0: Метрики Raw Score (views_decay → info only, er_variation → удалён)
        quality_keys = ['cv_views', 'reach', 'regularity', 'forward_rate', 'views_decay']
        engagement_keys = ['comments', 'er_trend', 'reaction_rate', 'reaction_stability']
        reputation_keys = ['verified', 'age', 'premium', 'source_diversity']

        def print_metrics(keys: list, title: str):
            print(f"  {title}:")
            for key in keys:
                data = breakdown.get(key, {})
                if isinstance(data, dict) and 'points' in data:
                    pts = data['points']
                    max_pts = data.get('max', 0)
                    value = data.get('value', 'N/A')

                    # Маркеры
                    markers = []
                    if data.get('floating_boost'):
                        markers.append('[FLOAT]')
                    if data.get('floating_weights'):
                        markers.append('[FLOAT]')  # v15.2: для комментариев и реакций
                    if data.get('viral_exception'):
                        markers.append('[VIRAL]')
                    if data.get('growth_trend'):
                        markers.append('[GROWTH]')

                    # v15.1: Зона для decay
                    zone = data.get('zone')
                    if zone:
                        zone_colors = {
                            'healthy_organic': green,
                            'viral_growth': green,
                            'stable': cyan,
                            'bot_wall': red,
                            'budget_cliff': red,
                            'suspicious_gap': yellow,
                            'suspicious_growth': yellow
                        }
                        zone_color = zone_colors.get(zone, reset)
                        markers.append(f'{zone_color}[{zone.upper()}]{reset}')

                    marker_str = ' ' + ' '.join(markers) if markers else ''

                    # v15.2: Улучшенный вывод для source_diversity
                    if key == 'source_diversity':
                        repost_ratio = data.get('repost_ratio', 0)
                        repost_pct = repost_ratio * 100
                        # value = 1 - source_max_share, поэтому source_max_share = 1 - value
                        diversity_value = value if isinstance(value, (int, float)) else 1.0
                        source_max_share = 1 - diversity_value  # концентрация из одного источника
                        source_pct = source_max_share * 100

                        if repost_pct > 0:
                            print(f"    {key}: {pts}/{max_pts} (репостов {repost_pct:.0f}%, концентрация {source_pct:.0f}%){marker_str}")
                        # v15.3: Если репостов нет — не показываем строку вообще
                    else:
                        print(f"    {key}: {pts}/{max_pts} ({value}){marker_str}")

        print_metrics(quality_keys, 'Качество')
        print_metrics(engagement_keys, 'Engagement')
        print_metrics(reputation_keys, 'Репутация')

        # v13.0: Info-only данные (влияют на Trust Factor)
        ad_load = breakdown.get('ad_load', {})
        if ad_load:
            print(f"\n  Trust Factor Data:")
            print(f"    ad_load: {ad_load.get('value', 0)}% ({ad_load.get('status', 'N/A')})")

            regularity = breakdown.get('regularity', {})
            if regularity:
                print(f"    regularity: CV {regularity.get('value', 'N/A')}")

            # v15.0: Posting Frequency
            posting = breakdown.get('posting_frequency', {})
            if posting and posting.get('posts_per_day', 0) > 0:
                posts_day = posting['posts_per_day']
                status = posting.get('status', 'normal')
                trust_mult = posting.get('trust_multiplier', 1.0)
                if trust_mult < 1.0:
                    print(f"    {yellow}posting: {posts_day:.1f}/день [{status.upper()}] ×{trust_mult}{reset}")
                else:
                    print(f"    posting: {posts_day:.1f}/день [{status}]")

            # v15.0: Private Links
            private = breakdown.get('private_links', {})
            if private and private.get('total_ad_posts', 0) > 0:
                priv_ratio = private.get('private_ratio', 0)
                trust_mult = private.get('trust_multiplier', 1.0)
                if priv_ratio > 0.3:
                    print(f"    {yellow}private_links: {priv_ratio*100:.0f}% приватных ×{trust_mult}{reset}")
                elif priv_ratio > 0:
                    print(f"    private_links: {priv_ratio*100:.0f}% приватных")

    # v38.0: LLM Analysis
    llm = result.get('llm_analysis')
    if llm:
        print(f"\n{cyan}--- LLM ANALYSIS v38.0 ---{reset}")

        # Tier и Cap
        tier = llm.get('tier', 'STANDARD')
        tier_cap = llm.get('tier_cap', 100)
        exclusion = llm.get('exclusion_reason')

        tier_colors = {
            'PREMIUM': green,
            'STANDARD': cyan,
            'LIMITED': yellow,
            'RESTRICTED': '\033[91m',  # red
            'EXCLUDED': '\033[91m\033[1m'  # red bold
        }
        tier_color = tier_colors.get(tier, reset)

        print(f"  Tier: {tier_color}{tier}{reset} (cap={tier_cap})")
        if exclusion:
            print(f"  {red}⛔ EXCLUDED: {exclusion}{reset}")

        llm_bonus = llm.get('llm_bonus', 0)
        llm_trust = llm.get('llm_trust_factor', 1.0)
        print(f"  LLM Bonus: +{llm_bonus:.1f} points")
        print(f"  LLM Trust: ×{llm_trust:.2f}")

        # V2.1: Post Analysis отключен — бесполезные метрики
        # toxicity, violence, political — человек сам видит

        # Comments analysis
        comments = llm.get('comments')
        if comments:
            print(f"\n  💬 COMMENT ANALYSIS:")
            # v41.0: authenticity REMOVED (duplicate of bot_percentage)

            bot_pct = comments.get('bot_percentage', 0)
            bot_color = green if bot_pct < 20 else (yellow if bot_pct < 50 else red)
            print(f"     Bots: {bot_color}{bot_pct}%{reset}")

            trust = comments.get('trust_score', 0)
            trust_color = green if trust >= 60 else (yellow if trust >= 30 else red)
            print(f"     Trust Score: {trust_color}{trust}/100{reset}")

            bot_signals = comments.get('bot_signals', [])
            if bot_signals:
                print(f"     Bot Signals: {bot_signals[:3]}")

            trust_signals = comments.get('trust_signals', [])
            if trust_signals:
                print(f"     Trust Signals: {trust_signals[:3]}")

    # User Forensics
    forensics = result.get('forensics')
    if forensics and forensics.get('status') == 'complete':
        print(f"\n{cyan}--- USER FORENSICS ---{reset}")
        print(f"  Юзеров: {forensics.get('users_analyzed', 0)}")

        # ID Clustering (v13.0: с градацией)
        clustering = forensics.get('id_clustering', {})
        ratio = clustering.get('neighbor_ratio', 0)
        if clustering.get('fatality'):
            print(f"  {red}ID Clustering: FATALITY{reset} ({ratio:.0%} соседних ID)")
        elif clustering.get('suspicious'):
            print(f"  {yellow}ID Clustering: SUSPICIOUS{reset} ({ratio:.0%} соседних ID)")
        else:
            print(f"  ID Clustering: {green}OK{reset} ({ratio:.0%} соседей)")

        # Geo/DC Check
        geo = forensics.get('geo_dc_check', {})
        if geo.get('triggered'):
            print(f"  {red}Geo/DC: TRIGGERED{reset} ({geo.get('foreign_ratio', 0):.0%} foreign)")
        else:
            print(f"  Geo/DC: {green}OK{reset}")

        # Premium (v15.3: N/A при малой выборке)
        users_analyzed = forensics.get('users_analyzed', 0)
        premium = forensics.get('premium_density', {})
        ratio = premium.get('premium_ratio', 0)
        if users_analyzed < 10:
            print(f"  Premium: {yellow}N/A{reset} (мало данных, {users_analyzed} юзеров)")
        elif premium.get('is_bonus'):
            print(f"  {green}Premium: {ratio:.1%}{reset}")
        elif premium.get('triggered'):
            print(f"  {red}Premium: {ratio:.1%}{reset}")
        else:
            print(f"  Premium: {ratio:.1%}")

    elif forensics and forensics.get('status') == 'FATALITY':
        print(f"\n{red}USER FORENSICS: FATALITY - ФЕРМА БОТОВ{reset}")

    # v15.0: Channel Health (Ghost Protocol)
    health = result.get('channel_health', {})
    if health and health.get('status') == 'complete':
        print(f"\n{cyan}--- CHANNEL HEALTH (v15.0) ---{reset}")
        online = health.get('online_count', 0)
        members = result.get('members', 1)
        ratio = (online / members * 100) if members > 0 else 0

        # Цвет по online ratio
        if ratio < 0.1:
            health_color = red
        elif ratio < 0.3:
            health_color = yellow
        else:
            health_color = green

        print(f"  Online: {health_color}{online:,}{reset} ({ratio:.2f}% от {members:,})")
        print(f"  Admins: {health.get('admins_count', 0)}")
        print(f"  Banned: {health.get('banned_count', 0)}")

        # Показать discrepancy если есть
        participants = health.get('participants_count', 0)
        if participants > 0 and abs(participants - members) > members * 0.05:
            disc_color = yellow if abs(participants - members) < members * 0.1 else red
            print(f"  Participants: {disc_color}{participants:,}{reset} (vs {members:,})")

    # Raw stats
    print("\n--- RAW STATS ---")
    for key, value in result.get('raw_stats', {}).items():
        if isinstance(value, (int, float)):
            print(f"  {key}: {value:,}" if isinstance(value, int) else f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")

    # Flags
    flags = result.get('flags', {})
    active_flags = [k for k, v in flags.items() if v]
    if active_flags:
        print(f"\n--- FLAGS: {', '.join(active_flags)} ---")


def save_result(result: dict, output_path: Path) -> None:
    """Сохраняет результат в JSON файл."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nРезультат сохранён: {output_path}")


def save_to_database(result: dict) -> None:
    """v57.0: Сохраняет результат скана в базу данных с полными данными и compression."""
    try:
        db = CrawlerDB()
        username = result.get('channel', '').lower()
        if not username:
            return

        # Определяем статус по verdict
        verdict = result.get('verdict', 'MEDIUM')
        if verdict in ('EXCELLENT', 'GOOD'):
            status = 'GOOD'
        elif verdict == 'SCAM':
            status = 'BAD'
        else:
            status = 'GOOD'  # MEDIUM, HIGH_RISK тоже сохраняем как GOOD

        # Добавляем канал если не существует
        db.add_channel(username)

        # v57.0: Собираем все данные для claim_and_complete
        breakdown = result.get('breakdown', {}) or {}
        flags = result.get('flags', {}) or {}
        channel_health = result.get('channel_health', {}) or {}
        conviction = result.get('conviction', {}) or {}
        raw_stats = result.get('raw_stats', {}) or {}

        # v57.0: Compress breakdown для хранения
        breakdown_compressed = compress_breakdown(breakdown)

        # v57.0: Используем claim_and_complete с полным набором данных
        db.claim_and_complete(
            username=username,
            status=status,
            score=result.get('score', 0),
            verdict=verdict,
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
            # v56.0: Новые поля
            raw_score=result.get('raw_score'),
            is_scam=result.get('is_scam', False),
            scam_reason=result.get('scam_reason'),
            tier=result.get('tier'),
            trust_penalties=result.get('trust_details'),
            conviction_score=conviction.get('effective_conviction') if conviction else None,
            conviction_factors=conviction.get('factors') if conviction else None,
            forensics=result.get('forensics'),
            online_count=channel_health.get('online_count') if channel_health else None,
            participants_count=channel_health.get('total_members') if channel_health else None,
            channel_age_days=breakdown.get('age', {}).get('value') if breakdown.get('age') else None,
            avg_views=raw_stats.get('avg_views') if raw_stats else None,
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
        )

        print(f"✓ Сохранено в БД: @{username} ({status})")

    except Exception as e:
        print(f"⚠ Ошибка сохранения в БД: {e}")


async def main(channel: str = None):
    """Главная функция CLI."""
    if not channel:
        if len(sys.argv) > 1:
            channel = sys.argv[1]
        else:
            print("Использование: python -m scanner.cli @channel_name")
            sys.exit(1)

    try:
        result = await scan_channel(channel)
        print_result(result)

        # Сохраняем результат в JSON
        output_dir = Path(__file__).parent.parent / "output"
        channel_name = result['channel'] or 'unknown'
        output_path = output_dir / f"{channel_name}.json"
        save_result(result, output_path)

        # v54.0: Сохраняем в базу данных
        save_to_database(result)

        return result

    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
