# Исправления и улучшения

## Проблемы, которые были решены

### 1. **Bad Gateway / Backend crashes**
**Проблема:** Backend крашился при необработанных исключениях, что приводило к 502 Bad Gateway.

**Решение:** Добавлен глобальный exception handler в [`Backend/app/main.py`](Backend/app/main.py):
- Ловит все необработанные ошибки
- Логирует их с полным traceback
- Возвращает клиенту 500 с информацией об ошибке
- Backend больше не крашится

### 2. **Спам в Telegram при повторах**
**Проблема:** При временных ошибках MyTax API (503) каждые 30 секунд отправлялось уведомление в Telegram, что создавало спам.

**Решение:** Добавлена настройка `TELEGRAM_RETRY_NOTIFICATION_INTERVAL`:
- Уведомления отправляются только при попытках 0, 5, 10, 15... (по умолчанию каждая 5-я)
- Настраивается через `.env`
- Спам прекращён

### 3. **Агрессивные retry-интервалы**
**Проблема:** При 503 от MyTax (технические работы) система долбила API каждые 30 секунд.

**Решение:** Добавлен настраиваемый экспоненциальный backoff:
- `TASK_RETRY_BASE_SECONDS=60` — базовый интервал (по умолчанию 1 минута)
- `TASK_RETRY_EXPONENTIAL_MULTIPLIER=2` — множитель (удвоение)
- `TASK_RETRY_MAX_SECONDS=1800` — максимум (30 минут)

**Как работает:**
- Попытка 0: retry через 60 сек
- Попытка 1: retry через 120 сек (60 * 2¹)
- Попытка 2: retry через 240 сек (60 * 2²)
- Попытка 3: retry через 480 сек (60 * 2³)
- Попытка 4 и далее: retry через 1800 сек (достигнут максимум)

### 4. **Проблемы с входом в панель**
**Проблема:** Копипаст логина/пароля из `.env` приводил к ошибке "Invalid login or password" из-за хвостовых пробелов/кавычек.

**Решение:** Улучшена нормализация credentials в [`Backend/app/services/panel_auth.py`](Backend/app/services/panel_auth.py):
- Автоматическое удаление пробелов
- Автоматическое удаление обрамляющих кавычек (`"` или `'`)
- Frontend тоже trim'ит перед отправкой

## Новые настройки в `.env`

Добавьте в свой `.env` (пример в [`.env.example`](.env.example)):

```env
# --- Retry настройки для задач ---
# Базовый интервал повтора при временных ошибках (например, 503 у MyTax)
TASK_RETRY_BASE_SECONDS=60
# Максимальный интервал retry (секунды)
TASK_RETRY_MAX_SECONDS=1800
# Множитель экспоненциального роста. 2 = удвоение каждый раз
TASK_RETRY_EXPONENTIAL_MULTIPLIER=2
# Раз в сколько попыток слать уведомление в Telegram при повторах
# 5 = отправляется при попытках 0, 5, 10, 15...
TELEGRAM_RETRY_NOTIFICATION_INTERVAL=5
```

## Как применить изменения

### Windows PowerShell

```powershell
# 1. Обновите .env (добавьте новые переменные или используйте значения по умолчанию)
# 2. Пересоберите и перезапустите сервисы
docker compose down
docker compose up -d --build

# 3. Проверьте логи
docker compose logs -f backend worker
```

### Linux/macOS

```bash
# 1. Обновите .env
# 2. Пересоберите
docker compose down
docker compose up -d --build

# 3. Проверьте
docker compose logs -f backend worker
```

## Диагностика

Если по-прежнему возникают проблемы:

### Проверка переменных окружения в контейнере

```powershell
# Проверить PANEL_LOGIN/PANEL_PASSWORD
docker compose exec backend python -c "import os; print('LOGIN:', repr(os.getenv('PANEL_LOGIN', ''))); print('PASS:', len(os.getenv('PANEL_PASSWORD', '')))"

# Проверить retry настройки
docker compose exec backend python -c "import os; print('RETRY_BASE:', os.getenv('TASK_RETRY_BASE_SECONDS', 'NOT SET'))"
```

### Запуск диагностического скрипта

```powershell
.\scripts\diagnose_auth.ps1
```

Скрипт покажет:
- Что записано в `.env`
- Что видит backend-контейнер
- Есть ли проблемы с форматированием
- Последние auth-логи

### Просмотр логов в реальном времени

```powershell
# Backend (API + auth)
docker compose logs -f backend

# Worker (обработка задач)
docker compose logs -f worker

# Все сразу
docker compose logs -f
```

## Что ещё улучшено

1. **Логирование улучшено:** В логах worker теперь указывается номер попытки при retry
2. **Exception handling:** Backend больше не падает при неожиданных ошибках
3. **Нормализация credentials:** Убраны проблемы с пробелами/кавычками при копипасте
4. **Документация:** Добавлены подробные комментарии в [`.env.example`](.env.example)

## Рекомендации

1. **При 503 от MyTax:** Увеличьте `TASK_RETRY_BASE_SECONDS` до 120-300 секунд
2. **При частых уведомлениях:** Увеличьте `TELEGRAM_RETRY_NOTIFICATION_INTERVAL` до 10
3. **Для быстрого retry:** Уменьшите `TASK_RETRY_BASE_SECONDS` до 30, но это может создать нагрузку на MyTax API
