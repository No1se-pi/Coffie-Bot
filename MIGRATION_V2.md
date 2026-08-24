# Coffie Bot V2 migration guide

V2 развивается поверх существующих `users.id` и журналов `loyalty_operations`,
`point_transactions`, `visits`, `stamp_transactions`, `audit_events`. Миграции не создают
вторую клиентскую базу и не переписывают исторические идентификаторы.

## Перед обновлением

1. Сделайте проверенный backup PostgreSQL и media.
2. Соберите новый image.
3. Остановите старые `frontend`, `backend`, `bot`, `worker` до запуска Alembic. Это исключает
   запись legacy-строк в окно между backfill и новым constraint.
4. Выполните `alembic upgrade head`, затем `alembic check`.
5. Примените актуальный seed и только после этого поднимите application services.

Штатный `scripts/deploy.sh` выполняет эту последовательность автоматически. Секреты и
полные identity subjects в диагностический вывод не включаются.

## Phase 1 revisions

- `0008_v2_venues`: создаёт `venues`, добавляет nullable `locations.venue_id`. На существующей
  установке с locations создаётся нейтральный `legacy-venue` и все старые location IDs
  сохраняются. На чистой базе фиктивный venue не создаётся; три demo venue приходят из seed.
- `0009_v2_customer_identities`: создаёт provider-neutral identities, переносит каждый
  ненулевой `users.telegram_id` в Telegram identity и разрешает phone-only users. Legacy
  Telegram column остаётся nullable compatibility projection; новый auth умеет lazy repair
  строки, созданной старым writer в rollout window.
- `0010_v2_customer_merge_foundation`: добавляет merge status/lineage и парные типы loyalty
  operation. Merge не меняет owner IDs исторических операций: canonical history читает их по
  recursive lineage. Баллы и штампы переносятся компенсирующими journal rows.

## Phase 2 revision (в работе)

`0011_v2_loyalty_wallets_and_point_lots` — forward-only migration разрабатываемой
Phase 2. До закрытия clean/legacy migration, parity и application gates её наличие в
ветке не означает готовый production upgrade.

Revision:

- добавляет venue-политику `loyalty_points_enabled`, accrual bps и rounding mode,
  shared/separate setting, calendar expiry/reminder и birthday policy;
- хранит birthday только как month/day и список eligible venues;
- создаёт `loyalty_wallets`, `point_lots`, `point_allocations`,
  `wallet_mode_switches`, `wallet_transfers`, routes для mode switch/account merge;
- создаёт один shared opening wallet для каждого existing loyalty state и opening lot
  только для положительного баланса;
- копирует баланс без пересчёта и не назначает opening lot ретроактивный
  `expires_at`; новые lots после upgrade получают calendar expiry в application layer;
- не изобретает lot/allocation lineage для legacy operations: их reversal после
  upgrade отказывает fail-closed, а ручная коррекция требует отдельный
  admin adjustment с reason и audit trail;
- проверяет внутри migration, что wallet/lot totals равны исходному
  `user_loyalty_states.points_balance`; несовпадение останавливает upgrade.

## Проверка после Phase 1

Проверяйте агрегаты, не выводя сами телефоны или Telegram IDs:

```sql
SELECT count(*) AS telegram_profiles_without_identity
FROM users u
WHERE u.telegram_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM customer_identities i
    WHERE i.user_id = u.id AND i.provider = 'telegram'
  );

SELECT count(*) AS locations_without_venue
FROM locations
WHERE venue_id IS NULL;

SELECT status, count(*)
FROM users
GROUP BY status
ORDER BY status;
```

Первый запрос должен вернуть `0`. Второй может быть ненулевым только для осознанно созданных
organization-level consolidation/pickup points.

## Проверка после Phase 2

После фактического upgrade до `0011` проверьте агрегаты, не выводя customer IDs:

```sql
SELECT count(*) AS profiles_with_wallet_mismatch
FROM user_loyalty_states AS state
LEFT JOIN (
  SELECT user_id, sum(balance_points)::bigint AS total
  FROM loyalty_wallets
  GROUP BY user_id
) AS wallets ON wallets.user_id = state.user_id
WHERE coalesce(wallets.total, 0) <> state.points_balance;

SELECT count(*) AS wallets_with_lot_mismatch
FROM loyalty_wallets AS wallet
LEFT JOIN (
  SELECT wallet_id, sum(remaining_points)::bigint AS total
  FROM point_lots
  GROUP BY wallet_id
) AS lots ON lots.wallet_id = wallet.id
WHERE coalesce(lots.total, 0) <> wallet.balance_points;

SELECT count(*) AS opening_lots_with_expiry
FROM point_lots
WHERE source_type = 'opening_balance' AND expires_at IS NOT NULL;
```

Все три запроса должны вернуть `0`. Затем проверьте `alembic check`, повторный
seed и application tests. Смена wallet mode не является migration-шагом: её
выполняет owner после запуска через API preview/confirm.

## Rollback

Revisions V2 forward-only: автоматический downgrade запрещён, потому что phone-only profiles,
merge lineage, point lots/allocations/routes и новые journal rows нельзя честно представить
старой схемой. При критической
ошибке оставьте writers выключенными и восстановите pre-upgrade database + media backup вместе
с совместимым image. Не удаляйте новые таблицы или CHECK constraints вручную.
