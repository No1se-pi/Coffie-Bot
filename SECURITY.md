# Security policy and threat model

Coffie Bot обрабатывает Telegram/phone identities, историю лояльности, заказы, доставку,
административные действия и контент одной организации с несколькими заведениями. Backend является единственной доверенной границей для identity,
ролей, расчётов и изменений состояния. Frontend, QR payload и входящие Telegram/HTTP данные
считаются недоверенными.

## Сообщение об уязвимости

Не создавайте публичный issue с token, персональными данными, рабочим QR или инструкцией по
эксплуатации. Передайте владельцу конкретного экземпляра приватно:

- версию/commit и затронутый deployment;
- минимальные шаги воспроизведения без реальных секретов;
- ожидаемое и фактическое поведение;
- оценку доступности данных и следы в audit/logs.

До появления отдельного security contact канал согласуется с владельцем репозитория.

## Telegram authentication

Mini App отправляет backend исходную строку Telegram `initData`. Backend обязан:

1. построить data-check string по спецификации Telegram;
2. вычислить HMAC с bot token и сравнить подпись constant-time операцией;
3. проверить `auth_date` и допустимое будущее смещение;
4. принять Telegram ID только из успешно проверенных данных;
5. сопоставить локального пользователя и выдать собственную короткоживущую session.

Нельзя принимать `user_id`, role, permission или итог расчёта от frontend как доказательство.
Не логируйте полную init data: она содержит подпись и пользовательские поля.

`DEV_AUTH_ENABLED` — только browser-development bypass. Production Settings и
`compose.prod.yaml` должны завершать запуск при попытке включить bypass.

## Customer identities и merge

- Telegram и phone subjects уникальны внутри provider namespace; `users.id` остаётся
  стабильным customer profile ID.
- Phone-only профиль создаёт сотрудник с `customers.create`; API и audit возвращают только
  маскированный номер/последние четыре цифры.
- Self-link принимает только Telegram Contact с `contact.user_id == from_user.id`; вручную
  введённый или пересланный контакт не считается доказательством владения.
- Коллизия двух профилей не разрешается автоматическим переносом. Privileged preview/confirm
  повторно блокирует обе записи, проверяет hash, требует reason/idempotency и пишет lineage.
- Merge не меняет owner IDs immutable journals. Source sessions/cards отзываются, source
  становится `merged`, а canonical history читает lineage рекурсивно.

## Sessions

- Клиент получает случайный opaque token с ограниченным TTL.
- В PostgreSQL хранится только SHA-256 hash/эквивалентный односторонний идентификатор token,
  срок действия и revocation metadata.
- Logout, отключение сотрудника и смена критических прав отзывают активные sessions.
- Token не передаётся в URL и не сохраняется в server logs.
- `SESSION_TOKEN_PEPPER` уникален для экземпляра и не совпадает с bot/database secret.

При утечке session token отзовите session; при подозрении на утечку pepper отзовите все
sessions, замените pepper и потребуйте повторный вход.

## Authorization, IDOR and roles

Каждый защищённый endpoint повторно загружает actor, active status, role и granular
permissions на backend. Скрытая кнопка во frontend не является проверкой.

- `customer` читает только собственные приватные объекты;
- `staff` получает ограниченный client view и действует только с нужным permission;
- `admin` не назначает и не снимает admin/owner;
- `owner` выполняет критические изменения, причём последнего активного owner отключить нельзя.

После RBAC выполняйте object-level проверку: ID, переданный в URL/body, не разрешает доступ сам
по себе. Staff не проводит операции со своей клиентской картой. Неуспешные проверки прав и
подозрительные попытки формируют audit event без раскрытия лишних данных в ответе.

## QR and loyalty operations

QR содержит только случайный opaque card token, не Telegram ID, role или баланс. Короткий код
— fallback для поиска, а не секрет авторизации. Reissue атомарно отзывает старую карту.

Сканирование только ищет ограниченную карточку и не меняет баланс. Confirm-команды:

- имеют уникальный idempotency key;
- заново проверяют actor, ограничения и business input;
- блокируют текущее состояние (`SELECT ... FOR UPDATE`);
- рассчитывают результат на backend;
- в одной транзакции пишут immutable operation, snapshot, audit и notification outbox.

Отмена — новая compensating operation со ссылкой на исходную. Исходный журнал не удаляется и
не переписывается.

## Uploads and media

Backend проверяет фактическую сигнатуру/MIME и размер, а не только extension. Разрешены JPEG,
PNG и WebP; SVG, HTML и исполняемые форматы запрещены. Сервер генерирует storage key, не
использует клиентский путь и отдаёт `nosniff`/подходящий `Content-Type`.

Media volume не должен исполняться web server как код. Исходное имя допускается только как
очищенная metadata. Перед публикацией новой категории файлов требуется отдельный security
review. В MVP нет антивирусной sandbox-проверки, поэтому лимиты и allowlist обязательны.

## Secrets and infrastructure

- `.env`, private keys, dumps и media исключены из Git.
- Compose получает secrets через environment interpolation; значения не записаны в YAML.
- Production публикует только frontend на loopback, PostgreSQL остаётся внутри Docker network.
- HTTPS завершается на доверенном host reverse proxy.
- Proxy headers принимаются только от известной Docker network, не от произвольного клиента.
- Containers запускаются с минимально необходимыми write paths; backend пишет только в media
  volume и временный `tmpfs`.
- Bot polling process должен быть единственным для данного token.

Ограничьте доступ к Docker socket: пользователь с правом управлять Docker фактически имеет
root-доступ к данным и secrets контейнеров. Не выводите полный результат `docker inspect` или
`docker compose config` в общедоступные логи.

## Logging and audit

Технические JSON logs и доменные audit events — разные механизмы. Не логируются:

- bot/database/session secrets;
- Telegram init data и session token;
- полный приватный request body;
- чувствительные tip URLs и приватные env-значения.

Audit хранит actor, subject/object, type, UTC time, severity, suspicious flag и ограниченную
metadata. Записи append-only. Доступ к audit ограничен admin/owner, а formatter должен иметь
безопасный fallback для неизвестной версии события.

## Backups

Database dump и media archive вместе содержат персональные данные и историю операций.

- храните backup с правами только для deployment-оператора;
- шифруйте off-host копии и защищайте ключ отдельно;
- задайте retention с владельцем и применимым законодательством;
- проверяйте checksum и restore в изолированном окружении;
- удаляйте просроченные копии контролируемо, а не случайным `rm` по вычисленному пути.

Restore-скрипты требуют явного подтверждения, останавливают пишущие процессы и не продолжают
запуск приложения после ошибки. Media archive проверяется на absolute/parent traversal paths
и не должен содержать symbolic/hard links.

## Incident response

### Утечка bot token

1. Отзовите token через BotFather и получите новый.
2. Обновите `BOT_TOKEN` только в secret environment.
3. Перезапустите backend и bot; убедитесь, что старый процесс остановлен.
4. Отзовите application sessions, если token мог использоваться для подделки init data.
5. Проверьте audit, регистрации, role changes, broadcasts и подозрительные операции за период.

### Утечка database/backup

1. Ограничьте доступ к VPS/storage и сохраните технические evidence.
2. Смените database password, session pepper и связанные operator credentials.
3. Отзовите sessions и оцените затронутые персональные данные/период backup.
4. Действуйте по договорной и применимой процедуре уведомления.

### Компрометация QR

QR не даёт права провести операцию, но раскрытый token позволяет предъявить чужую карту.
Owner/admin перевыпускает карту; старая становится недействительной, а история сохраняется.
При массовом инциденте используйте контролируемую batch-процедуру с audit, а не прямой SQL.

## Известные ограничения MVP

- локальное media storage без object-store versioning;
- нет автоматического облачного backup;
- нет встроенного WAF/edge rate limiter — ограничения следует настроить на reverse proxy и в
  приложении для auth/lookup/upload endpoints;
- нет malware sandbox для изображений;
- Telegram availability и delivery не транзакционны: outbox/retry сохраняет результат после
  commit, но не гарантирует мгновенную доставку;
- сложная компенсация уже погашенной награды требует admin review;
- корректное частичное expiry баллов требует FIFO-партий и может быть отключено в MVP.

## Production checklist

- [ ] Все placeholder secrets заменены и `.env` имеет ограниченные права.
- [ ] `DEV_AUTH_ENABLED=false`, debug выключен, разрешён только production origin.
- [ ] HTTPS и Telegram Web App URL совпадают.
- [ ] PostgreSQL/backend не опубликованы наружу; firewall проверен.
- [ ] Owner создан через CLI, demo staff отсутствует.
- [ ] Проверены RBAC, IDOR, старый QR, idempotency и concurrent operations.
- [ ] SVG/поддельный MIME/oversized upload отклоняются.
- [ ] Логи не содержат tokens/init data/private env.
- [ ] Backup создан, checksum проверен, restore rehearsal выполнен.
- [ ] Ответственные за token/domain/VPS/backups и security contact зафиксированы.
