from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import TelegramChannel


async def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    topic_id: int | None = None,
) -> None:
    payload = {
        'chat_id': chat_id,
        'text': text,
        'disable_web_page_preview': True,
    }
    if topic_id:
        payload['message_thread_id'] = topic_id

    client_kwargs = {'timeout': 15}
    if settings.telegram_proxy_url:
        client_kwargs['proxies'] = settings.telegram_proxy_url
    
    async with httpx.AsyncClient(**client_kwargs) as client:
        response = await client.post(f'https://api.telegram.org/bot{bot_token}/sendMessage', json=payload)
        response.raise_for_status()


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

    for channel in channels:
        if channel.events_json and event_name not in channel.events_json:
            continue
        full_text = message
        if channel.include_receipt_url and receipt_url:
            full_text += f'\nЧек: {receipt_url}'
        await send_telegram_message(
            bot_token=channel.bot_token,
            chat_id=channel.chat_id,
            text=full_text,
            topic_id=channel.topic_id,
        )
