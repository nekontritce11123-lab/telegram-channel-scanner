"""
Единая конфигурация проекта Scanner v2.0

Все константы вынесены сюда для централизованного управления.
Используй os.getenv() для переопределения через переменные окружения.

Использование:
    from scanner.config import OLLAMA_URL, OLLAMA_MODEL, GOOD_THRESHOLD
    from scanner.config import ensure_ollama_running
"""

import os
import sys
import time
import subprocess
import requests


# =============================================================================
# OLLAMA API
# =============================================================================

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))  # Унифицировано: 180 сек


# =============================================================================
# КЭШИРОВАНИЕ
# =============================================================================

CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "7"))


# =============================================================================
# CLASSIFIER
# =============================================================================

MAX_POSTS_FOR_AI = int(os.getenv("MAX_POSTS_FOR_AI", "50"))
MAX_CHARS_PER_POST = int(os.getenv("MAX_CHARS_PER_POST", "800"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))  # секунд между попытками

# Debug mode для classifier
DEBUG_CLASSIFIER = os.getenv("DEBUG_CLASSIFIER", "").lower() in ("1", "true", "yes")


# =============================================================================
# CRAWLER THRESHOLDS
# =============================================================================

GOOD_THRESHOLD = int(os.getenv("GOOD_THRESHOLD", "60"))      # Минимум для статуса GOOD в базе
COLLECT_THRESHOLD = int(os.getenv("COLLECT_THRESHOLD", "72")) # v41.1: Минимум для сбора ссылок (размножения)


# =============================================================================
# SIZE THRESHOLDS - пороги размеров каналов
# v23.0: centralized from scorer.py
# =============================================================================

SIZE_THRESHOLDS = {
    'micro': 200,      # < 200 подписчиков
    'small': 1000,     # 200 - 1000
    'medium': 5000,    # 1000 - 5000
    'large': 50000,    # 5000 - 50000
    # > 50000 = huge
}


# =============================================================================
# CRAWLER RATE LIMITING
# =============================================================================

CRAWLER_PAUSE_MIN = float(os.getenv("CRAWLER_PAUSE_MIN", "5"))   # Минимальная пауза между каналами
CRAWLER_PAUSE_MAX = float(os.getenv("CRAWLER_PAUSE_MAX", "10"))  # Максимальная пауза между каналами
CRAWLER_BIG_PAUSE = int(os.getenv("CRAWLER_BIG_PAUSE", "60"))    # Большая пауза каждые N каналов
CRAWLER_BIG_PAUSE_EVERY = int(os.getenv("CRAWLER_BIG_PAUSE_EVERY", "100"))  # Частота больших пауз


# =============================================================================
# CATEGORIES (read-only, не изменять через env)
# =============================================================================

CATEGORIES = [
    # Премиальные (CPM 2000-7000 руб)
    "CRYPTO",        # криптовалюты, DeFi, NFT, Web3, трейдинг
    "FINANCE",       # акции, инвестиции, форекс, банки (НЕ крипта)
    "REAL_ESTATE",   # недвижимость, ипотека, риэлторы
    "BUSINESS",      # B2B-услуги, SaaS, консалтинг, стартапы

    # Технологии (CPM 1000-2000 руб)
    "TECH",          # программирование, IT, гаджеты, DevOps
    "AI_ML",         # нейросети, ML, ChatGPT, Data Science

    # Образование и развитие (CPM 700-1200 руб)
    "EDUCATION",     # курсы, обучение, онлайн-школы
    "BEAUTY",        # косметика, парфюмерия, салоны красоты
    "HEALTH",        # фитнес, медицина, ЗОЖ, диетология
    "TRAVEL",        # туризм, авиа, отели, путешествия

    # Коммерция (CPM 500-1000 руб)
    "RETAIL",        # магазины, e-commerce, товары

    # Контент (CPM 100-500 руб)
    "ENTERTAINMENT", # игры, кино, музыка, мемы, юмор
    "NEWS",          # новости, политика, события
    "LIFESTYLE",     # личные блоги, лайфстайл

    # Высокий риск
    "GAMBLING",      # ставки, казино
    "ADULT",         # 18+ контент
]


# =============================================================================
# OLLAMA MANAGEMENT
# =============================================================================

def check_ollama_available() -> tuple[bool, str]:
    """
    Проверяет доступность Ollama сервера и наличие нужной модели.

    Returns:
        (is_available, error_message)
    """
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code != 200:
            return False, f"Ollama вернул HTTP {response.status_code}"

        # Проверяем что нужная модель установлена
        data = response.json()
        models = [m.get('name', '').split(':')[0] for m in data.get('models', [])]

        required_model = OLLAMA_MODEL.split(':')[0]
        if required_model not in models and OLLAMA_MODEL not in [m.get('name', '') for m in data.get('models', [])]:
            available = ', '.join(models) if models else 'нет моделей'
            return False, f"Модель {OLLAMA_MODEL} не найдена. Доступные: {available}. Установи: ollama pull {OLLAMA_MODEL}"

        return True, ""

    except requests.exceptions.ConnectionError:
        return False, "Ollama не запущен"
    except requests.exceptions.Timeout:
        return False, "Ollama не отвечает (timeout)"
    except Exception as e:
        return False, f"Ошибка проверки Ollama: {e}"


def start_ollama() -> bool:
    """
    Пытается запустить Ollama сервер.

    Returns:
        True если запущен успешно
    """
    print("Запускаю Ollama...")

    try:
        # На Windows запускаем через start чтобы не блокировать
        if sys.platform == 'win32':
            subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            )
        else:
            subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        # Ждём пока сервер запустится (до 30 секунд)
        for i in range(30):
            time.sleep(1)
            ok, _ = check_ollama_available()
            if ok:
                print(f"✓ Ollama запущен (заняло {i+1} сек)")
                return True
            if i % 5 == 4:
                print(f"  Ожидание Ollama... ({i+1}/30 сек)")

        return False

    except FileNotFoundError:
        print("❌ Ollama не установлен! Установи: https://ollama.ai")
        return False
    except Exception as e:
        print(f"❌ Не удалось запустить Ollama: {e}")
        return False


def ensure_ollama_running() -> bool:
    """
    Проверяет Ollama и запускает если не работает.

    Если Ollama не может быть запущен, выбрасывает RuntimeError.

    Returns:
        True если Ollama работает

    Raises:
        RuntimeError если Ollama не может быть запущен
    """
    ok, error = check_ollama_available()

    if ok:
        print(f"✓ Ollama работает (модель: {OLLAMA_MODEL})")
        return True

    print(f"⚠ {error}")

    # Пытаемся запустить
    if "не запущен" in error.lower() or "не отвечает" in error.lower():
        if start_ollama():
            # Проверяем снова
            ok, error = check_ollama_available()
            if ok:
                return True
            else:
                raise RuntimeError(f"Ollama запущен, но: {error}")
        else:
            raise RuntimeError("Не удалось запустить Ollama. Запусти вручную: ollama serve")

    # Другая ошибка (например, нет модели)
    raise RuntimeError(error)
