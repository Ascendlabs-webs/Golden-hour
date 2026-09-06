"""GoldenHour AI backend — FastAPI application factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config as cfg
from . import database as db
from .api.routes import router
from .api.ws import emit_sync, hub
from .processing import pipeline as pipe


def _ensure_seed() -> None:
    db.init_db()
    if not db.get_zones():
        if cfg.APP_MODE == "live":
            try:
                pipe.refresh_live()
            except Exception:
                pipe.refresh_demo()
        else:
            pipe.refresh_demo()
    else:
        # merge any new default sources (e.g. after upgrades) without wiping data
        with db.get_conn() as conn:
            existing = {s["source_id"] for s in db.get_sources()}
            for s in pipe.default_sources(cfg.APP_MODE):
                if s["source_id"] not in existing:
                    db.upsert_source(conn, s)
            # local subsystems are always available — backfill missing timestamps
            now = db.now_iso()
            conn.execute("UPDATE data_sources SET last_updated=COALESCE(last_updated, ?), "
                         "last_checked=COALESCE(last_checked, ?), "
                         "last_successful_update=COALESCE(last_successful_update, ?) "
                         "WHERE source_id IN ('engine','reports')", (now, now, now))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_seed()
    pipe.subscribe(emit_sync)
    pipe.start_scheduler()
    yield


def create_app() -> FastAPI:
    _ensure_seed()
    if emit_sync not in pipe._listeners:
        pipe.subscribe(emit_sync)
    app = FastAPI(title="GoldenHour AI",
                  description="Disaster-response prioritization prototype (academic).",
                  version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.CORS_ORIGINS + ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    @app.websocket("/ws/updates")
    async def ws_updates(ws: WebSocket):
        await ws.accept()
        await hub.connect(ws)
        try:
            await ws.send_text('{"event": "connected"}')
            while True:
                await ws.receive_text()  # keep-alive; client messages ignored
        except WebSocketDisconnect:
            await hub.disconnect(ws)
        except Exception:
            await hub.disconnect(ws)

    # Serve the built React dashboard (frontend/dist) from the same origin,
    # so the demo works from a single URL. API routes take precedence.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.joinpath("index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    else:

        @app.get("/")
        def root():
            return {"service": "GoldenHour AI backend", "mode": cfg.APP_MODE,
                    "docs": "/docs",
                    "disclaimer": "Academic prototype — scores are decision-support heuristics."}

    return app


app = create_app()
