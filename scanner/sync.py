"""
v61.0: Простая синхронизация через SCP.
Заменяет сложную HTTP синхронизацию.

Функции:
- fetch_requests() - забрать запросы с сервера
- push_database() - отправить БД на сервер
"""
import io
import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

try:
    import paramiko
except ImportError:
    paramiko = None
    print("WARNING: paramiko not installed. Run: pip install paramiko")

logger = logging.getLogger(__name__)

# Загружаем credentials из .env
_env_path = Path(__file__).parent.parent / "mini-app" / "deploy" / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# Конфигурация сервера
SERVER_HOST = os.getenv("BACKEND_HOST", "217.60.3.122")
SERVER_USER = os.getenv("BACKEND_USER", "root")
SERVER_PASS = os.getenv("BACKEND_PASS", "")
REMOTE_DIR = "/root/reklamshik"


def _get_sftp():
    """Создать SFTP соединение."""
    if paramiko is None:
        raise ImportError("paramiko not installed. Run: pip install paramiko")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            SERVER_HOST,
            username=SERVER_USER,
            password=SERVER_PASS,
            timeout=30
        )
    except Exception as e:
        logger.error(f"SSH connection failed: {e}")
        raise

    return ssh, ssh.open_sftp()


def fetch_requests() -> list[str]:
    """
    Забрать запросы с сервера и очистить файл.

    Returns:
        Список username'ов для обработки.
    """
    if paramiko is None:
        logger.warning("paramiko not installed, skipping fetch_requests")
        return []

    try:
        ssh, sftp = _get_sftp()
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return []

    try:
        remote_file = f"{REMOTE_DIR}/requests.json"

        # Читаем файл напрямую в память
        try:
            with sftp.file(remote_file, 'r') as f:
                content = f.read().decode('utf-8')
        except FileNotFoundError:
            logger.info("requests.json не найден на сервере")
            return []
        except IOError:
            logger.info("requests.json не найден на сервере")
            return []

        # Парсим запросы
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in requests.json, treating as empty")
            data = []

        if not data:
            return []

        usernames = [r.get("username", "") for r in data if r.get("username")]

        # Очищаем файл на сервере
        with sftp.file(remote_file, 'w') as f:
            f.write("[]")

        logger.info(f"✓ Забрано {len(usernames)} запросов с сервера: {usernames}")
        return usernames

    finally:
        sftp.close()
        ssh.close()


def push_database(db_path: str = "crawler.db") -> bool:
    """
    Скопировать локальную БД на сервер.

    Args:
        db_path: Путь к локальной БД (по умолчанию crawler.db в текущей директории)

    Returns:
        True если успешно, False если ошибка.
    """
    if paramiko is None:
        logger.warning("paramiko not installed, skipping push_database")
        return False

    local_db = Path(db_path)
    if not local_db.exists():
        # Попробуем найти в корне проекта
        project_root = Path(__file__).parent.parent
        local_db = project_root / "crawler.db"

    if not local_db.exists():
        logger.error(f"Локальная БД не найдена: {local_db}")
        return False

    try:
        ssh, sftp = _get_sftp()
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return False

    try:
        remote_db = f"{REMOTE_DIR}/crawler.db"

        size_kb = local_db.stat().st_size / 1024
        logger.info(f"Копирую БД ({size_kb:.1f} KB) на сервер...")

        sftp.put(str(local_db), remote_db)

        logger.info(f"✓ БД скопирована на сервер: {remote_db}")
        return True

    except Exception as e:
        logger.error(f"Failed to push database: {e}")
        return False

    finally:
        sftp.close()
        ssh.close()


def create_requests_file() -> bool:
    """
    Создать пустой requests.json на сервере если его нет.
    Вызывается при первом запуске.
    """
    if paramiko is None:
        return False

    try:
        ssh, sftp = _get_sftp()
    except Exception:
        return False

    try:
        remote_file = f"{REMOTE_DIR}/requests.json"

        # Проверяем существует ли файл
        try:
            sftp.stat(remote_file)
            logger.info("requests.json уже существует")
            return True
        except FileNotFoundError:
            pass

        # Создаём пустой файл
        with sftp.file(remote_file, 'w') as f:
            f.write("[]")

        logger.info(f"✓ Создан {remote_file}")
        return True

    finally:
        sftp.close()
        ssh.close()


# Для тестирования
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Testing sync.py ===")
    print(f"Server: {SERVER_HOST}")
    print(f"User: {SERVER_USER}")
    print(f"Remote dir: {REMOTE_DIR}")
    print()

    # Тест создания файла
    print("1. Creating requests.json if not exists...")
    create_requests_file()

    # Тест fetch
    print("\n2. Fetching requests...")
    requests = fetch_requests()
    print(f"   Got: {requests}")

    # Тест push (закомментирован для безопасности)
    # print("\n3. Pushing database...")
    # push_database()
