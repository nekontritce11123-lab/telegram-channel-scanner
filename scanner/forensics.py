"""
User Forensics v11.0 - Executioner System.
Криминалистический анализ пользователей с жёсткими штрафами.

Три метода детекции накрутки:
1. ID Clustering - FATALITY -100 (детектор ферм)
2. Geo/DC Check - штраф -50 (детектор индийских ботов)
3. Premium Density - штраф -20 / бонус +10 (качество аудитории)
4. Hidden Flags - штраф -10 (scam/fake юзеры)

Философия: За явное нарушение штраф НАМНОГО больше чем бонус.
"""
from dataclasses import dataclass
from typing import Any


# ============================================================================
# КОНСТАНТЫ v11.0 - EXECUTIONER SYSTEM
# ============================================================================

# Method 1: ID Clustering (FATALITY)
CLUSTER_NEIGHBOR_THRESHOLD = 0.30   # >30% соседних ID = ферма
CLUSTER_MAX_GAP = 500               # Максимальная разница ID для "соседей"
CLUSTER_PENALTY = -100              # FATALITY - убивает канал

# Method 2: Geo/DC Check
GEO_FOREIGN_THRESHOLD = 0.75        # >75% на чужих DC = боты
GEO_PENALTY = -50                   # Критический штраф
# DC 2, 4 = Europe/Russia (наши)
# DC 1, 3, 5 = USA/Asia (чужие для RU каналов)
RU_NATIVE_DCS = {2, 4}
FOREIGN_DCS = {1, 3, 5}

# Method 3: Premium Density
PREMIUM_ZERO_PENALTY = -20          # 0% премиумов = боты
PREMIUM_HIGH_THRESHOLD = 0.05       # >5% = качественная аудитория
PREMIUM_HIGH_BONUS = 10             # Бонус за качество

# Method 4: Hidden Flags
FLAG_PENALTY = -10                  # Штраф за scam/fake юзеров

# Общие настройки
MIN_USERS_FOR_ANALYSIS = 10         # Минимум юзеров для статистики


# ============================================================================
# РЕЗУЛЬТАТ АНАЛИЗА
# ============================================================================

@dataclass
class ForensicsResult:
    """Результат криминалистического анализа v11.0."""
    total_penalty: int
    id_clustering: dict
    geo_dc_check: dict
    premium_density: dict
    hidden_flags: dict
    users_analyzed: int
    status: str = 'complete'  # 'complete', 'insufficient_data', 'skipped'


# ============================================================================
# ОСНОВНОЙ КЛАСС
# ============================================================================

class UserForensics:
    """
    Криминалистический анализ пользователей v11.0 - Executioner System.
    Выявляет фермы, индийских ботов и низкокачественную аудиторию.
    """

    def __init__(self, users: list[Any]):
        """
        Args:
            users: Список объектов User (RawUserWrapper)
        """
        self.users = users
        self.results = {}

    # =========================================================================
    # METHOD 1: ID CLUSTERING (FATALITY -100)
    # =========================================================================

    def detect_id_clusters(self) -> dict:
        """
        Детектирует фермы по кластеризации Telegram ID.

        Telegram назначает ID последовательно. Если >30% юзеров имеют
        "соседние" ID (разница < 500), они зарегистрированы одновременно = ФЕРМА.

        Returns:
            {
                'neighbor_ratio': float,
                'neighbor_count': int,
                'total_users': int,
                'penalty': int,
                'triggered': bool,
                'fatality': bool,
                'description': str
            }
        """
        if len(self.users) < MIN_USERS_FOR_ANALYSIS:
            return {
                'neighbor_ratio': 0.0,
                'neighbor_count': 0,
                'total_users': len(self.users),
                'penalty': 0,
                'triggered': False,
                'fatality': False,
                'description': 'Недостаточно юзеров для анализа'
            }

        # Извлекаем ID
        user_ids = [u.id for u in self.users if u.id]

        if len(user_ids) < MIN_USERS_FOR_ANALYSIS:
            return {
                'neighbor_ratio': 0.0,
                'neighbor_count': 0,
                'total_users': len(user_ids),
                'penalty': 0,
                'triggered': False,
                'fatality': False,
                'description': 'Недостаточно ID для анализа'
            }

        # Сортируем по ID
        sorted_ids = sorted(user_ids)

        # Считаем "соседей" (разница < 500)
        neighbor_pairs = 0
        for i in range(len(sorted_ids) - 1):
            gap = sorted_ids[i + 1] - sorted_ids[i]
            if gap <= CLUSTER_MAX_GAP:
                neighbor_pairs += 1

        # Вычисляем ratio
        neighbor_ratio = neighbor_pairs / (len(sorted_ids) - 1) if len(sorted_ids) > 1 else 0

        # v13.0: Градация кластеризации
        # >30% = FATALITY (ферма)
        # >15% = SUSPICIOUS (подозрительно)
        SUSPICIOUS_THRESHOLD = 0.15

        fatality = neighbor_ratio > CLUSTER_NEIGHBOR_THRESHOLD  # >30%
        suspicious = neighbor_ratio > SUSPICIOUS_THRESHOLD and not fatality  # 15-30%
        triggered = fatality or suspicious
        penalty = CLUSTER_PENALTY if fatality else 0

        # Формируем описание
        if fatality:
            description = f"☠️ FATALITY: {neighbor_ratio:.0%} соседних ID (ферма)"
        elif suspicious:
            description = f"⚠️ SUSPICIOUS: {neighbor_ratio:.0%} соседних ID (подозрительно)"
        else:
            description = f"OK ({neighbor_ratio:.0%} соседей)"

        return {
            'neighbor_ratio': round(neighbor_ratio, 3),
            'neighbor_count': neighbor_pairs,
            'total_users': len(sorted_ids),
            'penalty': penalty,
            'triggered': triggered,
            'fatality': fatality,
            'suspicious': suspicious,  # v13.0: новый уровень
            'description': description
        }

    # =========================================================================
    # METHOD 2: GEO/DC CHECK (-50)
    # =========================================================================

    def check_geo_dc(self, is_ru_channel: bool = True) -> dict:
        """
        Проверяет географию аудитории по DC (датацентрам).

        DC определяется через user.photo.dc_id:
        - DC 2, 4 = Europe/Russia (родные для RU каналов)
        - DC 1, 3, 5 = USA/Asia (чужие)

        Если >75% юзеров на чужих DC для RU канала = боты из Индии.

        ВАЖНО: Юзеры без фото (dc_id=None) пропускаются.

        Returns:
            {
                'foreign_ratio': float,
                'foreign_count': int,
                'native_count': int,
                'users_with_dc': int,
                'dc_distribution': dict,
                'penalty': int,
                'triggered': bool,
                'description': str
            }
        """
        if not self.users:
            return {
                'foreign_ratio': 0.0,
                'foreign_count': 0,
                'native_count': 0,
                'users_with_dc': 0,
                'dc_distribution': {},
                'penalty': 0,
                'triggered': False,
                'description': 'Нет юзеров для анализа'
            }

        # Собираем DC только от юзеров с фото
        dc_counts = {}
        for user in self.users:
            if user.dc_id:
                dc_counts[user.dc_id] = dc_counts.get(user.dc_id, 0) + 1

        users_with_dc = sum(dc_counts.values())

        if users_with_dc < 5:
            return {
                'foreign_ratio': 0.0,
                'foreign_count': 0,
                'native_count': 0,
                'users_with_dc': users_with_dc,
                'dc_distribution': dc_counts,
                'penalty': 0,
                'triggered': False,
                'description': f'Мало юзеров с фото ({users_with_dc})'
            }

        # Считаем foreign vs native
        if is_ru_channel:
            foreign_count = sum(v for k, v in dc_counts.items() if k in FOREIGN_DCS)
            native_count = sum(v for k, v in dc_counts.items() if k in RU_NATIVE_DCS)
        else:
            # Для не-RU каналов пока не штрафуем
            foreign_count = 0
            native_count = users_with_dc

        foreign_ratio = foreign_count / users_with_dc if users_with_dc > 0 else 0

        # Триггер если >75% на чужих DC
        triggered = foreign_ratio > GEO_FOREIGN_THRESHOLD
        penalty = GEO_PENALTY if triggered else 0

        return {
            'foreign_ratio': round(foreign_ratio, 3),
            'foreign_count': foreign_count,
            'native_count': native_count,
            'users_with_dc': users_with_dc,
            'dc_distribution': dc_counts,
            'penalty': penalty,
            'triggered': triggered,
            'description': (
                f"🚨 GEO MISMATCH: {foreign_ratio:.0%} на чужих DC"
                if triggered else f"OK ({foreign_ratio:.0%} foreign)"
            )
        }

    # =========================================================================
    # METHOD 3: PREMIUM DENSITY (-20 / +10)
    # =========================================================================

    def check_premium_density(self) -> dict:
        """
        Проверяет плотность премиум-юзеров в аудитории.

        - 0% премиумов = скорее всего боты (штраф -20)
        - >5% премиумов = качественная платёжеспособная аудитория (бонус +10)

        Returns:
            {
                'premium_ratio': float,
                'premium_count': int,
                'total_users': int,
                'penalty': int,  # Может быть отрицательным (штраф) или положительным (бонус)
                'triggered': bool,
                'is_bonus': bool,
                'description': str
            }
        """
        if not self.users:
            return {
                'premium_ratio': 0.0,
                'premium_count': 0,
                'total_users': 0,
                'penalty': 0,
                'triggered': False,
                'is_bonus': False,
                'description': 'Нет юзеров для анализа'
            }

        # Считаем премиумов
        premium_count = sum(1 for u in self.users if u.is_premium)
        total = len(self.users)
        premium_ratio = premium_count / total if total > 0 else 0

        # Определяем штраф/бонус
        penalty = 0
        triggered = False
        is_bonus = False

        if premium_ratio == 0 and total >= MIN_USERS_FOR_ANALYSIS:
            # 0% премиумов при достаточной выборке = подозрительно
            penalty = PREMIUM_ZERO_PENALTY
            triggered = True
            is_bonus = False
        elif premium_ratio > PREMIUM_HIGH_THRESHOLD:
            # >5% премиумов = качественная аудитория
            penalty = PREMIUM_HIGH_BONUS
            triggered = True
            is_bonus = True

        return {
            'premium_ratio': round(premium_ratio, 3),
            'premium_count': premium_count,
            'total_users': total,
            'penalty': penalty,
            'triggered': triggered,
            'is_bonus': is_bonus,
            'description': (
                f"💎 QUALITY: {premium_ratio:.1%} премиумов (+{penalty})"
                if is_bonus else
                f"⚠️ LOW BUDGET: 0% премиумов ({penalty})"
                if triggered else
                f"OK ({premium_ratio:.1%} premium)"
            )
        }

    # =========================================================================
    # METHOD 4: HIDDEN FLAGS (-10)
    # =========================================================================

    def check_hidden_flags(self) -> dict:
        """
        Проверяет юзеров на скрытые флаги Telegram.

        Флаги:
        - is_scam: помечен как мошенник
        - is_fake: помечен как фейк
        - is_restricted: ограничен Telegram
        - is_deleted: удалённый аккаунт
        - is_bot: это бот (не штрафуем, но считаем)

        Returns:
            {
                'flagged_users': list[dict],
                'counts': dict,
                'total_flagged': int,
                'penalty': int,
                'triggered': bool,
                'description': str
            }
        """
        flagged = []
        counts = {
            'scam': 0,
            'fake': 0,
            'restricted': 0,
            'deleted': 0,
            'bot': 0
        }

        for user in self.users:
            user_flags = []

            if getattr(user, 'is_scam', False):
                user_flags.append('scam')
                counts['scam'] += 1

            if getattr(user, 'is_fake', False):
                user_flags.append('fake')
                counts['fake'] += 1

            if getattr(user, 'is_restricted', False):
                user_flags.append('restricted')
                counts['restricted'] += 1

            if getattr(user, 'is_deleted', False):
                user_flags.append('deleted')
                counts['deleted'] += 1

            if getattr(user, 'is_bot', False):
                user_flags.append('bot')
                counts['bot'] += 1

            if user_flags:
                flagged.append({
                    'user_id': getattr(user, 'id', None),
                    'username': getattr(user, 'username', None),
                    'flags': user_flags
                })

        # Триггерится если есть хоть один scam/fake
        triggered = counts['scam'] > 0 or counts['fake'] > 0
        penalty = FLAG_PENALTY if triggered else 0

        # Формируем описание
        if triggered:
            parts = []
            if counts['scam']:
                parts.append(f"{counts['scam']} scam")
            if counts['fake']:
                parts.append(f"{counts['fake']} fake")
            description = f"Найдено: {', '.join(parts)}"
        else:
            description = "Помеченных юзеров нет"

        return {
            'flagged_users': flagged[:10],  # Топ-10
            'counts': counts,
            'total_flagged': len(flagged),
            'penalty': penalty,
            'triggered': triggered,
            'description': description
        }

    # =========================================================================
    # MAIN: Объединённый анализ
    # =========================================================================

    def analyze(self, is_ru_channel: bool = True) -> ForensicsResult:
        """
        Выполняет полный криминалистический анализ v11.0.

        Args:
            is_ru_channel: Русскоязычный канал (для Geo Check)

        Returns:
            ForensicsResult с результатами всех методов
        """
        users_count = len(self.users)

        # Проверяем минимум юзеров
        if users_count < MIN_USERS_FOR_ANALYSIS:
            return ForensicsResult(
                total_penalty=0,
                id_clustering={'triggered': False, 'penalty': 0, 'fatality': False,
                               'description': 'Недостаточно данных'},
                geo_dc_check={'triggered': False, 'penalty': 0,
                              'description': 'Недостаточно данных'},
                premium_density={'triggered': False, 'penalty': 0, 'is_bonus': False,
                                 'description': 'Недостаточно данных'},
                hidden_flags={'triggered': False, 'penalty': 0,
                              'description': 'Недостаточно данных'},
                users_analyzed=users_count,
                status='insufficient_data'
            )

        # Выполняем все методы
        id_clustering = self.detect_id_clusters()
        geo_dc_check = self.check_geo_dc(is_ru_channel=is_ru_channel)
        premium_density = self.check_premium_density()
        hidden_flags = self.check_hidden_flags()

        # Суммируем штрафы/бонусы
        total_penalty = (
            id_clustering['penalty'] +
            geo_dc_check['penalty'] +
            premium_density['penalty'] +
            hidden_flags['penalty']
        )

        return ForensicsResult(
            total_penalty=total_penalty,
            id_clustering=id_clustering,
            geo_dc_check=geo_dc_check,
            premium_density=premium_density,
            hidden_flags=hidden_flags,
            users_analyzed=users_count,
            status='complete'
        )
