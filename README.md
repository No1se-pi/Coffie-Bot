# Coffie Bot

Coffie Bot — автономный шаблон Telegram-бота и web-приложения для одной локальной
организации с несколькими заведениями и физическими точками. Каждый клиентский экземпляр получает отдельный
репозиторий, Telegram-бота, PostgreSQL, media-хранилище и Docker Compose deployment.
Проект намеренно не является multi-tenant SaaS.

Текущая V1 лояльности расширяется поэтапно до V2 с заведениями, заказами и доставкой.
Фактический статус каждой фазы, compatibility-решения и выполненные проверки находятся в
[`IMPLEMENTATION_PLAN_V2.md`](IMPLEMENTATION_PLAN_V2.md); незавершённые пункты там не следует
считать готовыми функциями.

## Архитектура

В репозитории используется monorepo и модульный монолит:

- `backend` — FastAPI, SQLAlchemy/Alembic, общая бизнес-логика, aiogram bot, worker и CLI;
- `frontend` — React/TypeScript/Vite Mini App и responsive desktop Web Admin;
- `db` — PostgreSQL, единственный источник состояния;
- `bot` и `worker` — отдельные процессы того же backend-образа, а не микросервисы;
- `media` — persistent Docker volume для проверенных JPEG/PNG/WebP;
- `migrate` — одноразовый процесс того же backend-образа, который выполняется перед
  запуском API, bot и worker.

Публичный API расположен под `/api/v1`. Подробности находятся в
[`ARCHITECTURE.md`](ARCHITECTURE.md) и [`docs/API.md`](docs/API.md).

Loyalty V2 реализована в Phase 2: additive-контракт добавляет
shared/separate кошельки, point lots, строгое FIFO, календарное сгорание и
birthday month/day. Нормативные инварианты описаны в
[`docs/LOYALTY_V2.md`](docs/LOYALTY_V2.md).

Phase 3 добавляет venue-owned меню, универсальные модификаторы и авторитетный
server-side расчёт корзины. Контракт и инварианты snapshot для заказов описаны в
[`docs/MENU_PRICING.md`](docs/MENU_PRICING.md).

Phases 4–8 добавляют mixed-venue заказы, pickup/delivery и курьеров, ручные чеки,
отзывы, абонементы, массовые бонусы и desktop Web Admin с PostgreSQL-аналитикой.
Фактические проверки и ограничения каждой фазы перечислены в implementation plan.

## Требования

- Docker Engine или Docker Desktop;
- Docker Compose plugin 2.24 или новее (`docker compose version`);
- GNU Make — необязательно, все команды имеют эквивалент через Docker Compose;
- Telegram-бот, созданный через BotFather, для проверки реального Telegram flow.

Для запуска без Docker дополнительно нужны Python 3.13, Node.js 24 и npm 11.

## Быстрый запуск

1. Создайте локальный файл окружения:

   ```powershell
   Copy-Item .env.example .env
   ```

   На Linux/macOS: `cp .env.example .env`.

2. Измените как минимум `POSTGRES_PASSWORD`, пароль внутри host-side `DATABASE_URL`,
   `SESSION_TOKEN_PEPPER`, `BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` и
   `TELEGRAM_WEBAPP_URL`. Случайный pepper можно получить так:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. Соберите и запустите стек:

   ```bash
   make install
   make up
   ```

   Без Make:

   ```bash
   docker compose --env-file .env -f compose.yaml up --detach --build
   ```

   `migrate` дождётся готовности PostgreSQL и применит Alembic migrations. Только после
   его успешного завершения стартуют `backend`, `bot` и `worker`.

4. Создайте первого владельца, затем импортируйте нейтральные demo-данные:

   ```bash
   make create-owner OWNER_TELEGRAM_ID=123456789 OWNER_NAME="Имя владельца"
   make seed
   ```

   Эквивалент без Make:

   ```bash
   docker compose --env-file .env run --rm backend \
     python -m app.cli create-owner --telegram-id 123456789 --display-name "Имя владельца"
   docker compose --env-file .env run --rm backend \
     python -m app.cli seed --file /app/configs/demo-seed.json
   ```

   В production demo-сотрудник не импортируется, поэтому владелец нужен как автор
   первоначальных публикаций. Повторный запуск обеих команд должен быть безопасным.

5. Откройте:

- Mini App: <http://localhost:5173>;
- OpenAPI: <http://localhost:8000/docs>;
- liveness: <http://localhost:8000/api/v1/health/live>;
- readiness: <http://localhost:8000/api/v1/health/ready>.

`DEV_AUTH_ENABLED=true` разрешён только для локальной браузерной разработки.
Production-конфигурация принудительно отключает bypass.
Для production-входа в Web Admin можно настроить Telegram Login через BotFather
или привязанный к существующему owner/admin вход по логину и паролю. Для второго
варианта создайте хеш внутри backend-контейнера и добавьте три значения в `.env`:

```bash
docker compose --env-file .env -f compose.prod.yaml run --rm backend \
  python -m app.security.passwords 'сложный пароль'
# ADMIN_WEB_USERNAME=owner
# ADMIN_WEB_PASSWORD_HASH=вывод-команды
# ADMIN_WEB_TELEGRAM_ID=telegram-id-существующего-owner
```

Пароль не хранится в БД или frontend, а сессия после входа использует тот же
непрозрачный токен и backend-RBAC. Инструкция по Telegram Login находится в
[`DEPLOYMENT.md`](DEPLOYMENT.md#telegram-login-для-web-admin).

## Основные команды

Все Make-команды используют `ENV_FILE=.env` и `COMPOSE_FILE=compose.yaml`. Их можно
переопределить: `make up ENV_FILE=.env.staging COMPOSE_FILE=compose.prod.yaml`.

| Команда | Назначение и параметры |
|---|---|
| `make install` | Собрать backend и frontend images, установив закреплённые зависимости. |
| `make dev` | Запустить development stack в foreground с live reload. |
| `make up` | Запустить development stack в background. |
| `make down` | Остановить контейнеры без удаления volumes. |
| `make logs SERVICE=worker` | Следить за всеми логами или логами одного сервиса. |
| `make migrate` | Выполнить `alembic upgrade head`. |
| `make migration MESSAGE=add_field` | Сгенерировать новую migration в bind-mounted `backend/`. |
| `make seed SEED_FILE=/app/configs/demo-seed.json` | Импортировать стартовую конфигурацию. |
| `make create-owner OWNER_TELEGRAM_ID=... OWNER_NAME="..."` | Создать или обновить первого owner. ID обязателен, имя необязательно. |
| `make test` | Запустить backend pytest и frontend Vitest. |
| `make lint` | Запустить Ruff и ESLint. |
| `make format` | Применить Ruff formatter и Prettier. |
| `make format-check` | Проверить форматирование без изменений. |
| `make typecheck` | Запустить mypy и TypeScript typecheck. |
| `make compose-check` | Проверить обе Compose-модели. |
| `make backup BACKUP_DIR=backups/manual` | Создать dump PostgreSQL и архив media. Каталог необязателен. |
| `make restore BACKUP=backups/... CONFIRM=YES` | Заменить текущие БД и media содержимым backup. Подтверждение обязательно. |

`down` не удаляет данные. Не используйте `docker compose down -v`, если не хотите
безвозвратно удалить локальные PostgreSQL и media volumes.

## Миграции

Новая миграция создаётся только после изменения SQLAlchemy models:

```bash
make migration MESSAGE=add_notification_lease
make migrate
```

Проверьте сгенерированный файл вручную. Уже опубликованные migrations не редактируются:
исправление схемы оформляется новой migration. Для чистой проверки используйте отдельные
test volumes, а не production-базу.

## Разработка без Docker

PostgreSQL можно оставить в Compose (`docker compose ... up -d db`), а процессы запустить
на хосте:

Из корня репозитория, где находится `.env`:

```bash
python -m venv .venv
python -m pip install -e "./backend[dev]"
alembic -c backend/alembic.ini upgrade head
uvicorn app.main:app --reload
```

Во втором терминале:

```bash
cd frontend
npm ci
npm run dev
```

Для host-backend используется `DATABASE_URL` из `.env` с адресом `localhost`; Compose
подставляет контейнерный адрес `db` автоматически.

## Проверки

Перед завершением изменения выполняйте релевантные проверки, а перед merge — полный набор:

```bash
make lint
make format-check
make typecheck
make test
```

Критические сценарии ручной проверки перечислены в
[`docs/MANUAL_TEST_PLAN.md`](docs/MANUAL_TEST_PLAN.md). Тесты не обращаются к реальному
Telegram API.

## Конфигурация и эксплуатация

- [CUSTOMIZATION.md](CUSTOMIZATION.md) — подготовка отдельного экземпляра для кофейни;
- [DEPLOYMENT.md](DEPLOYMENT.md) — production Compose, HTTPS, обновления и backup/restore;
- [MIGRATION_V2.md](MIGRATION_V2.md) — forward-only V2 revisions, preflight и проверки;
- [docs/LOYALTY_V2.md](docs/LOYALTY_V2.md) — нормативный design и additive API contract
  завершённой Phase 2;
- [docs/MENU_PRICING.md](docs/MENU_PRICING.md) — меню, модификаторы, акции и pricing
  contract Phase 3;
- [SECURITY.md](SECURITY.md) — модель доверия, секреты и incident response;
- [docs/PRODUCT_DECISIONS.md](docs/PRODUCT_DECISIONS.md) — demo-значения, которые владелец
  обязан подтвердить до production;
- [docs/RBAC.md](docs/RBAC.md) — роли и granular permissions.

Секреты хранятся только в `.env` или в эквивалентном внешнем secret store. Бренд,
контакты и стартовые правила находятся в `configs/demo-seed.json`, а изменяемые через
админку значения после импорта — в PostgreSQL.

## Лицензия

Проект распространяется по MIT License. Перед передачей коммерческого экземпляра
убедитесь, что выбранная модель лицензирования соответствует договору с заказчиком.
