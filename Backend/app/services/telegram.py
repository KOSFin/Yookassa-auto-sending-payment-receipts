from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TelegramChannel


async def notify_store(
    db: AsyncSession,
    store_id: int,
    event_name: str,
    message: str,
    receipt_url: str = '',
) -> None:
    query = select(TelegramChannel).where(TelegramChannel.store_id == store_id, TelegramChannel.is_active.is_(True))
    result = await db.execute(query)
    channels = result.scalars().all()

    async with httpx.AsyncClient(timeout=15) as client:
        for channel in channels:
            if channel.events_json and event_name not in channel.events_json:
                continue
            full_text = message
            if channel.include_receipt_url and receipt_url:
                full_text += f'\nЧек: {receipt_url}'

            payload = {
                'chat_id': channel.chat_id,
                'text': full_text,
                'disable_web_page_preview': True,
            }
            if channel.topic_id:
                payload['message_thread_id'] = channel.topic_id

            await client.post(f'https://api.telegram.org/bot{channel.bot_token}/sendMessage', json=payload)
