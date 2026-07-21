# План реализации

Статус: MVP реализован и прошёл основной набор автоматических и Docker-проверок. Дата проверки: 2026-07-21.

## Зафиксированные решения

- Архитектура: monorepo и модульный монолит FastAPI/SQLAlchemy; PostgreSQL — единственный источник данных.
- Процессы Compose: `db`, `backend`, `bot`, `worker`, `frontend`. `bot` и `worker` используют тот же backend-образ и код, поэтому не являются отдельными микросервисами.
- Идентичность: `users` хранит Telegram identity; `staff_members` расширяет пользователя one-to-one. Это позволяет запретить сотруднику операции со своей картой.
- Роли: администратор управляет сотрудниками; назначить или снять администратора может только владелец.
- Установка обслуживает одну организацию. Таблица `locations` поддерживает несколько точек той же кофейни, одна точка создаётся по умолчанию.
- QR статичен до явного перевыпуска. История карт сохраняется, активной может быть только одна карта пользователя.
- Деньги хранятся в копейках, баллы — целыми числами. Все timestamps — UTC.
- Крупная операция в статусе `pending` не меняет баланс до одобрения.
- Журнал операций неизменяем; отмена создаёт compensating operation. Текущий баланс и счётчики — блокируемый снимок для быстрых чтений.
- Истечение баллов после MVP реализуется через партии начислений и FIFO allocations; в MVP можно отключить expiry, но нельзя обещать корректное частичное истечение без этой модели.
- Фоновые задачи без Redis: PostgreSQL queue/leases с `FOR UPDATE SKIP LOCKED` для рассылок, scheduled promotions и expiry.
- В профиле чаевых опубликованная версия остаётся видимой, пока изменённый вариант ожидает модерации.
- Seed-правило штампов: после девятого оплаченного напитка выдаётся награда «десятый напиток бесплатно».

## Этап 1 — планирование и каркас

- [x] Проверить репозиторий: только MIT `LICENSE`, ветка `dev`, initial commit, чистое дерево.
- [x] Прочитать и декомпозировать исходное ТЗ.
- [x] Зафиксировать правила разработки в `AGENTS.md`.
- [x] Зафиксировать архитектурные решения, модель данных и ключевые потоки в `ARCHITECTURE.md`.
- [x] Создать структуру backend/frontend/config/docs/scripts.
- [x] Закрепить совместимые версии зависимостей и добавить lock-файлы.
- [x] Добавить единые команды, `.env.example`, ignore/editor settings и CI.

## Этап 2 — основа backend

- [x] Конфигурация Pydantic Settings, structured logging, единый формат ошибок.
- [x] Async SQLAlchemy, PostgreSQL, session/transaction boundaries.
- [x] Модели и первоначальная Alembic migration с индексами/constraints.
- [x] `/api/v1/health/live` и `/api/v1/health/ready`.
- [x] Проверка Telegram Mini App init data и допустимого возраста.
- [x] Короткоживущие opaque sessions с хешем токена, logout/revoke.
- [x] Регистрация клиента, карта, короткий код, стартовый бонус.
- [x] Backend RBAC и staff permissions.

## Этап 3 — критический контур лояльности

- [x] Поиск клиента по активному QR/короткому коду без побочных эффектов.
- [x] Preview и атомарное начисление по сумме покупки.
- [x] Уникальная идемпотентность и защита от concurrent double spend.
- [x] Списание, ручная корректировка с причиной, блокировка и QR reissue.
- [x] Отмена собственной недавней операции compensating entry.
- [x] Посещения и уникальность business day.
- [x] Стрики, штампы, создание/погашение/отмена/истечение наград.
- [x] Структурированные audit events и человеческий formatter.
- [x] Базовые suspicious flags и лимиты.
- [x] Unit и integration tests критических инвариантов.

## Этап 4 — Telegram-бот и фоновые задачи

- [x] aiogram `/start`, регистрация, role-aware Mini App button, help/contact.
- [x] Шаблоны уведомлений и безопасная отправка после commit.
- [x] CLI `create-owner`, `seed`, export settings.
- [ ] Worker для broadcasts, scheduled content и expiry. Broadcast/outbox delivery готов; автоматический expiry баллов оставлен отключённым после MVP.
- [ ] Preview/test audience/confirm рассылки, delivery results и защита повторного запуска. Preview/create/confirm/cancel и безопасная доставка готовы; отдельной test-send операции нет.

## Этап 5 — клиентский Mini App

- [x] Telegram auth/bootstrap и browser-only development mode.
- [x] Главная, карта/QR/короткий код, баланс и прогресс.
- [x] История, награды, акции, меню.
- [x] Контакты, одобренные сотрудники/чаевые, feedback и privacy.
- [x] Светлая/тёмная тема, safe area, loading/empty/error states, accessibility.

## Этап 6 — интерфейс сотрудника

- [ ] Scanner через Telegram API с camera fallback и ручным кодом. Telegram scanner и ручной код готовы; отдельный browser-camera fallback не добавлен.
- [x] Ограниченная карточка клиента и последние операции.
- [x] Preview/confirm начисления, посещения, штампа, списания и reward redemption.
- [x] Результат, ссылка на операцию и доступная отмена.
- [x] Собственный tip profile и статус модерации.

## Этап 7 — административный интерфейс/API

- [x] Пользователи, история, корректировки, блокировка, QR, заметки.
- [x] Сотрудники, роли, granular permissions, sessions, invites.
- [x] Events с фильтрами и human-readable presentation.
- [ ] Loyalty settings и reward templates. Настройки лояльности готовы; отдельный CRUD шаблонов наград не включён в MVP.
- [ ] Promotions, menu/categories, contacts/locations/settings. Promotions и menu готовы; contacts/locations/settings пока управляются seed/config.
- [x] Feedback workflow, broadcasts и media uploads.
- [x] Подтверждение опасных действий с обязательной причиной.

## Этап 8 — инфраструктура и документация

- [x] Development Compose, health checks, volumes и migration job.
- [x] Production Compose example с reverse proxy/restart policy.
- [x] Локальное media storage и placeholder assets.
- [x] Backup/restore БД и media.
- [x] `README.md`, `CUSTOMIZATION.md`, `DEPLOYMENT.md`, `SECURITY.md`.
- [x] Нейтральные demo seed-данные; demo staff только в development.

## Этап 9 — итоговая проверка

- [x] Backend unit/integration tests на отдельной БД.
- [x] Backend lint, format check и typecheck.
- [x] Frontend component tests, lint, typecheck и production build.
- [x] Alembic upgrade с чистой PostgreSQL и seed.
- [x] Compose startup/health smoke test.
- [x] Проверка ролей, IDOR, uploads, secrets и dependency audit.
- [ ] Backup/restore rehearsal.
- [ ] Сверка всех 30 критериев готовности и финальный отчёт без неподтверждённых утверждений.

## Главные риски

1. Гонки при начислении/списании и повторной доставке запросов.
2. Компенсация посещения/штампа после уже выданной или погашенной награды.
3. Корректное FIFO-истечение партий баллов.
4. Telegram init data, session lifecycle, RBAC и IDOR.
5. Возобновляемые рассылки и scheduled jobs без брокера.
6. Различия scanner/camera API на Telegram iOS, Android, Desktop и в браузере.
7. Эволюция копируемого шаблона без нарушения миграций клиентских установок.
8. Безопасность media и резервных копий с персональными данными.
