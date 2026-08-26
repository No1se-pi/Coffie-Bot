# Loyalty V2

> Статус: Phase 2 завершена и прошла локальные gates. Production upgrade разрешается
> только после merge и успешного CI целевой ветки.

Loyalty V2 сохраняет старые `/api/v1/me`, `/me/history` и staff operation routes,
но хранит баллы в кошельках и отдельных партиях. `UserLoyaltyState.points_balance`
остаётся compatibility snapshot и равен сумме активных wallet balances клиента.
Публичные контракты Phase 2 аддитивны; ни наличие migration `0011`, ни этот
документ сами по себе не закрывают release gate.

## Модель

- `LoyaltyWallet` — mutable snapshot баланса. Shared wallet не имеет venue;
  separate wallet привязан к одному venue.
- `PointLot` — партия конкретного начисления: initial/remaining amount, source
  operation, creation time и optional expiry.
- `PointAllocation` — immutable связь spend/expiry/reversal operation с lot.
  Исторические allocations не переписываются.
- `WalletModeSwitch` и `WalletTransfer` — receipt смены mode и парные
  transfer operations, не изменение глобальной суммы баллов.
- `PointLotRoute` и account-merge route — immutable ответ на вопрос,
  в какой wallet должно вернуться позднее reversal-начисление.

## Начисление

Backend загружает location и venue и применяет venue accrual rate. В demo:

- «Кофейня и точка» — 1000 bps (10%);
- «ФудДворик» — 700 bps (7%);
- «Шашлык Джан» — 500 bps (5%).

Для каждого venue настраиваются `loyalty_points_enabled`, bps и собственный
rounding mode (`floor`, `half_up`, `ceiling`). Деньги хранятся в minor units,
а процент — в basis points. Округление выполняется только на backend. Для RUB
formula равна `round(amount_minor * accrual_bps / 1_000_000)`. Процент даёт
именно число баллов:
100 ₽ × 10% = 10 баллов даже при изменённой стоимости балла. Стоимость балла — отдельная
redemption setting и не входит в accrual formula. По умолчанию 1 балл покрывает
100 minor units, а redemption ограничен 50% стоимости. В separate mode лимит и
доступный wallet считаются отдельно для venue каждого suborder.

Для V1 staff clients, которые ещё не присылают `location_id`, shared mode
разрешает только server-side trusted default active Location/Venue. Начисление всё равно
идёт по его venue policy, а не по legacy global formula. В separate mode явный
`location_id` обязателен и backend проверяет, что Location/Venue active. Это же правило
действует для redemption, adjustment, welcome/reward bonus и других point mutations:
в separate mode trusted venue нельзя опустить или передать как готовый итог frontend.

## FIFO, expiry и reversal

Перед spend/expiry сервис блокирует wallet и его активные lots. После отсева уже
истёкших lots списание идёт в строгом FIFO по `earned_at`, затем `id`. `expires_at` не
пересортировывает партии: ТЗ явно требует сначала расходовать самые старые доступные
баллы. Единый lock order не даёт expiry состязаться со spend за один остаток.

Новый lot по умолчанию истекает через шесть календарных месяцев. Если такого дня
нет, берётся последний день целевого месяца. Явно сохранённая legacy
`points_validity_days` может временно переопределять calendar policy для совместимости;
opening lot, созданный migration из старого
`points_balance`, не имеет ретроактивного expiry.

Expiry и reversal — новые loyalty operations с allocations. Отмена spend восстанавливает
исходные lots только по их allocations; уже истёкший lot не воскрешается молча. Ни
сгорание, ни notification не вызывают Telegram внутри business transaction: они пишут outbox.
Операции, созданные до migration `0011`, не имеют точной lot/allocation lineage.
Их reversal fail-closed без изменения баланса; коррекция делается только отдельным
admin adjustment с причиной и audit trail.

Expiry worker имеет отдельный cadence и берёт ограниченную партию due lots, а не
сканирует всю таблицу в каждом коротком worker tick. Expiration и reminder
идемпотентны. Профиль без Telegram identity помечает notification как terminal skip,
чтобы не создавать бесконечный retry loop.

## Переключение shared/separate

Прямая смена mode при существующих балансах запрещена. Owner сначала получает
preview с hash, затем подтверждает его с reason и `Idempotency-Key`. Confirm повторно блокирует
настройку/wallets, проверяет preview и пишет парные transfer operations, allocations
и audit. Общая сумма до и после одинакова.

Переход `separate -> shared` однозначен: venue lots переносятся в master wallet с теми же
expiry. Для `shared -> separate` исходное venue каждого lot берётся из его accrual source.
Opening/misc lots без venue и lots с уже archived origin нельзя распределять догадкой:
preview показывает unresolved lots и требует явный active/non-archived
`fallback_venue_id`. Fallback входит в preview/request hash и повторно проверяется
под блокировкой.

Route создаётся для каждого переносимого source lot, даже если его
`remaining_points = 0`. Иначе reversal давного spend после mode switch не смог бы
однозначно выбрать текущий wallet. Такая же route lineage пишется при account merge.
Парные transfer journal rows объясняют перенос, но не изображают ложный глобальный
debit/credit: compatibility total не меняется.

## Birthday

Клиент может сохранить birthday month/day без ненужного года ровно один раз. После этого
изменение доступно только admin/owner, требует reason и создаёт audit event. По
умолчанию personal offer равен
10%, действует один день в timezone организации и не стакается. Дата 29 февраля в
невисокосный год наблюдается 28 февраля, если owner не выберет другую policy. Offer
доступен в каждом годовом окне; одноразовый usage limit в текущее ТЗ не входит.

Offer работает только в configured eligible venues. Пустой список
означает wildcard «все активные venues»; непустой — точно заданное множество.
Backend считает annual window по локальной дате; frontend не передаёт готовую eligibility.
Month/day не входят в staff lookup, courier DTO, обычные логи и audit metadata:
audit фиксирует факт изменения, actor и reason без точной даты. Phase 2 закрепляет birthday policy и
eligibility; фактическая цена заказа позже всё равно пересчитывается server-side
pricing/order pipeline.

## Additive API и UI

- `GET /me/wallets` возвращает mode, total, per-venue breakdown, expiry summary и
  unavailable flag для archived venue с остатком.
- `GET|PUT /me/birthday` читает/одноразово задаёт month/day.
- `GET|PUT /admin/loyalty` управляет V2 policy, но не меняет wallet mode.
- `POST /admin/loyalty/wallet-mode/preview|confirm` — единственный путь смены mode.
- `PUT /admin/users/{user_id}/birthday` меняет birthday с reason/audit.

Mini App показывает shared/separate breakdown, ближайшее сгорание и
недоступное archived venue, а birthday вводит отдельными month/day без года.
Admin UI показывает активный fallback selector только когда preview обнаружил
unresolved lots. Экраны прошли Phase 2 frontend/tests gate.
