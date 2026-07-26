#!/usr/bin/env sh
set -eu

umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
cd "$ROOT_DIR"

ENV_FILE=${ENV_FILE:-$ROOT_DIR/.env}
COMPOSE_FILE=${COMPOSE_FILE:-$ROOT_DIR/compose.prod.yaml}
BRANCH=${DEPLOY_BRANCH:-}
SKIP_BACKUP=false
STATUS_ONLY=false

usage() {
    printf '%s\n' "Usage: sh scripts/deploy.sh [--branch NAME] [--skip-backup] [--status]"
    printf '%s\n' "Fast-forwards the checkout, backs up live data, builds and verifies production."
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --branch)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            BRANCH=$2
            shift 2
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --status)
            STATUS_ONLY=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

for command_name in docker git curl; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Required command is missing: %s\n' "$command_name" >&2
        exit 1
    }
done

[ -f "$ENV_FILE" ] || {
    printf 'Environment file not found: %s\n' "$ENV_FILE" >&2
    exit 1
}
[ -f "$COMPOSE_FILE" ] || {
    printf 'Compose file not found: %s\n' "$COMPOSE_FILE" >&2
    exit 1
}
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    printf '%s\n' "Deploy must run from a Git checkout" >&2
    exit 1
}
docker compose version >/dev/null

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

current_branch=$(git branch --show-current)
BRANCH=${BRANCH:-$current_branch}
[ -n "$BRANCH" ] || {
    printf '%s\n' "Detached HEAD is not supported; pass --branch and check it out first" >&2
    exit 1
}
[ "$current_branch" = "$BRANCH" ] || {
    printf 'Current branch is %s, requested branch is %s. Switch explicitly first.\n' \
        "$current_branch" "$BRANCH" >&2
    exit 1
}

compose config --quiet

if [ "$STATUS_ONLY" = true ]; then
    printf 'Commit: %s\n' "$(git rev-parse --short HEAD)"
    printf 'Branch: %s\n' "$BRANCH"
    compose ps
    exit 0
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    printf '%s\n' "Tracked files have local changes; deploy refused to preserve them." >&2
    git status --short --untracked-files=no >&2
    exit 1
fi

LOCK_DIR=${DEPLOY_LOCK_DIR:-/tmp/coffie-bot-deploy.lock}
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    printf 'Another deploy appears to be running (lock: %s)\n' "$LOCK_DIR" >&2
    exit 1
fi
cleanup() {
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

old_commit=$(git rev-parse HEAD)
printf 'Fetching origin/%s...\n' "$BRANCH"
git fetch --prune origin "$BRANCH"
target_commit=$(git rev-parse "origin/$BRANCH")
git merge-base --is-ancestor "$old_commit" "$target_commit" || {
    printf '%s\n' "Remote history is not a fast-forward; deploy refused." >&2
    exit 1
}

backup_path=""
if [ "$SKIP_BACKUP" = false ] && compose ps --status running --services | grep -qx db; then
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    backup_path="backups/pre-deploy-$timestamp"
    printf 'Creating backup in %s...\n' "$backup_path"
    ENV_FILE="$ENV_FILE" COMPOSE_FILE="$COMPOSE_FILE" \
        sh "$SCRIPT_DIR/backup.sh" --output "$backup_path"
elif [ "$SKIP_BACKUP" = false ]; then
    printf '%s\n' "Database is not running; pre-deploy backup skipped (first launch)."
else
    printf '%s\n' "Backup skipped by explicit --skip-backup option."
fi

if [ "$old_commit" != "$target_commit" ]; then
    git merge --ff-only "origin/$BRANCH"
else
    printf '%s\n' "Checkout is already up to date."
fi

printf '%s\n' "Building production images..."
compose build --pull

printf '%s\n' "Applying forward-only database migrations..."
compose run --rm migrate

printf '%s\n' "Starting services and waiting for health checks..."
compose up --detach --remove-orphans --wait

# Nginx resolves a Compose service to its current container address. Recreate
# the proxy after backend updates so even older frontend images cannot retain a
# stale upstream address. --no-deps keeps the healthy backend and database up.
printf '%s\n' "Refreshing the frontend proxy..."
compose up --detach --no-deps --force-recreate --wait frontend

frontend_port=$(sed -n 's/^PROD_FRONTEND_PORT=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r"' | tr -d "'")
frontend_port=${frontend_port:-8080}
curl --fail --silent --show-error --max-time 10 \
    "http://127.0.0.1:$frontend_port/health" >/dev/null
curl --fail --silent --show-error --max-time 10 \
    "http://127.0.0.1:$frontend_port/api/v1/health/ready" >/dev/null

new_commit=$(git rev-parse HEAD)
printf '\nDeploy completed successfully.\n'
printf 'Previous commit: %s\n' "$old_commit"
printf 'Current commit:  %s\n' "$new_commit"
[ -z "$backup_path" ] || printf 'Backup:         %s\n' "$backup_path"
compose ps
