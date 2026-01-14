"""
CLI модуль для сканирования каналов.
v7.0: Low-Profile Scanner с User Forensics.
v7.1: Adaptive Paranoia Mode - показывает режим скоринга (Normal/Hardcore).
v11.0: Executioner System - отображение FATALITY, Geo/DC Check, Premium Density.
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
    v7.0: Low-Profile сканирование с User Forensics.

    Args:
        channel: username канала (с @ или без)

    Returns:
        dict с результатами анализа
    """
    async with get_client() as client:
        print(f"Подключение к Telegram...")

        # v7.0: smart_scan - всего 2 API запроса
        scan_result = await smart_scan(client, channel)

        chat = scan_result.chat
        messages = scan_result.messages
        comments_data = scan_result.comments_data
        users = scan_result.users

        print(f"Получено {len(messages)} сообщений из @{chat.username or chat.id}")
        if comments_data['enabled']:
            print(f"Комментарии: {comments_data['total_comments']} (avg {comments_data['avg_comments']:.1f})")

        # v7.0: Forensics данные
        print(f"User Forensics: {len(users)} юзеров для анализа")

        # v7.0: передаём users для Forensics анализа
        result = calculate_final_score(chat, messages, comments_data, users)

        # Добавляем метаданные
        result['scan_time'] = datetime.now().isoformat()
        result['title'] = getattr(chat, 'title', None)
        result['description'] = getattr(chat, 'description', None)

        return result


def print_result(result: dict) -> None:
    """Красиво выводит результат в консоль."""
    print("\n" + "=" * 60)
    print(f"КАНАЛ: @{result['channel']}")
    print(f"Название: {result.get('title', 'N/A')}")
    print(f"Подписчики: {result['members']:,}")
    print("=" * 60)

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

    verdict = result['verdict']
    color = verdict_colors.get(verdict, '')

    # v7.1: Показываем режим скоринга
    scoring_mode = result.get('scoring_mode', 'normal')
    mode_color = '\033[95m' if scoring_mode == 'hardcore' else '\033[96m'  # Magenta для Hardcore, Cyan для Normal

    print(f"\nСКОР: {color}{result['score']}/100{reset}")
    print(f"ВЕРДИКТ: {color}{verdict}{reset}")
    print(f"РЕЖИМ: {mode_color}{scoring_mode.upper()}{reset}")

    if result.get('reason'):
        print(f"ПРИЧИНА: {result['reason']}")

    print("\n--- BREAKDOWN ---")
    for key, data in result.get('breakdown', {}).items():
        if key in ('forensics', 'hidden_penalty', 'reaction_flatness'):
            continue  # Выводим отдельно
        if isinstance(data, dict) and 'points' in data:
            boost_marker = " [BOOSTED]" if data.get('hardcore_boost') else ""
            print(f"  {key}: {data['points']}/{data['max']} (value: {data['value']}){boost_marker}")

    # v11.0: Секция User Forensics - Executioner System
    forensics = result.get('breakdown', {}).get('forensics', {})
    if forensics:
        print("\n--- USER FORENSICS (v11.0 Executioner) ---")
        status = forensics.get('status', 'unknown')
        users_analyzed = forensics.get('users_analyzed', 0)
        total_penalty = forensics.get('total_penalty', 0)

        print(f"  Статус: {status}")
        print(f"  Юзеров проанализировано: {users_analyzed}")

        # v11.0: Показываем результат (штраф или бонус)
        if total_penalty < 0:
            print(f"  Итого: {red}{total_penalty}{reset}")
        elif total_penalty > 0:
            print(f"  Итого: {green}+{total_penalty}{reset} (Premium Bonus)")
        else:
            print(f"  Итого: 0")

        if status == 'complete':
            # Method 1: ID Clustering (FATALITY -100)
            clustering = forensics.get('id_clustering', {})
            if clustering.get('fatality'):
                print(f"    {red}☠️ ID CLUSTERING: FATALITY{reset} ({clustering.get('penalty', 0)})")
                print(f"      {clustering.get('description', '')}")
            elif clustering.get('triggered'):
                print(f"    ID Clustering: {red}TRIGGERED{reset} ({clustering.get('penalty', 0)})")
                print(f"      {clustering.get('description', '')}")
            else:
                ratio = clustering.get('neighbor_ratio', 0)
                print(f"    ID Clustering: {green}OK{reset} ({ratio:.0%} соседей)")

            # Method 2: Geo/DC Check (-50)
            geo = forensics.get('geo_dc_check', {})
            if geo.get('triggered'):
                print(f"    {red}🚨 GEO/DC CHECK: TRIGGERED{reset} ({geo.get('penalty', 0)})")
                print(f"      {geo.get('description', '')}")
                dc_dist = geo.get('dc_distribution', {})
                if dc_dist:
                    print(f"      DC distribution: {dc_dist}")
            else:
                foreign = geo.get('foreign_ratio', 0)
                users_dc = geo.get('users_with_dc', 0)
                print(f"    Geo/DC Check: {green}OK{reset} ({foreign:.0%} foreign, {users_dc} юзеров с фото)")

            # Method 3: Premium Density (-20 / +10)
            premium = forensics.get('premium_density', {})
            if premium.get('is_bonus'):
                print(f"    {green}💎 PREMIUM QUALITY:{reset} +{premium.get('penalty', 0)}")
                print(f"      {premium.get('description', '')}")
            elif premium.get('triggered'):
                print(f"    {red}⚠️ PREMIUM DENSITY:{reset} {premium.get('penalty', 0)}")
                print(f"      {premium.get('description', '')}")
            else:
                ratio = premium.get('premium_ratio', 0)
                print(f"    Premium Density: OK ({ratio:.1%} премиумов)")

            # Method 4: Hidden Flags (-10)
            flags = forensics.get('hidden_flags', {})
            if flags.get('triggered'):
                print(f"    Hidden Flags: {red}TRIGGERED{reset} ({flags.get('penalty', 0)})")
                print(f"      {flags.get('description', '')}")

        elif status == 'skipped':
            print(f"  {forensics.get('description', 'Нет данных')}")
        elif status == 'insufficient_data':
            print(f"  Недостаточно юзеров для анализа")

    # v7.1: Секция Hardcore Mode Penalties
    if scoring_mode == 'hardcore':
        print(f"\n--- {mode_color}HARDCORE PENALTIES{reset} ---")

        # Hidden Penalty
        hidden_penalty = result.get('breakdown', {}).get('hidden_penalty', {})
        if hidden_penalty:
            print(f"  Hidden Penalty: {red}{hidden_penalty.get('points', 0)}{reset}")
            print(f"    {hidden_penalty.get('description', '')}")

        # Reaction Flatness (F16)
        flatness = result.get('breakdown', {}).get('reaction_flatness', {})
        if flatness:
            if flatness.get('triggered'):
                print(f"  Reaction Flatness: {red}TRIGGERED{reset} ({flatness.get('penalty', 0)})")
                print(f"    {flatness.get('description', '')}")
            else:
                print(f"  Reaction Flatness: {green}OK{reset} (CV={flatness.get('cv', 0):.1f}%)")

    print("\n--- RAW STATS ---")
    for key, value in result.get('raw_stats', {}).items():
        print(f"  {key}: {value:,}" if isinstance(value, int) else f"  {key}: {value}")

    print("\n--- FLAGS ---")
    for key, value in result.get('flags', {}).items():
        print(f"  {key}: {value}")


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
