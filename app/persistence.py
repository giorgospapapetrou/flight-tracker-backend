"""Persistence layer: writes aircraft, flight, and position data to the DB.

Maintains a small in-memory cache of "currently open flights" so we can
group continuous sightings without a DB lookup on every message.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import settings
from app.db import Aircraft, Flight, Position, SessionLocal

logger = logging.getLogger(__name__)


# In-memory cache: icao -> open flight_id
# Avoids a SELECT on every message for the same aircraft.
_open_flights: dict[str, int] = {}


async def record_position(
    icao: str,
    callsign: str | None,
    lat: float | None,
    lon: float | None,
    altitude_ft: int | None,
    ground_speed_kt: int | None,
    heading_deg: int | None,
    vertical_rate_fpm: int | None,
    on_ground: bool,
) -> None:
    """Persist a single position update.

    Ensures the Aircraft row exists, ensures an open Flight exists,
    and inserts a Position row.
    """
    now = datetime.now(timezone.utc)
    gap = timedelta(seconds=settings.flight_gap_seconds)

    async with SessionLocal() as session:
        # 1. Upsert aircraft (atomic INSERT ... ON CONFLICT DO UPDATE)
        upsert_stmt = sqlite_insert(Aircraft).values(
            icao=icao,
            first_seen=now,
            last_seen=now,
        ).on_conflict_do_update(
            index_elements=["icao"],
            set_=dict(last_seen=now),
        )
        await session.execute(upsert_stmt)

        # 2. Determine the right flight
        flight_id = _open_flights.get(icao)
        flight: Flight | None = None

        if flight_id is not None:
            flight = await session.get(Flight, flight_id)
            if flight is None or flight.ended_at is not None:
                # Stale cache entry
                flight_id = None
                flight = None

        if flight is None:
            # Look for a recent open flight in DB
            cutoff = now - gap
            stmt = (
                select(Flight)
                .where(
                    Flight.aircraft_icao == icao,
                    Flight.ended_at.is_(None),
                    Flight.started_at >= cutoff,
                )
                .order_by(Flight.started_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            flight = result.scalar_one_or_none()

        if flight is None:
            # Start a new flight
            flight = Flight(
                aircraft_icao=icao,
                callsign=callsign,
                started_at=now,
            )
            session.add(flight)
            await session.flush()  # populate flight.id
            logger.debug("Started flight %d for %s", flight.id, icao)
        elif callsign and not flight.callsign:
            # Backfill callsign if it arrived later
            flight.callsign = callsign

        _open_flights[icao] = flight.id

        # 3. Insert the position row
        position = Position(
            flight_id=flight.id,
            timestamp=now,
            lat=lat,
            lon=lon,
            altitude_ft=altitude_ft,
            ground_speed_kt=ground_speed_kt,
            heading_deg=heading_deg,
            vertical_rate_fpm=vertical_rate_fpm,
            on_ground=on_ground,
        )
        session.add(position)

        await session.commit()


async def close_stale_flights() -> int:
    """Mark flights as ended if they've been silent for > flight_gap_seconds.

    Returns number of flights closed.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.flight_gap_seconds)

    async with SessionLocal() as session:
        # Find open flights whose latest position is older than the gap
        stmt = (
            select(Flight, Aircraft.last_seen)
            .join(Aircraft, Aircraft.icao == Flight.aircraft_icao)
            .where(
                Flight.ended_at.is_(None),
                Aircraft.last_seen < cutoff,
            )
        )
        result = await session.execute(stmt)
        rows = result.all()

        closed = 0
        for flight, last_seen in rows:
            flight.ended_at = last_seen
            _open_flights.pop(flight.aircraft_icao, None)
            closed += 1

        if closed:
            await session.commit()
            logger.info("Closed %d stale flights", closed)

        return closed


async def cleanup_old_data() -> tuple[int, int]:
    """Delete data older than retention_hours.

    Returns (positions_deleted, flights_deleted).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.retention_hours
    )

    async with SessionLocal() as session:
        # Delete old positions
        pos_result = await session.execute(
            delete(Position).where(Position.timestamp < cutoff)
        )
        # Delete flights with no remaining positions
        flight_result = await session.execute(
            delete(Flight).where(
                Flight.ended_at.is_not(None),
                Flight.ended_at < cutoff,
            )
        )
        await session.commit()
        positions_deleted = pos_result.rowcount or 0
        flights_deleted = flight_result.rowcount or 0

        if positions_deleted or flights_deleted:
            logger.info(
                "Cleanup: deleted %d positions, %d flights",
                positions_deleted, flights_deleted,
            )
        return positions_deleted, flights_deleted
