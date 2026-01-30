"""
Ad Detection Module v52.0
Extracted from metrics.py - Private links detection
"""
import re
from typing import Any

from .scorer_constants import TrustMultipliers


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
        trust_mult = TrustMultipliers.PRIVATE_100  # 0.25
    elif private_ratio > 0.8:
        trust_mult = TrustMultipliers.PRIVATE_80   # 0.35
    elif private_ratio > 0.6:
        trust_mult = TrustMultipliers.PRIVATE_60   # 0.50
    else:
        trust_mult = 1.0

    # Комбо: CRYPTO + много приватных
    if category == 'CRYPTO' and private_ratio > 0.4:
        trust_mult = min(trust_mult, TrustMultipliers.PRIVATE_CRYPTO_COMBO)  # 0.45

    # Комбо: приватные + комменты выключены
    if not comments_enabled and private_ratio > 0.5:
        trust_mult = min(trust_mult, TrustMultipliers.PRIVATE_HIDDEN_COMBO)  # 0.40

    return {
        'private_ratio': round(private_ratio, 2),
        'private_posts': posts_with_private,
        'total_ad_posts': total_ad_posts,
        'trust_multiplier': round(trust_mult, 2),
        'unique_private': len(private_links),
        'has_ads': True
    }
