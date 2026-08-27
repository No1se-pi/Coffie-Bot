# План реализации Coffie Bot V2

Статус: Phase 0–2 завершены; Phase 3 (Menu / Pricing) реализована локально и проходит release gates
этап. Loyalty V2 готова к merge, но становится deployable release только после
успешного CI целевой ветки.

Baseline: `main` / `7e2d1157e328ba9564417e05161c77b0d5d6401a`, 2026-08-24.

## Утверждённые границы продукта

- Один deployment обслуживает одну организацию заказчика.
- Внутри организации поддерживаются несколько заведений и несколько физических точек.
- Это не SaaS и не multi-tenant система: `tenant_id`, общий кабинет разных заказчиков,
  SaaS-биллинг, API Gateway, Kubernetes и микросервисы не добавляются.
- Backend остаётся модульным монолитом FastAPI/SQLAlchemy/Alembic. API, bot, worker и CLI
  используют одну бизнес-логику и одну PostgreSQL.
- Онлайн-платёж, r_keeper, MAX, Web Push, real-time GPS, сложная GIS и ML antifraud не входят
  в V2, но соответствующие provider/source поля не должны блокировать будущие интеграции.
- Существующие `/api/v1`, Telegram Mini App, bot, QR-карты, loyalty journal, RBAC, audit,
  media pipeline, outbox, Compose и backup/restore сохраняются и расширяются.

## Результат аудита текущей системы

### Реализовано и переиспользуется

- Проверка Telegram `initData`, TTL/HMAC, короткоживущие opaque sessions и хранение только
  хеша токена.
- Роли `customer/staff/admin/owner`, granular permissions и backend object-level checks.
- `users` как стабильный customer profile ID, one-to-one `staff_members`, отзыв sessions.
- Одна активная opaque QR-карта, короткий код, блокировка и атомарный reissue.
- Блокируемый loyalty snapshot, immutable operations/transactions, compensating reversal,
  idempotency keys и `SELECT ... FOR UPDATE` в опасных сценариях.
- Посещения, штампы, награды, QR-купоны, balance/history adapters старого API.
- Structured audit events, notification outbox, worker leases/retry и broadcasts.
- Secure JPEG/PNG/WebP media pipeline и persistent volume.
- Informational menu, promotions, locations, private feedback и tip profiles.
- React/Vite Mini App с customer/staff/mobile-admin маршрутами, scanner, QR и базовыми
  loading/error/empty состояниями.
- Docker Compose, Alembic `0001`-`0007`, seed, CLI owner, backup/restore и deploy script.

### Требует расширения

- `users` остаётся физической таблицей профиля, но Telegram перестаёт быть обязательной
  идентичностью. Legacy Telegram-поля временно остаются compatibility projection.
- `Location` остаётся физической точкой. Над ним вводится минимальная сущность `Venue`,
  потому что бренд/меню/suborder и точка выдачи/консолидации имеют разные жизненные циклы.
- Loyalty snapshot расширяется кошельками и партиями; старый `points_balance` остаётся
  compatibility snapshot до завершения migration/adapters.
- Menu/Promotion расширяются venue ownership, modifiers и pricing rules без универсального
  DSL rule engine.
- `api/client.ts`, крупные page-файлы и route guards постепенно делятся по feature-модулям;
  старый `coffeeApi` остаётся facade для существующих экранов.
- Worker получает point expiry, expiry reminders и новые outbox event types.
- Deploy временно останавливает пишущие процессы перед несовместимыми migrations; новый код
  также lazy-repair создаёт identity для Telegram-профиля, появившегося в окно rollout.

### Полностью новая функциональность

- Venues, customer identities, phone-only registration/linking и account merge.
- Shared/separate wallets, point lots, FIFO allocation/expiry и контролируемый wallet switch.
- Birthday и birthday promotion.
- Modifier groups/options, pricing engine, cart repricing и immutable order snapshots.
- Multi-venue orders/suborders, pickup/delivery и status event log.
- Courier role, assignment/self-claim и ограниченный courier view.
- Manual receipts, edit history и простые suspicious flags.
- Public moderated reviews, passes/subscriptions и bulk bonus batches.
- Desktop owner/admin shell, dashboard, tables, analytics и help.

## Архитектурные решения V2

### Customer и identities

`users.id` не меняется и считается стабильным customer profile ID. Массовое создание новой
таблицы `customers` и перепривязка десятков FK дали бы риск потери истории без бизнес-выгоды.

Новая `customer_identities` хранит provider (`telegram`, `phone`, в будущем `max`),
нормализованный уникальный subject, verification metadata и ссылку на `users.id`.

- существующие Telegram users получают identity через migration backfill;
- Telegram auth ищет identity, а legacy `users.telegram_id` использует только для lazy repair;
- phone-only profile получает карту и loyalty state без Telegram/session;
- номер хранится в каноническом E.164-подобном формате; поиск не возвращает лишние PII;
- подтверждённый собственный Telegram contact можно связать с phone-only profile;
- merged profile помечается `merged`, ссылается на canonical profile и больше не используется
  как actor/target новых операций;
- merge не переписывает immutable loyalty/audit journals. История canonical profile
  агрегируется по lineage, а баланс переносится парой объяснимых transfer operations.

### Venue и Location

`Venue` — заведение/бренд и владелец меню, accrual policy и suborders. `Location` — физическая
точка, адрес, часы, pickup/consolidation capability. Каждая location принадлежит venue;
consolidation location может обслуживать mixed order организации.

### Loyalty V2

- `LoyaltyWallet`: customer + scope (`shared` или конкретный venue) + balance snapshot.
- `PointLot`: отдельная партия начисления с initial/remaining amount и `expires_at`.
- `PointAllocation`: immutable распределение spend/expiry/reversal по партиям.
- Shared mode использует master wallet; separate mode — wallet конкретного venue.
- FIFO блокирует wallet и подходящие lots в устойчивом порядке.
- После отсева уже истёкших lots баллы расходуются в строгом FIFO по `earned_at`,
  затем `id`; expiry не меняет порядок партий.
- Expiry создаёт loyalty operation и outbox; reversal восстанавливает исходные allocations,
  не создавая баллы из воздуха и не воскрешая уже истёкший срок без явной политики.
- Wallet mode switch — owner-only preview/confirm с reason, idempotency, transfer operations и
  audit; прямое переключение поля при ненулевых балансах запрещено.
- Shared → separate требует active fallback venue для origin-less/archived-origin lots;
  immutable route пишется и для нулевого lot, чтобы reversal после switch/merge
  оставался однозначным.
- Venue accrual хранит enabled, basis points (`1000 = 10%`) и rounding mode.
  100 ₽ при 10% дают 10 баллов независимо от redemption value.
- Shared V1 request без location использует trusted default active Location/Venue и
  его policy; separate mode требует explicit validated location.

### Pricing и orders

- Frontend передаёт menu item, quantity, modifier selections, fulfillment inputs и желаемое
  списание; backend загружает актуальные правила и полностью пересчитывает результат.
- Promotions сортируются по priority; при равном priority выбирается максимальная выгода.
  Non-stackable — default. Stackable rules применяются в документированном порядке.
- Order хранит один customer-facing номер, suborders группируются по venue.
- Order item хранит snapshots названий, base price, modifiers, discounts, points и total.
- Изменение menu/promotion после checkout не меняет исторический order.
- Status transitions разрешает явная state machine; каждое изменение пишет event, audit и
  outbox в одной транзакции.

### Security и privacy

- Phone identity не считается подтверждённой только по совпадению текста; linking требует
  доверенного Telegram-contact/staff confirmation flow.
- Merge, wallet mode switch, order create, courier claim, receipt, subscription use и bulk
  bonus используют idempotency и транзакции.
- Courier DTO не содержит Telegram ID, birthday, loyalty history, internal notes или audit.
- Customer resources проверяют canonical ownership и не доверяют URL/body ID.
- Комментарии/docstrings обязательны вокруг migration compatibility, merge lineage, FIFO,
  pricing choice, status transitions и конкурентных claims.

## План migrations

Номера окончательные после реализации соответствующей фазы. Опубликованные `0001`-`0007`
не изменяются.

1. `0008_v2_venues`
   - `venues`, `locations.venue_id` и neutral legacy venue backfill;
   - global/default-location constraint заменяется только если это подтверждено моделью точек.
2. `0009_v2_customer_identities`
   - `customer_identities` и normalized provider subjects;
   - nullable legacy Telegram profile fields;
   - backfill Telegram identities для всех существующих users;
   - constraints/indexes добавляются после проверки backfill.
3. `0010_v2_customer_merge_foundation`
   - `customer_merges`, общий namespace-scoped idempotency receipt;
   - birthday/merge metadata и ручное обновление `user_status` CHECK;
   - lineage indexes без переписывания immutable history.
4. `0011_v2_loyalty_wallets_and_point_lots`
   - wallet mode/config, venue loyalty policy;
   - wallets, point lots, allocations, wallet transfer journal и immutable switch/merge routes;
   - birthday month/day, offer policy и eligible venues;
   - opening wallet/lot из каждого существующего `points_balance` без изменения суммы.
5. `0012_v2_menu_modifiers_and_pricing`
   - venue ownership menu/category/promotion;
   - modifier groups/options/item links и promotion targets/actions.
6. `0013_v2_orders_and_delivery`
   - orders, suborders, item/modifier snapshots, order events;
   - delivery settings/zones/details и pickup/consolidation references.
7. `0014_v2_courier_workflow`
   - courier-compatible role/permissions, assignments/claims и indexes/constraints.
8. `0015_v2_manual_receipts`
   - receipts, receipt revisions/media links и suspicious flags.
9. `0016_v2_reviews_subscriptions_and_bulk_bonus`
   - public reviews/moderation, pass templates/instances/usages, bulk bonus batches/items.
10. `0017_v2_admin_reporting_indexes`
   - только подтверждённо нужные reporting indexes/materialized snapshots; без BI warehouse.

Каждая migration проверяется на чистой PostgreSQL и как upgrade от `0007`. Backfill использует
set-based SQL/детерминированные IDs там, где нужна повторяемость, не вызывает application
services и не отправляет Telegram.

## API compatibility

Без breaking changes сохраняются:

- `POST /api/v1/auth/telegram`;
- `GET /api/v1/me`, `/me/card`, `/me/history`, `/me/rewards`;
- `POST /api/v1/staff/cards/lookup`;
- `POST /api/v1/staff/operations/*`;
- текущие admin content/staff/users/events/broadcast routes.

Legacy responses получают только additive nullable поля. Compatibility adapters читают
canonical wallet/customer representation, но сохраняют старые `balance_points`, `user_id` и
историю. Любое неизбежное несовместимое изменение фиксируется в `MIGRATION_V2.md` до merge.

Новые группы планируются в стиле текущего router. Контракты Phase 2
аддитивны, но до закрытия gate-ов остаются implementation-in-progress:

- `/venues`, `/customer-identities`, `/me/birthday`, `/me/wallets`;
- `/staff/customers`, `/staff/receipts`, `/staff/subscriptions`, `/staff/orders`;
- `/admin/customer-merge`, `/admin/venues`, `/admin/loyalty`,
  `/admin/loyalty/wallet-mode/preview|confirm`, `/admin/users/{id}/birthday`, `/admin/pricing`;
- `/cart/price`, `/orders`, `/delivery`, `/courier`;
- `/reviews`, `/subscriptions`, `/admin/analytics`, `/admin/help`.

## Фазы реализации

### Phase 0 — Baseline и CI

- [x] Проверены docs, model/service/repository/router/bot/worker/frontend/migrations/tests.
- [x] Локальный backend pytest: 142 passed, 1 warning.
- [x] Локальный frontend: lint, format, typecheck, 22 tests и production build passed.
- [x] Compose config и demo seed validation passed.
- [x] Исправить frontend dependency audit lock и immutable migration format gate.
- [x] Запустить все ранее skipped GitHub Actions commands локально.

### Phase 1 — Foundation

- [x] Обновить продуктовые границы в `AGENTS.md` и архитектурных docs.
- [x] Venue/Location model, admin/public API и seed трёх заведений.
- [x] Customer identities и migration/lazy repair existing Telegram users.
- [x] Phone-only staff create/lookup и безопасный Telegram contact linking.
- [x] Merge preview/confirm, lineage, transfer, session/card handling и audit.
- [x] Сохранить старые auth/me/card/history/staff operation contracts.
- [x] Backend integration/security/concurrency и frontend compatibility tests.
- [x] Чистая migration и upgrade с `0007`.

### Phase 2 — Loyalty V2

- [x] Venue percentage accrual 10%/7%/5% и configurable rounding.
- [x] Shared/separate wallets, owner-only mode transition.
- [x] Opening lots, FIFO spend, 6-month expiry, notifications и reversals.
- [x] 1 point = 1 RUB default и 50% per-venue redemption primitive для mixed order.
- [x] Birthday capture/lock/admin change и birthday promotion.
- [x] Wallet/expiry/birthday Mini App UI и tests.

Checkbox этапа не закрываются до фактического backend/frontend/migration/Compose
gate и фазового отчёта.

### Phase 3 — Menu / Pricing

- [x] Venue-owned category/item CRUD.
- [x] Generic modifier groups/options/quantities and admin UI.
- [x] Practical promotion conditions/actions, priority/benefit/stackability.
- [x] Backend pricing preview and snapshot-ready tests.

### Phase 4 — Orders

- [x] Cart reducer/UI and backend repricing.
- [x] Order/suborder models, create idempotency and snapshot.
- [x] Pickup/delivery settings/zones/fees and checkout.
- [x] State machines, event log, outbox notifications and customer tracking/history.

### Phase 5 — Courier

- [ ] Courier role/permissions/privacy DTO.
- [ ] Manual assignment and atomic self-claim.
- [ ] Available/mine/detail mobile UI and allowed transitions.
- [ ] Race/security tests and notifications.

### Phase 6 — Receipts

- [ ] Fast manual receipt flow via existing secure media.
- [ ] Optional later metadata, immutable revisions and source/external ID.
- [ ] Simple suspicious flags, staff UI and audit tests.

### Phase 7 — Reviews / Subscriptions / Bulk bonus

- [ ] Public review creation and moderation.
- [ ] Pass templates, issue/cancel/use and concurrent idempotent usage.
- [ ] Bulk bonus preview/confirm with per-customer operations.

### Phase 8 — Web Admin

- [ ] Standalone safe Telegram web login over existing session model.
- [ ] Desktop shell/sidebar/tables/forms/dialogs.
- [ ] Dashboard, orders, customers/merge, menu, loyalty, promotions, staff/couriers,
  receipts, reviews, analytics and help.
- [ ] Mobile admin remains available.

### Phase 9 — Hardening и передача

- [ ] Full lint/format/typecheck/tests/build/dependency audits.
- [ ] Clean and `0007 -> head` migration tests plus seed.
- [ ] Concurrency/idempotency/IDOR/privacy suite.
- [ ] Compose images/startup/health and backup/restore rehearsal where environment permits.
- [ ] Обновить все docs и финальный manual test plan.

## Baseline GitHub Actions

Последний run `30721204526` на baseline SHA завершился failure:

- Compose/images — passed.
- Backend остановился на format-check опубликованной migration `0002`; последующие mypy,
  migration и pytest были skipped.
- Frontend остановился на dependency audit; последующие lint/typecheck/test/build были skipped.
- На 2026-08-24 lock содержит high advisories в React Router и transitive packages.

Исправление Phase 0:

- обновить `react-router-dom` до исправленного patch и безопасно пересчитать lock;
- не использовать `--force` и подтвердить `npm audit = 0`;
- исключить только неизменяемый опубликованный `0002` из Ruff format gate вместо изменения
  migration history;
- после этого фактически выполнить все команды, ранее скрытые early-failure gate-ами.

## Progress log

### 2026-08-24 — audit

- Worktree был чистым и совпадал с `origin/main`.
- ТЗ прочитано полностью; V1 docs, backend, frontend, migrations/tests и Actions изучены.
- Выбран эволюционный путь без schema rewrite и без второго backend.
- Phase 0 repair: Ruff gates passed; frontend dependency audit = 0; lint, format, typecheck,
  22 tests и production build passed. Опубликованная `0002` не изменялась.
- Phase 1: добавлены Venue/Location, customer identities, phone-only create/link,
  account merge и compatibility adapters без смены existing `users.id`.
- PostgreSQL: clean `0001 -> 0010`, legacy `0007 -> 0010`, `alembic check`, concurrency и
  idempotency scenarios passed; full suite `180 passed`.
- Demo seed идемпотентен: повторный импорт оставляет 3 venues и 3 связанные
  locations.
- Frontend: dependency audit = 0; lint, format, typecheck, 30 tests и production build passed.
- Phase 2 design review уточнил strict FIFO, calendar-month expiry, privacy-safe birthday,
  separate-wallet guards и transfer/reversal invariants; детали сохранены в `docs/LOYALTY_V2.md`.
- По решению владельца релиз закрывается на Phase 1; partial Phase 2 implementation в
  deployable worktree не оставлена.
- Release gate после rollback: Ruff/format/mypy, PostgreSQL `180 passed`, Alembic parity,
  frontend audit=0/lint/format/typecheck/30 tests/build, Compose/scripts/JSON/diff — passed.
- Production Docker images backend/frontend собраны. Временный isolated production stack
  выполнил migrations и прошёл frontend `200` и backend readiness `ok`; containers/volumes удалены.
- Deploy guard теперь отклоняет и untracked build-context files, чтобы в image не попала
  миграция или Python-модуль вне release commit.
- После release-паузы работа над Phase 2 Loyalty V2 возобновлена; её gates
  на момент этой записи не закрыты.

### 2026-08-26 — Phase 2 Loyalty V2

- Reversal переведён на point-lot ledger: credit reversal списывает точную routed
  lineage, spend reversal создаёт связанную restore-партию, а legacy operation без
  lot/allocation fail-closed и требует отдельной admin correction.
- Reversal исторической операции после customer merge следует до terminal canonical
  profile; immutable исходная операция сохраняет прежний `user_id`.
- Исправлен PostgreSQL FK order при восстановлении нескольких FIFO allocations и
  version увеличивается один раз на затронутый wallet за атомарную операцию.
- Customer merge UI и DTO обрабатывают privacy-safe birthday conflict resolution и
  показывают перенос feedback без раскрытия точных дат.
- Backend gates: Ruff check/format, mypy и `229 passed` на PostgreSQL 17; clean
  `0001 -> 0011`, Alembic parity, lock/concurrency и reversal regressions прошли.
- Frontend gates: Prettier, ESLint, TypeScript, `39 passed` и production Vite build
  прошли. Development/production Compose config и production images прошли build.
- Seed выполнен повторно после смены wallet mode на `separate`: режим сохранился.
  Изолированный production Compose smoke применил все migrations и вернул frontend
  `200` и backend readiness `ok`; его containers и volumes удалены.
- Phase 2 предоставляет per-venue redemption calculation/validation. Оркестрация
  нескольких suborders будет подключена в Phase 4 поверх server-side pricing snapshot;
  она не считается готовой системой заказов на этом этапе.

### 2026-08-27 — Phase 3 Menu / Pricing

- Категории, товары, акции и универсальные modifier groups принадлежат `Venue`;
  composite PostgreSQL foreign keys запрещают cross-venue связи даже в обход сервиса.
- Pricing engine заново загружает trusted каталог, проверяет количества и считает
  mixed cart по venue с practical promotion rules, priority/benefit/stackability.
- Добавлены `/api/v1/cart/price`, admin pricing API и мобильная админка для групп
  модификаторов, привязок к товарам и правил скидок.
- Migration `0012` прошла clean `0001 -> 0012`, Alembic parity и повторный seed на
  PostgreSQL 17. Backend suite: `236 passed`; frontend: `40 passed`, audit/build зелёные.
- Development images собраны, backend/frontend smoke вернул `200`, а pricing route
  без сессии корректно закрыт `401`. Phase 4 сохраняет этот расчёт как order snapshot.

### 2026-08-27 — Phase 4 Orders

- Добавлен customer order с venue-suborders, неизменяемыми снимками позиций,
  модификаторов, акций и цен; mixed-venue корзина создаётся одной транзакцией.
- Создание защищено обязательным idempotency key и PostgreSQL advisory lock;
  баллы списываются FIFO отдельно по venue-частям и восстанавливаются компенсацией
  при допустимой отмене без переписывания исходного журнала.
- Реализованы pickup/delivery, простые выбираемые зоны, server-side fee/minimum/free
  threshold, расписание в timezone точки, точка выдачи и консолидации.
- State machine синхронизирует order/suborders, пишет append-only events, audit и
  notification outbox; клиент получил корзину, checkout, историю/детали, сотрудник —
  очередь, администратор — настройки доставки, зон и точек.
- Backend gates: Ruff/format, mypy и `245 passed` на PostgreSQL 17. Clean
  `0001 -> 0013`, повторный seed и migration head прошли на отдельной базе.
- Frontend gates: Prettier, TypeScript, ESLint, `42 passed`, production build и
  `npm audit` без уязвимостей. Development Compose images/startup и health smoke
  вернули backend live/ready `200` и frontend `200`.
