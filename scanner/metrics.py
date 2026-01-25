"""
Модуль расчёта метрик качества Telegram канала.
v41.1: Floating weights для закрытых комментов.
v51.0: SIZE_THRESHOLDS из config.py вместо hardcoded.
v51.1: shared_utils для iterate_reactions_with_emoji и get_sorted_messages.
"""
from datetime import datetime, timezone
from collections import Counter
from typing import Any
from dataclasses import dataclass
import re

from scanner.config import SIZE_THRESHOLDS
from scanner.shared_utils import (
    get_reaction_emoji as _get_reaction_emoji,
    iterate_reactions_with_emoji,
    get_sorted_messages,
)


# ============================================================================
# КАТЕГОРИЯ A: СИСТЕМА СОВОКУПНЫХ ФАКТОРОВ (Conviction Score)
# ============================================================================

@dataclass
class FraudFactor:
    """Один фактор накрутки."""
    name: str
    weight: int
    triggered: bool
    value: Any
    threshold: Any
    description: str


class FraudConvictionSystem:
    """
    Система совокупных факторов для детекции накрутки.
    Вместо жёстких стоп-сигналов накапливает баллы подозрительности.

    Правило: conviction >= 60 AND factors >= 3 → SCAM
    """

    # Пороги reach для разных размеров каналов
    REACH_THRESHOLDS = {
        'micro': 250,    # < 200 подписчиков
        'small': 180,    # 200-1000
        'medium': 150,   # 1000-5000
        'large': 130     # > 5000
    }

    def __init__(self, chat: Any, messages: list, comments_data: dict = None, comment_trust: int = 0):
        self.chat = chat
        self.messages = messages
        self.comments_data = comments_data or {'enabled': False, 'avg_comments': 0}
        self.comment_trust = comment_trust  # v47.4: Trust score из LLM (0-100)
        self.members = getattr(chat, 'members_count', 0) or 1
        self.factors: list[FraudFactor] = []

        self.views = [m.views for m in messages if hasattr(m, 'views') and m.views]
        self.avg_views = sum(self.views) / len(self.views) if self.views else 0

        # v47.4: Вычисляем forward_rate для алиби
        total_forwards = sum(m.forwards or 0 for m in messages if hasattr(m, 'forwards'))
        total_views = sum(m.views or 0 for m in messages if hasattr(m, 'views'))
        self.forward_rate = (total_forwards / total_views * 100) if total_views > 0 else 0

    def get_size_category(self) -> str:
        """v51.0: Использует SIZE_THRESHOLDS из config.py."""
        if self.members < SIZE_THRESHOLDS['micro']:
            return 'micro'
        elif self.members < SIZE_THRESHOLDS['small']:
            return 'small'
        elif self.members < SIZE_THRESHOLDS['medium']:
            return 'medium'
        return 'large'

    def check_f1_impossible_reach(self) -> FraudFactor:
        """
        F1: Reach слишком высокий для размера канала (вес 30).
        v47.4: "No-Mercy Edition" — алиби снимают обвинение:
        - Алиби 1: forward_rate > 3.0% (виральность через репосты)
        - Алиби 2: avg_comments > 5 AND comment_trust >= 70 (живая дискуссия)
        """
        size = self.get_size_category()
        threshold = self.REACH_THRESHOLDS[size]
        reach = (self.avg_views / self.members) * 100 if self.members > 0 else 0

        # v47.4: Проверяем алиби
        avg_comments = self.comments_data.get('avg_comments', 0)
        has_virality_alibi = self.forward_rate > 3.0

        # Адаптивный порог для комментариев (микро-каналы могут иметь меньше)
        comments_threshold = {
            'micro': 0.5,   # 25 комментов на 50 постов
            'small': 1.0,   # 50 комментов
            'medium': 2.0,  # 100 комментов
            'large': 5.0    # 250 комментов
        }.get(size, 5.0)
        has_comments_alibi = avg_comments > comments_threshold and self.comment_trust >= 70

        # Если есть алиби — reach не считается подозрительным
        if has_virality_alibi or has_comments_alibi:
            alibi_type = "virality" if has_virality_alibi else "comments"
            return FraudFactor(
                name='impossible_reach',
                weight=0,
                triggered=False,
                value=round(reach, 1),
                threshold=threshold,
                description=f"Reach {reach:.1f}% > {threshold}%, но есть алиби ({alibi_type})"
            )

        triggered = reach > threshold
        # Экстремальный reach получает больше веса
        weight = 35 if reach > 300 else (30 if triggered else 0)

        return FraudFactor(
            name='impossible_reach',
            weight=weight,
            triggered=triggered,
            value=round(reach, 1),
            threshold=threshold,
            description=f"Reach {reach:.1f}% > {threshold}% (для {size} канала)"
        )

    def check_f2_flat_cv(self) -> FraudFactor:
        """F2: Слишком ровные просмотры - CV < 15% (вес 25)."""
        if len(self.views) < 5:
            return FraudFactor('flat_cv', 0, False, None, 15, "Недостаточно данных")

        mean = sum(self.views) / len(self.views)
        if mean == 0:
            return FraudFactor('flat_cv', 0, False, 0, 15, "Нет просмотров")

        variance = sum((v - mean) ** 2 for v in self.views) / (len(self.views) - 1)
        cv = (variance ** 0.5 / mean) * 100

        triggered = cv < 15
        weight = 25 if cv < 10 else (20 if cv < 15 else 0)

        return FraudFactor(
            name='flat_cv',
            weight=weight,
            triggered=triggered,
            value=round(cv, 1),
            threshold=15,
            description=f"CV просмотров {cv:.1f}% {'<' if triggered else '>='} 15%"
        )

    def check_f3_dead_engagement(self) -> FraudFactor:
        """
        F3: Реакции есть, но комментариев нет (вес 20).
        v4.0: Проверяем RATIO comments/reactions, не абсолютные числа.
        """
        total_reactions = sum(get_message_reactions_count(m) for m in self.messages)
        avg_comments = self.comments_data.get('avg_comments', 0)
        comments_enabled = self.comments_data.get('enabled', False)

        if not comments_enabled:
            return FraudFactor('dead_engagement', 0, False, None, None,
                             "Комментарии отключены (см. F6)")

        reactions_per_post = total_reactions / len(self.messages) if self.messages else 0

        # v4.0: Проверяем RATIO - живая аудитория комментирует пропорционально реакциям
        # Если реакций много, а комментов мало - это боты
        if reactions_per_post > 0:
            comments_to_reactions_ratio = avg_comments / reactions_per_post
        else:
            comments_to_reactions_ratio = 1.0  # Нет реакций = не подозрительно

        # Много реакций (>50/пост) И низкий ratio (<0.02) = подозрительно
        # ИЛИ старый вариант: много реакций И мало комментов
        triggered = (reactions_per_post > 50 and comments_to_reactions_ratio < 0.02) or \
                    (reactions_per_post > 100 and avg_comments < 1)
        weight = 20 if triggered else 0

        return FraudFactor(
            name='dead_engagement',
            weight=weight,
            triggered=triggered,
            value={
                'reactions': round(reactions_per_post, 1),
                'comments': round(avg_comments, 2),
                'ratio': round(comments_to_reactions_ratio, 4)
            },
            threshold={'min_ratio': 0.02},
            description=f"Реакций {reactions_per_post:.1f}/пост, комментов {avg_comments:.2f}/пост, ratio {comments_to_reactions_ratio:.3f}"
        )

    def check_f4_no_decay(self) -> FraudFactor:
        """F4: Старые посты не накапливают просмотры (вес 15)."""
        if len(self.messages) < 12:
            return FraudFactor('no_decay', 0, False, None, None, "Недостаточно постов")

        sorted_msgs = sorted(
            [m for m in self.messages if hasattr(m, 'date') and m.date and m.views],
            key=lambda m: m.date, reverse=True
        )

        quarter = len(sorted_msgs) // 4
        if quarter < 3:
            return FraudFactor('no_decay', 0, False, None, None, "Недостаточно данных")

        new_views = [m.views for m in sorted_msgs[:quarter]]
        old_views = [m.views for m in sorted_msgs[-quarter:]]

        new_avg = sum(new_views) / len(new_views)
        old_avg = sum(old_views) / len(old_views)

        if new_avg == 0:
            return FraudFactor('no_decay', 0, False, None, None, "Нет просмотров")

        # Нормализуем на baseline для растущих каналов
        baseline = self.avg_views
        if baseline > 0:
            new_norm = new_avg / baseline
            old_norm = old_avg / baseline
            ratio = old_norm / new_norm if new_norm > 0 else 1.0
        else:
            ratio = old_avg / new_avg

        triggered = ratio < 0.85
        weight = 15 if ratio < 0.7 else (10 if ratio < 0.85 else 0)

        return FraudFactor(
            name='no_decay',
            weight=weight,
            triggered=triggered,
            value=round(ratio, 2),
            threshold=0.85,
            description=f"Decay ratio {ratio:.2f} {'<' if triggered else '>='} 0.85"
        )

    def check_f5_simple_reactions(self) -> FraudFactor:
        """F5: Только простые реакции >95% и <= 2 типа (вес 10)."""
        reaction_counts = {}
        total = 0

        for m in self.messages:
            if not hasattr(m, 'reactions') or not m.reactions:
                continue
            if hasattr(m.reactions, 'reactions') and m.reactions.reactions:
                for r in m.reactions.reactions:
                    emoji = get_reaction_emoji(r)
                    count = getattr(r, 'count', 0) or 0
                    reaction_counts[emoji] = reaction_counts.get(emoji, 0) + count
                    total += count

        if total == 0:
            return FraudFactor('simple_reactions', 0, False, None, None, "Нет реакций")

        unique_types = len(reaction_counts)
        bot_reactions = ['👍', '❤️', '❤', '🔥']
        bot_count = sum(reaction_counts.get(e, 0) for e in bot_reactions)
        bot_ratio = bot_count / total

        triggered = bot_ratio > 0.95 and unique_types <= 2
        weight = 10 if triggered else 0

        return FraudFactor(
            name='simple_reactions',
            weight=weight,
            triggered=triggered,
            value={'types': unique_types, 'bot_ratio': round(bot_ratio, 2)},
            threshold={'max_bot_ratio': 0.95, 'min_types': 2},
            description=f"{unique_types} типов, {bot_ratio:.0%} простых"
        )

    def check_f6_disabled_comments(self) -> FraudFactor:
        """F6: Комментарии отключены (вес 15)."""
        enabled = self.comments_data.get('enabled', False)
        triggered = not enabled

        return FraudFactor(
            name='disabled_comments',
            weight=15 if triggered else 0,
            triggered=triggered,
            value=enabled,
            threshold=True,
            description="Комментарии отключены" if triggered else "Комментарии включены"
        )

    def check_f7_bot_regularity(self) -> FraudFactor:
        """F7: Посты слишком регулярные - CV интервалов < 0.15 (вес 10)."""
        if len(self.messages) < 10:
            return FraudFactor('bot_regularity', 0, False, None, None, "Недостаточно постов")

        sorted_msgs = sorted(
            [m for m in self.messages if hasattr(m, 'date') and m.date],
            key=lambda m: m.date
        )

        intervals = []
        for i in range(1, len(sorted_msgs)):
            delta = (sorted_msgs[i].date - sorted_msgs[i-1].date).total_seconds() / 3600
            if delta > 0:
                intervals.append(delta)

        if len(intervals) < 5:
            return FraudFactor('bot_regularity', 0, False, None, None, "Недостаточно интервалов")

        mean_interval = sum(intervals) / len(intervals)
        if mean_interval == 0:
            return FraudFactor('bot_regularity', 0, False, None, None, "Нулевой интервал")

        variance = sum((i - mean_interval) ** 2 for i in intervals) / len(intervals)
        cv = (variance ** 0.5) / mean_interval

        triggered = cv < 0.15
        weight = 10 if triggered else 0

        return FraudFactor(
            name='bot_regularity',
            weight=weight,
            triggered=triggered,
            value=round(cv, 3),
            threshold=0.15,
            description=f"CV интервалов {cv:.3f} {'<' if triggered else '>='} 0.15"
        )

    def check_f8_flat_reactions(self) -> FraudFactor:
        """
        F8: Реакции на посте подозрительно ровные (вес 20).
        v4.0: Если CV количества разных реакций < 15% - боты ставят ровное количество.
        Пример: 222, 211, 203, 202, 198 - все около 200, CV ~5%
        """
        flat_posts = 0
        total_posts_with_reactions = 0

        for m in self.messages:
            if not hasattr(m, 'reactions') or not m.reactions:
                continue
            if not hasattr(m.reactions, 'reactions') or not m.reactions.reactions:
                continue

            counts = []
            for r in m.reactions.reactions:
                count = getattr(r, 'count', 0) or 0
                if count > 10:  # Только значимые реакции
                    counts.append(count)

            if len(counts) >= 3:  # Минимум 3 типа реакций
                total_posts_with_reactions += 1
                mean = sum(counts) / len(counts)
                if mean > 0:
                    variance = sum((c - mean) ** 2 for c in counts) / len(counts)
                    cv = (variance ** 0.5) / mean * 100
                    if cv < 15:  # Подозрительно ровные реакции
                        flat_posts += 1

        if total_posts_with_reactions < 3:
            return FraudFactor('flat_reactions', 0, False, None, None, "Недостаточно данных")

        flat_ratio = flat_posts / total_posts_with_reactions
        triggered = flat_ratio > 0.5  # >50% постов с ровными реакциями
        weight = 20 if triggered else 0

        return FraudFactor(
            name='flat_reactions',
            weight=weight,
            triggered=triggered,
            value={'flat_posts': flat_posts, 'total': total_posts_with_reactions, 'ratio': round(flat_ratio, 2)},
            threshold=0.5,
            description=f"{flat_posts}/{total_posts_with_reactions} постов с ровными реакциями (CV<15%)"
        )

    def check_f9_extreme_reach_decay(self) -> FraudFactor:
        """
        F9: Комбинация экстремального reach И отсутствия decay (вес 25).
        v4.0: Если reach > 200% И decay < 0.7 - это явный паттерн накрутки новых постов.
        """
        size = self.get_size_category()
        threshold = self.REACH_THRESHOLDS[size]
        reach = (self.avg_views / self.members) * 100 if self.members > 0 else 0

        # Вычисляем decay
        if len(self.messages) < 12:
            return FraudFactor('extreme_reach_decay', 0, False, None, None, "Недостаточно постов")

        sorted_msgs = sorted(
            [m for m in self.messages if hasattr(m, 'date') and m.date and m.views],
            key=lambda m: m.date, reverse=True
        )

        quarter = len(sorted_msgs) // 4
        if quarter < 3:
            return FraudFactor('extreme_reach_decay', 0, False, None, None, "Недостаточно данных")

        new_views = [m.views for m in sorted_msgs[:quarter]]
        old_views = [m.views for m in sorted_msgs[-quarter:]]

        new_avg = sum(new_views) / len(new_views) if new_views else 1
        old_avg = sum(old_views) / len(old_views) if old_views else 1

        baseline = self.avg_views or new_avg
        if baseline > 0 and new_avg > 0:
            new_norm = new_avg / baseline
            old_norm = old_avg / baseline
            decay_ratio = old_norm / new_norm
        else:
            decay_ratio = 1.0

        # Комбинация: reach > 200% И decay < 0.7
        triggered = reach > 200 and decay_ratio < 0.7
        weight = 25 if triggered else 0

        return FraudFactor(
            name='extreme_reach_decay',
            weight=weight,
            triggered=triggered,
            value={'reach': round(reach, 1), 'decay': round(decay_ratio, 2)},
            threshold={'reach': 200, 'decay': 0.7},
            description=f"Reach {reach:.1f}% + Decay {decay_ratio:.2f} (комбо-детекция)"
        )

    def check_f10_high_reactions_low_comments(self) -> FraudFactor:
        """
        F10: Много реакций, мало комментариев относительно размера (вес 15).
        v4.0: Если >500 реакций/пост, но <5 комментов - боты.
        v47.2: НЕ срабатывает если комменты выключены (это норма).
        """
        total_reactions = sum(get_message_reactions_count(m) for m in self.messages)
        reactions_per_post = total_reactions / len(self.messages) if self.messages else 0
        avg_comments = self.comments_data.get('avg_comments', 0)
        comments_enabled = self.comments_data.get('enabled', True)

        # v47.2: Если комменты выключены — 0 комментов это норма, не фрод
        if not comments_enabled:
            return FraudFactor(
                name='high_reactions_low_comments',
                weight=0,
                triggered=False,
                value={'reactions_per_post': round(reactions_per_post, 1), 'comments_enabled': False},
                threshold={'reactions': 500, 'comments': 5},
                description="Комменты выключены — фактор не применяется"
            )

        # Много реакций + мало комментариев = боты накручивают реакции
        triggered = reactions_per_post > 500 and avg_comments < 5
        weight = 15 if triggered else 0

        return FraudFactor(
            name='high_reactions_low_comments',
            weight=weight,
            triggered=triggered,
            value={'reactions_per_post': round(reactions_per_post, 1), 'avg_comments': round(avg_comments, 1)},
            threshold={'reactions': 500, 'comments': 5},
            description=f"Реакций {reactions_per_post:.1f}/пост, комментов {avg_comments:.1f}/пост"
        )

    def check_f11_suspicious_velocity(self) -> FraudFactor:
        """
        F11: Подозрительная скорость роста подписчиков (вес 20-25).
        v4.3: Аномальный рост = накрутка подписчиков.

        Пороги по размеру канала (warning, scam):
        - micro (<200): 30, 100 подписчиков/день
        - small (200-1000): 50, 200
        - medium (1000-5000): 150, 500
        - large (>5000): 300, 1000
        """
        VELOCITY_THRESHOLDS = {
            'micro': (30, 100),
            'small': (50, 200),
            'medium': (150, 500),
            'large': (300, 1000)
        }

        age_days = get_channel_age_days(self.chat)
        size = self.get_size_category()
        velocity = self.members / age_days if age_days > 0 else 0

        warning_threshold, scam_threshold = VELOCITY_THRESHOLDS[size]
        is_young = age_days < 90

        # Определяем вес
        weight = 0
        if velocity > scam_threshold:
            weight = 25 if is_young else 20
        elif velocity > warning_threshold:
            weight = 10 if is_young else 5

        triggered = weight > 0

        return FraudFactor(
            name='suspicious_velocity',
            weight=weight,
            triggered=triggered,
            value={
                'velocity': round(velocity, 1),
                'age_days': age_days,
                'members': self.members
            },
            threshold={'warning': warning_threshold, 'scam': scam_threshold},
            description=f"Рост {velocity:.1f} подп/день (возраст {age_days} дней)"
        )

    def check_f12_effective_members(self) -> FraudFactor:
        """
        F12: Эффективные подписчики vs реальные (вес 10-25).
        v4.3: Детектит накрутку подписчиков через несоответствие reach.

        Формула: effective_members = avg_views / expected_reach
        Если effectiveness_ratio < 30% = накрутка подписчиков
        """
        EXPECTED_REACH = {
            'micro': 0.80,   # Микроканалы: ожидаем 80% reach
            'small': 0.50,   # Малые: 50%
            'medium': 0.30,  # Средние: 30%
            'large': 0.15    # Большие: 15%
        }

        size = self.get_size_category()
        expected_reach = EXPECTED_REACH[size]

        # Эффективные подписчики = сколько ДОЛЖНО быть при таком reach
        if expected_reach > 0 and self.avg_views > 0:
            effective_members = self.avg_views / expected_reach
            effectiveness_ratio = effective_members / self.members if self.members > 0 else 1.0
        else:
            effectiveness_ratio = 1.0
            effective_members = self.members

        # Определяем вес
        weight = 0
        if effectiveness_ratio < 0.30:
            weight = 25  # Очень низкая эффективность = накрутка
        elif effectiveness_ratio < 0.50:
            weight = 10  # Подозрительно низкая

        triggered = weight > 0

        return FraudFactor(
            name='effective_members',
            weight=weight,
            triggered=triggered,
            value={
                'effective_members': round(effective_members, 0),
                'actual_members': self.members,
                'effectiveness_ratio': round(effectiveness_ratio, 2),
                'avg_views': round(self.avg_views, 0)
            },
            threshold={'critical': 0.30, 'warning': 0.50},
            description=f"Эффективность {effectiveness_ratio:.0%} ({effective_members:.0f} эфф. из {self.members} факт.)"
        )

    def check_f13_young_fast_inactive(self) -> FraudFactor:
        """
        F13: Комбо-детектор: молодой + быстрый рост + низкий engagement (вес 30).
        v4.3: Практически гарантированная накрутка.

        Условия:
        - Молодой: age < 60 дней
        - Быстрый: velocity > 100 подп/день
        - Неактивный: avg_reactions/views < 1% ИЛИ avg_comments < 0.5
        """
        age_days = get_channel_age_days(self.chat)
        velocity = self.members / age_days if age_days > 0 else 0

        # Считаем engagement
        total_reactions = sum(get_message_reactions_count(m) for m in self.messages)
        total_views = sum(m.views or 0 for m in self.messages if hasattr(m, 'views'))
        reaction_rate = (total_reactions / total_views * 100) if total_views > 0 else 0
        avg_comments = self.comments_data.get('avg_comments', 0)

        # Проверяем условия
        is_young = age_days < 60
        is_fast = velocity > 100
        is_inactive = reaction_rate < 1.0 or avg_comments < 0.5

        # Все три условия = SCAM
        triggered = is_young and is_fast and is_inactive
        weight = 30 if triggered else 0

        return FraudFactor(
            name='young_fast_inactive',
            weight=weight,
            triggered=triggered,
            value={
                'age_days': age_days,
                'velocity': round(velocity, 1),
                'reaction_rate': round(reaction_rate, 2),
                'avg_comments': round(avg_comments, 2),
                'conditions': {
                    'is_young': is_young,
                    'is_fast': is_fast,
                    'is_inactive': is_inactive
                }
            },
            threshold={'age': 60, 'velocity': 100, 'reaction_rate': 1.0, 'comments': 0.5},
            description=f"Young({is_young}) + Fast({is_fast}) + Inactive({is_inactive}) combo"
        )

    def check_virality_mitigation(self) -> int:
        """Смягчение для виральных каналов."""
        mitigation = 0

        # Высокий forward rate = органика
        total_forwards = sum(m.forwards or 0 for m in self.messages if hasattr(m, 'forwards'))
        total_views = sum(m.views or 0 for m in self.messages if hasattr(m, 'views'))
        if total_views > 0:
            forward_rate = total_forwards / total_views
            if forward_rate > 0.05:
                mitigation += 15

        # Верифицированный канал
        if getattr(self.chat, 'is_verified', False):
            mitigation += 20

        return mitigation

    def calculate_conviction(self) -> dict:
        """
        Вычисляет conviction score и выносит вердикт.
        v4.0: Добавлены F8, F9, F10. Порог снижен до 50+2.
        v4.3: Добавлены F11, F12, F13 для детекции накрутки подписчиков.
        """
        self.factors = [
            self.check_f1_impossible_reach(),
            self.check_f2_flat_cv(),
            self.check_f3_dead_engagement(),
            self.check_f4_no_decay(),
            self.check_f5_simple_reactions(),
            self.check_f6_disabled_comments(),
            self.check_f7_bot_regularity(),
            # v4.0: Новые факторы
            self.check_f8_flat_reactions(),
            self.check_f9_extreme_reach_decay(),
            self.check_f10_high_reactions_low_comments(),
            # v4.3: Growth Velocity факторы
            self.check_f11_suspicious_velocity(),
            self.check_f12_effective_members(),
            self.check_f13_young_fast_inactive(),
        ]

        conviction_score = sum(f.weight for f in self.factors)
        factors_triggered = sum(1 for f in self.factors if f.triggered)

        # Смягчение для виральных каналов
        mitigation = self.check_virality_mitigation()
        effective_conviction = max(0, conviction_score - mitigation)

        # v4.0: Правила вынесения вердикта SCAM (порог снижен)
        is_scam = False
        reason = ""

        if effective_conviction >= 50 and factors_triggered >= 2:
            is_scam = True
            reason = f"Conviction {effective_conviction} (>= 50) + {factors_triggered} факторов (>= 2)"
        elif effective_conviction >= 70 and factors_triggered >= 1:
            is_scam = True
            reason = f"Высокий conviction {effective_conviction} (>= 70)"
        elif conviction_score >= 80:
            is_scam = True
            reason = f"Критический conviction {conviction_score} (>= 80)"

        triggered_list = [f for f in self.factors if f.triggered]
        if triggered_list:
            reason += "\nФакторы: " + ", ".join(f.name for f in triggered_list)

        return {
            'is_scam': is_scam,
            'conviction_score': conviction_score,
            'effective_conviction': effective_conviction,
            'mitigation': mitigation,
            'factors_triggered': factors_triggered,
            'factors': [
                {'name': f.name, 'weight': f.weight, 'triggered': f.triggered,
                 'value': f.value, 'description': f.description}
                for f in self.factors
            ],
            'reason': reason
        }


def check_instant_scam(chat: Any, messages: list, comments_data: dict = None, comment_trust: int = 0) -> tuple[bool, str, dict, bool]:
    """
    Проверяет накрутку через систему совокупных факторов.
    Возвращает (is_scam, reason, conviction_details, is_insufficient_data).

    v37.2: Добавлен флаг is_insufficient_data для отличия новых каналов от скама.
    v47.4: Добавлен comment_trust для алиби в F1 (impossible_reach).
    """
    # Минимальные требования для оценки (v37.2)
    MIN_POSTS = 10
    MIN_MEMBERS = 100

    members = getattr(chat, 'participants_count', 0) or getattr(chat, 'members_count', 0) or 0

    if len(messages) < MIN_POSTS or members < MIN_MEMBERS:
        return False, "INSUFFICIENT_DATA", {}, True  # НЕ scam, просто мало данных

    # Абсолютные стоп-сигналы (Telegram флаги)
    if getattr(chat, 'is_scam', False):
        return True, "Telegram пометил канал как SCAM", {}, False

    if getattr(chat, 'is_fake', False):
        return True, "Telegram пометил канал как FAKE", {}, False

    views = [m.views for m in messages if hasattr(m, 'views') and m.views]
    if not views:
        return True, "Нет данных о просмотрах", {}, False

    # Математически невозможные значения
    for m in messages:
        if hasattr(m, 'forwards') and m.forwards and m.views and m.forwards > m.views:
            return True, "Пересылок больше чем просмотров (невозможно)", {}, False

        total_reactions = get_message_reactions_count(m)
        if m.views and total_reactions > m.views:
            return True, "Реакций больше чем просмотров (невозможно)", {}, False

    # Система совокупных факторов
    if comments_data is None:
        comments_data = {
            'enabled': getattr(chat, 'linked_chat', None) is not None,
            'avg_comments': 0.0
        }

    system = FraudConvictionSystem(chat, messages, comments_data, comment_trust)
    result = system.calculate_conviction()

    return result['is_scam'], result['reason'], result, False


# ============================================================================
# КАТЕГОРИЯ B: ОСНОВНЫЕ МЕТРИКИ (70 баллов)
# ============================================================================

def calculate_cv_views(views: list[int]) -> float:
    """
    B1: Coefficient of Variation просмотров.
    Чем выше CV, тем естественнее разброс.
    Боты дают ровные числа (низкий CV).
    """
    if not views or len(views) < 2:
        return 0.0

    mean = sum(views) / len(views)
    if mean == 0:
        return 0.0

    # Исправлено: выборочная дисперсия (n-1)
    variance = sum((v - mean) ** 2 for v in views) / (len(views) - 1)
    std = variance ** 0.5

    return (std / mean) * 100


def calculate_reach(avg_views: float, members_count: int) -> float:
    """
    B2: Охват аудитории (% подписчиков видит посты).
    """
    if members_count <= 0:
        return 0.0
    return (avg_views / members_count) * 100


def calculate_forwards_ratio(messages: list) -> float:
    """
    B4: Соотношение пересылок к просмотрам (%).
    """
    total_forwards = sum(m.forwards or 0 for m in messages if hasattr(m, 'forwards'))
    total_views = sum(m.views or 0 for m in messages if hasattr(m, 'views'))

    if total_views == 0:
        return 0.0

    return (total_forwards / total_views) * 100


def calculate_reaction_rate(messages: list) -> float:
    """
    B5: Соотношение реакций к просмотрам (%).
    """
    total_reactions = 0
    total_views = 0

    for m in messages:
        total_reactions += get_message_reactions_count(m)
        total_views += m.views or 0 if hasattr(m, 'views') else 0

    if total_views == 0:
        return 0.0

    return (total_reactions / total_views) * 100


# ============================================================================
# КАТЕГОРИЯ C: ВРЕМЕННЫЕ МЕТРИКИ (15 баллов)
# ============================================================================

def calculate_views_decay(messages: list) -> float:
    """
    C1: Накопление просмотров (нормализованное).
    Измеряет organic engagement, корректно работает с растущими каналами.

    Нормализуем просмотры на baseline (средние по каналу),
    чтобы растущие каналы не штрафовались.

    Возвращает ratio: normalized_old / normalized_new.
    ratio ~1.0 = норма (для растущих каналов)
    ratio > 1.0 = органика накапливается
    ratio < 0.7 = подозрительно (посты не набирают со временем)
    """
    if len(messages) < 12:
        return 1.0  # Мало данных

    # Сортируем по дате (новые первые)
    sorted_msgs = sorted(
        [m for m in messages if hasattr(m, 'date') and m.date and m.views],
        key=lambda m: m.date,
        reverse=True
    )

    quarter = len(sorted_msgs) // 4
    if quarter < 3:
        return 1.0

    new_views = [m.views for m in sorted_msgs[:quarter]]
    old_views = [m.views for m in sorted_msgs[-quarter:]]

    if not new_views or not old_views:
        return 1.0

    # Baseline - средние просмотры по всем постам
    all_views = [m.views for m in sorted_msgs]
    baseline = sum(all_views) / len(all_views) if all_views else 1

    if baseline == 0:
        return 1.0

    # Нормализуем на baseline
    new_normalized = [v / baseline for v in new_views]
    old_normalized = [v / baseline for v in old_views]

    new_avg_norm = sum(new_normalized) / len(new_normalized)
    old_avg_norm = sum(old_normalized) / len(old_normalized)

    if new_avg_norm == 0:
        return 1.0

    return old_avg_norm / new_avg_norm


def get_channel_age_days(chat: Any) -> int:
    """Возвращает возраст канала в днях."""
    chat_date = getattr(chat, 'date', None)
    if not chat_date:
        return 365  # По умолчанию считаем старым

    if chat_date.tzinfo is None:
        chat_date = chat_date.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return max(1, (now - chat_date).days)


def calculate_post_regularity(messages: list) -> float:
    """
    C3: Вариация интервалов между постами.
    Слишком ровные интервалы = бот.
    Возвращает CV интервалов.
    """
    if len(messages) < 5:
        return 0.5

    sorted_msgs = sorted(
        [m for m in messages if hasattr(m, 'date') and m.date],
        key=lambda m: m.date
    )

    intervals = []
    for i in range(1, len(sorted_msgs)):
        delta = (sorted_msgs[i].date - sorted_msgs[i-1].date).total_seconds() / 3600
        if delta > 0:
            intervals.append(delta)

    if len(intervals) < 5:
        return 0.5

    mean_interval = sum(intervals) / len(intervals)
    if mean_interval == 0:
        return 0.5

    variance = sum((i - mean_interval) ** 2 for i in intervals) / len(intervals)
    std_interval = variance ** 0.5

    return std_interval / mean_interval


def calculate_posts_per_day(messages: list, is_news: bool = False) -> dict:
    """
    Рассчитывает частоту постинга.

    Пороги (обычный канал):
    - < 6/day = normal (×1.0)
    - 6-12/day = active (×0.90)
    - 12-20/day = heavy (×0.75)
    - > 20/day = spam (×0.55)

    Для NEWS пороги выше: 20/40/60
    """
    sorted_msgs = sorted(
        [m for m in messages if hasattr(m, 'date') and m.date],
        key=lambda m: m.date
    )

    if len(sorted_msgs) < 2:
        return {
            'posts_per_day': 0,
            'total_days': 0,
            'posting_status': 'insufficient_data',
            'trust_multiplier': 1.0
        }

    total_seconds = (sorted_msgs[-1].date - sorted_msgs[0].date).total_seconds()
    total_days = max(total_seconds / 86400, 0.1)
    posts_per_day = len(sorted_msgs) / total_days

    # Пороги для NEWS выше
    if is_news:
        thresholds = (20, 40, 60)
    else:
        thresholds = (6, 12, 20)

    # Статус и множитель
    if posts_per_day < thresholds[0]:
        status = 'normal'
        trust_mult = 1.0
    elif posts_per_day < thresholds[1]:
        status = 'active'
        trust_mult = 0.90
    elif posts_per_day < thresholds[2]:
        status = 'heavy'
        trust_mult = 0.75
    else:
        status = 'spam'
        trust_mult = 0.55

    return {
        'posts_per_day': round(posts_per_day, 1),
        'total_days': round(total_days, 1),
        'posting_status': status,
        'trust_multiplier': trust_mult
    }


# ============================================================================
# КАТЕГОРИЯ D: АНАЛИЗ РЕАКЦИЙ (10 баллов)
# ============================================================================

def get_message_reactions_count(message: Any) -> int:
    """Безопасно получает общее количество реакций на сообщение."""
    if not hasattr(message, 'reactions') or not message.reactions:
        return 0

    reactions = message.reactions

    # Pyrogram: reactions.reactions - список ReactionCount
    if hasattr(reactions, 'reactions') and reactions.reactions:
        total = 0
        for r in reactions.reactions:
            total += getattr(r, 'count', 0) or 0
        return total

    return 0


def check_reactions_enabled(messages: list) -> bool:
    """
    v22.4: Проверяет включены ли реакции на канале.

    Логика:
    - Если реакции ОТКЛЮЧЕНЫ: ни один пост не имеет атрибута reactions
    - Если реакции ВКЛЮЧЕНЫ (но никто не реагировал): атрибут есть, но пустой/None
    - Если есть хоть одна реакция: точно включены

    Возвращает True если реакции включены (даже если 0 реакций).
    """
    if not messages:
        return True  # По умолчанию считаем включёнными

    # Проверяем есть ли реакции хоть на одном посте
    total_reactions = sum(get_message_reactions_count(m) for m in messages)
    if total_reactions > 0:
        return True  # Есть реакции = точно включены

    # Проверяем есть ли атрибут reactions хоть у одного поста
    # Telegram не возвращает reactions если они отключены на канале
    for m in messages:
        if hasattr(m, 'reactions') and m.reactions is not None:
            # Атрибут есть, но реакций нет = включены, просто никто не реагировал
            return True

    # Ни у одного поста нет атрибута reactions = реакции отключены
    return False


def get_reaction_emoji(reaction: Any) -> str:
    """
    Безопасно получает emoji реакции.
    v51.1: Делегирует в shared_utils для единообразия.
    """
    return _get_reaction_emoji(reaction)


def calculate_reaction_stability(messages: list) -> dict:
    """
    v52.2: Стабильность КОЛИЧЕСТВА реакций между постами.

    Двухфакторная метрика:
    1. CV (Coefficient of Variation) количества реакций, исключая топ-аутлайер
       - CV < 15% = подозрительно однородно (боты)
       - CV 15-80% = здоровая вариация (живой канал)
       - CV > 80% = хаос (накрутка или мёртвые посты)

    2. Концентрация топ-поста (доля реакций от общей суммы)
       - < 40% = нормально (реакции распределены)
       - 40-60% = есть хит, но ОК
       - > 60% = один пост накручен, остальные мёртвые

    Логика: живой канал имеет разные реакции на разные посты,
    но без экстремальной концентрации в одном.
    """
    # Собираем количество реакций на каждый пост
    reaction_counts = []

    for m in messages:
        count = get_message_reactions_count(m)
        reaction_counts.append(count)

    # Фильтруем посты с реакциями
    non_zero_counts = [c for c in reaction_counts if c > 0]

    if len(non_zero_counts) < 3:
        return {
            'stability_cv': 50.0,
            'top_concentration': 0.2,
            'status': 'insufficient_data',
            'posts_with_reactions': len(non_zero_counts),
            'total_posts': len(reaction_counts)
        }

    total_reactions = sum(non_zero_counts)

    # Концентрация топ-поста
    max_reactions = max(non_zero_counts)
    top_concentration = max_reactions / total_reactions if total_reactions > 0 else 0

    # CV без топ-аутлайера (robust CV)
    # Убираем один максимальный пост чтобы не искажать картину
    counts_without_top = sorted(non_zero_counts)[:-1] if len(non_zero_counts) > 3 else non_zero_counts

    if len(counts_without_top) < 2:
        # Слишком мало данных для CV
        return {
            'stability_cv': 50.0,
            'top_concentration': round(top_concentration, 3),
            'status': 'insufficient_data_for_cv',
            'posts_with_reactions': len(non_zero_counts),
            'total_posts': len(reaction_counts)
        }

    # Расчёт CV
    mean_count = sum(counts_without_top) / len(counts_without_top)
    if mean_count > 0:
        variance = sum((c - mean_count) ** 2 for c in counts_without_top) / (len(counts_without_top) - 1)
        std_dev = variance ** 0.5
        cv = (std_dev / mean_count) * 100
    else:
        cv = 0

    return {
        'stability_cv': round(cv, 1),
        'top_concentration': round(top_concentration, 3),
        'posts_with_reactions': len(non_zero_counts),
        'total_posts': len(reaction_counts),
        'mean_reactions': round(mean_count, 1),
        'max_reactions': max_reactions,
        'total_reactions': total_reactions
    }


def calculate_er_variation(messages: list) -> float:
    """
    D2: Вариация Engagement Rate между постами.
    CV должен быть высоким (разный ER на разных постах).
    """
    ers = []

    for m in messages:
        reactions = get_message_reactions_count(m)
        views = m.views or 0 if hasattr(m, 'views') else 0

        if views > 0:
            er = (reactions / views) * 100
            ers.append(er)

    if len(ers) < 5:
        return 50.0  # Мало данных - нейтральное значение

    mean_er = sum(ers) / len(ers)
    if mean_er == 0:
        return 50.0

    variance = sum((e - mean_er) ** 2 for e in ers) / len(ers)
    std_er = variance ** 0.5

    return (std_er / mean_er) * 100


def calculate_er_trend(messages: list) -> dict:
    """
    v45.0: Сравнивает ER новых постов с ER старых постов.
    Детектирует "зомби-каналы" где вовлеченность падает.

    ER = reactions / views * 100
    Trend = er_new / er_old

    Args:
        messages: Список сообщений с date, views, reactions

    Returns:
        {
            'er_new': float,      # Средний ER новых постов (первый квартиль)
            'er_old': float,      # Средний ER старых постов (последний квартиль)
            'er_trend': float,    # er_new / er_old (1.0 = стабильно)
            'status': str,        # 'growing'|'stable'|'declining'|'dying'|'always_dead'
            'posts_new': int,     # Кол-во постов в новой группе
            'posts_old': int,     # Кол-во постов в старой группе
        }

    Статусы:
        - growing: trend >= 1.1 (ER растёт, канал развивается)
        - stable: 0.9 <= trend < 1.1 (норма)
        - declining: 0.7 <= trend < 0.9 (предупреждение)
        - dying: trend < 0.7 (канал "стух", Trust Penalty)
        - always_dead: er_old < 0.1% (канал изначально без вовлечения)
        - insufficient_data: мало постов для анализа
    """
    # Фильтруем посты с датой и просмотрами
    valid_msgs = [
        m for m in messages
        if hasattr(m, 'date') and m.date
        and hasattr(m, 'views') and m.views and m.views > 0
    ]

    if len(valid_msgs) < 12:
        return {
            'er_new': 0.0,
            'er_old': 0.0,
            'er_trend': 1.0,
            'status': 'insufficient_data',
            'posts_new': 0,
            'posts_old': 0
        }

    # Сортируем по дате (новые первые)
    sorted_msgs = sorted(valid_msgs, key=lambda m: m.date, reverse=True)

    # Делим на квартили
    quarter = len(sorted_msgs) // 4
    if quarter < 3:
        quarter = 3  # Минимум 3 поста в группе

    new_msgs = sorted_msgs[:quarter]
    old_msgs = sorted_msgs[-quarter:]

    # Вычисляем ER для каждой группы
    def calc_group_er(msgs):
        ers = []
        for m in msgs:
            reactions = get_message_reactions_count(m)
            if m.views > 0:
                er = (reactions / m.views) * 100
                ers.append(er)
        return sum(ers) / len(ers) if ers else 0.0

    er_new = calc_group_er(new_msgs)
    er_old = calc_group_er(old_msgs)

    # Edge case: канал изначально мёртвый
    if er_old < 0.1:
        return {
            'er_new': round(er_new, 3),
            'er_old': round(er_old, 3),
            'er_trend': None,
            'status': 'always_dead',
            'posts_new': len(new_msgs),
            'posts_old': len(old_msgs)
        }

    # Вычисляем тренд
    er_trend = er_new / er_old if er_old > 0 else 1.0

    # Определяем статус
    if er_trend >= 1.1:
        status = 'growing'
    elif er_trend >= 0.9:
        status = 'stable'
    elif er_trend >= 0.7:
        status = 'declining'
    else:
        status = 'dying'

    return {
        'er_new': round(er_new, 3),
        'er_old': round(er_old, 3),
        'er_trend': round(er_trend, 3),
        'status': status,
        'posts_new': len(new_msgs),
        'posts_old': len(old_msgs)
    }


# ============================================================================
# КАТЕГОРИЯ E: ДОПОЛНИТЕЛЬНЫЕ ПРОВЕРКИ (5 баллов + бонусы)
# ============================================================================

def calculate_source_diversity(messages: list) -> float:
    """
    E1: Разнообразие источников репостов.
    Если >70% репостов из одного канала = сателлит.
    Возвращает max_share (доля самого частого источника).
    """
    sources = []

    for m in messages:
        fwd = getattr(m, 'forward_from_chat', None)
        if fwd:
            source_id = getattr(fwd, 'id', None)
            if source_id:
                sources.append(source_id)

    if not sources:
        return 0.0  # Нет репостов - ок

    source_counts = Counter(sources)
    max_share = max(source_counts.values()) / len(sources)

    return max_share


# check_round_numbers УДАЛЕНА в v3.0
# Причина: современные накрутчики не используют круглые числа, метрика давала шум

# check_is_ad_post и calculate_ad_load УДАЛЕНЫ в v41.0
# Причина: заменены на LLM ad_percentage детекцию


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def get_raw_stats(messages: list) -> dict:
    """Собирает сырую статистику по сообщениям."""
    total_views = 0
    total_forwards = 0
    total_reactions = 0

    for m in messages:
        total_views += m.views or 0 if hasattr(m, 'views') else 0
        total_forwards += m.forwards or 0 if hasattr(m, 'forwards') else 0
        total_reactions += get_message_reactions_count(m)

    posts_count = len(messages)
    avg_views = total_views / posts_count if posts_count else 0

    return {
        'total_views': total_views,
        'total_forwards': total_forwards,
        'total_reactions': total_reactions,
        'avg_views': round(avg_views, 1),
        'posts_analyzed': posts_count
    }


# ============================================================================
# v15.0: PRIVATE LINKS DETECTION
# ============================================================================

def analyze_private_invites(messages: list, category: str = None, comments_enabled: bool = True) -> dict:
    """
    Анализирует приватные ссылки в постах.
    ВСЁ В ПРОЦЕНТАХ — абсолютные числа не важны.

    Пороги:
    - >60% приватных = ×0.50
    - >80% приватных = ×0.35
    - 100% приватных = ×0.25

    Комбо:
    - CRYPTO + >40% приватных = ×0.45
    - >50% приватных + комменты выкл = ×0.40
    """
    private_pattern = re.compile(r't\.me/(?:\+|joinchat/)([a-zA-Z0-9_-]+)', re.IGNORECASE)
    public_pattern = re.compile(r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})', re.IGNORECASE)

    private_links = set()
    posts_with_private = 0
    posts_with_public = 0

    for msg in messages:
        text = getattr(msg, 'text', '') or ''
        if not text:
            continue

        has_private = bool(private_pattern.search(text))
        has_public = bool(public_pattern.search(text))

        if has_private:
            posts_with_private += 1
            private_links.update(private_pattern.findall(text))
        if has_public:
            posts_with_public += 1

    # Считаем % от ВСЕХ рекламных постов
    total_ad_posts = posts_with_private + posts_with_public
    if total_ad_posts == 0:
        return {
            'private_ratio': 0,
            'private_posts': 0,
            'total_ad_posts': 0,
            'trust_multiplier': 1.0,
            'unique_private': 0,
            'has_ads': False
        }

    private_ratio = posts_with_private / total_ad_posts

    # Базовый штраф по проценту
    if private_ratio >= 1.0:
        trust_mult = 0.25  # 100% приватных
    elif private_ratio > 0.8:
        trust_mult = 0.35  # >80%
    elif private_ratio > 0.6:
        trust_mult = 0.50  # >60%
    else:
        trust_mult = 1.0   # норма

    # Комбо: CRYPTO + много приватных
    if category == 'CRYPTO' and private_ratio > 0.4:
        trust_mult = min(trust_mult, 0.45)

    # Комбо: приватные + комменты выключены
    if not comments_enabled and private_ratio > 0.5:
        trust_mult = min(trust_mult, 0.40)

    return {
        'private_ratio': round(private_ratio, 2),
        'private_posts': posts_with_private,
        'total_ad_posts': total_ad_posts,
        'trust_multiplier': round(trust_mult, 2),
        'unique_private': len(private_links),
        'has_ads': True
    }
