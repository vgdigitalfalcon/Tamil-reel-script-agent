#!/usr/bin/env bash
# Dump the Postgres database to backups/ and keep the last 14 days.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
file="backups/scriptfalcon_$(date +%Y%m%d_%H%M%S).sql.gz"
$DOCKER compose exec -T db pg_dump -U scriptfalcon -d scriptfalcon | gzip > "$file"
find backups -name 'scriptfalcon_*.sql.gz' -mtime +14 -delete
echo "$(date -Is) backup written: $file"
# Restore: gunzip -c backups/<file>.sql.gz | docker compose exec -T db psql -U scriptfalcon -d scriptfalcon
