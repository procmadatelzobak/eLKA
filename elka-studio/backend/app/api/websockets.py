"""WebSocket endpoints for real-time task updates."""

from __future__ import annotations

import asyncio
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.session import SessionLocal
from app.models.task import Task


class ConnectionManager:
    """Keeps track of active WebSocket connections grouped by project."""

    def __init__(self) -> None:
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, project_id: int, websocket: WebSocket) -> None:
        """Register a WebSocket connection and send the initial task snapshot."""

        await websocket.accept()
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        async with self._lock:
            self._connections.setdefault(project_id, set()).add(websocket)
        await self.push_project_tasks(project_id)

    async def disconnect(self, project_id: int, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the manager."""

        async with self._lock:
            sockets = self._connections.get(project_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(project_id, None)

    def has_project(self, project_id: int) -> bool:
        """Return True when at least one connection listens to the project."""

        return bool(self._connections.get(project_id))

    def notify_project(self, project_id: int) -> None:
        """Schedule a task list update on the stored event loop."""

        if not self.has_project(project_id) or self._loop is None:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(self.push_project_tasks(project_id), self._loop)
        else:
            if loop is self._loop:
                loop.create_task(self.push_project_tasks(project_id))
            else:
                asyncio.run_coroutine_threadsafe(self.push_project_tasks(project_id), self._loop)

    async def push_project_tasks(self, project_id: int) -> None:
        """Send the task list for the given project to all active connections."""

        payload = await self._serialize_tasks(project_id)
        async with self._lock:
            sockets = list(self._connections.get(project_id, set()))

        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except WebSocketDisconnect:
                await self.disconnect(project_id, websocket)

    async def _serialize_tasks(self, project_id: int) -> list[dict]:
        """Fetch the latest tasks for a project and serialize them."""

        session = SessionLocal()
        try:
            tasks = (
                session.query(Task)
                .filter(Task.project_id == project_id)
                .order_by(Task.created_at.asc())
                .all()
            )
            return [task.to_dict() for task in tasks]
        finally:
            session.close()


connection_manager = ConnectionManager()

router = APIRouter()


@router.websocket("/ws/tasks/{project_id}")
async def task_updates(websocket: WebSocket, project_id: int) -> None:
    """Stream task updates for a specific project."""

    await connection_manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await connection_manager.disconnect(project_id, websocket)
    except Exception:  # pragma: no cover - safety net
        await connection_manager.disconnect(project_id, websocket)
