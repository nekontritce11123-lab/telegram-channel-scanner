"""
Добавляет SSH ключ на серверы для VSCode Remote SSH.
Использование: python add_ssh_key.py
"""

import paramiko
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Серверы
SERVERS = [
    {
        "name": "Frontend",
        "host": os.getenv("FRONTEND_HOST", "37.140.192.181"),
        "user": os.getenv("FRONTEND_USER", "root"),
        "pass": os.getenv("FRONTEND_PASS"),
    },
    {
        "name": "Backend",
        "host": os.getenv("BACKEND_HOST", "217.60.3.122"),
        "user": os.getenv("BACKEND_USER", "root"),
        "pass": os.getenv("BACKEND_PASS"),
    },
]

# SSH ключ
SSH_KEY_PATH = Path.home() / ".ssh" / "id_rsa.pub"

def add_key_to_server(server: dict, pub_key: str):
    """Добавляет SSH ключ на сервер."""
    print(f"\n{'='*50}")
    print(f"Добавляю ключ на {server['name']} ({server['host']})...")

    if not server['pass']:
        print(f"  ПРОПУСК: Пароль для {server['name']} не задан в .env")
        return False

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server['host'], username=server['user'], password=server['pass'])

        # Создаём .ssh и добавляем ключ
        commands = [
            "mkdir -p ~/.ssh",
            "chmod 700 ~/.ssh",
            f"echo '{pub_key}' >> ~/.ssh/authorized_keys",
            "chmod 600 ~/.ssh/authorized_keys",
            "sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys",  # Удаляем дубликаты
        ]

        for cmd in commands:
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdout.read()  # Ждём выполнения

        ssh.close()
        print(f"  [OK] Ключ добавлен на {server['name']}")
        return True

    except Exception as e:
        print(f"  [ERROR] Ошибка: {e}")
        return False


def main():
    # Читаем публичный ключ
    if not SSH_KEY_PATH.exists():
        print(f"SSH ключ не найден: {SSH_KEY_PATH}")
        print("Создай ключ: ssh-keygen -t rsa -b 4096")
        return

    pub_key = SSH_KEY_PATH.read_text().strip()
    print(f"SSH ключ: {pub_key[:50]}...")

    # Добавляем на все серверы
    success = 0
    for server in SERVERS:
        if add_key_to_server(server, pub_key):
            success += 1

    print(f"\n{'='*50}")
    print(f"Добавлено на {success}/{len(SERVERS)} серверов")

    if success > 0:
        print("\nТеперь можно подключаться через VSCode Remote SSH:")
        print("  Ctrl+Shift+P → Remote-SSH: Connect to Host...")
        print("  Выбрать: reklamshik-frontend или reklamshik-backend")


if __name__ == "__main__":
    main()
