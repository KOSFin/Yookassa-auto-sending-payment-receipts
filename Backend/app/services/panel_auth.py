from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from app.core.config import settings


def _normalize_credential(value: str | None) -> str:
    text = (value or '').strip()
    if len(text) >= 2 and ((text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'"))):
        text = text[1:-1].strip()
    return text


def is_panel_auth_configured() -> bool:
    return bool(_normalize_credential(settings.panel_login) and _normalize_credential(settings.panel_password))


def _secret_key_bytes() -> bytes:
    explicit = _normalize_credential(settings.panel_auth_secret)
    if explicit:
        return explicit.encode('utf-8')
    seed = f"{_normalize_credential(settings.panel_login)}:{_normalize_credential(settings.panel_password)}:{settings.app_name}"
    return hashlib.sha256(seed.encode('utf-8')).digest()


def verify_credentials(login: str, password: str) -> bool:
    expected_login = _normalize_credential(settings.panel_login)
    expected_password = _normalize_credential(settings.panel_password)
    actual_login = _normalize_credential(login)
    actual_password = _normalize_credential(password)
    
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"verify_credentials: expected_login_len={len(expected_login)}, actual_login_len={len(actual_login)}")
    logger.warning(f"verify_credentials: expected_pass_len={len(expected_password)}, actual_pass_len={len(actual_password)}")
    logger.warning(f"verify_credentials: login_match={hmac.compare_digest(actual_login, expected_login)}, pass_match={hmac.compare_digest(actual_password, expected_password)}")
    
    if not expected_login or not expected_password:
        logger.error("verify_credentials: expected credentials are empty")
        return False
    return hmac.compare_digest(actual_login, expected_login) and hmac.compare_digest(actual_password, expected_password)


def create_session_token(login: str) -> str:
    issued_at = int(time.time())
    nonce = base64.urlsafe_b64encode(os.urandom(16)).decode('ascii').rstrip('=')
    payload = f"{_normalize_credential(login)}|{issued_at}|{nonce}"
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

        if not hmac.compare_digest(login, _normalize_credential(settings.panel_login)):
            return False

        issued_at = int(issued_at_str)
        now = int(time.time())
        if now - issued_at > settings.panel_auth_token_ttl_seconds:
            return False

        return True
    except Exception:
        return False
