from __future__ import annotations

from datetime import UTC, datetime, timedelta
import ipaddress
import json
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Select, and_, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.config import settings
from app.models import (
    AppLog,
    MyTaxProfile,
    MaintenanceSettings,
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
    PanelAuthStatusOut,
    PanelLoginIn,
    MyTaxProfileCreate,
    ProfileAuthStatusOut,
    ProfilePhoneChallengeIn,
    ProfilePhoneVerifyIn,
    MyTaxProfileOut,
    PaymentEventOut,
    QueueRetryIn,
    ReceiptOut,
    ReceiptTaskOut,
    RelayTargetCreate,
    RelayTargetUpdate,
    RelayTargetOut,
    StatsOut,
    StoreCreate,
    StoreOut,
    StoreUpdate,
    TelegramChannelCreate,
    TelegramChannelUpdate,
    TelegramChannelOut,
    TelegramTestMessageIn,
    MaintenanceCleanupOut,
    MaintenanceSettingsOut,
    MaintenanceSettingsBase,
)
from app.services.panel_auth import (
    create_session_token,
    is_panel_auth_configured,
    verify_credentials,
    verify_session_token,
)
from app.services.mytax import (
    MyTaxApiError,
    UnofficialMyTaxClient,
    extract_cookie_names,
    extract_access_token,
    extract_refresh_token,
    normalize_cookie_blob,
)
from app.services.relay import relay_notification
from app.services.telegram import notify_store, send_telegram_message
from app.services.template import get_nested

router = APIRouter()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=None)


YOOKASSA_ALLOWED_IP_RANGES = [
    '185.71.76.0/27',
    '185.71.77.0/27',
    '77.75.153.0/25',
    '77.75.156.11/32',
    '77.75.156.35/32',
    '77.75.154.128/25',
    '2a02:5180::/32',
]


def _extract_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get('x-forwarded-for', '').strip()
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ''


def _is_ip_allowed(ip_value: str) -> bool:
    if not ip_value:
        return False
    configured = [item.strip() for item in YOOKASSA_ALLOWED_IP_RANGES if item.strip()]
    try:
        ip_obj = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    for item in configured:
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            continue
        if ip_obj in network:
            return True
    return False


def _validate_webhook_payload(payload: dict) -> tuple[str, dict]:
    if str(payload.get('type', 'notification')) not in {'notification', ''}:
        raise HTTPException(status_code=400, detail='Invalid webhook payload: type must be notification')
    event_name = str(payload.get('event') or '').strip()
    if not event_name or '.' not in event_name:
        raise HTTPException(status_code=400, detail='Invalid webhook payload: event is required')
    obj = payload.get('object')
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail='Invalid webhook payload: object is required')
    return event_name, obj


def _is_antifraud_enabled() -> bool:
    return bool(settings.webhook_antifraud_enabled)


def _yookassa_object_url(event_name: str, object_id: str) -> str:
    if event_name.startswith('refund.'):
        return f'https://api.yookassa.ru/v3/refunds/{object_id}'
    return f'https://api.yookassa.ru/v3/payments/{object_id}'


async def _verify_object_status_with_yookassa(event_name: str, object_payload: dict) -> None:
    object_id = str(object_payload.get('id') or '').strip()
    webhook_status = str(object_payload.get('status') or '').strip()
    if not object_id or not webhook_status:
        raise HTTPException(status_code=400, detail='Invalid webhook payload: object.id and object.status are required')

    if not settings.yookassa_shop_id.strip() or not settings.yookassa_secret_key.strip():
        raise HTTPException(
            status_code=503,
            detail='Anti-fraud status verification is enabled, but YOOKASSA_SHOP_ID/YOOKASSA_SECRET_KEY are missing',
        )

    url = _yookassa_object_url(event_name, object_id)
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.get(url, auth=(settings.yookassa_shop_id, settings.yookassa_secret_key))
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f'Failed to verify webhook object in YooKassa: {exc}') from exc

    body = response.json()
    remote_status = str(body.get('status') or '').strip()
    if not remote_status:
        raise HTTPException(status_code=502, detail='YooKassa verification response is missing status')
    if remote_status != webhook_status:
        raise HTTPException(
            status_code=403,
            detail=f'Webhook status mismatch: payload={webhook_status}, yookassa={remote_status}',
        )


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


def _sanitize_profile_payload(payload: MyTaxProfileCreate) -> dict:
    data = payload.model_dump()
    data['inn'] = (data.get('inn') or '').strip() or None
    data['password'] = (data.get('password') or '').strip() or None
    data['phone'] = _normalize_phone((data.get('phone') or '').strip())
    data['device_id'] = (data.get('device_id') or '').strip() or None

    raw_access_token = (data.get('access_token') or '').strip()
    raw_refresh_token = (data.get('refresh_token') or '').strip()
    normalized_access_token = extract_access_token(raw_access_token)
    normalized_refresh_token = extract_refresh_token(raw_access_token, raw_refresh_token)

    data['access_token'] = normalized_access_token
    data['refresh_token'] = normalized_refresh_token
    data['cookie_blob'] = normalize_cookie_blob(data.get('cookie_blob'))
    return data


def _normalize_phone(raw: str | None) -> str | None:
    value = (raw or '').strip()
    if not value:
        return None
    digits = re.sub(r'\D', '', value)
    if len(digits) == 10:
        digits = f'7{digits}'
    return digits or None


def _require_valid_phone(raw: str | None) -> str:
    phone = _normalize_phone(raw)
    if not phone:
        raise HTTPException(status_code=400, detail='Phone is required')
    if len(phone) != 11 or not phone.isdigit():
        raise HTTPException(status_code=400, detail='Номер телефона должен содержать 11 цифр')
    return phone


def _profile_auth_context(item: MyTaxProfile) -> dict:
    cookie_blob = normalize_cookie_blob(item.cookie_blob)
    return {
        'profile_id': item.id,
        'provider': str(item.provider),
        'has_inn': bool((item.inn or '').strip()),
        'has_password': bool((item.password or '').strip()),
        'has_phone': bool((item.phone or '').strip()),
        'has_access_token': bool(extract_access_token(item.access_token)),
        'has_refresh_token': bool((item.refresh_token or '').strip()),
        'has_cookie_blob': bool(cookie_blob),
        'cookie_names': extract_cookie_names(cookie_blob),
        'device_id': item.device_id or '',
    }


def _mytax_error_detail(exc: Exception) -> dict:
    if isinstance(exc, MyTaxApiError):
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        code = str(payload.get('code') or '')
        message = str(payload.get('message') or str(exc))
        additional_info = payload.get('additionalInfo')
        detail: dict[str, object] = {'message': message}
        if code:
            detail['code'] = code
        if isinstance(additional_info, dict) and additional_info:
            detail['additionalInfo'] = additional_info
        if exc.status_code is not None:
            detail['status'] = exc.status_code
        return detail
    return {'message': str(exc)}


async def _release_waiting_auth_tasks(db: AsyncSession, profile_id: int) -> int:
    stores_res = await db.execute(select(Store.id).where(Store.mytax_profile_id == profile_id))
    store_ids = [store_id for (store_id,) in stores_res.all()]
    if not store_ids:
        return 0
    queued_tasks_res = await db.execute(
        select(ReceiptTask).where(
            ReceiptTask.store_id.in_(store_ids),
            ReceiptTask.status == TaskStatus.WAITING_AUTH,
        )
    )
    queued_tasks = list(queued_tasks_res.scalars().all())
    for task in queued_tasks:
        task.status = TaskStatus.PENDING
        task.error_message = ''
        task.next_retry_at = datetime.utcnow()
    return len(queued_tasks)


async def _notify_auth_recovered(db: AsyncSession, profile_id: int, released_tasks: int) -> None:
    if released_tasks <= 0:
        return
    stores_res = await db.execute(select(Store.id).where(Store.mytax_profile_id == profile_id))
    store_ids = [store_id for (store_id,) in stores_res.all()]
    for store_id in store_ids:
        try:
            await notify_store(
                db,
                store_id=store_id,
                event_name='mytax_auth_recovered',
                message=(
                    'Авторизация Мой Налог восстановлена. '
                    f'Задач из очереди возвращено в обработку: {released_tasks}.'
                ),
            )
        except Exception:
            continue


async def _get_or_create_maintenance_settings(db: AsyncSession) -> MaintenanceSettings:
    item = await db.get(MaintenanceSettings, 1)
    if item is not None:
        return item
    item = MaintenanceSettings(id=1)
    db.add(item)
    await db.flush()
    return item


async def _delete_by_time_and_limit(
    db: AsyncSession,
    model,
    id_column,
    datetime_column,
    retention_days: int,
    keep_last: int,
    where_extra=None,
) -> int:
    deleted_total = 0

    if retention_days > 0:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        stmt = delete(model).where(datetime_column < cutoff)
        if where_extra is not None:
            stmt = stmt.where(where_extra)
        res = await db.execute(stmt)
        deleted_total += int(res.rowcount or 0)

    if keep_last > 0:
        threshold_res = await db.execute(
            select(id_column).order_by(id_column.desc()).offset(keep_last - 1).limit(1)
        )
        threshold_id = threshold_res.scalar_one_or_none()
        if threshold_id is not None:
            stmt = delete(model).where(id_column < threshold_id)
            if where_extra is not None:
                stmt = stmt.where(where_extra)
            res = await db.execute(stmt)
            deleted_total += int(res.rowcount or 0)

    return deleted_total


async def _run_cleanup(db: AsyncSession, settings: MaintenanceSettings) -> MaintenanceCleanupOut:
    # Delete in FK dependency order: receipts → receipt_tasks → payment_events → logs
    deleted_receipts = await _delete_by_time_and_limit(
        db,
        Receipt,
        Receipt.id,
        Receipt.created_at,
        settings.receipt_retention_days,
        settings.keep_last_receipts,
    )
    deleted_queue = await _delete_by_time_and_limit(
        db,
        ReceiptTask,
        ReceiptTask.id,
        ReceiptTask.created_at,
        settings.queue_retention_days,
        settings.keep_last_queue,
        where_extra=~exists(select(Receipt.id).where(Receipt.task_id == ReceiptTask.id)),
    )
    deleted_events = await _delete_by_time_and_limit(
        db,
        PaymentEvent,
        PaymentEvent.id,
        PaymentEvent.received_at,
        settings.event_retention_days,
        settings.keep_last_events,
        where_extra=~exists(select(ReceiptTask.id).where(ReceiptTask.event_id == PaymentEvent.id)),
    )
    deleted_logs = await _delete_by_time_and_limit(
        db,
        AppLog,
        AppLog.id,
        AppLog.created_at,
        settings.log_retention_days,
        settings.keep_last_logs,
    )
    settings.last_cleanup_at = datetime.utcnow()
    await db.flush()
    return MaintenanceCleanupOut(
        deleted_logs=deleted_logs,
        deleted_events=deleted_events,
        deleted_queue=deleted_queue,
        deleted_receipts=deleted_receipts,
        ran_at=settings.last_cleanup_at,
    )


@router.get('/health')
async def health() -> dict:
    return {'status': 'ok'}


@router.get('/auth/status', response_model=PanelAuthStatusOut)
async def panel_auth_status(request: Request) -> PanelAuthStatusOut:
    configured = is_panel_auth_configured()
    token = request.cookies.get(settings.panel_auth_cookie_name, '')
    authenticated = configured and bool(token) and verify_session_token(token)
    return PanelAuthStatusOut(configured=configured, authenticated=authenticated)


@router.post('/auth/login')
async def panel_auth_login(payload: PanelLoginIn, response: Response) -> dict:
    if not is_panel_auth_configured():
        raise HTTPException(status_code=503, detail='Panel auth is not configured. Set PANEL_LOGIN and PANEL_PASSWORD.')
    if not verify_credentials(payload.login, payload.password):
        raise HTTPException(status_code=401, detail='Invalid login or password')

    token = create_session_token(payload.login.strip())
    response.set_cookie(
        key=settings.panel_auth_cookie_name,
        value=token,
        max_age=settings.panel_auth_token_ttl_seconds,
        httponly=True,
        samesite='lax',
        secure=settings.panel_auth_cookie_secure,
        path='/',
    )
    return {'status': 'ok'}


@router.post('/auth/logout')
async def panel_auth_logout(response: Response) -> dict:
    response.delete_cookie(key=settings.panel_auth_cookie_name, path='/')
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
    item = MyTaxProfile(**_sanitize_profile_payload(payload))
    db.add(item)
    await _create_log(
        db,
        'mytax_profile_created',
        f'Создан профиль: {item.name}',
        context={'profile_name': item.name, 'provider': item.provider},
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.put('/profiles/{profile_id}', response_model=MyTaxProfileOut)
async def update_profile(profile_id: int, payload: MyTaxProfileCreate, db: AsyncSession = Depends(get_db)) -> MyTaxProfile:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')
    for key, value in _sanitize_profile_payload(payload).items():
        setattr(item, key, value)
    await _create_log(
        db,
        'mytax_profile_updated',
        f'Обновлен профиль: {item.name}',
        context={'profile_id': item.id, 'provider': item.provider},
    )
    item.is_authenticated = False
    item.last_error = 'Профиль обновлён. Выполните проверку входа.'
    await db.commit()
    await db.refresh(item)
    return item


@router.delete('/profiles/{profile_id}')
async def delete_profile(profile_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')

    stores_res = await db.execute(select(Store).where(Store.mytax_profile_id == profile_id))
    stores = list(stores_res.scalars().all())
    for store in stores:
        store.mytax_profile_id = None

    await db.delete(item)
    await _create_log(
        db,
        'mytax_profile_deleted',
        f'Удален профиль: {item.name}',
        context={'profile_id': profile_id, 'affected_stores': len(stores)},
    )
    await db.commit()
    return {'status': 'deleted'}


@router.post('/profiles/{profile_id}/login', response_model=MyTaxProfileOut)
async def login_profile(profile_id: int, payload: LoginProfileIn, db: AsyncSession = Depends(get_db)) -> MyTaxProfile:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')
    released_tasks = 0
    await _create_log(
        db,
        'mytax_auth_check_started',
        f'Запущена проверка авторизации профиля {item.name}',
        context=_profile_auth_context(item),
    )

    try:
        if item.provider == 'unofficial_api':
            client = UnofficialMyTaxClient(item)
            has_token_or_cookie = bool(extract_access_token(item.access_token) or normalize_cookie_blob(item.cookie_blob))
            has_refresh_token = bool((item.refresh_token or '').strip())
            has_inn_password = bool((item.inn or '').strip() and (item.password or '').strip())

            if has_token_or_cookie:
                try:
                    probe_user = await client.probe_auth()
                    item.is_authenticated = True
                    item.last_error = ''
                    item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
                    await _create_log(
                        db,
                        'mytax_auth_check_success',
                        f'Профиль {item.name} авторизован по access_token/cookie',
                        context={**_profile_auth_context(item), 'auth_method': 'token_or_cookie', 'user': probe_user},
                    )
                except Exception as probe_exc:
                    if has_refresh_token:
                        token_payload = await client.refresh_access_token()
                        token_payload_json = json.dumps(token_payload, ensure_ascii=False)
                        item.access_token = extract_access_token(token_payload_json)
                        item.refresh_token = extract_refresh_token(token_payload_json, item.refresh_token)
                        probe_user = await client.probe_auth()
                        item.is_authenticated = True
                        item.last_error = ''
                        item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
                        await _create_log(
                            db,
                            'mytax_auth_login_refresh_fallback_success',
                            f'Профиль {item.name} переавторизован по refresh_token после ошибки access_token/cookie',
                            context={
                                **_profile_auth_context(item),
                                'auth_method': 'refresh_token_fallback',
                                'probe_error': str(probe_exc),
                                'user': probe_user,
                            },
                        )
                    elif has_inn_password:
                        token_payload = await client.login_with_inn_password()
                        token_payload_json = json.dumps(token_payload, ensure_ascii=False)
                        item.access_token = extract_access_token(token_payload_json)
                        item.refresh_token = extract_refresh_token(token_payload_json, item.refresh_token)
                        probe_user = await client.probe_auth()
                        item.is_authenticated = True
                        item.last_error = ''
                        item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
                        await _create_log(
                            db,
                            'mytax_auth_login_password_fallback_success',
                            f'Профиль {item.name} переавторизован по ИНН/паролю после ошибки access_token/cookie',
                            context={
                                **_profile_auth_context(item),
                                'auth_method': 'inn_password_fallback',
                                'probe_error': str(probe_exc),
                                'user': probe_user,
                            },
                        )
                    else:
                        raise
            elif has_refresh_token:
                token_payload = await client.refresh_access_token()
                token_payload_json = json.dumps(token_payload, ensure_ascii=False)
                item.access_token = extract_access_token(token_payload_json)
                item.refresh_token = extract_refresh_token(token_payload_json, item.refresh_token)
                probe_user = await client.probe_auth()
                item.is_authenticated = True
                item.last_error = ''
                item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
                await _create_log(
                    db,
                    'mytax_auth_login_refresh_success',
                    f'Профиль {item.name} авторизован по refresh_token',
                    context={**_profile_auth_context(item), 'auth_method': 'refresh_token', 'user': probe_user},
                )
            elif item.inn and item.password:
                token_payload = await client.login_with_inn_password()
                item.access_token = extract_access_token(json.dumps(token_payload, ensure_ascii=False))
                item.refresh_token = extract_refresh_token(json.dumps(token_payload, ensure_ascii=False), item.refresh_token)
                probe_user = await client.probe_auth()
                item.is_authenticated = True
                item.last_error = ''
                item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
                await _create_log(
                    db,
                    'mytax_auth_login_password_success',
                    f'Профиль {item.name} авторизован по ИНН/паролю',
                    context={**_profile_auth_context(item), 'auth_method': 'inn_password', 'user': probe_user},
                )
            elif payload.force:
                raise MyTaxApiError('Недостаточно данных для проверки. Нужны cookie/access_token или ИНН+пароль')
            else:
                raise MyTaxApiError('Недостаточно данных для проверки. Нужны cookie/access_token или ИНН+пароль')

        else:
            if item.access_token:
                item.is_authenticated = True
                item.last_error = ''
                item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
            else:
                raise MyTaxApiError('Для official_api требуется access_token')

        released_tasks = await _release_waiting_auth_tasks(db, item.id)
    except Exception as exc:
        item.is_authenticated = False
        item.last_error = str(exc)
        await _create_log(
            db,
            'mytax_auth_check_failed',
            f'Проверка авторизации профиля {item.name} неуспешна: {exc}',
            level='error',
            context={**_profile_auth_context(item), 'error': str(exc)},
        )

    await _create_log(db, 'mytax_profile_login', f'Обновлен статус авторизации: {item.name}', context={'profile_id': item.id})
    if released_tasks:
        await _create_log(
            db,
            'queue_resume_after_auth',
            f'Возобновлено задач после авторизации: {released_tasks}',
            context={'profile_id': item.id, 'released_tasks': released_tasks},
        )
        await _notify_auth_recovered(db, item.id, released_tasks)
    await db.commit()
    await db.refresh(item)
    return item


@router.post('/profiles/{profile_id}/auth/check', response_model=ProfileAuthStatusOut)
async def check_profile_auth(profile_id: int, db: AsyncSession = Depends(get_db)) -> ProfileAuthStatusOut:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')

    provider = str(item.provider)
    if provider != 'unofficial_api':
        return ProfileAuthStatusOut(
            profile_id=item.id,
            is_authenticated=bool(item.access_token),
            message='Для official_api доступна только локальная проверка наличия access_token',
            provider=provider,
            user={},
        )

    try:
        client = UnofficialMyTaxClient(item)
        await _create_log(
            db,
            'mytax_auth_probe_started',
            f'Запущен auth probe профиля {item.name}',
            context=_profile_auth_context(item),
        )
        user = await client.probe_auth()
        item.is_authenticated = True
        item.last_error = ''
        item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
        released = await _release_waiting_auth_tasks(db, item.id)
        await _create_log(
            db,
            'mytax_auth_probe_success',
            f'Проверка авторизации профиля {item.name} успешна',
            context={**_profile_auth_context(item), 'released_tasks': released},
        )
        await db.commit()
        if released:
            await _notify_auth_recovered(db, item.id, released)
        return ProfileAuthStatusOut(
            profile_id=item.id,
            is_authenticated=True,
            message='Проверка успешна',
            provider=provider,
            user=user if isinstance(user, dict) else {},
        )
    except Exception as exc:
        item.is_authenticated = False
        item.last_error = str(exc)
        await _create_log(
            db,
            'mytax_auth_probe_failed',
            f'Проверка авторизации профиля {item.name} провалилась: {exc}',
            level='error',
            context={**_profile_auth_context(item), 'error': str(exc)},
        )
        await db.commit()
        return ProfileAuthStatusOut(
            profile_id=item.id,
            is_authenticated=False,
            message=str(exc),
            provider=provider,
            user={},
        )


@router.post('/profiles/{profile_id}/auth/phone/start')
async def start_profile_phone_auth(
    profile_id: int,
    payload: ProfilePhoneChallengeIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')
    if str(item.provider) != 'unofficial_api':
        raise HTTPException(status_code=400, detail='Phone auth is supported only for unofficial_api')

    phone = _require_valid_phone(payload.phone or item.phone)

    client = UnofficialMyTaxClient(item)
    try:
        await _create_log(
            db,
            'mytax_phone_challenge_start_requested',
            f'Запрошен старт SMS challenge для профиля {item.name}',
            context={**_profile_auth_context(item), 'phone': phone},
        )
        result = await client.start_phone_challenge(phone)
        item.phone = phone
        await _create_log(
            db,
            'mytax_phone_challenge_started',
            f'SMS challenge запрошен для профиля {item.name}',
            context={**_profile_auth_context(item), 'phone': phone, 'response': result},
        )
        await db.commit()
        return {'status': 'ok', 'phone': phone, **result}
    except Exception as exc:
        item.last_error = str(exc)
        detail = _mytax_error_detail(exc)
        await _create_log(
            db,
            'mytax_phone_challenge_failed',
            f'Не удалось запросить SMS challenge для профиля {item.name}: {exc}',
            level='error',
            context={**_profile_auth_context(item), 'phone': phone, 'error': str(exc), 'detail': detail},
        )
        await db.commit()
        code = str(detail.get('code') or '')
        if code == 'registration.sms.verification.not.expired':
            raise HTTPException(
                status_code=409,
                detail={
                    **detail,
                    'phone': phone,
                    'can_verify': True,
                    'action': 'use_existing_challenge',
                },
            ) from exc
        raise HTTPException(status_code=400, detail=detail) from exc


@router.post('/profiles/{profile_id}/auth/phone/verify', response_model=MyTaxProfileOut)
async def verify_profile_phone_auth(
    profile_id: int,
    payload: ProfilePhoneVerifyIn,
    db: AsyncSession = Depends(get_db),
) -> MyTaxProfile:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')
    if str(item.provider) != 'unofficial_api':
        raise HTTPException(status_code=400, detail='Phone auth is supported only for unofficial_api')

    phone = _require_valid_phone(payload.phone or item.phone)

    client = UnofficialMyTaxClient(item)
    try:
        await _create_log(
            db,
            'mytax_phone_verify_started',
            f'Запущена проверка SMS-кода для профиля {item.name}',
            context={**_profile_auth_context(item), 'phone': phone},
        )
        token_payload = await client.verify_phone_challenge(phone, payload.challenge_token, payload.code)
        token_payload_json = json.dumps(token_payload, ensure_ascii=False)
        item.phone = phone
        item.access_token = extract_access_token(token_payload_json)
        item.refresh_token = extract_refresh_token(token_payload_json, item.refresh_token)
        user = await client.probe_auth()
        item.is_authenticated = True
        item.last_error = ''
        item.last_auth_at = datetime.now(UTC).replace(tzinfo=None)
        released_tasks = await _release_waiting_auth_tasks(db, item.id)
        await _create_log(
            db,
            'mytax_phone_auth_success',
            f'Профиль {item.name} авторизован по телефону',
            context={**_profile_auth_context(item), 'phone': phone, 'user': user, 'released_tasks': released_tasks},
        )
        await _notify_auth_recovered(db, item.id, released_tasks)
        await db.commit()
        await db.refresh(item)
        return item
    except Exception as exc:
        item.is_authenticated = False
        item.last_error = str(exc)
        detail = _mytax_error_detail(exc)
        await _create_log(
            db,
            'mytax_phone_auth_failed',
            f'Ошибка подтверждения SMS-кода для профиля {item.name}: {exc}',
            level='error',
            context={**_profile_auth_context(item), 'phone': phone, 'error': str(exc), 'detail': detail},
        )
        await db.commit()
        raise HTTPException(status_code=400, detail=detail) from exc


@router.get('/profiles/{profile_id}/logs', response_model=list[AppLogOut])
async def list_profile_logs(
    profile_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AppLog]:
    item = await db.get(MyTaxProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Profile not found')

    result = await db.execute(select(AppLog).order_by(AppLog.id.desc()).limit(2000))
    logs = list(result.scalars().all())
    filtered = [
        log
        for log in logs
        if isinstance(log.context, dict) and str(log.context.get('profile_id', '')) == str(profile_id)
    ]
    return filtered[:limit]


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


@router.put('/relay-targets/{target_id}', response_model=RelayTargetOut)
async def update_relay_target(
    target_id: int,
    payload: RelayTargetUpdate,
    db: AsyncSession = Depends(get_db),
) -> RelayTarget:
    item = await db.get(RelayTarget, target_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Relay target not found')

    store = await db.get(Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail='Store not found')

    for key, value in payload.model_dump().items():
        setattr(item, key, value)

    await _create_log(
        db,
        'relay_target_updated',
        f'Обновлен ретранслятор: {item.name}',
        store_id=item.store_id,
        context={'target_id': item.id},
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.delete('/relay-targets/{target_id}')
async def delete_relay_target(target_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    item = await db.get(RelayTarget, target_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Relay target not found')

    await db.delete(item)
    await _create_log(
        db,
        'relay_target_deleted',
        f'Удален ретранслятор: {item.name}',
        store_id=item.store_id,
        context={'target_id': target_id},
    )
    await db.commit()
    return {'status': 'deleted'}


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


@router.put('/telegram-channels/{channel_id}', response_model=TelegramChannelOut)
async def update_telegram_channel(
    channel_id: int,
    payload: TelegramChannelUpdate,
    db: AsyncSession = Depends(get_db),
) -> TelegramChannel:
    item = await db.get(TelegramChannel, channel_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Telegram channel not found')

    store = await db.get(Store, payload.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail='Store not found')

    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await _create_log(
        db,
        'telegram_channel_updated',
        f'Обновлён Telegram канал: {item.name}',
        store_id=item.store_id,
        context={'channel_id': item.id},
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.post('/telegram-channels/{channel_id}/test')
async def test_telegram_channel(
    channel_id: int,
    payload: TelegramTestMessageIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await db.get(TelegramChannel, channel_id)
    if item is None:
        raise HTTPException(status_code=404, detail='Telegram channel not found')

    await send_telegram_message(
        bot_token=item.bot_token,
        chat_id=item.chat_id,
        text=payload.text,
        topic_id=item.topic_id,
    )
    await _create_log(
        db,
        'telegram_channel_test_sent',
        f'Отправлено тестовое сообщение в Telegram канал: {item.name}',
        store_id=item.store_id,
        context={'channel_id': item.id},
    )
    await db.commit()
    return {'status': 'sent'}


@router.get('/maintenance/settings', response_model=MaintenanceSettingsOut)
async def get_maintenance_settings(db: AsyncSession = Depends(get_db)) -> MaintenanceSettings:
    item = await _get_or_create_maintenance_settings(db)
    await db.commit()
    await db.refresh(item)
    return item


@router.put('/maintenance/settings', response_model=MaintenanceSettingsOut)
async def update_maintenance_settings(
    payload: MaintenanceSettingsBase,
    db: AsyncSession = Depends(get_db),
) -> MaintenanceSettings:
    item = await _get_or_create_maintenance_settings(db)
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await _create_log(
        db,
        'maintenance_settings_updated',
        'Обновлены настройки очистки БД',
        context=payload.model_dump(),
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.post('/maintenance/cleanup', response_model=MaintenanceCleanupOut)
async def run_maintenance_cleanup(db: AsyncSession = Depends(get_db)) -> MaintenanceCleanupOut:
    item = await _get_or_create_maintenance_settings(db)
    result = await _run_cleanup(db, item)
    await _create_log(
        db,
        'maintenance_cleanup_done',
        'Выполнена очистка БД по настройкам',
        context=result.model_dump(),
    )
    await db.commit()
    return result


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
    event: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[AppLog]:
    query: Select[tuple[AppLog]] = select(AppLog).order_by(AppLog.id.desc()).limit(limit)
    if store_id is not None:
        query = query.where(AppLog.store_id == store_id)
    if level is not None:
        query = query.where(AppLog.level == level)
    if event is not None:
        query = query.where(AppLog.event == event)
    if q:
        query = query.where(AppLog.message.ilike(f'%{q}%'))
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
async def yookassa_webhook(store_path: str, payload: dict, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Store).where(Store.webhook_path == store_path, Store.is_active.is_(True)))
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail='Store not found')

    event_name, object_payload = _validate_webhook_payload(payload)
    source_ip = _extract_client_ip(request)

    if _is_antifraud_enabled():
        if not _is_ip_allowed(source_ip):
            raise HTTPException(status_code=403, detail='Webhook source IP is not allowed')
        await _verify_object_status_with_yookassa(event_name, object_payload)

    payment_id = str(get_nested(payload, store.payment_id_path, ''))
    if not payment_id:
        payment_id = str(object_payload.get('id', 'unknown'))

    event = PaymentEvent(
        store_id=store.id,
        event_type=event_name,
        payment_id=payment_id,
        payload=payload,
    )
    db.add(event)
    await db.flush()

    event.relay_status = await relay_notification(db, store, payload, dispatch_stage='webhook')

    if event_name in {'payment.succeeded', 'payment.waiting_for_capture'}:
        existing_task_id = (await db.execute(
            select(ReceiptTask.id).where(
                ReceiptTask.store_id == store.id,
                ReceiptTask.payment_id == payment_id,
                ReceiptTask.task_type == TaskType.CREATE_RECEIPT
            ).limit(1)
        )).scalar_one_or_none()

        existing_receipt_id = (await db.execute(
            select(Receipt.id).where(
                Receipt.store_id == store.id,
                Receipt.payment_id == payment_id
            ).limit(1)
        )).scalar_one_or_none()

        if existing_task_id or existing_receipt_id:
            await _create_log(
                db,
                'webhook_create_skipped',
                f'Пропущено создание чека: уже есть задача или чек для платежа {payment_id}',
                store_id=store.id,
                level='info',
                context={'payment_id': payment_id, 'event_name': event_name, 'event_id': event.id},
            )
        else:
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
        receipt_uuid = (receipt.receipt_uuid if receipt else '') or ''
        if receipt_uuid.strip():
            task = ReceiptTask(
                store_id=store.id,
                event_id=event.id,
                payment_id=payment_id,
                task_type=TaskType.CANCEL_RECEIPT,
                payload={'receipt_uuid': receipt_uuid.strip()},
            )
            db.add(task)
            await notify_store(
                db,
                store_id=store.id,
                event_name='refund_received',
                message=f'Получено уведомление на возврат {payment_id} ({event_name})',
            )
        else:
            await _create_log(
                db,
                'webhook_cancel_skipped_no_receipt',
                f'Пропущена постановка cancel task: чек не найден для платежа {payment_id}',
                store_id=store.id,
                level='warning',
                context={'payment_id': payment_id, 'event_name': event_name, 'event_id': event.id},
            )
            await notify_store(
                db,
                store_id=store.id,
                event_name='refund_received_without_receipt',
                message=(
                    f'Получено уведомление {event_name} по платежу {payment_id}, '
                    'но локальный чек не найден. Задача отмены не создана.'
                ),
            )

    await _create_log(
        db,
        'webhook_received',
        f'Вебхук {event_name} для платежа {payment_id}',
        store_id=store.id,
        context={**payload, 'source_ip': source_ip},
    )
    await db.commit()
    return {'status': 'accepted', 'event_id': event.id, 'relay_status': event.relay_status}
