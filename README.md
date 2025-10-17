# eLKA Studio

eLKA Studio is a full-stack application for building and managing fictional universes. It combines a FastAPI backend, a Celery-powered task pipeline, and a React/Vite frontend to deliver a cohesive world-building experience.

## Features
- **Project management dashboard** – Create, organize, and synchronize projects across local and remote Git repositories.
- **Real-time task queue** – Monitor Celery jobs through Redis-backed WebSockets for immediate progress updates.
- **Inline story previews** – Open generated stories and processed files directly from the task queue without leaving the dashboard.
- **Story & saga generation** – Launch AI-assisted generation pipelines for single stories or multi-chapter sagas.
- **Automated lore processing** – Validate, archive, and version generated content with Git integration.
- **Universe Consistency Engine** – Extract facts, verify canon conflicts, and propose Git-ready updates.
- **Extensible architecture** – Modular backend services and a modern React frontend designed for customization.

## Quick Start
1. Clone the repository: `git clone <repo-url> && cd elka-studio`
2. Install everything with `make setup` (see `scripts/install.sh` for details).
   The installer now verifies required system packages (Python, npm, Redis, etc.) and will attempt to install any
   missing dependencies automatically. Be ready to enter your administrator password if prompted.
3. Create `config.yml` (copy `config.yml.example`) and update the `security.secret_key` value. Use the suggested `SECRET_KEY`
   printed by the installer or generate your own random string.
4. Launch the stack with `make run-dev`. The command now starts the FastAPI server, Celery worker, Redis, and the Vite frontend on [http://localhost:5173](http://localhost:5173).
5. Need only the backend APIs? Run `make run-backend` to skip the frontend server.
6. The UI is automatically available at [http://localhost:5173](http://localhost:5173).
7. Při prvním spuštění otevřete v levém panelu stránku **Settings** (ikona ozubeného kola) a uložte svůj Gemini API Key.
   Klíč se bezpečně uloží pouze do vašeho prohlížeče (localStorage) a okamžitě se použije pro všechny požadavky frontendové aplikace.
8. Vraťte se na stránku **Projects** a klikněte na tlačítko **Add/Import Project** – stejné rozhraní nyní podporuje inicializaci nového i napojení na existující lore vesmír. Formulář přijímá jak zkrácený tvar `uzivatel/projekt`, tak plnou Git URL; pokud se import nezdaří, dialog nyní zobrazí text chyby společně s HTTP statusem a kompletní traceback se objeví v konzoli backendu, takže problém snadno dohledáte přímo v příkazové řádce.

## Konfigurace
- CORS politika backendu je nyní načítána z `config.yml` (sekce `cors.allow_origins`). Výchozí hodnoty povolují vývojářský frontend na
  adresách `http://127.0.0.1:5173` a `http://localhost:5173`. Potřebujete-li další domény, přidejte je do seznamu nebo použijte proměnnou
  prostředí `ELKA_ALLOWED_ORIGINS` s čárkami oddělenými URL adresami. Inicializace CORS middleware probíhá ještě před registrací
  routerů, takže backend i Celery worker modul spolehlivě načtou bez chyb `NameError`.
- Sekce `security.secret_key` v `config.yml` nahrazuje potřebu proměnné prostředí `SECRET_KEY`. Backend i Celery worker ji
  automaticky načtou z konfigurace a použijí pro šifrování uložených Git tokenů. Pokud proměnnou prostředí přesto definujete, má
  přednost před hodnotou ze souboru.
- Soubor `config.yml` podporuje také sekce `git`, `ai` a `stories`. Pomocí nich určíte výchozí Git větev (`git.default_branch`), název
  modelu použitý v metadatech generovaných příběhů (`ai.model`) a pravidla pro archivaci příběhů (`stories.directory`, `stories.extension`,
  `stories.timestamp_format`). Pokud soubor chybí, aplikace automaticky použije bezpečné výchozí hodnoty.

## API Notes
- When creating projects programmatically, send `name`, `git_url`, and (optionally) `git_token` in the request body to `/api/projects`. The API normalises GitHub zkrácený zápis `owner/repo` na plnou URL a vrací lidsky čitelné chyby pro neplatné vstupy.
- The backend root endpoint (`/api/`) now returns a short status payload confirming the API is reachable and linking to the interactive documentation at `/docs`.
- Existing clients should be updated to use the new field names to avoid validation errors.
- Manual story submissions must send the text inside the `params.story_content` field when calling `POST /api/tasks/`. The dashboard form handles this automatically, but custom integrations should update their payloads to avoid `story_content must be a non-empty string` errors.
- The Universe Consistency Engine is available via `POST /api/tasks/story/process` with `project_id`, `story_text`, and optional `apply` flag. Dry-run responses report the planned diff; apply mode writes commits on a dedicated `uce/<project>` branch.
- When a project stores an encrypted Git token, Celery tasks now decrypt it and use a credential helper during `git push`, preventing repeated interactive GitHub login prompts during story processing or saga generation.
- Celery workers now share a singleton application context (`backend/app/core/context.py`) that bootstraps configuration, AI adapters, Git helpers, and validation/archival services once per worker. Task payloads must include the `project_id` (and optionally `pr_id`) so the worker can retrieve the correct repository without reopening the FastAPI stack for every job.

## Testing the Universe Consistency Engine
- Execute `pytest elka-studio/backend/tests/test_uce_core.py` to run deterministic unit tests covering fact extraction, universe loading, planner no-op detection, and Git application helpers.
- The suite provisions temporary Git repositories to simulate dry-run and apply flows, confirming that repeated runs emit explicit "no changes" notes instead of silent exits.

## Testing task status updates
- Run `pytest elka-studio/backend/tests/test_tasks_api.py` to verify that pausing a task updates the database record and broadcasts a notification through the shared `TaskManager` instance without raising errors.

## Project Structure
- `backend/` – FastAPI application, Celery configuration, and Python business logic.
- `frontend/` – React + Vite single-page application for interacting with eLKA Studio.
- `scripts/` – Automation helpers for installation, updates, and development workflows.
- `Makefile` – Unified entry point for setup, development, and maintenance tasks.

## Updating the Project
Run `bash scripts/update.sh` (or `make setup` again) to pull the latest code and refresh dependencies. The update script performs the same dependency checks as the installer, ensuring tools such as Redis and npm stay available. Keep your virtual environment active when working on the backend.

## Troubleshooting
- **Redis connection errors**: Ensure Redis is available locally or via Docker. Use `make stop` to clean up the development container.
- **Backend fails to start**: Confirm that `backend/venv` exists and that `config.yml` contains valid values (zejména `security.secret_key`). If the virtual environment becomes corrupted or is missing activation scripts, rerun `make setup` to let the installer recreate it automatically.
- **Node dependencies missing**: Re-run `npm install` inside the `frontend/` directory or execute `make setup`.

Happy world-building!
