"""
v69.1: Миграция ad_status для существующих каналов.
Запускается локально для пересчёта ad_status по описанию канала.

Использование:
    python migrate_ad_status.py           # Regex only (быстро)
    python migrate_ad_status.py --llm     # LLM + regex fallback (медленно, ~2 сек/канал)
"""
import sqlite3
import sys
from scanner.ad_detector import detect_ad_status

DB_PATH = 'crawler.db'


def migrate(use_llm: bool = False):
    """Пересчитывает ad_status для всех GOOD/BAD каналов."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Сначала проверяем/создаём колонку ad_status
    cursor.execute("PRAGMA table_info(channels)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'ad_status' not in columns:
        print("Добавляем колонку ad_status...")
        cursor.execute("ALTER TABLE channels ADD COLUMN ad_status INTEGER DEFAULT NULL")
        conn.commit()

    if 'ai_summary' not in columns:
        print("Добавляем колонку ai_summary...")
        cursor.execute("ALTER TABLE channels ADD COLUMN ai_summary TEXT DEFAULT NULL")
        conn.commit()

    # Получаем все каналы с описанием
    cursor.execute("""
        SELECT username, description
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
    """)
    rows = cursor.fetchall()

    mode = "LLM + regex fallback" if use_llm else "regex only"
    print(f"Найдено {len(rows)} каналов для обработки ({mode})")

    updated = 0
    stats = {0: 0, 1: 0, 2: 0}

    for username, description in rows:
        ad_status = detect_ad_status(description, use_llm=use_llm)
        cursor.execute(
            "UPDATE channels SET ad_status = ? WHERE username = ?",
            (ad_status, username)
        )
        stats[ad_status] += 1
        updated += 1

        if updated % 50 == 0:
            conn.commit()  # Сохраняем промежуточно
            print(f"Обработано: {updated}/{len(rows)}")

    conn.commit()
    conn.close()

    print(f"\n[OK] Обновлено {updated} каналов")
    print(f"   Нельзя купить (0): {stats[0]}")
    print(f"   Возможно (1): {stats[1]}")
    print(f"   Можно купить (2): {stats[2]}")


if __name__ == "__main__":
    use_llm = "--llm" in sys.argv
    migrate(use_llm=use_llm)
