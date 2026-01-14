"""
CLI модуль для сканирования каналов.
v15.3: UX доработки - убран "оригинальный контент", Premium N/A при малой выборке.

Формула: Final Score = Raw Score × Trust Factor

RAW SCORE (0-100) - "витрина":
- КАЧЕСТВО: 40 баллов (cv_views, reach, decay, forward_rate)
- ENGAGEMENT: 40 баллов (comments, reactions, er_variation, stability)
- РЕПУТАЦИЯ: 20 баллов (verified, age, premium, source)

TRUST FACTOR (0.0-1.0) - мультипликатор доверия:
- Forensics (ID Clustering, Geo/DC, Premium)
- Statistical Trust (Hollow Views, Zombie Engagement, Satellite)
- Ghost Protocol (Ghost Channel, Zombie Audience, Member Discrepancy)
- Decay Trust (Bot Wall ×0.6, Budget Cliff) - v15.1
- v15.2: Satellite только при мёртвых комментах
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Фикс для Windows консоли - поддержка unicode
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from .client import get_client, smart_scan
from .scorer import calculate_final_score


async def scan_channel(channel: str) -> dict:
    """
    Сканирует канал и возвращает результат анализа.
    v15.0: Ghost Protocol сканирование (3 API запроса).

    Args:
        channel: username канала (с @ или без)

    Returns:
        dict с результатами анализа
    """
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

        # v15.0: передаём channel_health для Ghost Protocol
        result = calculate_final_score(chat, messages, comments_data, users, channel_health)

        # Добавляем метаданные
        result['scan_time'] = datetime.now().isoformat()
        result['title'] = getattr(chat, 'title', None)
        result['description'] = getattr(chat, 'description', None)

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
        'SCAM': '\033[91m\033[1m' # Красный жирный
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

    print(f"\n{cyan}--- TRUST MULTIPLIER SYSTEM (v15.3) ---{reset}")
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

        # v13.0: Только метрики Raw Score (без reliability)
        quality_keys = ['cv_views', 'reach', 'views_decay', 'forward_rate']
        engagement_keys = ['comments', 'reaction_rate', 'er_variation', 'reaction_stability']
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

        # Сохраняем результат
        output_dir = Path(__file__).parent.parent / "output"
        channel_name = result['channel'] or 'unknown'
        output_path = output_dir / f"{channel_name}.json"
        save_result(result, output_path)

        return result

    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
