from __future__ import annotations

import json

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RelayMode, RelayTarget, Store
from app.services.template import render_template


async def relay_notification(
    db: AsyncSession,
    store: Store,
    payload: dict,
    receipt_url: str = '',
) -> str:
    query = select(RelayTarget).where(RelayTarget.store_id == store.id, RelayTarget.is_active.is_(True))
    result = await db.execute(query)
    targets = result.scalars().all()

    if not targets:
        return 'no_targets'

    status = 'success'
    async with httpx.AsyncClient(timeout=15) as client:
        for target in targets:
            body = payload.copy()
            if store.include_receipt_url_in_relay and receipt_url:
                body['generated_receipt_url'] = receipt_url

            if target.payload_template:
                rendered = render_template(target.payload_template, {'payload': body, **body})
                try:
                    body = json.loads(rendered)
                except json.JSONDecodeError:
                    body = {'rendered_payload': rendered, 'payload': body}

            if store.relay_mode == RelayMode.FIRE_AND_FORGET:
                try:
                    await client.request(target.method.upper(), target.url, json=body, headers=target.headers_json)
                except Exception:
                    status = 'partial_error'
                continue

            ok = False
            for _ in range(max(1, store.relay_retry_limit)):
                try:
                    response = await client.request(target.method.upper(), target.url, json=body, headers=target.headers_json)
                    if response.status_code == 200:
                        ok = True
                        break
                except Exception:
                    pass
            if not ok:
                status = 'error'

    return status
