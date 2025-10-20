"""WebSocket endpoints for real-time task updates."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.session import SessionLocal
from app.models.task import Task
from app.db.redis_client import get_redis_client


class ConnectionManager:
    """Keeps track of active WebSocket connections grouped by project."""

    def __init__(self) -> None:
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._listener_tasks: Dict[int, asyncio.Task] = {}
        self._redis_client = get_redis_client()

    async def connect(self, project_id: int, websocket: WebSocket) -> None:
        """Register a WebSocket connection and send the initial task snapshot."""

        await websocket.accept()
        async with self._lock:
            sockets = self._connections.setdefault(project_id, set())
            sockets.add(websocket)
            listener = self._listener_tasks.get(project_id)
            if listener is None or listener.done():
                task = asyncio.create_task(self._listen_for_project(project_id))
                self._listener_tasks[project_id] = task
        await self.push_project_tasks(project_id)

    async def disconnect(self, project_id: int, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the manager."""

        listener: asyncio.Task | None = None
        async with self._lock:
            sockets = self._connections.get(project_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(project_id, None)
                listener = self._listener_tasks.get(project_id)

        if listener:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

    def has_project(self, project_id: int) -> bool:
        """Return True when at least one connection listens to the project."""

        return bool(self._connections.get(project_id))

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

    async def broadcast_task_update(self, task_data: dict[str, Any]) -> None:
        """Send an updated task payload to listeners for the project."""

        project_id = task_data.get("project_id")
        try:
            project_id_int = int(project_id)
        except (TypeError, ValueError):
            return

        if not self.has_project(project_id_int):
            return

        await self.push_project_tasks(project_id_int)

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

    async def _listen_for_project(self, project_id: int) -> None:
        """Listen for Redis pub/sub events and fan them out to clients."""

        channel = f"project_{project_id}_tasks"
        pubsub = self._redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel)

        try:
            while True:
                message = await asyncio.to_thread(
                    pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0
                )
                if not message:
                    continue

                try:
                    await self.push_project_tasks(project_id)
                except Exception:  # pragma: no cover - websocket broadcast dependent
                    pass
        except asyncio.CancelledError:
            raise
        finally:
            pubsub.close()
            current = asyncio.current_task()
            async with self._lock:
                if self._listener_tasks.get(project_id) is current:
                    self._listener_tasks.pop(project_id, None)


connection_manager = ConnectionManager()
manager = connection_manager

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
