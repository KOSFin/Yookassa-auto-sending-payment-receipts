from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import Base, engine
from app.routers.api import router as api_router
from app.services.worker import worker_loop


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(api_router, prefix='/api')

_worker_task: asyncio.Task | None = None


@app.on_event('startup')
async def startup_event() -> None:
    global _worker_task
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if settings.run_embedded_worker and _worker_task is None:
        _worker_task = asyncio.create_task(worker_loop(settings.worker_poll_interval_seconds))


@app.on_event('shutdown')
async def shutdown_event() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
