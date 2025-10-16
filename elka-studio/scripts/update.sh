#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_VENV="$BACKEND_DIR/venv"

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

check_and_install_dependencies() {
    local missing_deps=()
    for dep in "${REQUIRED_DEPS[@]}"; do
        if [[ "$dep" == "python3-venv" ]]; then
            if ! python3 -m venv --help >/dev/null 2>&1; then
                missing_deps+=("$dep")
            fi
        elif ! command -v "$dep" >/dev/null 2>&1; then
            missing_deps+=("$dep")
        fi
    done

    if (( ${#missing_deps[@]} == 0 )); then
        return 0
    fi

    echo "Missing dependencies detected. Attempting to install them automatically..."
    local failed_deps=()
    for dep in "${missing_deps[@]}"; do
        local install_command=${INSTALL_COMMANDS[$dep]:-}
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
        echo "Please install them manually and re-run scripts/update.sh." >&2
        exit 1
    fi

    echo "All required dependencies have been installed."
}

check_and_install_dependencies

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
