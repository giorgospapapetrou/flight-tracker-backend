"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import init_db
from app.ingestor import start_background_tasks
from app.routes import aircraft, flights, stream
from app.state import state_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting flight tracker backend")
    await init_db()
    logger.info("Database initialized")
    tasks = start_background_tasks()
    try:
        yield
    finally:
        logger.info("Shutting down background tasks")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="Flight Tracker API",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(aircraft.router, prefix="/api/v1")
app.include_router(flights.router, prefix="/api/v1")
app.include_router(stream.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict:
    recent = await state_store.get_all_recent(settings.aircraft_stale_seconds)
    return {
        "status": "ok",
        "aircraft_currently_tracked": len(recent),
    }
