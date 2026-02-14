from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

import httpx

from app.core.config import settings
from app.models import MyTaxProfile, MyTaxProvider


class MyTaxAuthError(Exception):
    pass


class MyTaxApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str = '',
        payload: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
        self.payload = payload or {}


@dataclass
class MyTaxReceiptResult:
    receipt_uuid: str
    receipt_url: str
    raw: dict


def _parse_json_value(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if not value.startswith('{'):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def extract_access_token(raw: str | None) -> str:
    if not raw:
        return ''
    parsed = _parse_json_value(raw)
    if not parsed:
        return raw.strip()
    token = parsed.get('token') or parsed.get('accessToken') or parsed.get('access_token')
    if isinstance(token, str):
        return token.strip()
    return raw.strip()


def extract_refresh_token(raw_access_token: str | None, raw_refresh_token: str | None) -> str:
    if raw_refresh_token:
        return raw_refresh_token.strip()
    parsed = _parse_json_value(raw_access_token)
    if not parsed:
        return ''
    token = parsed.get('refreshToken') or parsed.get('refresh_token')
    return token.strip() if isinstance(token, str) else ''


def normalize_cookie_blob(raw: str | None) -> str:
    if not raw:
        return ''
    value = raw.strip()
    if not value:
        return ''
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, dict):
        cookie_value = parsed.get('cookie') or parsed.get('Cookie')
        if isinstance(cookie_value, str):
            return cookie_value.strip()
        cookies = parsed.get('cookies')
        if isinstance(cookies, list):
            pairs = []
            for item in cookies:
                if isinstance(item, dict):
                    name = item.get('name')
                    cookie_item_value = item.get('value')
                    if isinstance(name, str) and isinstance(cookie_item_value, str):
                        pairs.append(f'{name}={cookie_item_value}')
            if pairs:
                return '; '.join(pairs)
    if isinstance(parsed, list):
        pairs = []
        for item in parsed:
            if isinstance(item, dict):
                name = item.get('name')
                cookie_item_value = item.get('value')
                if isinstance(name, str) and isinstance(cookie_item_value, str):
                    pairs.append(f'{name}={cookie_item_value}')
        if pairs:
            return '; '.join(pairs)
    return value


def _cookie_pairs(raw: str | None) -> list[tuple[str, str]]:
    normalized = normalize_cookie_blob(raw)
    if not normalized:
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in normalized.split(';'):
        part = chunk.strip()
        if not part or '=' not in part:
            continue
        name, value = part.split('=', 1)
        key = name.strip()
        item_value = value.strip()
        if key:
            pairs.append((key, item_value))
    return pairs


def extract_cookie_names(raw: str | None) -> list[str]:
    names = {name for name, _ in _cookie_pairs(raw)}
    return sorted(names)


def extract_xsrf_token(raw: str | None) -> str:
    for name, value in _cookie_pairs(raw):
        if name.lower() in {'xsrf-token', 'x-xsrf-token'}:
            return unquote(value)
    return ''


def _resolve_income_payment_type(payload: dict[str, Any] | None) -> str:
    if not payload:
        return 'WIRE'
    object_payload = payload.get('object')
    if not isinstance(object_payload, dict):
        return 'WIRE'
    payment_method = object_payload.get('payment_method')
    method_type = None
    if isinstance(payment_method, dict):
        method_type = payment_method.get('type')
    if isinstance(method_type, str) and method_type.lower() == 'cash':
        return 'CASH'
    return 'WIRE'


class MyTaxClient:
    def __init__(self, profile: MyTaxProfile):
        self.profile = profile

    async def _request(
        self,
        method: str,
        url: str,
        json_payload: dict | None = None,
        headers: dict | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.request(method, url, json=json_payload, headers=headers)
            if response.status_code in {401, 403}:
                raise MyTaxAuthError('Ошибка авторизации в Мой Налог, требуется повторный вход')
            if response.status_code >= 400:
                parsed_payload: dict[str, Any] | None = None
                try:
                    candidate = response.json()
                    if isinstance(candidate, dict):
                        parsed_payload = candidate
                except ValueError:
                    parsed_payload = None
                raise MyTaxApiError(
                    f'MyTax API error {response.status_code}: {response.text}',
                    status_code=response.status_code,
                    response_text=response.text,
                    payload=parsed_payload,
                )
            if response.content:
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type.lower():
                    return response.json()
                text = response.text.strip()
                if text:
                    try:
                        return response.json()
                    except ValueError:
                        return {'raw_text': text}
            return {}
        except MyTaxAuthError:
            raise
        except httpx.HTTPError as exc:
            raise MyTaxApiError(f'Ошибка HTTP запроса в Мой Налог: {exc}') from exc

    async def ensure_authenticated(self) -> None:
        if not self.profile.is_authenticated:
            raise MyTaxAuthError('Профиль не аутентифицирован')

    async def create_receipt(
        self,
        description: str,
        amount: float,
        payment_id: str,
        event_payload: dict[str, Any] | None = None,
    ) -> MyTaxReceiptResult:
        raise NotImplementedError

    async def cancel_receipt(self, receipt_uuid: str) -> dict:
        raise NotImplementedError


class UnofficialMyTaxClient(MyTaxClient):
    base_url = 'https://lknpd.nalog.ru'

    def _resolved_device_id(self) -> str:
        if self.profile.device_id and self.profile.device_id.strip():
            return self.profile.device_id.strip()
        generated = f'ya-{self.profile.id}-{uuid4().hex[:10]}'
        self.profile.device_id = generated
        return generated

    def _device_info(self) -> dict[str, Any]:
        return {
            'sourceType': 'WEB',
            'sourceDeviceId': self._resolved_device_id(),
            'appVersion': '1.0.0',
            'metaDetails': {
                'userAgent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            },
        }

    async def ensure_authenticated(self) -> None:
        if not self.profile.is_authenticated:
            raise MyTaxAuthError('Профиль не аутентифицирован')
        if not (extract_access_token(self.profile.access_token) or normalize_cookie_blob(self.profile.cookie_blob)):
            raise MyTaxAuthError('Нет access_token/cookie для неофициального API')

    def _headers(self) -> dict:
        headers: dict[str, str] = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': self.base_url,
            'Referer': f'{self.base_url}/',
            'User-Agent': self._device_info()['metaDetails']['userAgent'],
        }
        access_token = extract_access_token(self.profile.access_token)
        cookie_blob = normalize_cookie_blob(self.profile.cookie_blob)
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
        if cookie_blob:
            headers['Cookie'] = cookie_blob
        xsrf_token = extract_xsrf_token(cookie_blob)
        if xsrf_token:
            headers['X-XSRF-TOKEN'] = xsrf_token
        headers['Device-Id'] = self._resolved_device_id()
        return headers

    async def probe_auth(self) -> dict[str, Any]:
        headers = self._headers()
        endpoints = ('/api/v1/user', '/api/v1/taxpayer')
        last_error: Exception | None = None
        for endpoint in endpoints:
            try:
                response = await self._request('GET', f'{self.base_url}{endpoint}', headers=headers)
                if isinstance(response, dict):
                    return response
                return {'raw': response}
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise MyTaxApiError('Не удалось выполнить проверку авторизации')

    async def login_with_inn_password(self) -> dict[str, Any]:
        if not (self.profile.inn and self.profile.password):
            raise MyTaxAuthError('Для входа по ИНН/паролю требуется указать оба поля')
        payload = {
            'username': self.profile.inn,
            'password': self.profile.password,
            'deviceInfo': self._device_info(),
        }
        token_payload = await self._request(
            'POST',
            f'{self.base_url}/api/v1/auth/lkfl',
            json_payload=payload,
            headers={'Content-Type': 'application/json', 'Referrer': 'https://lknpd.nalog.ru/auth/login'},
        )
        if isinstance(token_payload, dict):
            return token_payload
        raise MyTaxApiError('Не удалось получить токен по ИНН/паролю: неожиданный формат ответа')

    async def start_phone_challenge(self, phone: str) -> dict[str, Any]:
        for require_tp in (True, False):
            payload = {'phone': phone, 'requireTpToBeActive': require_tp}
            try:
                response = await self._request(
                    'POST',
                    f'{self.base_url}/api/v2/auth/challenge/sms/start',
                    json_payload=payload,
                    headers={'Content-Type': 'application/json', 'Referrer': 'https://lknpd.nalog.ru/auth/login'},
                )
                if isinstance(response, dict):
                    response.setdefault('requireTpToBeActive', require_tp)
                    return response
                raise MyTaxApiError('Не удалось получить challengeToken: неожиданный формат ответа')
            except MyTaxApiError as exc:
                message = str(exc)
                if require_tp and 'auth.failed.no.tp' in message:
                    continue
                raise
        raise MyTaxApiError('Не удалось запросить SMS challenge')

    async def verify_phone_challenge(self, phone: str, challenge_token: str, code: str) -> dict[str, Any]:
        payload = {
            'phone': phone,
            'code': code,
            'challengeToken': challenge_token,
            'deviceInfo': self._device_info(),
        }
        token_payload = await self._request(
            'POST',
            f'{self.base_url}/api/v1/auth/challenge/sms/verify',
            json_payload=payload,
            headers={'Content-Type': 'application/json', 'Referrer': 'https://lknpd.nalog.ru/auth/login'},
        )
        if isinstance(token_payload, dict):
            return token_payload
        raise MyTaxApiError('Не удалось подтвердить SMS-код: неожиданный формат ответа')

    async def create_receipt(
        self,
        description: str,
        amount: float,
        payment_id: str,
        event_payload: dict[str, Any] | None = None,
    ) -> MyTaxReceiptResult:
        await self.ensure_authenticated()
        operation_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        payment_type = _resolve_income_payment_type(event_payload)
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
            'paymentType': payment_type,
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

    async def create_receipt(
        self,
        description: str,
        amount: float,
        payment_id: str,
        event_payload: dict[str, Any] | None = None,
    ) -> MyTaxReceiptResult:
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
