# ScriptFalcon FastAPI backend
# Build:  docker build -t scriptfalcon-api .
# Run:    docker run -p 8000:8000 --env-file .env scriptfalcon-api
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2 \
    SQLITE_DB_PATH=/app/data/scriptfalcon.db

WORKDIR /app

# Install dependencies first so code changes don't invalidate this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data

COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser sql ./sql
COPY --chown=appuser:appuser frontend ./frontend
COPY --chown=appuser:appuser deliverables ./deliverables
COPY --chown=appuser:appuser api.py docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health', timeout=4)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
