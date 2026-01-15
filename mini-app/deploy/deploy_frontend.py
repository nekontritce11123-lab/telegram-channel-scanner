"""
Деплой frontend на 37.140.192.181 через Paramiko.
Использование:
  1. cd frontend && npm run build
  2. python deploy_frontend.py
"""

import paramiko
import os
from pathlib import Path

# Конфигурация
FRONTEND_HOST = "37.140.192.181"
FRONTEND_USER = "u3372484"
FRONTEND_PASS = "j758aqXHELv2l2AM"
REMOTE_PATH = "/var/www/u3372484/data/www/ads.factchain-traker.online"


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
