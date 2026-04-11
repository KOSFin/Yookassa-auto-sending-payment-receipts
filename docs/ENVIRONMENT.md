# Переменные окружения

Ниже практический справочник по `.env`.

## Обязательные

- `POSTGRES_DB` — имя БД.
- `POSTGRES_USER` — пользователь БД.
- `POSTGRES_PASSWORD` — пароль БД.
- `PANEL_LOGIN` — логин входа в панель.
- `PANEL_PASSWORD` — пароль входа в панель.

Если `PANEL_LOGIN` или `PANEL_PASSWORD` пустые — панель блокируется.

## Рекомендуемые

- `PANEL_AUTH_SECRET` — секрет подписи сессий.
- `PROXY_BASE_URL` — публичный URL (обычно `https://...`).
- `PANEL_AUTH_COOKIE_SECURE=true` — для HTTPS.

## Worker

- `WORKER_POLL_INTERVAL_SECONDS` (integer, обычно 10-30).
- `RUN_EMBEDDED_WORKER` (`true/false`).
- `RECEIPT_TIMEZONE` — часовой пояс для `operationTime/requestTime` при регистрации чека в Мой Налог.

Поддерживаемые форматы `RECEIPT_TIMEZONE`:
1. `UTC`;
2. Смещение: `+05:00`, `-03:30`, `+0500`, `+05`;
3. IANA-таймзона: `Asia/Yekaterinburg`, `Europe/Moscow`.

## Anti-fraud

- `WEBHOOK_ANTIFRAUD_ENABLED` (`true/false`) — единый тумблер.
- `YOOKASSA_SHOP_ID` — обязателен при включённом anti-fraud.
- `YOOKASSA_SECRET_KEY` — обязателен при включённом anti-fraud.

При `WEBHOOK_ANTIFRAUD_ENABLED=true` выполняются:
1. Проверка IP источника webhook;
2. Проверка статуса объекта через YooKassa API.

## Telegram

- `TELEGRAM_PROXY_URL` — глобальный прокси для всех Telegram API запросов (опционально).
  Примеры:
  - `http://proxy.example.com:8080`
  - `http://user:pass@proxy.example.com:8080`
  - `socks5://proxy.example.com:1080`

## Legacy

- `WEBHOOK_IP_VALIDATION` — legacy совместимость. Используйте `WEBHOOK_ANTIFRAUD_ENABLED`.
