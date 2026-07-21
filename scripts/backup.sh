#!/usr/bin/env sh
set -eu

umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
cd "$ROOT_DIR"

ENV_FILE=${ENV_FILE:-$ROOT_DIR/.env}
COMPOSE_FILE=${COMPOSE_FILE:-$ROOT_DIR/compose.yaml}
DESTINATION=""

usage() {
    printf '%s\n' "Usage: sh scripts/backup.sh [--output DIRECTORY]"
    printf '%s\n' "Creates database.dump, media.tar.gz and manifest.txt."
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            DESTINATION=$2
            shift 2
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

[ -f "$ENV_FILE" ] || {
    printf 'Environment file not found: %s (copy .env.example to .env)\n' "$ENV_FILE" >&2
    exit 1
}
[ -f "$COMPOSE_FILE" ] || {
    printf 'Compose file not found: %s\n' "$COMPOSE_FILE" >&2
    exit 1
}
command -v docker >/dev/null 2>&1 || {
    printf '%s\n' "Docker CLI is required" >&2
    exit 1
}

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
if [ -z "$DESTINATION" ]; then
    DESTINATION="$ROOT_DIR/backups/$timestamp"
elif [ "${DESTINATION#/}" = "$DESTINATION" ]; then
    DESTINATION="$ROOT_DIR/$DESTINATION"
fi

if [ -d "$DESTINATION" ] && [ -n "$(find "$DESTINATION" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    printf 'Backup destination is not empty: %s\n' "$DESTINATION" >&2
    exit 1
fi
mkdir -p "$DESTINATION"
DESTINATION=$(CDPATH= cd -- "$DESTINATION" && pwd -P)

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
compose up --detach --wait db

container_dump="/tmp/coffie-backup-$timestamp.dump"
cleanup() {
    compose exec -T db rm -f "$container_dump" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

compose exec -T db sh -eu -c '
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
        --host 127.0.0.1 \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --format custom \
        --compress 6 \
        --no-owner \
        --no-privileges \
        --file "$1"
' sh "$container_dump"
compose cp "db:$container_dump" "$DESTINATION/database.dump"

media_volume=${MEDIA_VOLUME_NAME:-$(dotenv_value MEDIA_VOLUME_NAME)}
media_volume=${media_volume:-coffie-bot-media}
helper_image=${BACKUP_HELPER_IMAGE:-$(dotenv_value BACKUP_HELPER_IMAGE)}
helper_image=${helper_image:-postgres:17-alpine}

docker volume inspect "$media_volume" >/dev/null
docker run --rm \
    --volume "$media_volume:/source:ro" \
    --volume "$DESTINATION:/backup" \
    "$helper_image" \
    sh -eu -c 'tar -czf /backup/media.tar.gz -C /source .'

{
    printf 'created_at_utc=%s\n' "$timestamp"
    printf 'database_file=database.dump\n'
    printf 'database_format=postgresql_custom\n'
    printf 'media_file=media.tar.gz\n'
    printf 'media_format=tar_gzip\n'
    printf 'media_volume=%s\n' "$media_volume"
    printf 'compose_file=%s\n' "$COMPOSE_FILE"
} >"$DESTINATION/manifest.txt"

if command -v sha256sum >/dev/null 2>&1; then
    (
        cd "$DESTINATION"
        sha256sum database.dump media.tar.gz >SHA256SUMS
    )
fi

trap - EXIT HUP INT TERM
cleanup
printf 'Backup created: %s\n' "$DESTINATION"
