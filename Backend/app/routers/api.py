from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import (
    AppLog,
    MyTaxProfile,
    PaymentEvent,
    Receipt,
    ReceiptStatus,
    ReceiptTask,
    RelayTarget,
    Store,
    TaskStatus,
    TaskType,
    TelegramChannel,
)
from app.schemas import (
    AppLogOut,
    LoginProfileIn,
    MyTaxProfileCreate,
    MyTaxProfileOut,
    PaymentEventOut,
    QueueRetryIn,
    ReceiptOut,
    ReceiptTaskOut,
    RelayTargetCreate,
    RelayTargetOut,
    StatsOut,
    StoreCreate,
    StoreOut,
    StoreUpdate,
    TelegramChannelCreate,
    TelegramChannelOut,
)
from app.services.relay import relay_notification
from app.services.telegram import notify_store
from app.services.template import get_nested

router = APIRouter()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=None)


async def _create_log(
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


@router.get('/health')
async def health() -> dict:
    return {'status': 'ok'}


@router.get('/stores', response_model=list[StoreOut])
async def list_stores(db: AsyncSession = Depends(get_db)) -> list[Store]:
    result = await db.execute(select(Store).order_by(Store.created_at.desc()))
    return list(result.scalars().all())


@router.post('/stores', response_model=StoreOut)
async def create_store(payload: StoreCreate, db: AsyncSession = Depends(get_db)) -> Store:
    item = Store(**payload.model_dump())
    db.add(item)
    await _create_log(db, 'store_created', f'Создан магазин: {item.name}')
    await db.commit()
    await db.refresh(item)
    return item


@router.put('/stores/{store_id}', response_model=StoreOut)
async def update_store(store_id: int, payload: StoreUpdate, db: AsyncSession = Depends(get_db)) -> Store:
    item = await db.get(Store, store_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Store not found')
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await _create_log(db, 'store_updated', f'Обновлен магазин: {item.name}', store_id=item.id)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete('/stores/{store_id}')
async def delete_store(store_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    item = await db.get(Store, store_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Store not found')
    await db.delete(item)
    await _create_log(db, 'store_deleted', f'Удален магазин: {item.name}', store_id=store_id)
    await db.commit()
    return {'status': 'deleted'}


@router.get('/profiles', response_model=list[MyTaxProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db)) -> list[MyTaxProfile]:
    result = await db.execute(select(MyTaxProfile).order_by(MyTaxProfile.created_at.desc()))
    return list(result.scalars().all())


@router.post('/profiles', response_model=MyTaxProfileOut)
async def create_profile(payload: MyTaxProfileCreate, db: AsyncSession = Depends(get_db)) -> MyTaxProfile:
    item = MyTaxProfile(**payload.model_dump())
    db.add(item)
    await _create_log(db, 'mytax_profile_created', f'Создан профиль: {item.name}')
    await db.commit()
    await db.refresh(item)
    return item


@router.put('/profiles/{profile_id}', response_model=MyTaxProfileOut)
async def update_profile(profile_id: int, payload: MyTaxProfileCreate, db: AsyncSession = Depends(get_db)) -> MyTaxProfile:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await _create_log(db, 'mytax_profile_updated', f'Обновлен профиль: {item.name}')
    await db.commit()
    await db.refresh(item)
    return item


@router.post('/profiles/{profile_id}/login', response_model=MyTaxProfileOut)
async def login_profile(profile_id: int, payload: LoginProfileIn, db: AsyncSession = Depends(get_db)) -> MyTaxProfile:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')
    if payload.force or item.inn:
        item.is_authenticated = True
        item.last_error = ''
        item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        item.is_authenticated = False
        item.last_error = 'Недостаточно данных для авторизации'
    await _create_log(db, 'mytax_profile_login', f'Обновлен статус авторизации: {item.name}')
    await db.commit()
    await db.refresh(item)
    return item


@router.get('/relay-targets', response_model=list[RelayTargetOut])
async def list_relay_targets(
    store_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[RelayTarget]:
    query: Select[tuple[RelayTarget]] = select(RelayTarget).order_by(RelayTarget.id.desc())
    if store_id is not None:
        query = query.where(RelayTarget.store_id == store_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post('/relay-targets', response_model=RelayTargetOut)
async def create_relay_target(payload: RelayTargetCreate, db: AsyncSession = Depends(get_db)) -> RelayTarget:
    store = await db.get(Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail='Store not found')
    item = RelayTarget(**payload.model_dump())
    db.add(item)
    await _create_log(db, 'relay_target_created', f'Добавлен ретранслятор: {item.name}', store_id=payload.store_id)
    await db.commit()
    await db.refresh(item)
    return item


@router.get('/telegram-channels', response_model=list[TelegramChannelOut])
async def list_telegram_channels(
    store_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[TelegramChannel]:
    query: Select[tuple[TelegramChannel]] = select(TelegramChannel).order_by(TelegramChannel.id.desc())
    if store_id is not None:
        query = query.where(TelegramChannel.store_id == store_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post('/telegram-channels', response_model=TelegramChannelOut)
async def create_telegram_channel(payload: TelegramChannelCreate, db: AsyncSession = Depends(get_db)) -> TelegramChannel:
    store = await db.get(Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail='Store not found')
    item = TelegramChannel(**payload.model_dump())
    db.add(item)
    await _create_log(db, 'telegram_channel_created', f'Добавлен Telegram канал: {item.name}', store_id=payload.store_id)
    await db.commit()
    await db.refresh(item)
    return item


@router.get('/events', response_model=list[PaymentEventOut])
async def list_events(
    store_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentEvent]:
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    conditions = []
    if store_id is not None:
        conditions.append(PaymentEvent.store_id == store_id)
    if parsed_from is not None:
        conditions.append(PaymentEvent.received_at >= parsed_from)
    if parsed_to is not None:
        conditions.append(PaymentEvent.received_at <= parsed_to)

    query: Select[tuple[PaymentEvent]] = select(PaymentEvent).order_by(PaymentEvent.id.desc()).limit(500)
    if conditions:
        query = query.where(and_(*conditions))

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get('/queue', response_model=list[ReceiptTaskOut])
async def list_queue(
    store_id: int | None = Query(default=None),
    status: TaskStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ReceiptTask]:
    query: Select[tuple[ReceiptTask]] = select(ReceiptTask).order_by(ReceiptTask.id.desc()).limit(500)
    if store_id is not None:
        query = query.where(ReceiptTask.store_id == store_id)
    if status is not None:
        query = query.where(ReceiptTask.status == status)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post('/queue/retry')
async def retry_task(payload: QueueRetryIn, db: AsyncSession = Depends(get_db)) -> dict:
    task = await db.get(ReceiptTask, payload.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail='Task not found')
    task.status = TaskStatus.PENDING
    task.error_message = ''
    task.next_retry_at = datetime.utcnow()
    await _create_log(db, 'queue_retry', f'Повтор задачи #{task.id}', store_id=task.store_id)
    await db.commit()
    return {'status': 'queued'}


@router.get('/receipts', response_model=list[ReceiptOut])
async def list_receipts(
    store_id: int | None = Query(default=None),
    status: ReceiptStatus | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[Receipt]:
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    conditions = []
    if store_id is not None:
        conditions.append(Receipt.store_id == store_id)
    if status is not None:
        conditions.append(Receipt.status == status)
    if parsed_from is not None:
        conditions.append(Receipt.created_at >= parsed_from)
    if parsed_to is not None:
        conditions.append(Receipt.created_at <= parsed_to)

    query: Select[tuple[Receipt]] = select(Receipt).order_by(Receipt.id.desc()).limit(500)
    if conditions:
        query = query.where(and_(*conditions))

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get('/logs', response_model=list[AppLogOut])
async def list_logs(
    store_id: int | None = Query(default=None),
    level: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[AppLog]:
    query: Select[tuple[AppLog]] = select(AppLog).order_by(AppLog.id.desc()).limit(500)
    if store_id is not None:
        query = query.where(AppLog.store_id == store_id)
    if level is not None:
        query = query.where(AppLog.level == level)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get('/stats', response_model=StatsOut)
async def get_stats(
    store_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StatsOut:
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    event_conds = []
    task_conds = []
    receipt_conds = []

    if store_id is not None:
        event_conds.append(PaymentEvent.store_id == store_id)
        task_conds.append(ReceiptTask.store_id == store_id)
        receipt_conds.append(Receipt.store_id == store_id)
    if parsed_from is not None:
        event_conds.append(PaymentEvent.received_at >= parsed_from)
        task_conds.append(ReceiptTask.created_at >= parsed_from)
        receipt_conds.append(Receipt.created_at >= parsed_from)
    if parsed_to is not None:
        event_conds.append(PaymentEvent.received_at <= parsed_to)
        task_conds.append(ReceiptTask.created_at <= parsed_to)
        receipt_conds.append(Receipt.created_at <= parsed_to)

    events_q = select(func.count(PaymentEvent.id))
    if event_conds:
        events_q = events_q.where(and_(*event_conds))

    success_q = select(func.count(ReceiptTask.id)).where(ReceiptTask.status == TaskStatus.SUCCESS)
    failed_q = select(func.count(ReceiptTask.id)).where(ReceiptTask.status == TaskStatus.FAILED)
    waiting_q = select(func.count(ReceiptTask.id)).where(ReceiptTask.status == TaskStatus.WAITING_AUTH)
    pending_q = select(func.count(ReceiptTask.id)).where(ReceiptTask.status == TaskStatus.PENDING)
    if task_conds:
        success_q = success_q.where(and_(*task_conds))
        failed_q = failed_q.where(and_(*task_conds))
        waiting_q = waiting_q.where(and_(*task_conds))
        pending_q = pending_q.where(and_(*task_conds))

    receipts_q = select(func.count(Receipt.id))
    if receipt_conds:
        receipts_q = receipts_q.where(and_(*receipt_conds))

    total_events = int((await db.execute(events_q)).scalar() or 0)
    success_tasks = int((await db.execute(success_q)).scalar() or 0)
    failed_tasks = int((await db.execute(failed_q)).scalar() or 0)
    waiting_auth_tasks = int((await db.execute(waiting_q)).scalar() or 0)
    pending_tasks = int((await db.execute(pending_q)).scalar() or 0)
    total_receipts = int((await db.execute(receipts_q)).scalar() or 0)

    return StatsOut(
        total_events=total_events,
        success_tasks=success_tasks,
        failed_tasks=failed_tasks,
        waiting_auth_tasks=waiting_auth_tasks,
        pending_tasks=pending_tasks,
        total_receipts=total_receipts,
    )


@router.post('/webhook/{store_path}')
async def yookassa_webhook(store_path: str, payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Store).where(Store.webhook_path == store_path, Store.is_active.is_(True)))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail='Store not found')

    payment_id = str(get_nested(payload, store.payment_id_path, ''))
    if not payment_id:
        payment_id = str(payload.get('object', {}).get('id', 'unknown'))
    event_name = str(payload.get('event', 'unknown'))

    event = PaymentEvent(
        store_id=store.id,
        event_type=event_name,
        payment_id=payment_id,
        payload=payload,
    )
    db.add(event)
    await db.flush()

    event.relay_status = await relay_notification(db, store, payload)

    if event_name in {'payment.succeeded', 'payment.waiting_for_capture'}:
        task = ReceiptTask(
            store_id=store.id,
            event_id=event.id,
            payment_id=payment_id,
            task_type=TaskType.CREATE_RECEIPT,
            payload=payload,
        )
        db.add(task)
        await notify_store(
            db,
            store_id=store.id,
            event_name='payment_received',
            message=f'Получен платеж {payment_id} ({event_name})',
        )

    if event_name in {'refund.succeeded', 'payment.canceled'} and store.auto_cancel_on_refund:
        receipt_q = (
            select(Receipt)
            .where(Receipt.store_id == store.id, Receipt.payment_id == payment_id)
            .order_by(Receipt.created_at.desc())
            .limit(1)
        )
        receipt = (await db.execute(receipt_q)).scalar_one_or_none()
        task = ReceiptTask(
            store_id=store.id,
            event_id=event.id,
            payment_id=payment_id,
            task_type=TaskType.CANCEL_RECEIPT,
            payload={'receipt_uuid': receipt.receipt_uuid if receipt else ''},
        )
        db.add(task)
        await notify_store(
            db,
            store_id=store.id,
            event_name='refund_received',
            message=f'Получено уведомление на возврат {payment_id} ({event_name})',
        )

    await _create_log(db, 'webhook_received', f'Вебхук {event_name} для платежа {payment_id}', store_id=store.id, context=payload)
    await db.commit()
    return {'status': 'accepted', 'event_id': event.id, 'relay_status': event.relay_status}
