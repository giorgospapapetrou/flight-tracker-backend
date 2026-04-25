"""Flights endpoints: list flights and get position history for replay."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db import Aircraft, Flight, Position, SessionLocal

router = APIRouter(prefix="/flights", tags=["flights"])


class FlightSummary(BaseModel):
    id: int
    aircraft_icao: str
    aircraft_registration: str | None
    aircraft_type: str | None
    callsign: str | None
    started_at: datetime
    ended_at: datetime | None
    position_count: int
    max_altitude_ft: int | None
    min_altitude_ft: int | None


class FlightsResponse(BaseModel):
    flights: list[FlightSummary]


class PositionPoint(BaseModel):
    t: datetime
    lat: float | None
    lon: float | None
    alt: int | None
    spd: int | None
    hdg: int | None
    vr: int | None


class FlightPositionsResponse(BaseModel):
    flight_id: int
    positions: list[PositionPoint]


@router.get("", response_model=FlightsResponse)
async def list_flights(
    flight_date: date | None = Query(default=None, alias="date"),
) -> FlightsResponse:
    """List flights observed on the given date (defaults to today UTC)."""
    target_date = flight_date or datetime.now(timezone.utc).date()
    day_start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with SessionLocal() as session:
        stmt = (
            select(
                Flight,
                func.count(Position.id).label("pos_count"),
                func.max(Position.altitude_ft).label("max_alt"),
                func.min(Position.altitude_ft).label("min_alt"),
            )
            .join(Position, Position.flight_id == Flight.id, isouter=True)
            .where(
                Flight.started_at >= day_start,
                Flight.started_at < day_end,
            )
            .group_by(Flight.id)
            .order_by(Flight.started_at.desc())
            .options(selectinload(Flight.aircraft))
        )
        result = await session.execute(stmt)
        rows = result.all()

        flights = [
            FlightSummary(
                id=flight.id,
                aircraft_icao=flight.aircraft_icao,
                aircraft_registration=flight.aircraft.registration,
                aircraft_type=flight.aircraft.aircraft_type,
                callsign=flight.callsign,
                started_at=flight.started_at,
                ended_at=flight.ended_at,
                position_count=pos_count or 0,
                max_altitude_ft=max_alt,
                min_altitude_ft=min_alt,
            )
            for flight, pos_count, max_alt, min_alt in rows
        ]
        return FlightsResponse(flights=flights)


@router.get("/{flight_id}/positions", response_model=FlightPositionsResponse)
async def flight_positions(flight_id: int) -> FlightPositionsResponse:
    """Return all position points for a flight, ordered by time."""
    async with SessionLocal() as session:
        flight = await session.get(Flight, flight_id)
        if flight is None:
            raise HTTPException(status_code=404, detail="Flight not found")

        stmt = (
            select(Position)
            .where(Position.flight_id == flight_id)
            .order_by(Position.timestamp)
        )
        result = await session.execute(stmt)
        positions = result.scalars().all()

        return FlightPositionsResponse(
            flight_id=flight_id,
            positions=[
                PositionPoint(
                    t=p.timestamp,
                    lat=p.lat,
                    lon=p.lon,
                    alt=p.altitude_ft,
                    spd=p.ground_speed_kt,
                    hdg=p.heading_deg,
                    vr=p.vertical_rate_fpm,
                )
                for p in positions
            ],
        )
