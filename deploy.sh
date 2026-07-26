#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec sh "$ROOT_DIR/scripts/deploy.sh" "$@"
