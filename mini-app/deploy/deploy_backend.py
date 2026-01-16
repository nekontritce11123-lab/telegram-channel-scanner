"""
Деплой backend на 217.60.3.122 через Paramiko.
Использование: python deploy_backend.py
"""

import paramiko
import os
from pathlib import Path

# Конфигурация
BACKEND_HOST = "217.60.3.122"
BACKEND_USER = "root"
BACKEND_PASS = "ZiW_1qjEippLtS2xrV"
REMOTE_PATH = "/root/reklamshik"


def deploy():
    print(f"Подключаюсь к {BACKEND_HOST}...")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(BACKEND_HOST, username=BACKEND_USER, password=BACKEND_PASS)

    sftp = ssh.open_sftp()

    # Путь к backend
    local_backend = Path(__file__).parent.parent / "backend"

    print("Создаю директории...")
    dirs_to_create = [
        REMOTE_PATH,
        f"{REMOTE_PATH}/scanner",
    ]
    for d in dirs_to_create:
        ssh.exec_command(f"mkdir -p {d}")

    # v24.0: Копируем основной scanner/ из корня проекта (не дубль из backend/)
    print("Загружаю scanner/ из корня проекта...")
    local_scanner = Path(__file__).parent.parent.parent / "scanner"
    for local_file in local_scanner.rglob("*"):
        if local_file.is_file() and "__pycache__" not in str(local_file):
            relative = local_file.relative_to(local_scanner)
            remote_file = f"{REMOTE_PATH}/scanner/{relative}"
            remote_dir = os.path.dirname(remote_file)

            ssh.exec_command(f"mkdir -p {remote_dir}")

            try:
                sftp.put(str(local_file), remote_file)
                print(f"  scanner/{relative}")
            except Exception as e:
                print(f"  Ошибка scanner/{relative}: {e}")

    print("Загружаю backend файлы...")
    for local_file in local_backend.rglob("*"):
        # v24.0: Пропускаем scanner/ — уже скопирован из корня
        if local_file.is_file() and "__pycache__" not in str(local_file) and "scanner" not in str(local_file):
            relative = local_file.relative_to(local_backend)
            remote_file = f"{REMOTE_PATH}/{relative}"
            remote_dir = os.path.dirname(remote_file)

            ssh.exec_command(f"mkdir -p {remote_dir}")

            try:
                sftp.put(str(local_file), remote_file)
                print(f"  {relative}")
            except Exception as e:
                print(f"  Ошибка {relative}: {e}")

    print("Настраиваю Python окружение...")
    commands = [
        "apt update && apt install -y python3 python3-pip python3-venv",
        f"python3 -m venv {REMOTE_PATH}/venv",
        f"{REMOTE_PATH}/venv/bin/pip install --upgrade pip",
        f"{REMOTE_PATH}/venv/bin/pip install -r {REMOTE_PATH}/requirements.txt",
    ]

    for cmd in commands:
        print(f"  {cmd[:50]}...")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        stdout.channel.recv_exit_status()

    print("Создаю systemd сервисы...")

    # API service
    api_service = f'''[Unit]
Description=Reklamshik API Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_PATH}
Environment=PATH={REMOTE_PATH}/venv/bin
ExecStart={REMOTE_PATH}/venv/bin/uvicorn main:app --host 0.0.0.0 --port 3002
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'''

    # Bot service
    bot_service = f'''[Unit]
Description=Reklamshik Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_PATH}
Environment=PATH={REMOTE_PATH}/venv/bin
ExecStart={REMOTE_PATH}/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'''

    # Записываем сервисы
    with sftp.file("/etc/systemd/system/reklamshik-api.service", "w") as f:
        f.write(api_service)

    with sftp.file("/etc/systemd/system/reklamshik-bot.service", "w") as f:
        f.write(bot_service)

    # Запускаем
    print("Запускаю сервисы...")
    ssh.exec_command("systemctl daemon-reload")
    ssh.exec_command("systemctl enable reklamshik-api reklamshik-bot")
    ssh.exec_command("systemctl restart reklamshik-api reklamshik-bot")

    sftp.close()
    ssh.close()

    print("\nДеплой backend завершён!")
    print(f"API: http://{BACKEND_HOST}:3002/api/health")


if __name__ == "__main__":
    deploy()
