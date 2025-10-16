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
declare -A INSTALL_COMMANDS=(
    [python3]="apt-get install -y python3"
    [python3-venv]="apt-get install -y python3-venv"
    [git]="apt-get install -y git"
    [npm]="apt-get install -y npm"
    [redis-server]="apt-get install -y redis-server"
)

APT_UPDATED=0

run_with_privilege() {
    local command=$1

    if [[ $EUID -ne 0 ]]; then
        if command -v sudo >/dev/null 2>&1; then
            sudo bash -c "$command"
        else
            echo "Administrator privileges are required to run '$command'. Please install dependencies manually and re-run the script." >&2
            return 1
        fi
    else
        bash -c "$command"
    fi
}

ensure_apt_updated() {
    if (( APT_UPDATED == 0 )); then
        echo "Updating package index (apt-get update)..."
        if ! run_with_privilege "apt-get update"; then
            return 1
        fi
        APT_UPDATED=1
    fi
    return 0
}

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
    echo "Missing dependencies detected. Attempting to install them automatically..."
    failed_deps=()
    for dep in "${missing_deps[@]}"; do
        install_command=${INSTALL_COMMANDS[$dep]:-}
        if [[ -z "$install_command" ]]; then
            echo "No automatic installation command configured for '$dep'." >&2
            failed_deps+=("$dep")
            continue
        fi

        if [[ "$install_command" == apt-get* ]]; then
            if ! command -v apt-get >/dev/null 2>&1; then
                echo "apt-get is not available, cannot install '$dep' automatically." >&2
                failed_deps+=("$dep")
                continue
            fi
            if ! ensure_apt_updated; then
                failed_deps+=("$dep")
                continue
            fi
        fi

        echo "Installing dependency '$dep'..."
        if ! run_with_privilege "$install_command"; then
            echo "Failed to install '$dep'." >&2
            failed_deps+=("$dep")
            continue
        fi

        # Re-check that the dependency is now available
        if [[ "$dep" == "python3-venv" ]]; then
            if ! python3 -m venv --help >/dev/null 2>&1; then
                failed_deps+=("$dep")
            fi
        elif ! command -v "$dep" >/dev/null 2>&1; then
            failed_deps+=("$dep")
        fi
    done

    if (( ${#failed_deps[@]} > 0 )); then
        echo "The following dependencies could not be installed automatically:" >&2
        for dep in "${failed_deps[@]}"; do
            echo "  - $dep" >&2
        done
        echo "Please install them manually and re-run scripts/install.sh." >&2
        exit 1
    fi
    echo "All required dependencies have been installed."
fi

# Backend setup
echo "\nSetting up backend environment..."
cd "$BACKEND_DIR"

if [[ ! -d venv || ! -f venv/bin/activate ]]; then
    if [[ -d venv ]]; then
        echo "Existing virtual environment is incomplete. Recreating..."
        rm -rf venv
    else
        echo "Creating Python virtual environment..."
    fi
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
