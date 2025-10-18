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
   The installer verifies required system packages (Python, npm, Redis, etc.) and will attempt to install any missing dependencies automatically. Be ready to enter your administrator password if prompted.
3. Create `config.yml` (copy `config.yml.example`) and update the `security.secret_key` value. Use the suggested `SECRET_KEY` printed by the installer or generate your own random string.
4. Launch the stack with `make run-dev`. The command starts the FastAPI server, Celery worker, Redis, and the Vite frontend on [http://localhost:5173](http://localhost:5173).
5. Need only the backend APIs? Run `make run-backend` to skip the frontend server.
6. The UI is automatically available at [http://localhost:5173](http://localhost:5173).
7. On first launch, open the **Settings** page (gear icon) in the left navigation pane and store your Gemini API key. The key is saved securely in your browser (localStorage) and immediately used for every frontend request.
8. Return to the **Projects** page and click **Add/Import Project**—the same dialog now supports both initializing a new universe and connecting to an existing lore repository. The form accepts either the shorthand `user/project` or a full Git URL. If the import fails, the dialog shows the error message together with the HTTP status code, and the backend logs the full traceback so you can diagnose the issue directly from the terminal.

## Configuration
- The backend CORS policy is loaded from `config.yml` (section `cors.allow_origins`). The defaults allow the development frontend at `http://127.0.0.1:5173` and `http://localhost:5173`. If you need more domains, add them to the list or set the `ELKA_ALLOWED_ORIGINS` environment variable with comma-separated URLs. The CORS middleware initializes before routers are registered, so both the backend and Celery worker modules load without `NameError` exceptions.
- The `security.secret_key` section in `config.yml` replaces the need for the `SECRET_KEY` environment variable. The backend and Celery worker automatically read the value from configuration and use it when encrypting stored Git tokens. If you still define the environment variable, it takes precedence over the configuration value.
- `config.yml` also supports the `git`, `ai`, `tasks`, and `stories` sections. They control the default Git branch (`git.default_branch`), the model name recorded in generated story metadata (`ai.model`), per-pipeline model routing (`tasks.*.model`), and archival rules (`stories.directory`, `stories.extension`, `stories.timestamp_format`). The `ai.models` section defines aliases (`gemini-pro`, `gemini-flash`) and default models of the current generation (`gemini-2.5`). If the file is missing, the application falls back to safe defaults automatically.

## AI Providers
- The backend uses a deterministic **heuristic** adapter if no API key is configured. As soon as you define `GEMINI_API_KEY`, two clients become available:
  - `AI_VALIDATOR_MODEL` (default `gemini-2.5-pro`) analyzes and verifies story consistency.
  - `AI_WRITER_MODEL` (default `gemini-2.5-flash`) generates Markdown source material for timelines, entities, and summaries.
- In `config.yml` you can optionally store `ai.gemini_api_key`, `ai.validator_model`, `ai.writer_model`, and aliases in `ai.models`. Environment variables always take precedence and prevent accidentally logging secrets.
- If the API key is missing or the provider is set to `heuristic`, the system switches to the deterministic strategy and stays compatible with existing projects.
- Quick environment and configuration setup:
  ```bash
  export GEMINI_API_KEY="your-secret"

  # config.yml
  ai:
    provider: "gemini"
    models:
      gemini-pro: "gemini-2.5-pro"
      gemini-flash: "gemini-2.5-flash"
    validator_model: "gemini-2.5-pro"
    writer_model: "gemini-2.5-flash"
  ```
- The API documentation (`/docs`) now highlights that validation uses Gemini 2.5 Pro and content generation uses Gemini 2.5 Flash when those models are active.

## Universe Consistency Engine workflow

### Quickstart

1. **Configuration** – Copy `config.yml.example` and at minimum fill in the `security.secret_key` section. Activate Gemini through `ai.provider: "gemini"` and set the models:

   ```yaml
   ai:
     provider: "gemini"
     models:
       gemini-pro: "gemini-2.5-pro"
       gemini-flash: "gemini-2.5-flash"
     validator_model: "gemini-2.5-pro"
     writer_model: "gemini-2.5-flash"
   ```

2. **Environment variables** – Create a `.env` file (loaded by `make run-dev`), for example:

   ```dotenv
   GEMINI_API_KEY=your-secret
   AI_PROVIDER=gemini
   AI_VALIDATOR_MODEL=gemini-2.5-pro
   AI_WRITER_MODEL=gemini-2.5-flash
   ```

3. **Run the services** – In one terminal start the backend and Celery with `make run-backend`, and in another run `make run-worker`. The frontend (`make run-frontend`) is optional; backend + worker are enough to test the API.

4. **DRY-RUN** – Submit a story without applying changes:

   ```bash
   curl -X POST http://localhost:8000/api/tasks/story/process \
     -H "Content-Type: application/json" \
     -d '{"project_id": 1, "story_text": "Legend of the Spring Battle"}'
   ```

   The response `{ "task_id": ..., "celery_task_id": ... }` references a record in the database. After the task completes, `result.diff_preview` contains the full unified diff and file list without modifying the repository.

5. **APPLY** – Run the same story with `apply: true`:

   ```bash
   curl -X POST http://localhost:8000/api/tasks/story/process \
     -H "Content-Type: application/json" \
     -d '{"project_id": 1, "story_text": "Legend of the Spring Battle", "apply": true}'
   ```

   The worker creates a branch `task/process-story-<TASK_ID>`, writes the changes, commits them, and performs a `git push`. The resulting `commit_sha` and diff preview are available in `result.commit_sha` and `result.diff_preview`. The branch remains temporary until you approve the outcome via `POST /api/tasks/{task_id}/approve`, which merges the changes into the project’s default branch.

6. **Idempotence** – Re-running the same story returns `notes: ["no-op: universe already up-to-date"]` and an empty diff, because the timeline and entity data are normalized deterministically (for example, seasons map to quarters and duplicates are recognized by their normalized data key).

### Additional information

- `POST /api/tasks/story/process` accepts `{ project_id, story_text, apply? }`. The default **DRY-RUN** mode always stores the diff in the task record.
- The legends (`Legendy/*.md`) and the template `templates/universe_scaffold/Legends/CORE_TRUTHS.md` are automatically loaded during validation.
- If Gemini is unavailable, the heuristic adapter keeps the workflow running—the resulting diffs and Git commits remain deterministic.
- Quick local test: run `pytest elka-studio/backend/tests/test_uce_pipeline.py` to confirm the full **DRY-RUN → APPLY → NO-OP** flow against a temporary Git repository.

## API Notes
- When creating projects programmatically, send `name`, `git_url`, and (optionally) `git_token` in the request body to `/api/projects`. The API normalizes the GitHub shorthand `owner/repo` into a full URL and returns human-readable errors for invalid inputs.
- The backend root endpoint (`/api/`) returns a short status payload confirming the API is reachable and linking to the interactive documentation at `/docs`.
- Existing clients should be updated to use the new field names to avoid validation errors.
- Manual story submissions must place the text inside the `params.story_content` field when calling `POST /api/tasks/`. The dashboard form already handles this, but custom integrations should update their payloads to avoid `story_content must be a non-empty string` errors.
- The Universe Consistency Engine is available through `POST /api/tasks/story/process` with `project_id`, `story_text`, and an optional `apply` flag. Dry-run responses report the planned diff; the apply mode stores the changes on the temporary branch `task/process-story-<TASK_ID>`, which merges into the default branch once approved.
- Approve task results with `POST /api/tasks/{task_id}/approve`. The endpoint sets `result_approved = true`, merges into the main branch (for example `main`), and records the resulting SHA in `result.merge_commit`.
- When a project stores an encrypted Git token, Celery tasks decrypt it and use a credential helper during `git push`, preventing repeated interactive GitHub login prompts during story processing or saga generation.
- Celery workers share a singleton application context (`backend/app/core/context.py`) that bootstraps configuration, AI adapters, Git helpers, and validation/archival services once per worker. Task payloads must include the `project_id` (and optionally `pr_id`) so the worker can retrieve the correct repository without reinitializing the FastAPI stack for every job.

## Testing the Universe Consistency Engine
- Run `pytest elka-studio/backend/tests/test_uce_core.py` to execute deterministic unit tests covering fact extraction, universe loading, planner no-op detection, and Git application helpers.
- The suite provisions temporary Git repositories to simulate dry-run and apply flows, confirming that repeated runs emit explicit "no changes" notes instead of silently exiting.

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
- **Backend fails to start**: Confirm that `backend/venv` exists and that `config.yml` contains valid values (especially `security.secret_key`). If the virtual environment becomes corrupted or is missing activation scripts, rerun `make setup` so the installer can recreate it automatically.
- **Node dependencies missing**: Re-run `npm install` inside the `frontend/` directory or execute `make setup`.

## Stage 3 acceptance checklist
- **Configuration** – Verify that `GEMINI_API_KEY`, `AI_PROVIDER`, `AI_VALIDATOR_MODEL`, and `AI_WRITER_MODEL` are present either in the environment or `config.yml`; see the snippets above for reference values.
- **Changed files** – Run `git status --short` or `git diff --stat` to review updates across adapters, configuration helpers, Celery tasks, and documentation.
- **Quick test** – Execute `pytest elka-studio/backend/tests/test_uce_core.py::test_plan_changes_uses_writer_for_body` to confirm the writer adapter routes to Gemini Flash, or run the full suite with `pytest`.
- **Commit message** – Use a Conventional Commits prefix such as `feat: integrate gemini adapters for lore workflows` when recording work on the feature branch.

Happy world-building!
