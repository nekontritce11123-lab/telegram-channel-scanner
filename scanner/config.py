"""
Единая конфигурация проекта Scanner v1.0

Все константы вынесены сюда для централизованного управления.
Используй os.getenv() для переопределения через переменные окружения.

Использование:
    from scanner.config import OLLAMA_URL, OLLAMA_MODEL, GOOD_THRESHOLD
"""

import os


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
