from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from app.core.config import settings


def is_panel_auth_configured() -> bool:
    return bool(settings.panel_login.strip() and settings.panel_password)


def _secret_key_bytes() -> bytes:
    explicit = settings.panel_auth_secret.strip()
    if explicit:
        return explicit.encode('utf-8')
    seed = f"{settings.panel_login}:{settings.panel_password}:{settings.app_name}"
    return hashlib.sha256(seed.encode('utf-8')).digest()


def verify_credentials(login: str, password: str) -> bool:
    expected_login = settings.panel_login.strip()
    expected_password = settings.panel_password
    if not expected_login or not expected_password:
        return False
    return hmac.compare_digest(login or '', expected_login) and hmac.compare_digest(password or '', expected_password)


def create_session_token(login: str) -> str:
    issued_at = int(time.time())
    nonce = base64.urlsafe_b64encode(os.urandom(16)).decode('ascii').rstrip('=')
    payload = f"{login}|{issued_at}|{nonce}"
    signature = hmac.new(_secret_key_bytes(), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    raw = f"{payload}|{signature}"
    return base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii')


def verify_session_token(token: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(token.encode('ascii')).decode('utf-8')
        login, issued_at_str, nonce, signature = decoded.split('|', 3)
        payload = f"{login}|{issued_at_str}|{nonce}"
        expected_signature = hmac.new(_secret_key_bytes(), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return False

        if not hmac.compare_digest(login, settings.panel_login.strip()):
            return False

        issued_at = int(issued_at_str)
        now = int(time.time())
        if now - issued_at > settings.panel_auth_token_ttl_seconds:
            return False

        return True
    except Exception:
        return False
