from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import Base, engine, ensure_runtime_schema
from app.routers.api import router as api_router
from app.services.panel_auth import is_panel_auth_configured, verify_session_token
from app.services.worker import worker_loop

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.middleware('http')
async def global_exception_handler(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        logger.exception('Unhandled exception in request %s %s', request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={'detail': f'Internal server error: {type(exc).__name__}'},
        )


@app.middleware('http')
async def panel_auth_guard(request: Request, call_next):
    path = request.url.path
    if not path.startswith('/api'):
        return await call_next(request)
    if path.startswith('/api/health') or path.startswith('/api/webhook/') or path.startswith('/api/auth/'):
        return await call_next(request)

    if not is_panel_auth_configured():
        return JSONResponse(
            status_code=503,
            content={'detail': 'Panel auth is not configured. Set PANEL_LOGIN and PANEL_PASSWORD.'},
        )

    token = request.cookies.get(settings.panel_auth_cookie_name, '')
    if not token or not verify_session_token(token):
        return JSONResponse(status_code=401, content={'detail': 'Authentication required'})

    return await call_next(request)

app.include_router(api_router, prefix='/api')

_worker_task: asyncio.Task | None = None


@app.on_event('startup')
async def startup_event() -> None:
    global _worker_task
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_runtime_schema()
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
