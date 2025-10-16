#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip
pip install -r "$PROJECT_ROOT/requirements.txt"

echo "Virtual environment created at $VENV_DIR"
echo "Dependencies installed. Activate the environment with: source $VENV_DIR/bin/activate"
