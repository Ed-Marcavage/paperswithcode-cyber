#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec docker compose --env-file "$root/.local.env" -f "$root/local-dev/compose.yaml" "$@"
