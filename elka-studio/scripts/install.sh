#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

cat <<'MSG'
=====================================
 Welcome to the eLKA Studio installer
=====================================
MSG

# Dependency checks
REQUIRED_DEPS=(python3 python3-venv git npm redis-server)
declare -A INSTALL_HINTS=(
    [python3]="sudo apt-get install python3"
    [python3-venv]="sudo apt-get install python3-venv"
    [git]="sudo apt-get install git"
    [npm]="sudo apt-get install npm"
    [redis-server]="sudo apt-get install redis-server"
)

missing_deps=()

for dep in "${REQUIRED_DEPS[@]}"; do
    if [[ "$dep" == "python3-venv" ]]; then
        if ! python3 -m venv --help >/dev/null 2>&1; then
            missing_deps+=("$dep")
        fi
    elif ! command -v "$dep" >/dev/null 2>&1; then
        missing_deps+=("$dep")
    fi
done

if (( ${#missing_deps[@]} > 0 )); then
    echo "The following dependencies are required before installation can continue:" >&2
    for dep in "${missing_deps[@]}"; do
        echo "  - $dep (install with: ${INSTALL_HINTS[$dep]})" >&2
    done
    echo "Please install the missing packages and re-run scripts/install.sh." >&2
    exit 1
fi

# Backend setup
echo "\nSetting up backend environment..."
cd "$BACKEND_DIR"

if [[ ! -d venv ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
else
    echo "Reusing existing Python virtual environment."
fi

# shellcheck disable=SC1091
source venv/bin/activate

pip install --upgrade pip
BACKEND_REQUIREMENTS_FILE="requirements.txt"
if [[ ! -f "$BACKEND_REQUIREMENTS_FILE" && -f "$PROJECT_ROOT/requirements.txt" ]]; then
    BACKEND_REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
fi
pip install -r "$BACKEND_REQUIREMENTS_FILE"

deactivate

# Frontend setup
echo "\nInstalling frontend dependencies..."
cd "$FRONTEND_DIR"
npm install

# Configuration
echo "\nChecking configuration files..."
ENV_FILE="$BACKEND_DIR/.env"
ENV_EXAMPLE="$BACKEND_DIR/.env.example"
if [[ ! -f "$ENV_FILE" && -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "Created backend/.env from backend/.env.example. Please review and update the configuration values."
fi

if command -v openssl >/dev/null 2>&1; then
    SECRET_KEY=$(openssl rand -hex 32)
else
    SECRET_KEY=$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)
fi

echo "Suggested SECRET_KEY value (add to backend/.env): $SECRET_KEY"

echo "\nInstallation complete!"
echo "Next steps:"
echo "  1. Update backend/.env with your secrets (e.g., SECRET_KEY above)."
echo "  2. Start the development stack with: make run-dev"
echo "  3. (Optional) In another terminal start the frontend only: make run-frontend"

echo "Happy world-building with eLKA Studio!"
