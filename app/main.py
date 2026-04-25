"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.ingestor import start_background_tasks
from app.routes import aircraft
from app.state import state_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting flight tracker backend")
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
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(aircraft.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict:
    recent = await state_store.get_all_recent(settings.aircraft_stale_seconds)
    return {
        "status": "ok",
        "aircraft_currently_tracked": len(recent),
    }
