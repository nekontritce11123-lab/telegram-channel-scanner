"""
rescan_summaries.py - Генерация AI описаний для существующих каналов

v71.0: Миграция существующих каналов на ai_summary.
       Использует content_json из БД (посты уже сохранены).

Использование:
    python rescan_summaries.py              # Обработать все без ai_summary
    python rescan_summaries.py --limit 50   # Обработать первые 50
    python rescan_summaries.py --check      # Только статистика
"""

import os
import sys
import json
import sqlite3
import argparse

# Добавляем scanner в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner.summarizer import generate_channel_summary


def rescan_summaries(db_path: str = "crawler.db", limit: int = None, check_only: bool = False):
    """
    Генерирует ai_summary для каналов без описания.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Проверяем что колонка ai_summary существует
    cursor.execute("PRAGMA table_info(channels)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'ai_summary' not in columns:
        print("[ERROR] Колонка ai_summary не найдена!")
        print("Сначала запустите краулер для создания миграции.")
        conn.close()
        return

    # Получаем каналы без ai_summary
    query = """
        SELECT username, title, description, content_json
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
        AND (ai_summary IS NULL OR ai_summary = '')
        AND content_json IS NOT NULL
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    channels = cursor.fetchall()

    # Статистика
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN ai_summary IS NOT NULL AND ai_summary != '' THEN 1 ELSE 0 END) as with_summary,
            SUM(CASE WHEN content_json IS NOT NULL THEN 1 ELSE 0 END) as with_content
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
    """)
    stats = cursor.fetchone()
    total = stats['total']
    with_summary = stats['with_summary'] or 0
    with_content = stats['with_content'] or 0

    print(f"\n{'='*50}")
    print(f"AI Summary Migration v71.0")
    print(f"{'='*50}")
    print(f"Всего каналов (GOOD/BAD): {total}")
    print(f"С описанием:              {with_summary}")
    print(f"Без описания:             {total - with_summary}")
    print(f"С контентом:              {with_content}")
    print(f"Для обработки:            {len(channels)}")
    print(f"{'='*50}\n")

    if check_only:
        conn.close()
        return

    if not channels:
        print("Все каналы уже имеют описание!")
        conn.close()
        return

    success = 0
    failed = 0
    no_content = 0

    for i, channel in enumerate(channels, 1):
        username = channel['username']
        title = channel['title'] or username
        description = channel['description']

        try:
            # Парсим content_json
            content_json = channel['content_json']
            if not content_json:
                print(f"[{i}/{len(channels)}] @{username}: нет контента")
                no_content += 1
                continue

            content = json.loads(content_json)
            posts = content.get('posts', [])

            if not posts:
                print(f"[{i}/{len(channels)}] @{username}: нет постов")
                no_content += 1
                continue

            # Генерируем описание
            summary = generate_channel_summary(
                title=title,
                description=description,
                posts=posts,
                max_posts=10
            )

            if not summary:
                print(f"[{i}/{len(channels)}] @{username}: LLM не вернул описание")
                failed += 1
                continue

            # Сохраняем в БД
            cursor.execute(
                "UPDATE channels SET ai_summary = ? WHERE username = ?",
                (summary, username)
            )
            conn.commit()

            print(f"[{i}/{len(channels)}] @{username}: OK ({len(summary)} chars)")
            success += 1

        except json.JSONDecodeError as e:
            print(f"[{i}/{len(channels)}] @{username}: JSON error - {e}")
            failed += 1
        except Exception as e:
            print(f"[{i}/{len(channels)}] @{username}: ERROR - {type(e).__name__}: {e}")
            failed += 1

    conn.close()

    # Итоги
    print(f"\n{'='*50}")
    print(f"РЕЗУЛЬТАТ")
    print(f"{'='*50}")
    print(f"Успешно:      {success}")
    print(f"Без контента: {no_content}")
    print(f"Ошибки:       {failed}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Генерация AI описаний для каналов")
    parser.add_argument("--db", default="crawler.db", help="Путь к БД")
    parser.add_argument("--limit", type=int, help="Максимум каналов")
    parser.add_argument("--check", action="store_true", help="Только статистика")

    args = parser.parse_args()

    rescan_summaries(
        db_path=args.db,
        limit=args.limit,
        check_only=args.check
    )


if __name__ == "__main__":
    main()
