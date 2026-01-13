#!/usr/bin/env python3
"""
Точка входа для сканера Telegram каналов.

Использование:
    python run.py @TheFactChain
    python run.py TheFactChain
"""
import asyncio
import sys

from scanner.cli import main as scan_main


if __name__ == "__main__":
    # По умолчанию сканируем TheFactChain
    channel = sys.argv[1] if len(sys.argv) > 1 else "TheFactChain"

    asyncio.run(scan_main(channel))
