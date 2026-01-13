"""
CLI модуль для сканирования каналов.
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

from .client import get_client, get_channel_data
from .scorer import calculate_final_score


async def scan_channel(channel: str) -> dict:
    """
    Сканирует канал и возвращает результат анализа.

    Args:
        channel: username канала (с @ или без)

    Returns:
        dict с результатами анализа
    """
    async with get_client() as client:
        print(f"Подключение к Telegram...")
        chat, messages, comments_data = await get_channel_data(client, channel)
        print(f"Получено {len(messages)} сообщений из @{chat.username or chat.id}")
        if comments_data['enabled']:
            print(f"Комментарии: {comments_data['total_comments']} (avg {comments_data['avg_comments']:.1f})")

        result = calculate_final_score(chat, messages, comments_data)

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

    verdict = result['verdict']
    color = verdict_colors.get(verdict, '')

    print(f"\nСКОР: {color}{result['score']}/100{reset}")
    print(f"ВЕРДИКТ: {color}{verdict}{reset}")

    if result.get('reason'):
        print(f"ПРИЧИНА: {result['reason']}")

    print("\n--- BREAKDOWN ---")
    for key, data in result.get('breakdown', {}).items():
        if isinstance(data, dict) and 'points' in data:
            print(f"  {key}: {data['points']}/{data['max']} (value: {data['value']})")

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
