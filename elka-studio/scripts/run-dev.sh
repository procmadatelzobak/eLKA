#!/usr/bin/env bash

set -euo pipefail

ACTION=${1:-run}

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REDIS_CONTAINER_NAME="elka-studio-redis"
REDIS_CONTAINER_STARTED=0

stop_redis_container() {
    local quiet=${1:-0}
    if ! command -v docker >/dev/null 2>&1; then
        if [[ $quiet -eq 0 ]]; then
            echo "Docker is not available. If Redis was started manually, stop it using your preferred method."
        fi
        return
    fi

    if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER_NAME}$"; then
        echo "Stopping Redis Docker container '${REDIS_CONTAINER_NAME}'..."
        docker stop "${REDIS_CONTAINER_NAME}" >/dev/null || true
    elif [[ $quiet -eq 0 ]]; then
        echo "Redis Docker container '${REDIS_CONTAINER_NAME}' is not running."
    fi
}

if [[ "$ACTION" == "stop-services" ]]; then
    stop_redis_container 0
    exit 0
fi

ensure_redis() {
    if command -v redis-cli >/dev/null 2>&1; then
        if redis-cli ping >/dev/null 2>&1; then
            echo "Redis server already running."
            return
        fi
    fi

    if command -v docker >/dev/null 2>&1; then
        if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER_NAME}$"; then
            echo "Redis Docker container '${REDIS_CONTAINER_NAME}' already running."
            return
        fi

        if docker ps -a --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER_NAME}$"; then
            echo "Starting existing Redis container '${REDIS_CONTAINER_NAME}'."
            docker start "${REDIS_CONTAINER_NAME}" >/dev/null
        else
            echo "Starting Redis in Docker container '${REDIS_CONTAINER_NAME}'."
            docker run -d --rm --name "${REDIS_CONTAINER_NAME}" -p 6379:6379 redis:7-alpine >/dev/null
        fi
        REDIS_CONTAINER_STARTED=1
    else
        echo "Redis server is not running and Docker is unavailable. Please start Redis manually." >&2
        exit 1
    fi
}

cleanup() {
    echo "Stopping development processes..."
    [[ -n "${UVICORN_PID:-}" ]] && kill "${UVICORN_PID}" 2>/dev/null || true
    [[ -n "${CELERY_PID:-}" ]] && kill "${CELERY_PID}" 2>/dev/null || true

    if [[ ${REDIS_CONTAINER_STARTED} -eq 1 ]]; then
        stop_redis_container 1
    fi
}

ensure_redis

trap cleanup EXIT

export PYTHONPATH="${ROOT_DIR}/backend:${PYTHONPATH:-}"

cd "${ROOT_DIR}/backend"

echo "Starting FastAPI server..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

echo "Starting Celery worker..."
celery -A app.celery_app.celery_app worker --loglevel=info &
CELERY_PID=$!

wait -n "${UVICORN_PID}" "${CELERY_PID}"
