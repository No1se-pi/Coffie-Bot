#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
cd "$ROOT_DIR"

ENV_FILE=${ENV_FILE:-$ROOT_DIR/.env}
COMPOSE_FILE=${COMPOSE_FILE:-$ROOT_DIR/compose.yaml}
BACKUP_DIR=""
CONFIRMED=false

usage() {
    printf '%s\n' "Usage: sh scripts/restore.sh --from BACKUP_DIRECTORY --yes"
    printf '%s\n' "The command replaces the current PostgreSQL database and media volume."
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --from)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            BACKUP_DIR=$2
            shift 2
            ;;
        --yes)
            CONFIRMED=true
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

[ -n "$BACKUP_DIR" ] || { usage >&2; exit 2; }
[ "$CONFIRMED" = true ] || {
    printf '%s\n' "Restore was not confirmed. Re-run with --yes." >&2
    exit 2
}
if [ "${BACKUP_DIR#/}" = "$BACKUP_DIR" ]; then
    BACKUP_DIR="$ROOT_DIR/$BACKUP_DIR"
fi
[ -d "$BACKUP_DIR" ] || { printf 'Backup directory not found: %s\n' "$BACKUP_DIR" >&2; exit 1; }
BACKUP_DIR=$(CDPATH= cd -- "$BACKUP_DIR" && pwd -P)
[ -f "$BACKUP_DIR/database.dump" ] || { printf '%s\n' "database.dump is missing" >&2; exit 1; }
[ -f "$BACKUP_DIR/media.tar.gz" ] || { printf '%s\n' "media.tar.gz is missing" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { printf 'Environment file not found: %s\n' "$ENV_FILE" >&2; exit 1; }
[ -f "$COMPOSE_FILE" ] || { printf 'Compose file not found: %s\n' "$COMPOSE_FILE" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { printf '%s\n' "Docker CLI is required" >&2; exit 1; }

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

dotenv_value() {
    key=$1
    value=$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r')
    case "$value" in
        \"*\") value=${value#\"}; value=${value%\"} ;;
        \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    printf '%s' "$value"
}

compose config --quiet

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
container_dump="/tmp/coffie-restore-$timestamp.dump"
completed=false
cleanup() {
    compose exec -T db rm -f "$container_dump" >/dev/null 2>&1 || true
    if [ "$completed" != true ]; then
        printf '%s\n' "Restore failed; application services were left stopped. Inspect the error before restarting them." >&2
    fi
}
trap cleanup EXIT HUP INT TERM

printf '%s\n' "Stopping application processes before restore..."
compose stop frontend backend bot worker
compose up --detach --wait db
compose cp "$BACKUP_DIR/database.dump" "db:$container_dump"

compose exec -T db sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
        --host 127.0.0.1 \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        --single-transaction \
        --exit-on-error \
        "$1"
' sh "$container_dump"

media_volume=${MEDIA_VOLUME_NAME:-$(dotenv_value MEDIA_VOLUME_NAME)}
media_volume=${media_volume:-coffie-bot-media}
helper_image=${BACKUP_HELPER_IMAGE:-$(dotenv_value BACKUP_HELPER_IMAGE)}
helper_image=${helper_image:-postgres:17-alpine}
docker volume inspect "$media_volume" >/dev/null
docker run --rm \
    --volume "$media_volume:/target" \
    --volume "$BACKUP_DIR:/backup:ro" \
    "$helper_image" \
    sh -eu -c '
        if tar -tzf /backup/media.tar.gz | grep -Eq "(^/|(^|/)\.\.(/|$))"; then
            echo "Unsafe path in media archive" >&2
            exit 1
        fi
        if tar -tvzf /backup/media.tar.gz | grep -Eq "^[lh]"; then
            echo "Links are not allowed in media archive" >&2
            exit 1
        fi
        find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
        tar -xzf /backup/media.tar.gz -C /target
    '

compose run --rm migrate
compose up --detach backend bot worker frontend

completed=true
trap - EXIT HUP INT TERM
cleanup
printf 'Restore completed from: %s\n' "$BACKUP_DIR"
