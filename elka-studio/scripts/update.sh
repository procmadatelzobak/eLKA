#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found. Run 'make setup' first." >&2
  exit 1
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade -r "$PROJECT_ROOT/requirements.txt"
