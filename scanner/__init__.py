# Telegram Channel Scanner
# v51.2: убрали cli для избежания torch зависимости на сервере
from .scorer import calculate_final_score
from .client import get_client
# scan_channel доступен через: from scanner.cli import scan_channel
