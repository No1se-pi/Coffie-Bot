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

## Rollback

Revisions V2 forward-only: автоматический downgrade запрещён, потому что phone-only profiles,
merge lineage и новые journal rows нельзя честно представить старой схемой. При критической
ошибке оставьте writers выключенными и восстановите pre-upgrade database + media backup вместе
с совместимым image. Не удаляйте новые таблицы или CHECK constraints вручную.
