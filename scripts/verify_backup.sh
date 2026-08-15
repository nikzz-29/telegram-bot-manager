#!/usr/bin/env bash
set -euo pipefail

backup_path="${1:?Usage: $0 /path/to/tg-manager-*.dump.gz}"
container_name="tg-manager-backup-verify-$$"

if [[ ! -f "$backup_path" ]]; then
  printf 'Backup not found: %s\n' "$backup_path" >&2
  exit 1
fi

cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --name "$container_name" \
  --env POSTGRES_PASSWORD=verify-only \
  postgres:16-alpine >/dev/null

for _ in {1..30}; do
  if docker exec "$container_name" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker exec "$container_name" pg_isready -U postgres >/dev/null 2>&1; then
  printf 'Temporary PostgreSQL did not become ready.\n' >&2
  exit 1
fi

gzip -dc "$backup_path" | docker exec -i "$container_name" \
  pg_restore -U postgres -d postgres --exit-on-error --no-owner --no-privileges

printf 'Backup restore verification passed: %s\n' "$backup_path"
