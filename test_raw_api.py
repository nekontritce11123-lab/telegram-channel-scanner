"""Тест Raw MTProto API для получения replies"""
import asyncio
from scanner.client import get_client
from pyrogram.raw import functions

async def main():
    async with get_client() as client:
        print("Тестируем Raw MTProto API...")

        # Получаем peer
        peer = await client.resolve_peer("TheFactChain")
        print(f"Peer: {peer}")

        # Raw GetHistory
        result = await client.invoke(
            functions.messages.GetHistory(
                peer=peer,
                offset_id=0,
                offset_date=0,
                add_offset=0,
                limit=5,
                max_id=0,
                min_id=0,
                hash=0
            )
        )

        print(f"\nТип результата: {type(result)}")
        print(f"Количество сообщений: {len(result.messages)}")

        for i, msg in enumerate(result.messages[:3]):
            print(f"\n=== Сообщение {i+1} ===")
            print(f"ID: {msg.id}")
            print(f"Тип: {type(msg).__name__}")

            # Проверяем replies
            if hasattr(msg, 'replies'):
                replies = msg.replies
                print(f"replies: {replies}")
                if replies:
                    print(f"  replies.replies (количество): {replies.replies}")
                    print(f"  replies.comments: {getattr(replies, 'comments', None)}")
            else:
                print("replies: НЕТ АТРИБУТА")

            # Проверяем views
            if hasattr(msg, 'views'):
                print(f"views: {msg.views}")

if __name__ == "__main__":
    asyncio.run(main())
