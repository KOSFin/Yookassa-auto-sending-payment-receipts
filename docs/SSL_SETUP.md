# SSL/TLS настройка (подробно)

Ниже пример с внешним Nginx + certbot (на хосте) и проксированием в контейнерный `proxy`.

## Вариант A: certbot + host nginx (рекомендуется)

### 1) DNS

Создайте запись:
- `A your-domain.tld -> <IP_сервера>`

Проверка:

```bash
dig +short your-domain.tld
```

### 2) Откройте порты

- 80/tcp
- 443/tcp

### 3) Установите Nginx и certbot (Ubuntu пример)

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

### 4) Конфиг Nginx для первичного HTTP

Создайте файл `/etc/nginx/sites-available/yookassa-auto`:

```nginx
server {
    listen 80;
    server_name your-domain.tld;

    location / {
        proxy_pass http://127.0.0.1:90;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Активируйте:

```bash
sudo ln -s /etc/nginx/sites-available/yookassa-auto /etc/nginx/sites-enabled/yookassa-auto
sudo nginx -t
sudo systemctl reload nginx
```

### 5) Выпуск сертификата

```bash
sudo certbot --nginx -d your-domain.tld --redirect -m you@example.com --agree-tos -n
```

### 6) Проверка

```bash
curl -I https://your-domain.tld/api/health
```

Ожидается `200`.

### 7) Важные переменные .env при HTTPS

```env
PROXY_BASE_URL=https://your-domain.tld
PANEL_AUTH_COOKIE_SECURE=true
```

## Вариант B: сертификаты внутри контейнерного nginx

Если хотите монтировать сертификаты в `deploy/nginx/certs`:
- положите `fullchain.pem` и `privkey.pem`;
- обновите nginx conf в `deploy/nginx/conf.d/default.conf` под `listen 443 ssl`;
- перезапустите `docker compose up -d --build`.

Этот вариант более ручной и требует аккуратного продления сертификатов.

## Автопродление certbot

Проверка таймера:

```bash
systemctl status certbot.timer
```

Dry-run:

```bash
sudo certbot renew --dry-run
```
