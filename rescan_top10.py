"""
Скрипт подготовки БД для пересканирования топ-10 каналов.
v15.1: Отбор лучших каналов по категориям и сброс для пересканирования.
"""

import sqlite3
from datetime import datetime

DB_PATH = "crawler.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # === ШАГ 1: Backup ===
    print("=" * 50)
    print("ШАГ 1: Создание backup...")
    backup_table = f"channels_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM channels")
    cursor.execute(f"SELECT COUNT(*) FROM {backup_table}")
    backup_count = cursor.fetchone()[0]
    print(f"Backup создан: {backup_table} ({backup_count} записей)")

    # === Статистика ДО ===
    print("\n" + "=" * 50)
    print("СТАТИСТИКА ДО:")
    cursor.execute("SELECT status, COUNT(*) FROM channels GROUP BY status")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    cursor.execute("""
        SELECT category, COUNT(*) as cnt
        FROM channels WHERE status='GOOD'
        GROUP BY category ORDER BY cnt DESC
    """)
    print("\nКатегории GOOD:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    # === ШАГ 2: Отбор топ-10 ===
    print("\n" + "=" * 50)
    print("ШАГ 2: Отбор топ-10 по каждой категории...")

    # Сначала смотрим что отберём
    cursor.execute("""
        SELECT username, category, score FROM (
            SELECT username, category, score,
                   ROW_NUMBER() OVER (PARTITION BY category ORDER BY score DESC) as rn
            FROM channels WHERE status='GOOD'
        ) WHERE rn <= 10
        ORDER BY category, score DESC
    """)
    top10 = cursor.fetchall()
    print(f"Будет сохранено: {len(top10)} каналов")

    # Группируем для вывода
    from collections import defaultdict
    by_cat = defaultdict(list)
    for username, category, score in top10:
        by_cat[category].append((username, score))

    for cat in sorted(by_cat.keys()):
        channels = by_cat[cat]
        print(f"\n{cat} ({len(channels)}):")
        for username, score in channels[:3]:
            print(f"  @{username}: {score}")
        if len(channels) > 3:
            print(f"  ... и ещё {len(channels) - 3}")

    # === ШАГ 3: Удаление остальных ===
    print("\n" + "=" * 50)
    print("ШАГ 3: Удаление каналов не в топ-10...")

    # Создаём временную таблицу с топ-10
    cursor.execute("DROP TABLE IF EXISTS top10_temp")
    cursor.execute("""
        CREATE TEMP TABLE top10_temp AS
        SELECT username FROM (
            SELECT username, ROW_NUMBER() OVER (PARTITION BY category ORDER BY score DESC) as rn
            FROM channels WHERE status='GOOD'
        ) WHERE rn <= 10
    """)

    # Удаляем всё что не в топ-10
    cursor.execute("DELETE FROM channels WHERE username NOT IN (SELECT username FROM top10_temp)")
    deleted = cursor.rowcount
    print(f"Удалено: {deleted} каналов")

    # === ШАГ 4: Сброс для пересканирования ===
    print("\n" + "=" * 50)
    print("ШАГ 4: Сброс для пересканирования...")

    cursor.execute("""
        UPDATE channels
        SET status='WAITING',
            score=NULL,
            verdict=NULL,
            trust_factor=NULL,
            breakdown_json=NULL,
            scanned_at=NULL
    """)
    reset_count = cursor.rowcount
    print(f"Сброшено: {reset_count} каналов")

    # === Статистика ПОСЛЕ ===
    print("\n" + "=" * 50)
    print("СТАТИСТИКА ПОСЛЕ:")
    cursor.execute("SELECT status, COUNT(*) FROM channels GROUP BY status")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    cursor.execute("SELECT COUNT(DISTINCT category) FROM channels")
    cat_count = cursor.fetchone()[0]
    print(f"\nКатегорий: {cat_count}")

    # === Сохранение ===
    conn.commit()
    conn.close()

    print("\n" + "=" * 50)
    print("ГОТОВО!")
    print(f"Backup: {backup_table}")
    print(f"Каналов для пересканирования: {reset_count}")
    print("\nЗапустите: python crawler.py")


if __name__ == "__main__":
    main()
