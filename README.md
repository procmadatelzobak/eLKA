# eLKA Studio

eLKA Studio is a full-stack application for building and managing fictional universes. It combines a FastAPI backend, a Celery-powered task pipeline, and a React/Vite frontend to deliver a cohesive world-building experience.

## Features
- **Project management dashboard** – Create, organize, and synchronize projects across local and remote Git repositories.
- **Real-time task queue** – Monitor Celery jobs through Redis-backed WebSockets for immediate progress updates.
- **Story & saga generation** – Launch AI-assisted generation pipelines for single stories or multi-chapter sagas.
- **Automated lore processing** – Validate, archive, and version generated content with Git integration.
- **Extensible architecture** – Modular backend services and a modern React frontend designed for customization.

## Quick Start
1. Clone the repository: `git clone <repo-url> && cd elka-studio`
2. Install everything with `make setup` (see `scripts/install.sh` for details).
   The installer now verifies required system packages (Python, npm, Redis, etc.) and will attempt to install any
   missing dependencies automatically. Be ready to enter your administrator password if prompted.
3. Update `backend/.env` with your secrets (use the suggested `SECRET_KEY` from the installer).
4. Launch the stack with `make run-dev`. The command now starts the FastAPI server, Celery worker, Redis, and the Vite frontend on [http://localhost:5173](http://localhost:5173).
5. Need only the backend APIs? Run `make run-backend` to skip the frontend server.
6. The UI is automatically available at [http://localhost:5173](http://localhost:5173).
7. Při prvním spuštění otevřete v levém panelu stránku **Settings** (ikona ozubeného kola) a uložte svůj Gemini API Key.
   Klíč se bezpečně uloží pouze do vašeho prohlížeče (localStorage) a okamžitě se použije pro všechny požadavky frontendové aplikace.
8. Vraťte se na stránku **Projects** a klikněte na tlačítko **Add/Import Project** – stejné rozhraní nyní podporuje inicializaci nového i napojení na existující lore vesmír. Formulář přijímá jak zkrácený tvar `uzivatel/projekt`, tak plnou Git URL; pokud se import nezdaří, dialog nyní zobrazí text chyby společně s HTTP statusem a kompletní traceback se objeví v konzoli backendu, takže problém snadno dohledáte přímo v příkazové řádce.

## API Notes
- When creating projects programmatically, send `name`, `git_url`, and (optionally) `git_token` in the request body to `/projects`. The API normalises GitHub zkrácený zápis `owner/repo` na plnou URL a vrací lidsky čitelné chyby pro neplatné vstupy.
- The backend root endpoint (`/`) now returns a short status payload confirming the API is reachable and linking to the interactive documentation at `/docs`.
- Existing clients should be updated to use the new field names to avoid validation errors.

## Project Structure
- `backend/` – FastAPI application, Celery configuration, and Python business logic.
- `frontend/` – React + Vite single-page application for interacting with eLKA Studio.
- `scripts/` – Automation helpers for installation, updates, and development workflows.
- `Makefile` – Unified entry point for setup, development, and maintenance tasks.

## Updating the Project
Run `bash scripts/update.sh` (or `make setup` again) to pull the latest code and refresh dependencies. The update script performs the same dependency checks as the installer, ensuring tools such as Redis and npm stay available. Keep your virtual environment active when working on the backend.

## Troubleshooting
- **Redis connection errors**: Ensure Redis is available locally or via Docker. Use `make stop` to clean up the development container.
- **Backend fails to start**: Confirm that `backend/venv` exists and that `backend/.env` contains valid configuration values. If the virtual environment becomes corrupted or is missing activation scripts, rerun `make setup` to let the installer recreate it automatically.
- **Node dependencies missing**: Re-run `npm install` inside the `frontend/` directory or execute `make setup`.

Happy world-building!
