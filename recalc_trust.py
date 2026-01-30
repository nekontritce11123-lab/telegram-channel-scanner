"""
recalc_trust.py - Пересчёт trust_factor по новым формулам v78.0

Без обращения к Telegram API - использует данные из БД.

Изменения v78.0:
- Порог бот-штрафа: 30% -> 40% (слабая модерация — норма)
- Штрафы перемножаются (не min)
- trust_factor = forensic × llm
"""

import json
import sqlite3
import sys


def calculate_bot_mult_v78(bot_pct: int) -> float:
    """v78.0: Порог 40% (слабая модерация — норма)."""
    if bot_pct is None or bot_pct <= 40:
        return 1.0
    # Линейный штраф от 40% до 100%
    penalty = (bot_pct - 40) / 100.0
    return max(0.3, 1.0 - penalty)


def calculate_ad_mult(ad_pct: int) -> float:
    """Штраф за рекламу (без изменений)."""
    if ad_pct is None:
        return 1.0
    if ad_pct <= 20:
        return 1.0
    elif ad_pct <= 30:
        return 0.95
    elif ad_pct <= 40:
        return 0.85
    elif ad_pct <= 50:
        return 0.70
    elif ad_pct <= 60:
        return 0.50
    elif ad_pct <= 70:
        return 0.40
    else:
        return 0.35


def calculate_premium_mult(premium_ratio: float, users_analyzed: int) -> float:
    """Штраф за отсутствие премиумов."""
    if users_analyzed < 10:
        return 1.0  # Недостаточно данных
    if premium_ratio is None or premium_ratio == 0:
        return 0.8  # 0% премиумов = подозрительно
    return 1.0


def recalc_trust():
    conn = sqlite3.connect('crawler.db')
    cursor = conn.cursor()

    # Получаем все каналы с данными
    cursor.execute("""
        SELECT username, breakdown_json, forensics_json, trust_factor, score
        FROM channels
        WHERE status IN ('GOOD', 'BAD')
    """)
    rows = cursor.fetchall()

    print(f"Найдено {len(rows)} каналов для пересчёта trust_factor")
    print("=" * 60)

    updated = 0
    changed = 0

    for row in rows:
        username = row[0]
        breakdown_json = row[1]
        forensics_json = row[2]
        old_trust = row[3] or 1.0
        old_score = row[4] or 0

        # Извлекаем bot_percentage и ad_percentage из breakdown
        bot_pct = None
        ad_pct = None

        if breakdown_json:
            try:
                data = json.loads(breakdown_json)
                bd = data.get('breakdown', data)
                llm = bd.get('llm_analysis', bd.get('ll', {}))
                if llm:
                    bot_pct = llm.get('bot_percentage')
                    ad_pct = llm.get('ad_percentage')
            except (json.JSONDecodeError, TypeError):
                pass

        # Извлекаем premium данные из forensics
        premium_ratio = 0
        users_analyzed = 0

        if forensics_json:
            try:
                forensics = json.loads(forensics_json)
                pd = forensics.get('premium_density', {})
                premium_ratio = pd.get('premium_ratio', 0) or 0
                users_analyzed = forensics.get('users_analyzed', 0) or 0
            except (json.JSONDecodeError, TypeError):
                pass

        # Рассчитываем новые множители
        bot_mult = calculate_bot_mult_v78(bot_pct)
        ad_mult = calculate_ad_mult(ad_pct)
        premium_mult = calculate_premium_mult(premium_ratio, users_analyzed)

        # v68.1: Перемножаем ВСЕ штрафы
        new_trust = max(0.1, bot_mult * ad_mult * premium_mult)
        new_trust = round(new_trust, 2)

        # Пересчитываем score
        # Нужен raw_score, но у нас его нет напрямую
        # Приблизительно: raw_score = old_score / old_trust (если old_trust > 0)
        if old_trust > 0:
            raw_score = old_score / old_trust
        else:
            raw_score = old_score

        new_score = int(raw_score * new_trust)
        new_score = max(0, min(100, new_score))

        # Вердикт
        if new_score >= 75:
            new_verdict = 'EXCELLENT'
        elif new_score >= 55:
            new_verdict = 'GOOD'
        elif new_score >= 40:
            new_verdict = 'MEDIUM'
        elif new_score >= 25:
            new_verdict = 'HIGH_RISK'
        else:
            new_verdict = 'SCAM'

        # Статус
        new_status = 'GOOD' if new_score >= 60 else 'BAD'

        # Обновляем если изменилось
        if abs(new_trust - old_trust) > 0.01 or new_score != old_score:
            cursor.execute("""
                UPDATE channels
                SET trust_factor = ?, score = ?, verdict = ?, status = ?
                WHERE username = ?
            """, (new_trust, new_score, new_verdict, new_status, username))
            changed += 1

            # Показываем изменения
            trust_change = f"{old_trust:.2f} -> {new_trust:.2f}"
            score_change = f"{old_score} -> {new_score}"
            details = []
            if bot_pct is not None and bot_pct > 0:
                details.append(f"bot:{bot_pct}%={bot_mult:.2f}")
            if ad_pct is not None and ad_pct > 0:
                details.append(f"ad:{ad_pct}%={ad_mult:.2f}")
            if premium_ratio == 0 and users_analyzed >= 10:
                details.append(f"prem:0%={premium_mult:.2f}")

            print(f"@{username}: trust {trust_change}, score {score_change}")
            if details:
                print(f"    [{', '.join(details)}]")

        updated += 1

    conn.commit()
    conn.close()

    print("=" * 60)
    print(f"Обработано: {updated}")
    print(f"Изменено: {changed}")


if __name__ == "__main__":
    recalc_trust()
