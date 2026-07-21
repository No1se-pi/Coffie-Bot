# План реализации

Статус: активная разработка MVP. Дата исходного анализа: 2026-07-21.

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
- [ ] Создать структуру backend/frontend/config/docs/scripts.
- [ ] Закрепить совместимые версии зависимостей и добавить lock-файлы.
- [ ] Добавить единые команды, `.env.example`, ignore/editor settings и CI.

## Этап 2 — основа backend

- [ ] Конфигурация Pydantic Settings, structured logging, единый формат ошибок.
- [ ] Async SQLAlchemy, PostgreSQL, session/transaction boundaries.
- [ ] Модели и первоначальная Alembic migration с индексами/constraints.
- [ ] `/api/v1/health/live` и `/api/v1/health/ready`.
- [ ] Проверка Telegram Mini App init data и допустимого возраста.
- [ ] Короткоживущие opaque sessions с хешем токена, logout/revoke.
- [ ] Регистрация клиента, карта, короткий код, стартовый бонус.
- [ ] Backend RBAC и staff permissions.

## Этап 3 — критический контур лояльности

- [ ] Поиск клиента по активному QR/короткому коду без побочных эффектов.
- [ ] Preview и атомарное начисление по сумме покупки.
- [ ] Уникальная идемпотентность и защита от concurrent double spend.
- [ ] Списание, ручная корректировка с причиной, блокировка и QR reissue.
- [ ] Отмена собственной недавней операции compensating entry.
- [ ] Посещения и уникальность business day.
- [ ] Стрики, штампы, создание/погашение/отмена/истечение наград.
- [ ] Структурированные audit events и человеческий formatter.
- [ ] Базовые suspicious flags и лимиты.
- [ ] Unit и integration tests критических инвариантов.

## Этап 4 — Telegram-бот и фоновые задачи

- [ ] aiogram `/start`, регистрация, role-aware Mini App button, help/contact.
- [ ] Шаблоны уведомлений и безопасная отправка после commit.
- [ ] CLI `create-owner`, `seed`, export settings.
- [ ] Worker для broadcasts, scheduled content и expiry.
- [ ] Preview/test audience/confirm рассылки, delivery results и защита повторного запуска.

## Этап 5 — клиентский Mini App

- [ ] Telegram auth/bootstrap и browser-only development mode.
- [ ] Главная, карта/QR/короткий код, баланс и прогресс.
- [ ] История, награды, акции, меню.
- [ ] Контакты, одобренные сотрудники/чаевые, feedback и privacy.
- [ ] Светлая/тёмная тема, safe area, loading/empty/error states, accessibility.

## Этап 6 — интерфейс сотрудника

- [ ] Scanner через Telegram API с camera fallback и ручным кодом.
- [ ] Ограниченная карточка клиента и последние операции.
- [ ] Preview/confirm начисления, посещения, штампа, списания и reward redemption.
- [ ] Результат, ссылка на операцию и доступная отмена.
- [ ] Собственный tip profile и статус модерации.

## Этап 7 — административный интерфейс/API

- [ ] Пользователи, история, корректировки, блокировка, QR, заметки.
- [ ] Сотрудники, роли, granular permissions, sessions, invites.
- [ ] Events с фильтрами и human-readable presentation.
- [ ] Loyalty settings и reward templates.
- [ ] Promotions, menu/categories, contacts/locations/settings.
- [ ] Feedback workflow, broadcasts и media uploads.
- [ ] Подтверждение опасных действий с обязательной причиной.

## Этап 8 — инфраструктура и документация

- [ ] Development Compose, health checks, volumes и migration job.
- [ ] Production Compose example с reverse proxy/restart policy.
- [ ] Локальное media storage и placeholder assets.
- [ ] Backup/restore БД и media.
- [ ] `README.md`, `CUSTOMIZATION.md`, `DEPLOYMENT.md`, `SECURITY.md`.
- [ ] Нейтральные demo seed-данные; demo staff только в development.

## Этап 9 — итоговая проверка

- [ ] Backend unit/integration tests на отдельной БД.
- [ ] Backend lint, format check и typecheck.
- [ ] Frontend component tests, lint, typecheck и production build.
- [ ] Alembic upgrade с чистой PostgreSQL и seed.
- [ ] Compose startup/health smoke test.
- [ ] Проверка ролей, IDOR, uploads, secrets и dependency audit.
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

