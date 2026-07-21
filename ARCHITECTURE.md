# Архитектура

## Контекст и границы

Coffie Bot — автономная установка программы лояльности одной кофейни. Репозиторий копируется и разворачивается независимо для каждого заказчика. В одной установке одна база, один Telegram-бот, одна конфигурация и одно media-хранилище. Несколько `locations` означают только несколько точек одной организации.

## Компоненты

```text
Telegram client ── initData ──> React Mini App ── HTTPS /api/v1 ──> FastAPI
       │                                                        │
       └──────── messages <── aiogram bot <── notification outbox
                                                                │
                                  worker <── PostgreSQL ─────────┘
                                      │              │
                                  Telegram API   media volume
```

- `frontend`: mobile-first React/Vite приложение. Отображает доступные роли, но не принимает решений о правах.
- `backend`: FastAPI transport, application services, repositories, SQLAlchemy models и security boundary.
- `bot`: aiogram polling/webhook process из того же Python-образа; `/start`, Mini App button, уведомления и broadcasts.
- `worker`: задачи из PostgreSQL с lease/retry; не содержит отдельной бизнес-логики.
- `db`: PostgreSQL. Состояние, неизменяемые операции, аудит, контент и фоновые задания.
- `media`: локальный persistent volume; метаданные и ownership — в БД.

## Слои backend

```text
api / bot / cli / worker
          │
application services + authorization policies
          │
repositories + unit of work
          │
SQLAlchemy models / PostgreSQL
```

Transport не выполняет расчёты и не меняет модели напрямую. Сервис получает actor и команду, проверяет permission и инварианты, блокирует необходимые строки, записывает доменную операцию, snapshot, audit event и outbox в одной транзакции.

## Основная модель данных

- Identity/access: `users`, `staff_members`, `staff_permissions`, `sessions`, `staff_invites`.
- Карты: `user_cards`; один active QR на пользователя, старые записи отозваны и остаются для аудита.
- Loyalty: `loyalty_settings`, `user_loyalty_states`, `loyalty_operations`, `point_transactions`, `visits`, `stamp_transactions`.
- Rewards: `reward_templates`, `rewards`; статусная машина `active -> redeemed|expired|cancelled`, обратный переход запрещён.
- Content: `promotions`, `menu_categories`, `menu_items`, `locations`, `app_settings`.
- Staff/community: `staff_tip_profiles`, `feedback_items`.
- Delivery/audit: `broadcasts`, `broadcast_deliveries`, `notification_outbox`, `audit_events`.
- Media: `media_files` с generated storage key, detected MIME, size и owner/reference metadata.

Деньги хранятся как integer minor units. UUID используется для внутренних/public IDs, отдельный случайный токен — для QR, короткий числовой/буквенный код — только fallback. Все timestamps сохраняются в UTC.

## Авторизация

1. Frontend отправляет исходную строку Telegram `initData`, не разобранные доверенные поля.
2. Backend вычисляет data-check string, проверяет HMAC подпись через bot token и constant-time comparison.
3. Backend проверяет `auth_date` против допустимого TTL.
4. Подтверждённый Telegram user ID сопоставляется с локальным `user`; первый вход атомарно создаёт пользователя, карту и welcome operation.
5. Backend выдаёт случайный короткоживущий session token. В `sessions` хранится только SHA-256 hash, TTL и revocation data.
6. Каждый запрос загружает actor, его active status, role и granular permissions. Объектные проверки выполняются после RBAC.

Development bypass разрешён только при явных `APP_ENV=development` и `DEV_AUTH_ENABLED=true`; production-конфигурация с bypass должна завершать запуск ошибкой.

## QR flow

1. Сотрудник сканирует opaque card token или вводит короткий код.
2. API находит только активную карту и проверяет блокировку клиента.
3. Возвращает ограниченный staff view; сканирование ничего не начисляет.
4. Сотрудник отправляет preview команды. Backend рассчитывает результат из настроек.
5. Confirm содержит новый idempotency key, но не готовый баланс.
6. Сервис повторно проверяет роль/permission, запрет self-operation, лимиты и блокировку; блокирует loyalty state.
7. В одной транзакции создаёт operation/transaction, меняет snapshot, создаёт audit и notification outbox.
8. Worker/bot отправляет уведомление после commit. Ошибка Telegram не откатывает уже подтверждённую покупку и допускает retry.

Перевыпуск создаёт новую карту и отзывает старую атомарно. Старый QR возвращает нейтральную ошибку без данных клиента.

## Начисление и списание

- Preview и confirm используют одну функцию расчёта, но confirm всегда пересчитывает данные под блокировкой.
- Purchase amount > 0 и не выше configured maximum. Начисление = сумма / «рублей на балл» с заданным округлением, затем применяются min/daily/per-operation limits.
- Уникальный `(operation_type, idempotency_key)` предотвращает повтор. При повторе с тем же payload возвращается прежний результат; несовпадающий payload — conflict.
- Списание ограничено доступным балансом, минимумом и процентом заказа; frontend не передаёт итоговый баланс.
- Admin adjustment и reversal требуют непустую нормализованную причину.
- Reversal ссылается на original operation, разрешён только один раз и не удаляет original.

## Посещения, штампы и награды

- Business date вычисляется на backend по timezone и configurable day-boundary.
- Unique constraint пользователя и business date предотвращает повторное посещение даже при гонке.
- Стрик и штампы меняются под блокировкой loyalty state. Достижение threshold создаёт reward в той же транзакции.
- Redemption использует row lock и conditional state transition; повтор даёт conflict, не второе погашение.
- Сложные последствия reversal после выданной/погашенной награды в MVP требуют admin review и audit flag; автоматическое каскадное удаление запрещено.

## Аудит и события

`audit_events` хранит type, actor, subject/object, UTC timestamp, severity, suspicious flag, IP/user-agent subset и JSON metadata. Готовая человекочитаемая строка не является источником данных: formatter строит её из type и metadata с безопасным fallback для неизвестных версий.

Технические JSON logs и audit events разделены. В логи не попадают секреты, init data, session tokens и полные приватные payloads.

## Уведомления и рассылки

Notification outbox записывается вместе с доменной транзакцией. Worker получает записи через `FOR UPDATE SKIP LOCKED`, устанавливает lease, отправляет, записывает attempts/result и планирует retry с backoff.

Broadcast имеет draft/preview/confirmed/running/completed/failed status и immutable audience snapshot/deliveries. Уникальная delivery на `(broadcast_id, user_id)` защищает повторный запуск. Ошибка одного пользователя не останавливает остальные доставки.

## Media

Backend ограничивает размер, читает сигнатуру разрешённых JPEG/PNG/WebP, генерирует random storage key и пишет файл без execute permissions в выделенный volume. Исходное имя используется только как необязательные безопасные metadata. Публичная выдача использует known storage key, `nosniff` и attachment/appropriate image headers.

