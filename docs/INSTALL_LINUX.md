# Установка и запуск на Linux

## 1. Требования

- Linux (Ubuntu/Debian/CentOS/AlmaLinux)
- Docker Engine
- Docker Compose plugin
- `curl` (желательно)

Проверка:

```bash
docker --version
docker compose version
```

## 2. Подготовка

```bash
cd /opt/yookassa-auto
cp .env.example .env
```

Заполните минимум в `.env`:

```env
POSTGRES_PASSWORD=very-strong-password
PROXY_BASE_URL=https://your-domain.tld
PANEL_LOGIN=admin
PANEL_PASSWORD=very-strong-panel-password
PANEL_AUTH_SECRET=long-random-secret
PANEL_AUTH_COOKIE_SECURE=true
```

## 3. Запуск через helper script

```bash
chmod +x scripts/up.sh
./scripts/up.sh
```

Скрипт:

- создаёт `.env` при отсутствии;
- выполняет `docker compose up -d --build --remove-orphans`;
- показывает состояние сервисов;
- делает проверку `http://127.0.0.1/api/health`.

## 4. Ручной запуск (без скрипта)

```bash
docker compose up -d --build --remove-orphans
```

## 5. Базовые операции

```bash
# Логи
docker compose logs backend --tail=200
docker compose logs worker --tail=200
docker compose logs proxy --tail=200

# Остановка
docker compose down

# Запуск
docker compose up -d
```

## 6. Рекомендации для production

- Не используйте `docker compose down -v` (потеряете БД volume).
- Ставьте сильные `POSTGRES_PASSWORD`, `PANEL_PASSWORD` и `PANEL_AUTH_SECRET`.
- Держите `PANEL_AUTH_COOKIE_SECURE=true` при HTTPS.
