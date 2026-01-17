"""
Деплой frontend на 37.140.192.181 через Paramiko.
Использование:
  1. cd frontend && npm run build
  2. python deploy_frontend.py

ВАЖНО: Создайте файл .env в папке deploy/ на основе .env.example
"""

import paramiko
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env из папки deploy
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Конфигурация из .env
FRONTEND_HOST = os.getenv("FRONTEND_HOST", "37.140.192.181")
FRONTEND_USER = os.getenv("FRONTEND_USER", "u3372484")
FRONTEND_PASS = os.getenv("FRONTEND_PASS")
REMOTE_PATH = "/var/www/u3372484/data/www/ads.factchain-traker.online"

# Проверяем что пароль задан
if not FRONTEND_PASS:
    print("ОШИБКА: FRONTEND_PASS не задан!")
    print("Создайте файл .env в папке deploy/ на основе .env.example")
    sys.exit(1)


def deploy():
    print(f"Подключаюсь к {FRONTEND_HOST}...")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(FRONTEND_HOST, username=FRONTEND_USER, password=FRONTEND_PASS)

    sftp = ssh.open_sftp()

    # Путь к билду
    dist_path = Path(__file__).parent.parent / "frontend" / "dist"

    if not dist_path.exists():
        print("Ошибка: папка dist не найдена!")
        print("Запустите: cd frontend && npm run build")
        ssh.close()
        return

    # Очищаем старые файлы
    print("Очищаю старые файлы...")
    ssh.exec_command(f"rm -rf {REMOTE_PATH}/*")

    # Создаём директорию assets
    ssh.exec_command(f"mkdir -p {REMOTE_PATH}/assets")

    # Загружаем новые файлы
    print("Загружаю файлы...")
    for local_file in dist_path.rglob("*"):
        if local_file.is_file():
            # Use POSIX paths for Linux server
            relative = local_file.relative_to(dist_path).as_posix()
            remote_file = f"{REMOTE_PATH}/{relative}"
            remote_dir = os.path.dirname(remote_file)

            # Создаём директорию
            ssh.exec_command(f"mkdir -p {remote_dir}")

            try:
                sftp.put(str(local_file), remote_file)
                print(f"  {relative}")
            except Exception as e:
                print(f"  Ошибка {relative}: {e}")

    sftp.close()
    ssh.close()

    print("\nДеплой frontend завершён!")
    print(f"URL: https://ads.factchain-traker.online")


if __name__ == "__main__":
    deploy()
