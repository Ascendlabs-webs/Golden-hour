"""WebSocket broadcast for live dashboard updates (polling remains as fallback)."""
from __future__ import annotations

import asyncio
import json


class Hub:
    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, event: str, payload: dict) -> None:
        msg = json.dumps({"event": event, **payload})
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


hub = Hub()


def emit_sync(event: str, payload: dict) -> None:
    """Called from pipeline (sync context) — schedules broadcast on the loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(hub.broadcast(event, payload))
