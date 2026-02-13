from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import AsyncSessionLocal
from app.models import (
    AppLog,
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

logger = logging.getLogger(__name__)


async def _create_worker_log(
    db: AsyncSession,
    event: str,
    message: str,
    store_id: int | None = None,
    level: str = 'info',
    context: dict | None = None,
) -> None:
    db.add(
        AppLog(
            store_id=store_id,
            level=level,
            event=event,
            message=message,
            context=context or {},
        )
    )


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

        logger.info(
            'Picked task id=%s type=%s store_id=%s status=%s attempts=%s/%s',
            task.id,
            task.task_type,
            task.store_id,
            task.status,
            task.attempts,
            task.max_attempts,
        )
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
            await _create_worker_log(
                db,
                'worker_task_failed',
                f'Task #{task.id} failed: store/event/profile not found',
                store_id=task.store_id,
                level='error',
            )
            logger.error('Task %s failed: store/event/profile not found', task.id)
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
                    message=f'Receipt created for payment {task.payment_id}',
                    receipt_url=receipt_result.receipt_url,
                )

            elif task.task_type == TaskType.CANCEL_RECEIPT:
                receipt_uuid = task.payload.get('receipt_uuid', '')
                if not receipt_uuid:
                    raise ValueError('receipt_uuid is required for cancel task')
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
                    message=f'Receipt canceled for payment {task.payment_id}',
                )

            task.status = TaskStatus.SUCCESS
            task.error_message = ''
            payment_event.status = EventStatus.PROCESSED
            payment_event.processed_at = datetime.utcnow()
            store.mytax_profile.last_error = ''
            await _create_worker_log(
                db,
                'worker_task_success',
                f'Task #{task.id} processed successfully',
                store_id=task.store_id,
                context={'task_type': str(task.task_type), 'payment_id': task.payment_id},
            )
            logger.info('Task %s completed successfully', task.id)

        except MyTaxAuthError as exc:
            task.status = TaskStatus.WAITING_AUTH
            task.error_message = str(exc)
            task.next_retry_at = datetime.utcnow() + timedelta(minutes=15)
            payment_event.status = EventStatus.FAILED
            payment_event.error_message = str(exc)
            store.mytax_profile.is_authenticated = False
            store.mytax_profile.last_error = str(exc)
            await _create_worker_log(
                db,
                'worker_auth_required',
                f'Task #{task.id} requires MyTax re-authentication',
                store_id=task.store_id,
                level='warning',
                context={'task_id': task.id, 'payment_id': task.payment_id, 'error': str(exc)},
            )
            logger.warning('Task %s moved to waiting_auth: %s', task.id, exc)
            await notify_store(
                db,
                store_id=task.store_id,
                event_name='mytax_auth_required',
                message=f'MyTax re-authentication required: {exc}',
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
            level = 'error' if task.status == TaskStatus.FAILED else 'warning'
            await _create_worker_log(
                db,
                'worker_task_retry' if task.status == TaskStatus.PENDING else 'worker_task_failed',
                f'Task #{task.id} failed: {exc}',
                store_id=task.store_id,
                level=level,
                context={
                    'task_id': task.id,
                    'payment_id': task.payment_id,
                    'attempts': task.attempts,
                    'max_attempts': task.max_attempts,
                },
            )
            if task.status == TaskStatus.FAILED:
                logger.error('Task %s failed permanently: %s', task.id, exc)
            else:
                logger.warning('Task %s failed and was rescheduled: %s', task.id, exc)

        await db.commit()


async def worker_loop(poll_seconds: int) -> None:
    logger.info('Worker loop started (poll_seconds=%s)', poll_seconds)
    while True:
        try:
            await process_one_task()
        except asyncio.CancelledError:
            logger.info('Worker loop cancelled')
            raise
        except Exception:
            logger.exception('Unhandled exception in worker loop')
        await asyncio.sleep(poll_seconds)
