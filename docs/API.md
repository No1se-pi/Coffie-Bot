# API v1 contract

Все endpoints имеют префикс `/api/v1`. JSON использует `snake_case`. Денежные значения передаются как `*_minor` (копейки), timestamps — ISO 8601 UTC. Приватные endpoints принимают `Authorization: Bearer <opaque-session-token>`.

V2 contract реализован аддитивно поверх стабильных `users.id` и
immutable journals. Актуальный migration head и фактические release gates
фиксируются в `MIGRATION_V2.md` и `IMPLEMENTATION_PLAN_V2.md`.

## Общие ответы

Ошибка:

```json
{
  "error": {
    "code": "card_blocked",
    "message": "Карта заблокирована",
    "details": {},
    "request_id": "..."
  }
}
```

Списки:

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

Dangerous POST endpoints требуют `Idempotency-Key` (UUID, до 128 символов). Повтор с тем же payload возвращает исходный результат; тот же ключ с другим payload возвращает `409 idempotency_conflict`.

## Auth и текущий пользователь

- `POST /auth/telegram` — body `{ "init_data": "query-string" }`; проверяет подпись/TTL, регистрирует при первом входе, возвращает `{access_token, expires_at, user, staff}`.
- `POST /auth/telegram/web` — Telegram Login Widget payload; отдельно
  проверяет Login Widget HMAC/TTL и выдаёт ту же opaque session. Этот
  endpoint не принимает Mini App `init_data`.
- `POST /auth/logout` — отзывает текущую session.
- `GET /me` — profile, роли и разрешения.
- `GET /me/card` — active QR payload, короткий код, balance/progress.
- `GET /me/history?page=&page_size=&type=` — собственные операции.
- `GET /me/rewards?status=` — собственные награды.
- `GET /me/identities` — подтверждённые provider identities текущего профиля.
- `GET /me/wallets` (Phase 2) — wallet mode, суммарный compatibility balance,
  shared/venue breakdown, ближайшее expiry и доступность venue. Кошелёк
  archived venue с ненулевым балансом не скрывается, но помечается как
  недоступный для новых операций.
- `GET /me/birthday` (Phase 2) — собственные month/day, lock state и краткое
  описание активного birthday offer без года рождения.
- `PUT /me/birthday` (Phase 2) — одноразово сохраняет
  `{ "birthday": { "month": 2, "day": 29 } }`; повторное self-service изменение
  отклоняется.

## Публичный контент для авторизованного пользователя

- `GET /menu/categories`, `GET /menu/items?category_id=&available=`.
- `GET /promotions?active=true`.
- `GET /contacts` — кофейня и locations.
- `GET /venues` — активные заведения организации в настроенном порядке.
- `GET /staff-profiles` — только approved/visible tip profiles.
- `POST /feedback` — rating/category/message/may_contact.

## Staff operations

- `POST /staff/cards/lookup` — ровно один из `{qr_token, short_code, phone}`; телефон
  нормализуется backend, операция остаётся read-only.
- `POST /staff/customers` — phone-only профиль + карта + loyalty aggregate; требует
  `customers.create` и `Idempotency-Key`, возвращает только маскированный телефон.
- `POST /staff/operations/accrual/preview` — `{user_id, purchase_amount_minor,
  location_id?}`; Phase 2 по `location_id` загружает active venue и его policy.
- `POST /staff/operations/accrual` — confirm с тем же business input; результат всегда пересчитывается.
- `POST /staff/operations/redemption/preview`, `POST /staff/operations/redemption` — в
  Phase 2 принимают тот же optional `location_id`.
- `POST /staff/operations/visits` — business date вычисляет backend.
- `POST /staff/operations/stamps`.
- `POST /staff/rewards/{reward_id}/redeem`.
- `POST /staff/operations/{operation_id}/reverse` — `{reason}`.
- `GET /staff/operations/recent` — только доступный роли scope.
- `GET|PUT /staff/me/tip-profile` — update создаёт pending review.

Preview не принимает и не возвращает секреты; confirm никогда не принимает `new_balance` или готовое количество начисления.

Для compatibility с V1 staff clients в shared mode отсутствующий `location_id`
разрешается только через server-side trusted default active Location/Venue и его
venue accrual policy. Это не fallback на старую global formula. В separate mode
`location_id` обязателен, должен указывать на active Location/Venue и проходит
проверку backend.

## Admin users и staff

- `GET /admin/dashboard` — операционная сводка для admin/owner.
- `GET /admin/analytics?days=7..90` — агрегаты заказов, выручки, loyalty,
  доставки, чеков, абонементов и сотрудников; требует permission
  просмотра admin events.
- `GET /admin/users?query=&status=&page=&page_size=`.
- `GET /admin/users/{user_id}` и `/history`, `/rewards`.
- `PATCH /admin/users/{user_id}/note` — обновляет audit-safe внутреннюю заметку.
- `POST /admin/users/{user_id}/adjustments` — `{delta_points, reason}`.
- `PUT /admin/users/{user_id}/birthday` (Phase 2) — admin/owner меняет month/day
  только с непустой `reason`; old/new value и actor фиксируются в audit.
- `POST /admin/users/{user_id}/block`, `/unblock`, `/cards/reissue`.
- `POST /admin/users/{user_id}/rewards` и `/rewards/{reward_id}/cancel`.
- `GET /admin/users/{user_id}/identities` — provider identities для поддержки/merge.
- `POST /admin/customer-merge/preview` — проверка source/canonical и расчёт
  transfer/revoke summary с `preview_hash`.
- `POST /admin/customer-merge/confirm` — обязательные `preview_hash`, `reason`,
  `confirm=true` и `Idempotency-Key`; повторно проверяет состояние внутри транзакции.
- `GET|POST /admin/staff`, `GET|PATCH /admin/staff/{staff_id}`.
- `POST /admin/staff/{staff_id}/revoke-sessions`.
- `POST /admin/staff/invites` — TTL-limited one-time token.
- `POST /admin/staff/{staff_id}/role` — `admin`/`owner` transitions требуют owner.

## Orders и staff queue

- `GET /order-options` — trusted pickup/delivery options для checkout.
- `POST /orders` — создаёт server-priced order snapshot; требует
  `Idempotency-Key`.
- `GET /orders`, `GET /orders/{order_id}`, `POST /orders/{order_id}/cancel` — только
  собственные заказы customer.
- `GET /staff/orders?venue_id=&statuses=&limit=` и
  `GET /staff/orders/{order_id}` — очередь и полная карточка заказа в рамках
  разрешённого venue scope.
- `POST /staff/orders/{order_id}/transition` — только разрешённый state
  transition с optional reason/comment; бизнес-правила повторно проверяет backend.

## Admin audit/content

- `GET /admin/venues`, `GET /admin/venues/{id}`, `POST|PATCH /admin/venues`;
  explicit `/{id}/archive` и `/{id}/restore`.

- `GET /admin/events` — period/actor/user/type/severity/suspicious/adjustments/reversed filters.
- `GET|PUT /admin/loyalty-settings` — `visit_reward` и `stamp_reward` принимают один из компактных вариантов: позиция меню (`menu_item`), собственная текстовая награда (`custom`) или автоматическое начисление (`points`).
- `GET|PUT /admin/loyalty` (Phase 2) — V2 policy: per-venue enabled/bps/rounding,
  expiry/reminder, value/redemption limit, default bonus venue и birthday offer/eligible
  venues. `wallet_mode` не меняется этим `PUT`.
- `POST /admin/loyalty/wallet-mode/preview` (Phase 2, owner-only) — принимает
  `target_mode` и optional active `fallback_venue_id`; возвращает conservation
  summary, unresolved lots и `preview_hash`, не меняя state.
- `POST /admin/loyalty/wallet-mode/confirm` (Phase 2, owner-only) — требует
  `target_mode`, тот же fallback, `preview_hash`, `reason`, `confirm=true` и
  `Idempotency-Key`; stale preview и неактивный fallback отклоняются.
- `GET|POST|PATCH /admin/promotions`; explicit `/publish` and `/archive` actions.
- `GET|POST|PATCH /admin/menu/categories`, `/admin/menu/items`; архивные позиции доступны владельцу через `include_archived=true`.
- `POST /admin/menu/items/{id}/archive` (и legacy `/hide`) скрывает позицию, запрещает продажу и деактивирует связанную награду за баллы; `POST /restore` возвращает её как скрытый/недоступный черновик.
- `DELETE /admin/menu/items/{id}` с обязательным `Idempotency-Key` разрешён только для уже архивной позиции и оставляет audit event уровня `warning`; повтор с тем же ключом безопасно возвращает успех. Позицию, выбранную текущей наградой за посещения или штампы, нельзя архивировать/удалить: сначала владелец должен выбрать другую награду (`409 menu_item_is_current_loyalty_reward`).
- `GET /admin/feedback`, `PATCH /admin/feedback/{id}`.
- `DELETE /admin/feedback/{id}` — только после переноса в архив; audit event сохраняется.
- `POST /admin/media` multipart upload; metadata response, no client-controlled storage path.
- `GET|POST /admin/broadcasts`, `GET /admin/broadcasts/{id}`; `/preview`, `/{id}/confirm`, `/{id}/cancel`.
- `GET /admin/tip-profiles/pending`; `POST /admin/tip-profiles/{id}/approve|hide`.

Загруженные публичные файлы выдаются через `GET /media/{media_id}`; storage path клиенту не раскрывается.

## Health

- `GET /api/v1/health/live` — процесс отвечает (полный путь указан явно).
- `GET /api/v1/health/ready` — database readiness; `503` при недоступной зависимости.
