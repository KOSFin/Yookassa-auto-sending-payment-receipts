from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import TelegramChannel

logger = logging.getLogger(__name__)


class TelegramDeliveryError(Exception):
    pass


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

    client_kwargs: dict[str, object] = {'timeout': 15}
    if settings.telegram_proxy_url:
        client_kwargs['proxy'] = settings.telegram_proxy_url

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.post(f'https://api.telegram.org/bot{bot_token}/sendMessage', json=payload)
            response.raise_for_status()
    except httpx.ConnectTimeout as exc:
        raise TelegramDeliveryError('Не удалось подключиться к Telegram API: превышен таймаут подключения.') from exc
    except httpx.TimeoutException as exc:
        raise TelegramDeliveryError('Telegram API не ответил вовремя: превышен таймаут запроса.') from exc
    except httpx.HTTPStatusError as exc:
        raise TelegramDeliveryError(f'Telegram API вернул HTTP {exc.response.status_code}.') from exc
    except httpx.HTTPError as exc:
        raise TelegramDeliveryError(f'Ошибка запроса к Telegram API: {exc.__class__.__name__}.') from exc


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
        try:
            await send_telegram_message(
                bot_token=channel.bot_token,
                chat_id=channel.chat_id,
                text=full_text,
                topic_id=channel.topic_id,
            )
        except TelegramDeliveryError as exc:
            logger.warning(
                'Telegram notification failed (store_id=%s, channel_id=%s, event=%s): %s',
                store_id,
                channel.id,
                event_name,
                exc,
            )
