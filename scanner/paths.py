"""
Centralized path management v1.0
Prevents garbage in root by enforcing directory structure.

Usage:
    from scanner.paths import get_db_path, get_session_path, ensure_directories

    ensure_directories()  # Call at app startup
    db_path = get_db_path()  # Returns data/crawler.db
    session_path = get_session_path("scanner_session")  # Returns sessions/scanner_session
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Primary directories
DATA_DIR = PROJECT_ROOT / "data"
SESSIONS_DIR = PROJECT_ROOT / "sessions"

def ensure_directories():
    """Create required directories. Call at app startup."""
    DATA_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)

def get_db_path(db_name: str = "crawler.db") -> Path:
    """Get path for database. Always in data/."""
    return DATA_DIR / db_name

def get_session_path(session_name: str) -> Path:
    """Get path for Pyrogram session. Always in sessions/."""
    return SESSIONS_DIR / session_name
