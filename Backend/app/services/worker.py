from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import AsyncSessionLocal
from app.models import (
    AppLog,
    EventStatus,
    MaintenanceSettings,
    PaymentEvent,
    Receipt,
    ReceiptStatus,
    ReceiptTask,
    Store,
    TaskStatus,
    TaskType,
)
from app.services.mytax import MyTaxAuthError, MyTaxTransientError, build_mytax_client
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


async def _get_or_create_maintenance_settings(db: AsyncSession) -> MaintenanceSettings:
    item = await db.get(MaintenanceSettings, 1)
    if item is not None:
        return item
    item = MaintenanceSettings(id=1)
    db.add(item)
    await db.flush()
    return item


async def _cleanup_by_rule(
    db: AsyncSession,
    model,
    id_column,
    datetime_column,
    retention_days: int,
    keep_last: int,
) -> int:
    deleted_total = 0
    if retention_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        res = await db.execute(delete(model).where(datetime_column < cutoff))
        deleted_total += int(res.rowcount or 0)

    if keep_last > 0:
        threshold_res = await db.execute(
            select(id_column).order_by(id_column.desc()).offset(keep_last - 1).limit(1)
        )
        threshold_id = threshold_res.scalar_one_or_none()
        if threshold_id is not None:
            res = await db.execute(delete(model).where(id_column < threshold_id))
            deleted_total += int(res.rowcount or 0)

    return deleted_total


async def process_cleanup_if_due(db: AsyncSession) -> None:
    settings = await _get_or_create_maintenance_settings(db)
    now = datetime.utcnow()
    last = settings.last_cleanup_at
    if last is not None:
        delta_seconds = (now - last).total_seconds()
        if delta_seconds < max(60, settings.cleanup_interval_minutes * 60):
            return

    deleted_logs = await _cleanup_by_rule(
        db,
        AppLog,
        AppLog.id,
        AppLog.created_at,
        settings.log_retention_days,
        settings.keep_last_logs,
    )
    deleted_events = await _cleanup_by_rule(
        db,
        PaymentEvent,
        PaymentEvent.id,
        PaymentEvent.received_at,
        settings.event_retention_days,
        settings.keep_last_events,
    )
    deleted_queue = await _cleanup_by_rule(
        db,
        ReceiptTask,
        ReceiptTask.id,
        ReceiptTask.created_at,
        settings.queue_retention_days,
        settings.keep_last_queue,
    )
    deleted_receipts = await _cleanup_by_rule(
        db,
        Receipt,
        Receipt.id,
        Receipt.created_at,
        settings.receipt_retention_days,
        settings.keep_last_receipts,
    )

    settings.last_cleanup_at = now
    deleted_total = deleted_logs + deleted_events + deleted_queue + deleted_receipts
    if deleted_total > 0:
        await _create_worker_log(
            db,
            'maintenance_cleanup_done',
            'Worker выполнил автоочистку БД',
            context={
                'deleted_logs': deleted_logs,
                'deleted_events': deleted_events,
                'deleted_queue': deleted_queue,
                'deleted_receipts': deleted_receipts,
                'interval_minutes': settings.cleanup_interval_minutes,
            },
        )
        logger.info(
            'Cleanup done: logs=%s events=%s queue=%s receipts=%s',
            deleted_logs,
            deleted_events,
            deleted_queue,
            deleted_receipts,
        )
    await db.commit()


async def process_one_task() -> None:
    async with AsyncSessionLocal() as db:
        try:
            await process_cleanup_if_due(db)
        except ProgrammingError as exc:
            if 'maintenance_settings' in str(exc):
                await db.rollback()
                logger.warning('Skipping cleanup: maintenance_settings table is not available yet')
            else:
                raise
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
            await _create_worker_log(
                db,
                'worker_task_processing',
                f'Task #{task.id} started ({task.task_type})',
                store_id=task.store_id,
                context={
                    'task_id': task.id,
                    'task_type': str(task.task_type),
                    'profile_id': store.mytax_profile.id,
                    'provider': str(store.mytax_profile.provider),
                    'has_access_token': bool(store.mytax_profile.access_token),
                    'has_cookie_blob': bool(store.mytax_profile.cookie_blob),
                },
            )

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

                payment_event.relay_status = await relay_notification(
                    db,
                    store,
                    payment_event.payload,
                    receipt_result.receipt_url,
                    receipt_result.receipt_uuid,
                )

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
                context={
                    'task_id': task.id,
                    'payment_id': task.payment_id,
                    'error': str(exc),
                    'profile_id': store.mytax_profile.id,
                    'provider': str(store.mytax_profile.provider),
                    'has_access_token': bool(store.mytax_profile.access_token),
                    'has_cookie_blob': bool(store.mytax_profile.cookie_blob),
                },
            )
            logger.warning('Task %s moved to waiting_auth: %s', task.id, exc)
            await notify_store(
                db,
                store_id=task.store_id,
                event_name='mytax_auth_required',
                message=(
                    f'Слетела авторизация Мой Налог: {exc}. '
                    f'Задача по платежу {task.payment_id} переведена в ожидание и будет выполнена после входа.'
                ),
            )

            waiting_count_q = select(func.count(ReceiptTask.id)).where(
                ReceiptTask.store_id == task.store_id,
                ReceiptTask.status == TaskStatus.WAITING_AUTH,
            )
            waiting_count = int((await db.execute(waiting_count_q)).scalar() or 0)
            await notify_store(
                db,
                store_id=task.store_id,
                event_name='mytax_auth_queue_waiting',
                message=(
                    'Чеки поставлены в очередь до повторной авторизации. '
                    f'Сейчас в ожидании: {waiting_count}.'
                ),
            )

        except MyTaxTransientError as exc:
            task.status = TaskStatus.PENDING
            task.attempts = max(0, task.attempts - 1)
            retry_seconds = min(1800, 30 + task.attempts * 30)
            task.next_retry_at = datetime.utcnow() + timedelta(seconds=retry_seconds)
            task.error_message = str(exc)
            payment_event.status = EventStatus.RECEIVED
            payment_event.error_message = str(exc)
            await _create_worker_log(
                db,
                'worker_task_transient_retry',
                f'Task #{task.id} transient MyTax error, retry scheduled: {exc}',
                store_id=task.store_id,
                level='warning',
                context={
                    'task_id': task.id,
                    'payment_id': task.payment_id,
                    'attempts': task.attempts,
                    'retry_in_seconds': retry_seconds,
                },
            )
            logger.warning(
                'Task %s transient MyTax error, retry in %s sec: %s',
                task.id,
                retry_seconds,
                exc,
            )
            await notify_store(
                db,
                store_id=task.store_id,
                event_name='task_retry_scheduled',
                message=(
                    f'Временная ошибка Мой Налог для платежа {task.payment_id}. '
                    f'Повтор через {retry_seconds} сек.'
                ),
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
                await notify_store(
                    db,
                    store_id=task.store_id,
                    event_name='receipt_failed',
                    message=(
                        f'Не удалось обработать чек по платежу {task.payment_id}: {exc}. '
                        'Превышен лимит попыток.'
                    ),
                )
            else:
                logger.warning('Task %s failed and was rescheduled: %s', task.id, exc)
                await notify_store(
                    db,
                    store_id=task.store_id,
                    event_name='task_retry_scheduled',
                    message=(
                        f'Ошибка обработки чека по платежу {task.payment_id}: {exc}. '
                        'Задача будет повторена автоматически.'
                    ),
                )

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
