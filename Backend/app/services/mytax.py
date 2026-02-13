from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from app.core.config import settings
from app.models import MyTaxProfile, MyTaxProvider


class MyTaxAuthError(Exception):
    pass


class MyTaxApiError(Exception):
    pass


@dataclass
class MyTaxReceiptResult:
    receipt_uuid: str
    receipt_url: str
    raw: dict


class MyTaxClient:
    def __init__(self, profile: MyTaxProfile):
        self.profile = profile

    async def _request(
        self,
        method: str,
        url: str,
        json_payload: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.request(method, url, json=json_payload, headers=headers)
            if response.status_code in {401, 403}:
                raise MyTaxAuthError('Ошибка авторизации в Мой Налог, требуется повторный вход')
            if response.status_code >= 400:
                raise MyTaxApiError(f'MyTax API error {response.status_code}: {response.text}')
            if response.content:
                return response.json()
            return {}
        except MyTaxAuthError:
            raise
        except httpx.HTTPError as exc:
            raise MyTaxApiError(f'Ошибка HTTP запроса в Мой Налог: {exc}') from exc

    async def ensure_authenticated(self) -> None:
        if not self.profile.is_authenticated:
            raise MyTaxAuthError('Профиль не аутентифицирован')

    async def create_receipt(self, description: str, amount: float, payment_id: str) -> MyTaxReceiptResult:
        raise NotImplementedError

    async def cancel_receipt(self, receipt_uuid: str) -> dict:
        raise NotImplementedError


class UnofficialMyTaxClient(MyTaxClient):
    base_url = 'https://lknpd.nalog.ru'

    async def ensure_authenticated(self) -> None:
        if not self.profile.is_authenticated:
            raise MyTaxAuthError('Профиль не аутентифицирован')
        if not (self.profile.access_token or self.profile.cookie_blob):
            raise MyTaxAuthError('Нет access_token/cookie для неофициального API')

    def _headers(self) -> dict:
        headers: dict[str, str] = {'Content-Type': 'application/json'}
        if self.profile.access_token:
            headers['Authorization'] = f'Bearer {self.profile.access_token}'
        if self.profile.cookie_blob:
            headers['Cookie'] = self.profile.cookie_blob
        if self.profile.device_id:
            headers['Device-Id'] = self.profile.device_id
        return headers

    async def create_receipt(self, description: str, amount: float, payment_id: str) -> MyTaxReceiptResult:
        await self.ensure_authenticated()
        operation_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = {
            'operationTime': operation_time,
            'requestTime': operation_time,
            'services': [
                {
                    'name': description[:128],
                    'amount': float(amount),
                    'quantity': 1,
                }
            ],
            'paymentType': 'CASHLESS',
            'ignoreMaxTotalIncomeRestriction': True,
            'client': {'displayName': ''},
            'externalIncomeId': payment_id,
        }
        raw = await self._request('POST', f'{self.base_url}/api/v1/income', json_payload=payload, headers=self._headers())
        receipt_uuid = str(raw.get('approvedReceiptUuid') or raw.get('receiptUuid') or raw.get('id') or payment_id)
        receipt_url = str(raw.get('receiptUrl') or f'{self.base_url}/web/receipts/{receipt_uuid}')
        return MyTaxReceiptResult(receipt_uuid=receipt_uuid, receipt_url=receipt_url, raw=raw)

    async def cancel_receipt(self, receipt_uuid: str) -> dict:
        await self.ensure_authenticated()
        payload = {'receiptUuid': receipt_uuid}
        return await self._request('POST', f'{self.base_url}/api/v1/cancel', json_payload=payload, headers=self._headers())


class OfficialMyTaxClient(MyTaxClient):
    async def ensure_authenticated(self) -> None:
        if not self.profile.is_authenticated:
            raise MyTaxAuthError('Профиль не аутентифицирован')
        if not self.profile.access_token:
            raise MyTaxAuthError('Нет access_token для official API')

    def _headers(self) -> dict:
        return {'Authorization': f'Bearer {self.profile.access_token}', 'Content-Type': 'application/json'}

    async def create_receipt(self, description: str, amount: float, payment_id: str) -> MyTaxReceiptResult:
        await self.ensure_authenticated()
        if not settings.proxy_base_url:
            raise MyTaxApiError('Для official API требуется настроить endpoint в интеграции')
        payload = {
            'description': description,
            'amount': float(amount),
            'payment_id': payment_id,
        }
        raw = await self._request('POST', f'{settings.proxy_base_url}/mytax/receipt', json_payload=payload, headers=self._headers())
        receipt_uuid = str(raw.get('receipt_uuid') or payment_id)
        receipt_url = str(raw.get('receipt_url') or '')
        return MyTaxReceiptResult(receipt_uuid=receipt_uuid, receipt_url=receipt_url, raw=raw)

    async def cancel_receipt(self, receipt_uuid: str) -> dict:
        await self.ensure_authenticated()
        payload = {'receipt_uuid': receipt_uuid}
        return await self._request('POST', f'{settings.proxy_base_url}/mytax/cancel', json_payload=payload, headers=self._headers())


def build_mytax_client(profile: MyTaxProfile) -> MyTaxClient:
    if profile.provider == MyTaxProvider.UNOFFICIAL_API:
        return UnofficialMyTaxClient(profile)
    if profile.provider == MyTaxProvider.OFFICIAL_API:
        return OfficialMyTaxClient(profile)
    raise MyTaxApiError('Неизвестный провайдер Мой Налог')
