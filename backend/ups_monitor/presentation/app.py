import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..application.monitor import Monitor
from ..application.sampler import sample_periodically
from ..domain.ports import UpsSource
from ..infrastructure.nut import NutSource
from ..infrastructure.settings import Settings
from ..infrastructure.sqlite_store import SQLiteSampleStore
from .routes import router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, source: UpsSource | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = SQLiteSampleStore(settings.db_path, settings.ups_name)
    monitor = Monitor(
        source=source if source is not None else NutSource(settings.ups_name, settings.upsc_timeout_seconds),
        store=store,
        retention=settings.retention,
        sample_interval_seconds=settings.sample_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(store.initialize)
        stop = asyncio.Event()
        task = asyncio.create_task(sample_periodically(monitor, stop, settings.cleanup_interval_seconds))
        try:
            yield
        finally:
            stop.set()
            await task
            try:
                await asyncio.to_thread(store.checkpoint)
            except Exception:
                logger.warning("No se pudo ejecutar checkpoint WAL de SQLite al cerrar.", exc_info=True)

    app = FastAPI(
        title="UPS Monitor API",
        description="Estado actual e historial de un UPS a través de NUT.",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.monitor = monitor
    app.state.settings = settings
    app.state.ups_name = settings.ups_name
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    app.include_router(router)
    if settings.frontend_dist and (settings.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app
