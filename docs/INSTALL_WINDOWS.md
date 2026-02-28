# Установка и запуск на Windows (подробно)

## 1. Требования

- Windows 10/11
- Docker Desktop (WSL2 backend включён)
- PowerShell 5.1+ или PowerShell 7+

Проверка:

```powershell
docker --version
docker compose version
```

## 2. Подготовка проекта

```powershell
cd c:\dev
yookassa-auto
Copy-Item .env.example .env
```

Откройте `.env` и заполните минимум:

```env
POSTGRES_PASSWORD=very-strong-password
PROXY_BASE_URL=https://your-domain.tld
PANEL_LOGIN=admin
PANEL_PASSWORD=very-strong-panel-password
PANEL_AUTH_SECRET=long-random-secret
PANEL_AUTH_COOKIE_SECURE=true
```

## 3. Первый запуск (автоматизировано)

```powershell
./scripts/up.ps1
```

Что делает скрипт:
- создаёт `.env` из `.env.example`, если его нет;
- при `FORCE_RESET_PROXY=1` пересоздаёт контейнер proxy;
- выполняет `docker compose up -d --build --remove-orphans`;
- показывает `docker compose ps`;
- делает health-check `http://127.0.0.1/api/health`.

## 4. Полезные команды

```powershell
# Логи

docker compose logs backend --tail=200
docker compose logs worker --tail=200
docker compose logs proxy --tail=200

# Остановка

docker compose down

# Перезапуск

docker compose up -d
```

## 5. Частые проблемы

- Панель пишет, что auth не настроен:
  - проверьте `PANEL_LOGIN` и `PANEL_PASSWORD` в `.env`.
- После включения HTTPS не работает логин:
  - проверьте `PANEL_AUTH_COOKIE_SECURE=true`.
- Порт занят:
  - смените `PROXY_HTTP_PORT` в `.env`.
