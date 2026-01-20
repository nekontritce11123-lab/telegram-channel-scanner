"""
Синхронизация локальной БД с сервером (копирование crawler.db)
"""
import paramiko
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

BACKEND_HOST = os.getenv("BACKEND_HOST", "217.60.3.122")
BACKEND_USER = os.getenv("BACKEND_USER", "root")
BACKEND_PASS = os.getenv("BACKEND_PASS")
REMOTE_PATH = "/root/reklamshik"

def sync():
    print(f"Подключаюсь к {BACKEND_HOST}...")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BACKEND_HOST, username=BACKEND_USER, password=BACKEND_PASS)

    sftp = ssh.open_sftp()

    # Путь к локальной БД
    local_db = Path(__file__).parent.parent.parent / "crawler.db"

    if not local_db.exists():
        print(f"Ошибка: локальная БД не найдена: {local_db}")
        ssh.close()
        return

    print(f"Загружаю БД: {local_db} -> {REMOTE_PATH}/crawler.db")

    # Создаём бэкап на сервере
    ssh.exec_command(f"cp {REMOTE_PATH}/crawler.db {REMOTE_PATH}/crawler.db.bak")

    # Загружаем новую БД
    sftp.put(str(local_db), f"{REMOTE_PATH}/crawler.db")

    print("БД загружена!")

    # Перезапускаем API чтобы он подхватил новую БД
    print("Перезапускаю API...")
    ssh.exec_command("systemctl restart reklamshik-api")

    sftp.close()
    ssh.close()

    print("\nСинхронизация завершена!")
    print("Подождите 10-15 секунд для перезапуска API")


if __name__ == "__main__":
    sync()
