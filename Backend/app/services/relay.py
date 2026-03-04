from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppLog
from app.models import RelayMode, RelayTarget, Store
from app.services.template import render_template

logger = logging.getLogger(__name__)


def _short_text(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return f'{value[:limit]}... [truncated {len(value) - limit} chars]'


def _add_relay_log(
    db: AsyncSession,
    store_id: int,
    level: str,
    event: str,
    message: str,
    context: dict,
) -> None:
    db.add(
        AppLog(
            store_id=store_id,
            level=level,
            event=event,
            message=message,
            context=context,
        )
    )


async def relay_notification(
    db: AsyncSession,
    store: Store,
    payload: dict,
    receipt_url: str = '',
    receipt_uuid: str = '',
    dispatch_stage: str = 'webhook',
) -> str:
    query = select(RelayTarget).where(RelayTarget.store_id == store.id, RelayTarget.is_active.is_(True))
    result = await db.execute(query)
    targets = result.scalars().all()

    if not targets:
        return 'no_targets'

    has_receipt_data = bool(receipt_url or receipt_uuid)
    attempted_targets = 0
    skipped_targets = 0
    status = 'success'

    async with httpx.AsyncClient(timeout=15) as client:
        for target in targets:
            if dispatch_stage == 'webhook' and target.include_receipt_url and not has_receipt_data:
                skipped_targets += 1
                _add_relay_log(
                    db,
                    store.id,
                    'info',
                    'relay_dispatch_skipped',
                    f'Relay target skipped until receipt is created: {target.name}',
                    {
                        'stage': dispatch_stage,
                        'target_id': target.id,
                        'target_name': target.name,
                        'url': target.url,
                        'reason': 'receipt_url_required',
                    },
                )
                continue

            if dispatch_stage == 'receipt' and not target.include_receipt_url:
                continue

            attempted_targets += 1
            body = payload.copy()
            if target.include_receipt_url:
                if receipt_url:
                    body['generated_receipt_url'] = receipt_url
                if receipt_uuid:
                    body['generated_receipt_uuid'] = receipt_uuid

            if target.payload_template:
                rendered = render_template(target.payload_template, {'payload': body, **body})
                try:
                    body = json.loads(rendered)
                except json.JSONDecodeError:
                    body = {'rendered_payload': rendered, 'payload': body}

            if store.relay_mode == RelayMode.FIRE_AND_FORGET:
                try:
                    response = await client.request(target.method.upper(), target.url, json=body, headers=target.headers_json)
                    _add_relay_log(
                        db,
                        store.id,
                        'info',
                        'relay_dispatch_sent',
                        f'Relay delivered to {target.name} (fire-and-forget)',
                        {
                            'stage': dispatch_stage,
                            'target_id': target.id,
                            'target_name': target.name,
                            'url': target.url,
                            'method': target.method.upper(),
                            'request_headers': target.headers_json,
                            'request_body': body,
                            'response_status': response.status_code,
                            'response_body': _short_text(response.text),
                        },
                    )
                except Exception as exc:
                    status = 'partial_error'
                    _add_relay_log(
                        db,
                        store.id,
                        'error',
                        'relay_dispatch_failed',
                        f'Relay failed for {target.name} (fire-and-forget): {exc}',
                        {
                            'stage': dispatch_stage,
                            'target_id': target.id,
                            'target_name': target.name,
                            'url': target.url,
                            'method': target.method.upper(),
                            'request_headers': target.headers_json,
                            'request_body': body,
                            'error': str(exc),
                        },
                    )
                continue

            ok = False
            for attempt in range(1, max(1, store.relay_retry_limit) + 1):
                try:
                    response = await client.request(target.method.upper(), target.url, json=body, headers=target.headers_json)
                    _add_relay_log(
                        db,
                        store.id,
                        'info',
                        'relay_dispatch_attempt',
                        f'Relay attempt {attempt} for {target.name} returned HTTP {response.status_code}',
                        {
                            'stage': dispatch_stage,
                            'target_id': target.id,
                            'target_name': target.name,
                            'url': target.url,
                            'method': target.method.upper(),
                            'attempt': attempt,
                            'retry_limit': max(1, store.relay_retry_limit),
                            'request_headers': target.headers_json,
                            'request_body': body,
                            'response_status': response.status_code,
                            'response_body': _short_text(response.text),
                        },
                    )
                    if response.status_code == 200:
                        ok = True
                        break
                except Exception as exc:
                    _add_relay_log(
                        db,
                        store.id,
                        'warning',
                        'relay_dispatch_attempt_failed',
                        f'Relay attempt {attempt} for {target.name} failed: {exc}',
                        {
                            'stage': dispatch_stage,
                            'target_id': target.id,
                            'target_name': target.name,
                            'url': target.url,
                            'method': target.method.upper(),
                            'attempt': attempt,
                            'retry_limit': max(1, store.relay_retry_limit),
                            'request_headers': target.headers_json,
                            'request_body': body,
                            'error': str(exc),
                        },
                    )
            if not ok:
                status = 'error'
                _add_relay_log(
                    db,
                    store.id,
                    'error',
                    'relay_dispatch_failed',
                    f'Relay target failed after retries: {target.name}',
                    {
                        'stage': dispatch_stage,
                        'target_id': target.id,
                        'target_name': target.name,
                        'url': target.url,
                        'method': target.method.upper(),
                        'retry_limit': max(1, store.relay_retry_limit),
                        'request_body': body,
                    },
                )

    if attempted_targets == 0:
        if dispatch_stage == 'webhook' and skipped_targets > 0:
            return 'deferred_until_receipt'
        return 'no_targets_for_phase'

    if status == 'success' and skipped_targets > 0 and dispatch_stage == 'webhook':
        logger.info(
            'Relay webhook stage sent to %s targets, %s targets deferred until receipt',
            attempted_targets,
            skipped_targets,
        )

    return status
