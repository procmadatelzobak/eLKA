# eLKA Studio – Frontend

This directory hosts the React + Vite single-page application that powers the eLKA Studio user interface. The UI communicates with the FastAPI backend exposed at `http://localhost:8000/api`.

## Requirements

- Node.js 20+
- npm 10+

## Local development

```bash
npm install
npm run dev
```

The development server is available at [http://localhost:5173](http://localhost:5173). The backend base URL can be customised through the `VITE_API_BASE_URL` environment variable.

> 💡 **Tip:** From the repository root you can run `make run-dev` to launch both the backend and this Vite server (with `--host 0.0.0.0`). Use `make run-backend` if you only need the API.

## Project structure

```
src/
├── components/        # Shared UI components such as modals and forms
├── layouts/           # Reusable page layouts (sidebar + content)
├── pages/             # Routeable views managed by React Router
├── services/          # API and websocket clients
└── main.jsx           # Application entry point
```

## Available npm scripts

- `npm run dev` – start the development server with HMR
- `npm run build` – produce a production bundle
- `npm run preview` – preview the production bundle locally
- `npm run lint` – run ESLint against the source code

## API client

`src/services/api.js` defines the Axios instance that targets `http://localhost:8000/api` by default. Override the base URL via a `.env` file with the `VITE_API_BASE_URL` variable.

## Project dashboard

`ProjectDashboardPage` is the primary workspace for a project. It lets you submit new tasks (story processing, seed-based story generation, saga creation) and observe their progress in real time through websockets.

- The control panel validates and submits requests with the `createTask` helper from `src/services/api.js`.
- The queue consumes updates via `TaskSocket` (`src/services/websocket.js`) to render progress and logs.
- Completed tasks expose modals to preview the generated story and archived files.
- Pause and resume actions are delegated to the `pauseTask` and `resumeTask` API helpers.

### WebSocket configuration

The websocket URL defaults to the value derived from `VITE_API_BASE_URL`. If the backend runs on a different host or port, override it with the `VITE_WS_BASE_URL` environment variable (for example `ws://localhost:8000`).
