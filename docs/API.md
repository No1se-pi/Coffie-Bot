# API v1 contract

Все endpoints имеют префикс `/api/v1`. JSON использует `snake_case`. Денежные значения передаются как `*_minor` (копейки), timestamps — ISO 8601 UTC. Приватные endpoints принимают `Authorization: Bearer <opaque-session-token>`.

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
- `POST /auth/logout` — отзывает текущую session.
- `GET /me` — profile, роли и разрешения.
- `GET /me/card` — active QR payload, короткий код, balance/progress.
- `GET /me/history?page=&page_size=&type=` — собственные операции.
- `GET /me/rewards?status=` — собственные награды.
- `GET /me/identities` — подтверждённые provider identities текущего профиля.

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
- `POST /staff/operations/accrual/preview` — `{user_id, purchase_amount_minor}`.
- `POST /staff/operations/accrual` — confirm с тем же business input; результат всегда пересчитывается.
- `POST /staff/operations/redemption/preview`, `POST /staff/operations/redemption`.
- `POST /staff/operations/visits` — business date вычисляет backend.
- `POST /staff/operations/stamps`.
- `POST /staff/rewards/{reward_id}/redeem`.
- `POST /staff/operations/{operation_id}/reverse` — `{reason}`.
- `GET /staff/operations/recent` — только доступный роли scope.
- `GET|PUT /staff/me/tip-profile` — update создаёт pending review.

Preview не принимает и не возвращает секреты; confirm никогда не принимает `new_balance` или готовое количество начисления.

## Admin users и staff

- `GET /admin/users?query=&status=&page=&page_size=`.
- `GET /admin/users/{user_id}` и `/history`, `/rewards`.
- `POST /admin/users/{user_id}/adjustments` — `{delta_points, reason}`.
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

## Admin audit/content

- `GET /admin/venues`, `GET /admin/venues/{id}`, `POST|PATCH /admin/venues`;
  explicit `/{id}/archive` и `/{id}/restore`.

- `GET /admin/events` — period/actor/user/type/severity/suspicious/adjustments/reversed filters.
- `GET|PUT /admin/loyalty-settings` — `visit_reward` и `stamp_reward` принимают один из компактных вариантов: позиция меню (`menu_item`), собственная текстовая награда (`custom`) или автоматическое начисление (`points`).
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
