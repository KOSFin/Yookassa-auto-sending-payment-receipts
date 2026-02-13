from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.db import AsyncSessionLocal
from app.models import (
    EventStatus,
    PaymentEvent,
    Receipt,
    ReceiptStatus,
    ReceiptTask,
    Store,
    TaskStatus,
    TaskType,
)
from app.services.mytax import MyTaxAuthError, build_mytax_client
from app.services.relay import relay_notification
from app.services.telegram import notify_store
from app.services.template import build_context, render_template


async def process_one_task() -> None:
    async with AsyncSessionLocal() as db:
        query = (
            select(ReceiptTask)
            .where(
                or_(ReceiptTask.status == TaskStatus.PENDING, ReceiptTask.status == TaskStatus.WAITING_AUTH),
                ReceiptTask.next_retry_at <= datetime.utcnow(),
            )
            .order_by(ReceiptTask.created_at.asc())
            .limit(1)
        )
        result = await db.execute(query)
        task = result.scalar_one_or_none()
        if task is None:
            return

        task.status = TaskStatus.PROCESSING
        task.attempts += 1
        await db.flush()

        store_query = select(Store).options(selectinload(Store.mytax_profile)).where(Store.id == task.store_id)
        store_result = await db.execute(store_query)
        store = store_result.scalar_one_or_none()
        payment_event = await db.get(PaymentEvent, task.event_id)

        if store is None or payment_event is None or store.mytax_profile is None:
            task.status = TaskStatus.FAILED
            task.error_message = 'Store/event/profile not found'
            await db.commit()
            return

        try:
            client = build_mytax_client(store.mytax_profile)

            if task.task_type == TaskType.CREATE_RECEIPT:
                context = build_context(payment_event.payload, store)
                description = render_template(store.description_template, context)
                amount_raw = context.get('amount', 0)
                amount = float(amount_raw or 0)

                receipt_result = await client.create_receipt(
                    description=description,
                    amount=amount,
                    payment_id=task.payment_id,
                    event_payload=payment_event.payload,
                )
                receipt = Receipt(
                    store_id=store.id,
                    task_id=task.id,
                    payment_id=task.payment_id,
                    receipt_uuid=receipt_result.receipt_uuid,
                    receipt_url=receipt_result.receipt_url,
                    amount=amount,
                    currency='RUB',
                    description=description,
                    status=ReceiptStatus.CREATED,
                    raw_response=receipt_result.raw,
                )
                db.add(receipt)

                payment_event.relay_status = await relay_notification(db, store, payment_event.payload, receipt_result.receipt_url)

                await notify_store(
                    db,
                    store_id=store.id,
                    event_name='receipt_created',
                    message=f'Сформирован чек для платежа {task.payment_id}',
                    receipt_url=receipt_result.receipt_url,
                )

            elif task.task_type == TaskType.CANCEL_RECEIPT:
                receipt_uuid = task.payload.get('receipt_uuid', '')
                if not receipt_uuid:
                    raise ValueError('Не найден receipt_uuid для отмены чека')
                await client.cancel_receipt(receipt_uuid)

                receipt_query = (
                    select(Receipt)
                    .where(Receipt.store_id == store.id, Receipt.payment_id == task.payment_id)
                    .order_by(Receipt.created_at.desc())
                    .limit(1)
                )
                receipt_res = await db.execute(receipt_query)
                receipt = receipt_res.scalar_one_or_none()
                if receipt is not None:
                    receipt.status = ReceiptStatus.CANCELED
                    receipt.canceled_at = datetime.utcnow()

                await notify_store(
                    db,
                    store_id=store.id,
                    event_name='receipt_canceled',
                    message=f'Чек отозван для платежа {task.payment_id}',
                )

            task.status = TaskStatus.SUCCESS
            task.error_message = ''
            payment_event.status = EventStatus.PROCESSED
            payment_event.processed_at = datetime.utcnow()

        except MyTaxAuthError as exc:
            task.status = TaskStatus.WAITING_AUTH
            task.error_message = str(exc)
            task.next_retry_at = datetime.utcnow() + timedelta(minutes=15)
            payment_event.status = EventStatus.FAILED
            payment_event.error_message = str(exc)
            await notify_store(
                db,
                store_id=task.store_id,
                event_name='mytax_auth_required',
                message=f'Требуется переавторизация Мой Налог: {exc}',
            )
        except Exception as exc:
            if task.attempts >= task.max_attempts:
                task.status = TaskStatus.FAILED
            else:
                task.status = TaskStatus.PENDING
                task.next_retry_at = datetime.utcnow() + timedelta(seconds=min(300, task.attempts * 20))
            task.error_message = str(exc)
            payment_event.status = EventStatus.FAILED
            payment_event.error_message = str(exc)

        await db.commit()


async def worker_loop(poll_seconds: int) -> None:
    while True:
        await process_one_task()
        await asyncio.sleep(poll_seconds)
