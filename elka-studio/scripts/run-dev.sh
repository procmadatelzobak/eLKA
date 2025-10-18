#!/usr/bin/env bash

set -euo pipefail

ACTION=${1:-run}

RUN_FRONTEND=1
if [[ "$ACTION" == "backend-only" ]]; then
    RUN_FRONTEND=0
    ACTION="run"
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REDIS_CONTAINER_NAME="elka-studio-redis"
REDIS_CONTAINER_STARTED=0
BACKEND_DIR="$ROOT_DIR/backend"
BACKEND_VENV="$BACKEND_DIR/venv"
UVICORN_BIN="$BACKEND_VENV/bin/uvicorn"
CELERY_BIN="$BACKEND_VENV/bin/celery"
BACKEND_PYTHON="$BACKEND_VENV/bin/python"
BACKEND_PIP="$BACKEND_VENV/bin/pip"
BACKEND_REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"
FRONTEND_DIR="$ROOT_DIR/frontend"

ensure_backend_tools() {
    if [[ ! -d "$BACKEND_VENV" ]]; then
        echo "Backend virtual environment not found at '$BACKEND_VENV'. Run 'make setup' first." >&2
        exit 1
    fi

    if [[ ! -x "$UVICORN_BIN" || ! -x "$CELERY_BIN" || ! -x "$BACKEND_PYTHON" || ! -x "$BACKEND_PIP" ]]; then
        echo "Required backend tools are missing from the virtual environment. Re-run 'make setup' to install Python dependencies." >&2
        exit 1
    fi
}

ensure_backend_dependencies() {
    local missing_modules=()
    local module
    local modules=(
        limits
    )

    for module in "${modules[@]}"; do
        if ! "$BACKEND_PYTHON" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$module') else 1)" >/dev/null 2>&1; then
            missing_modules+=("$module")
        fi
    done

    if (( ${#missing_modules[@]} > 0 )); then
        if [[ ! -f "$BACKEND_REQUIREMENTS_FILE" ]]; then
            echo "Backend requirements file not found at '$BACKEND_REQUIREMENTS_FILE'. Please run 'make setup'." >&2
            exit 1
        fi

        echo "Installing missing backend Python packages: ${missing_modules[*]}..."
        "$BACKEND_PIP" install -r "$BACKEND_REQUIREMENTS_FILE"
    fi
}

ensure_frontend_tools() {
    if [[ $RUN_FRONTEND -eq 0 ]]; then
        return
    fi

    if [[ ! -d "$FRONTEND_DIR" ]]; then
        echo "Frontend directory not found at '$FRONTEND_DIR'." >&2
        exit 1
    fi

    if ! command -v npm >/dev/null 2>&1; then
        echo "npm is required to run the frontend development server. Install Node.js 20+ or rerun 'make setup'." >&2
        exit 1
    fi

    if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
        echo "Installing frontend dependencies (npm install)..."
        (cd "$FRONTEND_DIR" && npm install)
    fi
}

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
    [[ -n "${FRONTEND_PID:-}" ]] && kill "${FRONTEND_PID}" 2>/dev/null || true

    if [[ ${REDIS_CONTAINER_STARTED} -eq 1 ]]; then
        stop_redis_container 1
    fi
}

ensure_redis
ensure_backend_tools
ensure_backend_dependencies
ensure_frontend_tools

trap cleanup EXIT

export PYTHONPATH="${ROOT_DIR}/backend:${PYTHONPATH:-}"

cd "$BACKEND_DIR"

echo "Starting FastAPI server..."
"$UVICORN_BIN" app.main:app --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

echo "Starting Celery worker..."
"$CELERY_BIN" -A app.celery_app.celery_app worker --loglevel=info &
CELERY_PID=$!

if [[ $RUN_FRONTEND -eq 1 ]]; then
    echo "Starting frontend development server..."
    (
        cd "$FRONTEND_DIR"
        npm run dev -- --host 0.0.0.0 --port 5173
    ) &
    FRONTEND_PID=$!
fi

PIDS=("${UVICORN_PID}" "${CELERY_PID}")
if [[ -n "${FRONTEND_PID:-}" ]]; then
    PIDS+=("${FRONTEND_PID}")
fi

wait -n "${PIDS[@]}"
