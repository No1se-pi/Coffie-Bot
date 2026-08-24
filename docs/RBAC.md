# Матрица ролей и разрешений

Backend является единственным источником решения о доступе. Навигация frontend лишь скрывает недоступные действия и не заменяет проверку.

| Действие | Customer | Staff | Admin | Owner |
|---|:---:|:---:|:---:|:---:|
| Собственная карта/история/награды | ✓ | ✓ | ✓ | ✓ |
| Свои wallets/expiry и birthday | ✓ | ✓ | ✓ | ✓ |
| Публичные меню, акции, контакты, tips | ✓ | ✓ | ✓ | ✓ |
| Отправить feedback | ✓ | ✓ | ✓ | ✓ |
| Найти клиента по QR/коду/телефону | — | `card.lookup` | ✓ | ✓ |
| Создать phone-only клиента | — | `customers.create` | ✓ | ✓ |
| Начислить баллы | — | `accrue_points` | ✓ | ✓ |
| Списать баллы | — | `redeem_points` | ✓ | ✓ |
| Добавить посещение | — | `mark_visit` | ✓ | ✓ |
| Добавить штамп | — | `add_stamp` | ✓ | ✓ |
| Погасить награду | — | `redeem_reward` | ✓ | ✓ |
| Отменить свою недавнюю операцию | — | `reverse_own_operation` | ✓ | ✓ |
| Ручная корректировка баланса | — | — | ✓ | ✓ |
| Изменить birthday клиента с reason | — | — | ✓ | ✓ |
| Блокировка/QR reissue клиента | — | — | ✓ | ✓ |
| Merge двух customer-профилей | — | — | ✓ | ✓ |
| Merge с одним staff-профилем | — | — | — | ✓ |
| Собственный tip profile | — | ✓ | ✓ | ✓ |
| Модерация tip profiles | — | — | ✓ | ✓ |
| Контент, меню, feedback, broadcasts | — | — | ✓ | ✓ |
| Создать/отключить сотрудника | — | — | ✓ | ✓ |
| Изменить granular staff permissions | — | — | ✓ | ✓ |
| Назначить/снять администратора | — | — | — | ✓ |
| Критические настройки и export | — | — | — | ✓ |
| Переключить shared/separate wallet mode | — | — | — | ✓ |

## Объектные ограничения

- Customer читает только собственные приватные ресурсы.
- Staff получает ограниченный client view и не читает Telegram ID, session data, internal notes и полные audit metadata.
- Staff/courier DTO не раскрывают birthday; собственную дату каждый actor
  читает только как customer через `/me/birthday`.
- Staff не выполняет loyalty operation со своей картой независимо от permission.
- Staff reversal разрешён только для собственной операции в окне настройки и только один раз.
- Admin не меняет роль `admin`/`owner` и не отключает последнего владельца.
- Owner-профиль и два staff-профиля не объединяются ни при каких permissions.
- Merge требует preview hash, явное подтверждение, причину и idempotency key.
- Customer задаёт birthday один раз; admin/owner меняет его только с reason/audit.
- Admin/owner могут менять обычные loyalty policy. Смена wallet mode отделена
  от settings update и всегда требует owner, preview hash, reason и idempotency key.
- Любое административное изменение создаёт audit event с actor, object, причиной/metadata и временем.
