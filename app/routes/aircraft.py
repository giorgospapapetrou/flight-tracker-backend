"""Aircraft endpoints: currently tracked aircraft."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.state import state_store

router = APIRouter(prefix="/aircraft", tags=["aircraft"])


class AircraftOut(BaseModel):
    icao: str
    callsign: str | None
    registration: str | None
    aircraft_type: str | None
    lat: float | None
    lon: float | None
    altitude_ft: int | None
    ground_speed_kt: int | None
    heading_deg: int | None
    vertical_rate_fpm: int | None
    on_ground: bool
    last_position_at: datetime | None


class CurrentAircraftResponse(BaseModel):
    aircraft: list[AircraftOut]
    server_time: datetime


@router.get("/current", response_model=CurrentAircraftResponse)
async def current_aircraft() -> CurrentAircraftResponse:
    recent = await state_store.get_all_recent(settings.aircraft_stale_seconds)
    return CurrentAircraftResponse(
        aircraft=[AircraftOut(**a.__dict__) for a in recent],
        server_time=datetime.now(timezone.utc),
    )
