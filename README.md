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
3. Update `backend/.env` with your secrets (use the suggested `SECRET_KEY` from the installer).
4. Launch the stack with `make run-dev`.
5. (Optional) In a second terminal, run `make run-frontend` for hot-reloading the UI.
6. Open [http://localhost:5173](http://localhost:5173) in your browser.

## Project Structure
- `backend/` – FastAPI application, Celery configuration, and Python business logic.
- `frontend/` – React + Vite single-page application for interacting with eLKA Studio.
- `scripts/` – Automation helpers for installation, updates, and development workflows.
- `Makefile` – Unified entry point for setup, development, and maintenance tasks.

## Updating the Project
Run `bash scripts/update.sh` (or `make setup` again) to pull the latest code and refresh dependencies. Keep your virtual environment active when working on the backend.

## Troubleshooting
- **Redis connection errors**: Ensure Redis is available locally or via Docker. Use `make stop` to clean up the development container.
- **Backend fails to start**: Confirm that `backend/venv` exists and that `backend/.env` contains valid configuration values.
- **Node dependencies missing**: Re-run `npm install` inside the `frontend/` directory or execute `make setup`.

Happy world-building!
