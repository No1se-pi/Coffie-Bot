# Архитектура

## Контекст и границы

Coffie Bot — автономная установка для одной организации заказчика. Репозиторий копируется и разворачивается независимо для каждого заказчика. В одной установке одна база, один Telegram-бот, одна конфигурация и одно media-хранилище. Внутри установки может быть несколько `venues` и физических `locations`, но они не являются независимыми tenant-организациями.

V2 развивается миграционно поверх текущей схемы. `users.id` сохраняется как стабильный
customer profile ID, identities выносятся отдельно, `Venue` представляет заведение/бренд, а
`Location` — физическую точку или точку выдачи. План и честный статус реализации описаны в
[`IMPLEMENTATION_PLAN_V2.md`](IMPLEMENTATION_PLAN_V2.md).

## Компоненты

```text
Telegram client ── initData ──> React Mini App ── HTTPS /api/v1 ──> FastAPI
Browser ── signed Telegram Login ──> desktop Web Admin ──────────┤
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
- Loyalty compatibility journal: `loyalty_settings`, `user_loyalty_states`,
  `loyalty_operations`, `point_transactions`, `visits`, `stamp_transactions`.
- Loyalty V2 (Phase 2 в работе): `loyalty_wallets`, `point_lots`,
  `point_allocations`, `wallet_mode_switches`, `wallet_transfers`, неизменяемые
  routes партий и birthday policy. `user_loyalty_states.points_balance` остаётся
  compatibility snapshot и равен сумме wallet balances.
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

Для входа в Web Admin вне Mini App используется Telegram Login Widget. Backend принимает
только подписанный Telegram payload, отдельно проверяет HMAC и TTL по алгоритму Login Widget,
после чего вызывает тот же identity/session service. Алгоритм Mini App `initData` не
переиспользуется: у этих двух Telegram flows разные derivation keys. В обоих случаях frontend
получает одинаковый opaque session token, а в БД хранится только его hash.

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
- Purchase amount > 0 и не выше configured maximum. Phase 2 определяет
  начисление по venue: `round(amount_minor * accrual_bps / 1_000_000)` для RUB,
  где rounding mode также задан на venue. Demo-ставки — 1000/700/500 bps
  (10%/7%/5%). Денежная ценность балла в эту формулу не входит.
- Уникальный `(operation_type, idempotency_key)` предотвращает повтор. При повторе с тем же payload возвращается прежний результат; несовпадающий payload — conflict.
- Списание ограничено доступным балансом, минимумом и процентом заказа; frontend не передаёт итоговый баланс.
  По умолчанию 1 балл покрывает 1 RUB, а лимит равен 50% соответствующей
  venue-части заказа.
- Admin adjustment и reversal требуют непустую нормализованную причину.
- Reversal ссылается на original operation, разрешён только один раз и не удаляет original.

### Кошельки, FIFO и сгорание (Phase 2)

- Shared mode имеет master wallet; separate mode — кошелёк venue. Любая
  point mutation в separate mode требует trusted active venue/location.
- Spend и expiry блокируют wallet и lots. После отсева уже истёкших
  партий spend идёт строго по `earned_at, id`; `expires_at` не превращает FIFO в FEFO.
- Новые lots по умолчанию живут шесть календарных месяцев с clamp
  на последний день целевого месяца. Opening lot migration не получает
  ретроактивного expiry.
- Expiry/reversal создают immutable operations и allocations. Worker обрабатывает
  expiry/reminder ограниченными партиями, а Telegram-доставку выполняет
  только через outbox после commit.
- Смена mode — owner-only preview/confirm. При shared → separate для origin-less
  или archived-origin lots owner выбирает active fallback venue. Route фиксируется
  даже для уже полностью израсходованного lot, чтобы поздний reversal оставался
  однозначным.

## Заказы, выдача и доставка

`CustomerOrder` — один заказ для клиента; товары каждого `Venue` сохраняются в
`OrderSuborder`. При создании backend повторно загружает меню и правила pricing,
фиксирует денежные значения, названия, модификаторы и применённые акции. Изменение
каталога после commit не меняет исторический заказ.

Создание заказа требует idempotency key. PostgreSQL advisory lock сериализует повторы
одного пользователя и ключа, а unique constraint не допускает дубль. Списание баллов,
FIFO allocations, order/suborders, snapshots, первый event и notification outbox
записываются в одной транзакции. Отмена возвращает баллы связанной компенсирующей
операцией; исходные операции и события не переписываются.

Pickup location и delivery zone выбираются только из активной конфигурации. Стоимость,
минимум, бесплатный порог, доступность scheduling и часы работы рассчитывает backend.
Простая зона — явный выбор пользователя, а не неподтверждённое GIS-сопоставление.
Адресные данные доступны customer/staff order DTO. Courier получает отдельный минимальный
DTO: свободная очередь содержит только номер, точки, зону и время; имя, телефон, адрес,
детали подъезда и комментарий появляются лишь после назначения именно этому курьеру.
Loyalty, birthday, internal notes, Telegram ID и audit history в courier API отсутствуют.

### Courier workflow (Phase 5)

`courier` — отдельная роль с фиксированным набором delivery permissions, а не разновидность
staff. Активный курьер может видеть свободные доставки, атомарно принять одну из них и
работать только со своими заказами. Claim блокирует `CustomerOrder` через `FOR UPDATE` и
повторно проверяет status/assignment внутри транзакции.
Все courier mutations требуют `Idempotency-Key`; уникальный audit key обеспечивает
безопасный replay после потерянного HTTP-ответа и не допускает повторного применения команды.

Staff/admin с `orders.manage` может назначить активного курьера вручную. Отказ возвращает
заказ в `waiting_for_courier` только до pickup. После pickup разрешены лишь последовательные
переходы `picked_up → in_transit → delivered`; GPS и фиктивная карта не используются.
Каждое изменение состояния создаёт append-only `OrderEvent`, структурированный audit event
и customer notification через outbox после commit.

Разрешённые переходы задаёт state machine. Venue-suborders проходят приготовление,
общий customer status выводится из всех частей; каждый переход создаёт append-only
`OrderEvent`, audit event и, при изменении общего статуса, outbox notification.

## Посещения, штампы и награды

- Business date вычисляется на backend по timezone и configurable day-boundary.
- Unique constraint пользователя и business date предотвращает повторное посещение даже при гонке.
- Стрик и штампы меняются под блокировкой loyalty state. Достижение threshold создаёт reward в той же транзакции.
- Redemption использует row lock и conditional state transition; повтор даёт conflict, не второе погашение.
- Сложные последствия reversal после выданной/погашенной награды в MVP требуют admin review и audit flag; автоматическое каскадное удаление запрещено.

## Аудит и события

`audit_events` хранит type, actor, subject/object, UTC timestamp, severity, suspicious flag, IP/user-agent subset и JSON metadata. Готовая человекочитаемая строка не является источником данных: formatter строит её из type и metadata с безопасным fallback для неизвестных версий.

Технические JSON logs и audit events разделены. В логи не попадают секреты, init data, session tokens и полные приватные payloads.

## Web Admin и аналитика

Мобильная админка и desktop Web Admin — два responsive представления одного React-приложения
и того же `/api/v1`. Desktop shell добавляет боковую навигацию, но не создаёт отдельный backend
или набор привилегий. Карточка клиента, заказ, меню, loyalty, акции, сотрудники/курьеры, чеки,
отзывы и абонементы используют существующие application services и RBAC.

Dashboard и analytics читают агрегаты напрямую из PostgreSQL через отдельный read-only
repository/service. Клиент не получает сырые телефоны, адреса или Telegram ID для построения
графиков; сторонний analytics SaaS не используется. Business-day метрики рассчитываются с
timezone и границей дня из настроек loyalty.

## Уведомления и рассылки

Notification outbox записывается вместе с доменной транзакцией. Worker получает записи через `FOR UPDATE SKIP LOCKED`, устанавливает lease, отправляет, записывает attempts/result и планирует retry с backoff.

Broadcast имеет draft/preview/confirmed/running/completed/failed status и immutable audience snapshot/deliveries. Уникальная delivery на `(broadcast_id, user_id)` защищает повторный запуск. Ошибка одного пользователя не останавливает остальные доставки.

## Media

Backend ограничивает размер, читает сигнатуру разрешённых JPEG/PNG/WebP, генерирует random storage key и пишет файл без execute permissions в выделенный volume. Исходное имя используется только как необязательные безопасные metadata. Публичная выдача использует known storage key, `nosniff` и attachment/appropriate image headers.

Receipt images используют тот же pipeline, но не публичную выдачу: общий media endpoint
возвращает для kind `receipt` нейтральный 404, а чтение доступно только staff с
`receipts.manage` через отдельный authenticated route.

## Ручные чеки

`Receipt` хранит текущий оптимизированный snapshot и future-compatible source
`manual/rkeeper/other_pos`; `(source, external_id)` уникален, когда внешний ID задан.
Текущий staff transport создаёт исключительно manual receipt и требует проверенное фото.

Создание сериализуется advisory lock и защищено `(created_by_staff_id, idempotency_key)`.
Каждое дополнение номера, fiscal data, note, external ID или фото создаёт полный неизменяемый
`ReceiptRevision`; повтор с тем же ключом возвращает ту же ревизию. Отмена меняет только
status/cancel metadata и оставляет исходный чек и историю.

`ReceiptRiskSettings` хранит пороги установки. Сервис пишет объяснимые flags для высокой
суммы, частоты сотрудника/клиента, одинаковых сумм, повторного номера, отсутствующего фото
и частых отмен. Это сигналы владельцу для проверки, а не автоматический ML-вердикт.

## Публичные отзывы

`PublicReview` не заменяет private `FeedbackItem`. Customer может связать отзыв с заведением,
своим заказом и optional сотрудником; связь order проверяется backend по canonical owner и
venue, поэтому чужой UUID не раскрывает заказ. Новый отзыв всегда `pending`. В публичный feed
попадают только `approved`; `rejected` и `hidden` остаются доступны модератору и автору.
Approve/reject/hide сохраняют moderator, UTC timestamp, optional note и audit event.

## Абонементы

`PassTemplate` — не банковская подписка и не платёж: это неизменяемое правило количества,
срока и optional allowed venues/categories/items. При выдаче `CustomerPass` фиксирует имя,
описание, изображение, total uses и expires_at. Issue/cancel требуют idempotency key.

Использование блокирует pass через `SELECT FOR UPDATE`, повторно проверяет active/expiry,
trusted venue и menu item, затем уменьшает остаток ровно на один. `PassUsage` append-only
хранит actor, customer, pass, venue, item, before/after и собственный idempotency key.
Последнее использование атомарно переводит pass в `exhausted`; два concurrent staff не могут
успешно списать единственный остаток дважды.

## Массовый бонус

Bulk bonus — admin/owner preview/confirm. Preview возвращает ordered audience snapshot,
recipient count, total points и hash. Confirm повторно вычисляет eligible audience, требует
тот же hash, блокирует user/loyalty state в порядке UUID и выполняется одной транзакцией.

`BulkBonusBatch` объясняет общую команду, `BulkBonusItem` связывает каждого получателя с
отдельной `LoyaltyOperation`. Для каждого клиента создаются `PointTransaction`, отдельный
`PointLot` с expiry policy и notification outbox; snapshot баланса обновляется только через
общий point ledger. Batch и операции защищены PostgreSQL unique constraints и advisory lock.
