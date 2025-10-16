#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_VENV="$BACKEND_DIR/venv"

cd "$PROJECT_ROOT"

echo "Pulling latest changes..."
git pull

echo "\nUpdating backend dependencies..."
if [[ ! -x "$BACKEND_VENV/bin/pip" ]]; then
    echo "Backend virtual environment not found at $BACKEND_VENV. Run 'make setup' first." >&2
    exit 1
fi
"$BACKEND_VENV/bin/pip" install -r "$BACKEND_DIR/requirements.txt"

echo "\nUpdating frontend dependencies..."
(cd "$FRONTEND_DIR" && npm install)

echo "\nUpdate complete. You're ready to continue working on eLKA Studio!"
