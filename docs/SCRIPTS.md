# Скрипты автоматизации

## scripts/up.ps1 (Windows)

Запуск:

```powershell
./scripts/up.ps1
```

Поведение:
- создаёт `.env` из `.env.example`, если нет;
- запускает стек с пересборкой;
- показывает статус контейнеров;
- выполняет health-check через proxy.

Доп. флаги:
- `FORCE_RESET_PROXY=1` — пересоздать контейнер proxy перед запуском.
- `COMPOSE_FORCE_RECREATE=1` — добавить `--force-recreate`.

## scripts/up.sh (Linux/macOS)

Запуск:

```bash
chmod +x scripts/up.sh
./scripts/up.sh
```

Поведение аналогично PowerShell-версии.
