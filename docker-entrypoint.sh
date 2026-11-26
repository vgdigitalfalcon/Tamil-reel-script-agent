#!/bin/sh
set -e

# Create/migrate the database schema once, before workers start,
# so multiple uvicorn workers don't race on CREATE TABLE.
python -c "from src.db import CRMDatabase; CRMDatabase()"

if [ -z "$DATABASE_URL" ]; then
    echo "WARNING: DATABASE_URL is not set. Using SQLite at $SQLITE_DB_PATH." >&2
    echo "         Data is lost when the container is removed unless /app/data is a mounted volume." >&2
fi

exec uvicorn api:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --timeout-keep-alive 75
