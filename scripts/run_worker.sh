#!/usr/bin/env sh
set -eu

CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-2}"
LOGLEVEL="${CELERY_LOGLEVEL:-info}"

exec uv run celery -A app.worker.celery_app worker --loglevel="$LOGLEVEL" --concurrency="$CONCURRENCY"
