.DEFAULT_GOAL := help

ENV_FILE ?= .env
COMPOSE_FILE ?= compose.yaml
COMPOSE := docker compose --env-file "$(ENV_FILE)" -f "$(COMPOSE_FILE)"
RUN_BACKEND := $(COMPOSE) run --rm backend
RUN_FRONTEND := $(COMPOSE) run --rm frontend
# Tests must not inherit development-only auth/debug values. The extra read-only
# mount preserves the repository-relative seed path used both locally and in CI.
RUN_BACKEND_TEST := $(COMPOSE) run --rm -e APP_ENV=test -e APP_DEBUG=false -e DEV_AUTH_ENABLED=false --volume "$(CURDIR)/configs:/configs:ro" backend
SEED_FILE ?= /app/configs/demo-seed.json

.PHONY: help install dev up down logs migrate migration seed create-owner test lint format format-check typecheck backup restore deploy compose-check prod-up prod-down prod-logs

help: ## Show the supported developer commands.
	@echo "Usage: make <target> [NAME=value]"
	@echo ""
	@echo "Core: install dev up down logs migrate migration seed create-owner"
	@echo "Quality: test lint format format-check typecheck compose-check"
	@echo "Operations: backup restore deploy prod-up prod-down prod-logs"
	@echo ""
	@echo "Examples:"
	@echo "  make migration MESSAGE=add_reward_expiry"
	@echo "  make create-owner OWNER_TELEGRAM_ID=123456789 OWNER_NAME=Owner"
	@echo "  make logs SERVICE=worker"
	@echo "  make restore BACKUP=backups/20260721T210000Z CONFIRM=YES"

install: ## Build the development images and install their locked dependencies.
	$(COMPOSE) build backend frontend

dev: ## Build and run the development stack in the foreground.
	$(COMPOSE) up --build

up: ## Build and run the development stack in the background.
	$(COMPOSE) up --detach --build

down: ## Stop containers without deleting persistent data.
	$(COMPOSE) down --remove-orphans

logs: ## Follow logs; optionally pass SERVICE=backend|bot|worker|frontend|db.
	$(COMPOSE) logs --follow --tail=200 $(SERVICE)

migrate: ## Apply all committed Alembic migrations.
	$(COMPOSE) run --rm migrate

migration: ## Generate a migration; requires MESSAGE=short_description.
	@$(if $(strip $(MESSAGE)),,$(error MESSAGE is required, for example: make migration MESSAGE=add_reward_expiry))
	$(RUN_BACKEND) alembic revision --autogenerate -m "$(MESSAGE)"

seed: ## Import neutral demo data; override SEED_FILE for another file.
	$(RUN_BACKEND) python -m app.cli seed --file "$(SEED_FILE)"

create-owner: ## Create/update the first owner; requires OWNER_TELEGRAM_ID.
	@$(if $(strip $(OWNER_TELEGRAM_ID)),,$(error OWNER_TELEGRAM_ID is required))
	$(RUN_BACKEND) python -m app.cli create-owner --telegram-id "$(OWNER_TELEGRAM_ID)" $(if $(strip $(OWNER_NAME)),--display-name "$(OWNER_NAME)",)

test: ## Run backend and frontend tests.
	$(RUN_BACKEND_TEST) pytest
	$(RUN_FRONTEND) npm run test

lint: ## Run backend and frontend linters.
	$(RUN_BACKEND) ruff check .
	$(RUN_FRONTEND) npm run lint

format: ## Format backend and frontend source files.
	$(RUN_BACKEND) ruff format .
	$(RUN_FRONTEND) npm run format

format-check: ## Check formatting without changing files.
	$(RUN_BACKEND) ruff format --check .
	$(RUN_FRONTEND) npm run format:check

typecheck: ## Run backend and frontend static type checks.
	$(RUN_BACKEND) mypy app
	$(RUN_FRONTEND) npm run typecheck

backup: ## Back up PostgreSQL and media; optionally pass BACKUP_DIR=path.
	ENV_FILE="$(ENV_FILE)" COMPOSE_FILE="$(COMPOSE_FILE)" sh ./scripts/backup.sh $(if $(strip $(BACKUP_DIR)),--output "$(BACKUP_DIR)",)

restore: ## Restore PostgreSQL and media; requires BACKUP=path CONFIRM=YES.
	@$(if $(strip $(BACKUP)),,$(error BACKUP is required))
	@$(if $(filter YES,$(CONFIRM)),,$(error Restoring replaces data; pass CONFIRM=YES))
	ENV_FILE="$(ENV_FILE)" COMPOSE_FILE="$(COMPOSE_FILE)" sh ./scripts/restore.sh --from "$(BACKUP)" --yes

deploy: ## Safely update the current production branch; optionally pass BRANCH=main.
	ENV_FILE="$(ENV_FILE)" COMPOSE_FILE="compose.prod.yaml" sh ./scripts/deploy.sh $(if $(strip $(BRANCH)),--branch "$(BRANCH)",)

compose-check: ## Validate development and production Compose models.
	docker compose --env-file "$(ENV_FILE)" -f compose.yaml config --quiet
	docker compose --env-file "$(ENV_FILE)" -f compose.prod.yaml config --quiet

prod-up: ## Build and start the production example.
	docker compose --env-file "$(ENV_FILE)" -f compose.prod.yaml up --detach --build

prod-down: ## Stop the production example without deleting volumes.
	docker compose --env-file "$(ENV_FILE)" -f compose.prod.yaml down --remove-orphans

prod-logs: ## Follow production logs; optionally pass SERVICE=name.
	docker compose --env-file "$(ENV_FILE)" -f compose.prod.yaml logs --follow --tail=200 $(SERVICE)
