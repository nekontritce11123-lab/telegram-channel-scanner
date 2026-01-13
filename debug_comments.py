"""Диагностика комментариев через get_discussion_replies"""
import asyncio
from scanner.client import get_client

async def main():
    async with get_client() as client:
        chat = await client.get_chat("TheFactChain")
        print(f"Канал: {chat.title}")
        print(f"Linked chat: {chat.linked_chat}")

        if chat.linked_chat:
            print(f"Группа для комментов: {chat.linked_chat.title} (ID: {chat.linked_chat.id})")

        # Получаем 1 сообщение
        async for msg in client.get_chat_history("TheFactChain", limit=1):
            print(f"\nПост ID: {msg.id}")
            print(f"Views: {msg.views}")

            # Пробуем получить комментарии
            try:
                count = 0
                async for reply in client.get_discussion_replies(chat.id, msg.id, limit=100):
                    count += 1
                print(f"Комментариев: {count}")
            except Exception as e:
                print(f"Ошибка get_discussion_replies: {e}")

if __name__ == "__main__":
    asyncio.run(main())
