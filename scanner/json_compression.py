"""
scanner/json_compression.py - v23.0 JSON Compression for Database Fields

Reduces JSON storage size by 60-75%:
- breakdown_json: 2-4 KB -> 0.5-1 KB
- posts_raw_json: 2-4 KB -> 0.8-1.5 KB
- user_ids_json: 1-3 KB -> 0.5-1 KB

All functions are backward-compatible: decompress detects format automatically.
"""

from datetime import datetime
from typing import Any

# ============================================================================
# KEY MAPPINGS
# ============================================================================

# breakdown_json: metric name -> short key
BREAKDOWN_KEYS = {
    'cv_views': 'cv',
    'reach': 're',
    'views_decay': 'vd',
    'forward_rate': 'fr',
    'comments': 'co',
    'reaction_rate': 'rr',
    'er_variation': 'ev',
    'reaction_stability': 'rs',
    'stability': 'rs',        # Alias (scorer.py uses both names)
    'verified': 've',
    'age': 'ag',
    'premium': 'pr',
    'source_diversity': 'sd',
    'source': 'sd',           # Alias
}

# Reverse mapping for decompression
BREAKDOWN_KEYS_REV = {v: k for k, v in BREAKDOWN_KEYS.items() if k not in ('stability', 'source')}
# Prefer canonical names
BREAKDOWN_KEYS_REV['rs'] = 'reaction_stability'
BREAKDOWN_KEYS_REV['sd'] = 'source_diversity'

# posts_raw_json: field index positions
# [id, timestamp, views, forwards, reactions]
POST_FIELDS = ['id', 'date', 'views', 'forwards', 'reactions']

# user_ids_json: key mappings
USER_IDS_KEYS = {
    'ids': 'i',
    'premium_ids': 'p',
}


# ============================================================================
# MAX VALUES FROM WEIGHTS (for decompression)
# ============================================================================

def _get_max_values() -> dict:
    """
    Get max values for each metric from scorer.py WEIGHTS.
    Returns flat dict: {'cv_views': 15, 'reach': 10, ...}
    """
    try:
        from .scorer import RAW_WEIGHTS
        result = {}
        for category, metrics in RAW_WEIGHTS.items():
            if isinstance(metrics, dict):
                result.update(metrics)
        return result
    except ImportError:
        # Fallback if import fails (e.g., circular import)
        return {
            'cv_views': 15, 'reach': 7, 'views_decay': 5, 'forward_rate': 13,
            'comments': 15, 'reaction_rate': 15, 'er_variation': 5, 'stability': 5,
            'verified': 0, 'age': 7, 'premium': 7, 'source': 6,
        }


# ============================================================================
# BREAKDOWN COMPRESSION
# ============================================================================

def compress_breakdown(breakdown: dict) -> dict:
    """
    Compress breakdown_json from ~2-4 KB to ~0.5-1 KB.

    Input format:
    {
        "cv_views": {"value": 45.2, "points": 12, "max": 15},
        "reach": {"value": 30.5, "points": 8, "max": 10},
        ...
    }

    Output format:
    {
        "cv": [45.2, 12],
        "re": [30.5, 8],
        ...
        "_v": 1  # version marker
    }

    - Short keys (cv_views -> cv)
    - Array format [value, points] instead of dict
    - Remove "max" - it's deterministic from WEIGHTS
    """
    if not breakdown or not isinstance(breakdown, dict):
        return breakdown

    # Skip if already compressed
    if is_compressed(breakdown):
        return breakdown

    result = {'_v': 1}  # Version marker

    for key, data in breakdown.items():
        # Skip special keys
        if key.startswith('_') or key in ('reactions_enabled', 'comments_enabled', 'floating_weights'):
            result[key] = data
            continue

        # Get short key
        short_key = BREAKDOWN_KEYS.get(key, key[:2])

        if isinstance(data, dict) and 'value' in data:
            # Standard metric: {value, points, max} -> [value, points]
            value = data.get('value', 0)
            points = data.get('points', 0)

            # Round floats to 2 decimals
            if isinstance(value, float):
                value = round(value, 2)

            result[short_key] = [value, points]
        else:
            # Non-standard data, keep as-is with short key
            result[short_key] = data

    return result


def decompress_breakdown(compressed: dict) -> dict:
    """
    Decompress breakdown_json back to full format.

    Input: {"cv": [45.2, 12], "_v": 1}
    Output: {"cv_views": {"value": 45.2, "points": 12, "max": 15}}

    Automatically detects compressed vs uncompressed format.
    """
    if not compressed or not isinstance(compressed, dict):
        return compressed

    # Already uncompressed?
    if not is_compressed(compressed):
        return compressed

    max_values = _get_max_values()
    result = {}

    for key, data in compressed.items():
        # Skip version marker
        if key == '_v':
            continue

        # Restore special keys
        if key in ('reactions_enabled', 'comments_enabled', 'floating_weights'):
            result[key] = data
            continue

        # Restore long key
        long_key = BREAKDOWN_KEYS_REV.get(key, key)

        if isinstance(data, list) and len(data) == 2:
            # Compressed metric: [value, points] -> {value, points, max}
            value, points = data
            max_val = max_values.get(long_key, 0)

            result[long_key] = {
                'value': value,
                'points': points,
                'max': max_val,
            }
        else:
            # Non-standard data
            result[long_key] = data

    return result


# ============================================================================
# POSTS RAW COMPRESSION
# ============================================================================

def compress_posts_raw(posts: list) -> list:
    """
    Compress posts_raw_json from ~2-4 KB to ~0.8-1.5 KB.

    Input format:
    [
        {"id": 123, "date": "2024-01-15T10:30:00", "views": 1500, "forwards": 50, "reactions": 100},
        ...
    ]

    Output format:
    [
        [123, 1705313400, 1500, 50, 100],
        ...
    ]

    - Array format instead of dict
    - Unix timestamp instead of ISO string
    """
    if not posts or not isinstance(posts, list):
        return posts

    # Check if already compressed (first item is list)
    if posts and isinstance(posts[0], list):
        return posts

    result = []
    for post in posts:
        if isinstance(post, dict):
            # Convert date to timestamp
            date_val = post.get('date')
            if isinstance(date_val, str):
                try:
                    dt = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                    timestamp = int(dt.timestamp())
                except (ValueError, AttributeError):
                    timestamp = 0
            elif isinstance(date_val, (int, float)):
                timestamp = int(date_val)
            else:
                timestamp = 0

            row = [
                post.get('id', 0),
                timestamp,
                post.get('views', 0),
                post.get('forwards', 0),
                post.get('reactions', 0),
            ]
            result.append(row)
        elif isinstance(post, list):
            # Already in array format
            result.append(post)

    return result


def decompress_posts_raw(compressed: list) -> list:
    """
    Decompress posts_raw_json back to full format.

    Input: [[123, 1705313400, 1500, 50, 100], ...]
    Output: [{"id": 123, "date": "2024-01-15T10:30:00", "views": 1500, "forwards": 50, "reactions": 100}, ...]

    Automatically detects compressed vs uncompressed format.
    """
    if not compressed or not isinstance(compressed, list):
        return compressed

    # Check if already uncompressed (first item is dict)
    if compressed and isinstance(compressed[0], dict):
        return compressed

    result = []
    for row in compressed:
        if isinstance(row, list) and len(row) >= 5:
            post_id, timestamp, views, forwards, reactions = row[:5]

            # Convert timestamp to ISO string
            try:
                dt = datetime.fromtimestamp(timestamp)
                date_str = dt.isoformat()
            except (ValueError, OSError):
                date_str = ""

            result.append({
                'id': post_id,
                'date': date_str,
                'views': views,
                'forwards': forwards,
                'reactions': reactions,
            })
        elif isinstance(row, dict):
            # Already uncompressed
            result.append(row)

    return result


# ============================================================================
# USER IDS COMPRESSION
# ============================================================================

def compress_user_ids(user_ids: dict) -> dict:
    """
    Compress user_ids_json from ~1-3 KB to ~0.5-1 KB.

    Input format:
    {
        "ids": [123, 456, 789, 1000],
        "premium_ids": [456, 1000]  # duplication!
    }

    Output format:
    {
        "i": [123, 456, 789, 1000],
        "p": [1, 3],  # indices of premium users in "i"
        "_v": 1
    }

    - Short keys
    - premium_ids as indices (eliminates duplication)
    """
    if not user_ids or not isinstance(user_ids, dict):
        return user_ids

    # Skip if already compressed
    if is_compressed_user_ids(user_ids):
        return user_ids

    ids = user_ids.get('ids', [])
    premium_ids = set(user_ids.get('premium_ids', []))

    # Build index map
    id_to_index = {uid: idx for idx, uid in enumerate(ids)}

    # Premium indices
    premium_indices = sorted([
        id_to_index[pid] for pid in premium_ids
        if pid in id_to_index
    ])

    return {
        'i': ids,
        'p': premium_indices,
        '_v': 1,
    }


def decompress_user_ids(compressed: dict) -> dict:
    """
    Decompress user_ids_json back to full format.

    Input: {"i": [123, 456, 789], "p": [1], "_v": 1}
    Output: {"ids": [123, 456, 789], "premium_ids": [456]}

    Automatically detects compressed vs uncompressed format.
    """
    if not compressed or not isinstance(compressed, dict):
        return compressed

    # Already uncompressed?
    if not is_compressed_user_ids(compressed):
        return compressed

    ids = compressed.get('i', [])
    premium_indices = compressed.get('p', [])

    # Restore premium_ids from indices
    premium_ids = [ids[idx] for idx in premium_indices if idx < len(ids)]

    return {
        'ids': ids,
        'premium_ids': premium_ids,
    }


# ============================================================================
# VERSION DETECTION
# ============================================================================

def is_compressed(data: dict) -> bool:
    """
    Check if breakdown data uses compressed format.

    Compressed format has:
    - '_v' version marker, OR
    - Short keys (2 chars like 'cv', 're', 'co')
    """
    if not data or not isinstance(data, dict):
        return False

    # Version marker is definitive
    if '_v' in data:
        return True

    # Check for short keys (compressed uses 2-char keys)
    short_keys = {'cv', 're', 'vd', 'fr', 'co', 'rr', 'ev', 'rs', 've', 'ag', 'pr', 'sd'}
    for key in data.keys():
        if key in short_keys:
            return True

    return False


def is_compressed_user_ids(data: dict) -> bool:
    """
    Check if user_ids data uses compressed format.

    Compressed format has 'i' and 'p' keys instead of 'ids' and 'premium_ids'.
    """
    if not data or not isinstance(data, dict):
        return False

    # Version marker or short keys
    return '_v' in data or ('i' in data and 'ids' not in data)


def is_compressed_posts(data: list) -> bool:
    """
    Check if posts data uses compressed format.

    Compressed format: [[id, ts, views, fwd, react], ...]
    Uncompressed format: [{"id": ..., "date": ..., ...}, ...]
    """
    if not data or not isinstance(data, list):
        return False

    if data and isinstance(data[0], list):
        return True

    return False


# ============================================================================
# SMART COMPRESS/DECOMPRESS (auto-detect)
# ============================================================================

def smart_compress(data: Any, field_type: str) -> Any:
    """
    Smart compression based on field type.

    Args:
        data: Data to compress
        field_type: One of 'breakdown', 'posts', 'user_ids'

    Returns:
        Compressed data
    """
    if field_type == 'breakdown':
        return compress_breakdown(data)
    elif field_type == 'posts':
        return compress_posts_raw(data)
    elif field_type == 'user_ids':
        return compress_user_ids(data)
    return data


def smart_decompress(data: Any, field_type: str) -> Any:
    """
    Smart decompression based on field type.

    Args:
        data: Data to decompress
        field_type: One of 'breakdown', 'posts', 'user_ids'

    Returns:
        Decompressed data (full format)
    """
    if field_type == 'breakdown':
        return decompress_breakdown(data)
    elif field_type == 'posts':
        return decompress_posts_raw(data)
    elif field_type == 'user_ids':
        return decompress_user_ids(data)
    return data
