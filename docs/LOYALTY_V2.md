# Loyalty V2

> Статус: согласованный design следующего этапа. В deployable Phase 1 кошельки/lots/birthday
> ещё не реализованы.

Loyalty V2 сохраняет старые `/api/v1/me`, `/me/history` и staff operation routes,
но хранит баллы в кошельках и отдельных партиях. `UserLoyaltyState.points_balance`
остаётся compatibility snapshot и равен сумме активных wallet balances клиента.

## Модель

- `LoyaltyWallet` — mutable snapshot баланса. Shared wallet не имеет venue;
  separate wallet привязан к одному venue.
- `PointLot` — партия конкретного начисления: initial/remaining amount, source
  operation, creation time и optional expiry.
- `PointAllocation` — immutable связь spend/expiry/reversal operation с lot.
  Исторические allocations не переписываются.

## Начисление

Backend загружает location и venue и применяет venue accrual rate. В demo:

- «Кофейня и точка» — 1000 bps (10%);
- «ФудДворик» — 700 bps (7%);
- «Шашлык Джан» — 500 bps (5%).

Деньги хранятся в minor units, а процент — в basis points. Округление
выполняется только на backend по настроенному mode. Процент даёт именно число баллов:
100 ₽ × 10% = 10 баллов даже при изменённой стоимости балла. Стоимость балла — отдельная
redemption setting и не входит в accrual formula. По умолчанию 1 балл покрывает
100 minor units, а redemption ограничен 50% стоимости. В separate mode лимит и
доступный wallet считаются отдельно для venue каждого suborder.

## FIFO, expiry и reversal

Перед spend/expiry сервис блокирует wallet и его активные lots. После отсева уже
истёкших lots списание идёт в строгом FIFO по сохраняемому `earned_at`, затем `id`. `expires_at` не
пересортировывает партии: ТЗ явно требует сначала расходовать самые старые доступные
баллы. Единый lock order не даёт expiry состязаться со spend за один остаток.

Новый lot по умолчанию истекает через шесть календарных месяцев. Если такого дня
нет, берётся последний день целевого меся. Opening lot, созданный migration из старого
`points_balance`, не имеет ретроактивного expiry.

Expiry и reversal — новые loyalty operations с allocations. Отмена spend восстанавливает
исходные lots только по их allocations; уже истёкший lot не воскрешается молча. Ни
сгорание, ни notification не вызывают Telegram внутри business transaction: они пишут outbox.

## Переключение shared/separate

Прямая смена mode при существующих балансах запрещена. Owner сначала получает
preview с hash, затем подтверждает его с reason и `Idempotency-Key`. Confirm повторно блокирует
настройку/wallets, проверяет preview и пишет парные transfer operations, allocations
и audit. Общая сумма до и после одинакова.

Переход `separate -> shared` однозначен: venue lots переносятся в master wallet с теми же
expiry. Для `shared -> separate` исходное venue каждого lot берётся из его accrual source.
Opening/misc lots без venue нельзя распределять догадкой: preview обязан показать их
отдельно и потребовать явную destination policy до confirm.

## Birthday

Клиент может сохранить birthday month/day без ненужного года ровно один раз. После этого
изменение доступно
только admin/owner, требует reason и создаёт audit event. По умолчанию personal offer равен
10%, действует один день в timezone организации и не стакается. Дата 29 февраля в
невисокосный год наблюдается 28 февраля, если owner не выберет другую policy. Offer
доступен в каждом годовом окне; одноразовый usage limit в текущее ТЗ не входит.
