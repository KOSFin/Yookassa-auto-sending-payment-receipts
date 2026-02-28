# Эксплуатация: backup, update, restore

## 1) Backup PostgreSQL

Linux/macOS:

```bash
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql
```

Windows PowerShell:

```powershell
docker compose exec -T postgres pg_dump -U $env:POSTGRES_USER $env:POSTGRES_DB | Out-File -Encoding utf8 backup.sql
```

## 2) Обновление без потери данных

```bash
docker compose pull
docker compose up -d --build --remove-orphans
```

Проверка:

```bash
docker compose ps
docker compose logs backend --tail=200
docker compose logs worker --tail=200
curl -fsS http://127.0.0.1/api/health
```

Важно:
- Не используйте `docker compose down -v`.
- Не удаляйте volume `postgres_data`.

## 3) Восстановление из backup

Linux/macOS:

```bash
cat backup.sql | docker compose exec -T postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

Windows PowerShell:

```powershell
Get-Content backup.sql | docker compose exec -T postgres psql -U $env:POSTGRES_USER $env:POSTGRES_DB
```

## 4) Мониторинг

```bash
docker compose logs backend --tail=200
docker compose logs worker --tail=200
docker compose logs proxy --tail=200
```
