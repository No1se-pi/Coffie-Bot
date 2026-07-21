# Production deployment

`compose.prod.yaml` — самостоятельная production-модель. Она запускает PostgreSQL,
одноразовые migrations, API, Telegram bot, worker и frontend. API, bot, worker и migrations
используют один backend image. Frontend Nginx проксирует `/api/` во внутренний `backend:8000`;
наружу публикуется только loopback-порт frontend для host-level TLS proxy.

## Требования к серверу

- Linux VPS с актуальными security updates;
- Docker Engine и Compose plugin 2.24+;
- домен с A/AAAA record на VPS;
- открытые наружу TCP 80/443; PostgreSQL и application ports не открываются;
- достаточно диска для PostgreSQL, media, Docker layers и минимум двух поколений backup.

Не запускайте рядом ручные `uvicorn`, bot или worker процессы: один bot token должен иметь
ровно один polling/webhook consumer.

## Подготовка конфигурации

На сервере получите конкретный release/commit репозитория, затем:

```bash
cp .env.example .env
chmod 600 .env
```

Замените все placeholder secrets и задайте уникальные имена volumes. Production минимум:

```dotenv
POSTGRES_PASSWORD=<long-random-secret>
SESSION_TOKEN_PEPPER=<independent-random-secret>
BOT_TOKEN=<token-from-botfather>
TELEGRAM_BOT_USERNAME=<username-without-at>
TELEGRAM_WEBAPP_URL=https://coffee.example.com
CORS_ORIGINS=["https://coffee.example.com"]
DEV_AUTH_ENABLED=false
PROD_FRONTEND_BIND_ADDRESS=127.0.0.1
PROD_FRONTEND_PORT=8080
```

Если пароль PostgreSQL содержит URL-special characters, используйте URL-encoded значение
или безопасный набор случайных букв/цифр: Compose строит `DATABASE_URL` из компонентов.
Не печатайте результат обычного `docker compose config` в CI/logs: он содержит развёрнутые
значения environment. Для проверки используйте `config --quiet`.

## Первый запуск

```bash
docker compose --env-file .env -f compose.prod.yaml config --quiet
docker compose --env-file .env -f compose.prod.yaml build --pull
docker compose --env-file .env -f compose.prod.yaml up --detach
docker compose --env-file .env -f compose.prod.yaml ps
```

`db` сначала должен стать healthy. Затем `migrate` выполняет `alembic upgrade head` и
завершается с кодом 0. Только после этого запускаются backend, bot и worker; frontend ждёт
healthy backend. Завершившийся `migrate` со статусом `Exited (0)` — нормальное состояние.

Сначала создайте owner, затем импортируйте первичную конфигурацию:

```bash
docker compose --env-file .env -f compose.prod.yaml run --rm backend \
  python -m app.cli create-owner --telegram-id 123456789 --display-name "Owner"
docker compose --env-file .env -f compose.prod.yaml run --rm backend \
  python -m app.cli seed --file /app/configs/demo-seed.json
```

Перед production seed замените demo-контент и убедитесь, что `development_only` staff не
импортирован. Owner используется как автор первоначальных публикаций.

## HTTPS и reverse proxy

Контейнер frontend слушает `127.0.0.1:8080` на host и внутри Docker проксирует `/api/` к
backend. Поэтому внешний Caddy/Nginx должен направлять весь домен на frontend. Минимальный
Caddyfile:

```caddyfile
coffee.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
```

Минимальный Nginx server после настройки сертификата:

```nginx
server {
    listen 443 ssl http2;
    server_name coffee.example.com;

    ssl_certificate /etc/letsencrypt/live/coffee.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/coffee.example.com/privkey.pem;

    client_max_body_size 6m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Backend не опубликован на host. Он принимает forwarded headers только от диапазона Docker
network, заданного `FORWARDED_ALLOW_IPS`; не устанавливайте `*`, если API когда-либо станет
доступен напрямую.

Проверка после выпуска сертификата:

```bash
curl --fail https://coffee.example.com/health
curl --fail https://coffee.example.com/api/v1/health/live
curl --fail https://coffee.example.com/api/v1/health/ready
```

`live` подтверждает только работу процесса, `ready` дополнительно проверяет PostgreSQL.

## Telegram Mini App

После появления HTTPS URL:

1. Укажите тот же URL в `TELEGRAM_WEBAPP_URL` и `CORS_ORIGINS`.
2. Через BotFather настройте menu button/Web App URL для конкретного бота.
3. Перезапустите backend и bot.
4. Проверьте вход из Telegram iOS, Android и Desktop.
5. Убедитесь, что изменённые или просроченные `initData` отклоняются.

Не используйте HTTP URL, IP-адрес или другой origin в production. Frontend никогда не должен
передавать backend собственный «доверенный» Telegram ID или role.

## Persistent data

Compose создаёт два боевых named volumes:

- `POSTGRES_VOLUME_NAME` — база и migration state;
- `MEDIA_VOLUME_NAME` — загруженные изображения.

Имена фиксируются в `.env`. Не меняйте их при обычном обновлении и не выполняйте `down -v`.
Файл `configs/demo-seed.json` монтируется read-only; после импорта изменяемые настройки
живут в PostgreSQL.

## Backup

Backup включает PostgreSQL custom dump, `media.tar.gz`, manifest и контрольные суммы (когда
доступен `sha256sum`). База должна быть доступна; скрипт сам дождётся healthy `db`.

Linux:

```bash
COMPOSE_FILE=compose.prod.yaml ENV_FILE=.env sh scripts/backup.sh
COMPOSE_FILE=compose.prod.yaml ENV_FILE=.env sh scripts/backup.sh --output backups/pre-update
```

PowerShell:

```powershell
.\scripts\backup.ps1 -ComposeFile compose.prod.yaml -EnvFile .env
.\scripts\backup.ps1 -Destination backups\pre-update -ComposeFile compose.prod.yaml -EnvFile .env
```

Backup содержит персональные данные и внутренний аудит. Ограничьте права, зашифруйте копию и
перенесите хотя бы одно поколение вне VPS. Периодически проверяйте checksum и выполняйте
restore rehearsal в отдельном окружении. Скрипты не загружают данные в облако автоматически.

## Restore

Restore полностью заменяет текущие БД и media, поэтому требует явного подтверждения. Сначала
сделайте backup текущего состояния. Скрипт останавливает frontend/backend/bot/worker,
восстанавливает PostgreSQL одной транзакцией, проверяет пути media archive, применяет текущие
migrations и затем запускает сервисы.

Linux:

```bash
COMPOSE_FILE=compose.prod.yaml ENV_FILE=.env \
  sh scripts/restore.sh --from backups/20260721T210000Z --yes
```

PowerShell:

```powershell
.\scripts\restore.ps1 -BackupPath backups\20260721T210000Z -Force `
  -ComposeFile compose.prod.yaml -EnvFile .env
```

При ошибке application services остаются остановленными. Не поднимайте их вслепую: сначала
изучите вывод `pg_restore`/tar и целостность выбранного backup.

## Обновление

1. Зафиксируйте текущий commit/image tag и создайте backup.
2. Получите нужный release без переписывания локального `.env`.
3. Просмотрите новые migrations и release notes.
4. Выполните:

   ```bash
   docker compose --env-file .env -f compose.prod.yaml build --pull
   docker compose --env-file .env -f compose.prod.yaml run --rm migrate
   docker compose --env-file .env -f compose.prod.yaml up --detach
   ```

5. Проверьте health, логи, Telegram `/start`, вход Mini App и одну безопасную операцию.

Alembic migrations считаются forward-only. Откат image на старый commit допустим только если
он совместим с уже применённой схемой. Для несовместимой схемы используйте заранее проверенный
backup целиком; не пытайтесь вручную удалять колонки на рабочей базе.

## Диагностика

```bash
docker compose --env-file .env -f compose.prod.yaml ps
docker compose --env-file .env -f compose.prod.yaml logs --tail=200 backend
docker compose --env-file .env -f compose.prod.yaml logs --tail=200 bot worker
docker compose --env-file .env -f compose.prod.yaml exec db \
  sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Не публикуйте полные `.env`, bot token, Telegram init data, session tokens или приватные
payloads при отправке логов. Технически чистый лог не доказывает доставку уведомления:
проверяйте outbox/delivery state и фактическое сообщение в Telegram.
