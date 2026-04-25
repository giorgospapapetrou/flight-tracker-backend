"""In-memory state store of currently tracked aircraft.

This is the live view of the sky. Every ADS-B message from dump1090
updates this store. The live map endpoint reads from here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AircraftState:
    """Current known state of one aircraft, merged from many ADS-B messages."""

    icao: str
    callsign: str | None = None
    registration: str | None = None
    aircraft_type: str | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_ft: int | None = None
    ground_speed_kt: int | None = None
    heading_deg: int | None = None
    vertical_rate_fpm: int | None = None
    on_ground: bool = False
    last_position_at: datetime | None = None
    last_seen_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AircraftStateStore:
    """Thread-safe-ish store of aircraft keyed by ICAO hex."""

    def __init__(self) -> None:
        self._aircraft: dict[str, AircraftState] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, icao: str, **updates) -> AircraftState:
        """Insert or update fields on an aircraft."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            if icao not in self._aircraft:
                self._aircraft[icao] = AircraftState(icao=icao)

            aircraft = self._aircraft[icao]
            for key, value in updates.items():
                if value is not None:
                    setattr(aircraft, key, value)
            aircraft.last_seen_at = now

            if any(k in updates for k in ("lat", "lon", "altitude_ft")):
                aircraft.last_position_at = now

            return aircraft

    async def get_all_recent(self, max_age_seconds: int) -> list[AircraftState]:
        """Return aircraft seen within the last max_age_seconds."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now.timestamp() - max_age_seconds
            return [
                a for a in self._aircraft.values()
                if a.last_seen_at.timestamp() >= cutoff
            ]

    async def prune_stale(self, max_age_seconds: int) -> int:
        """Remove aircraft not seen recently. Returns number removed."""
        async with self._lock:
            now_ts = datetime.now(timezone.utc).timestamp()
            cutoff = now_ts - max_age_seconds
            stale = [
                icao for icao, a in self._aircraft.items()
                if a.last_seen_at.timestamp() < cutoff
            ]
            for icao in stale:
                del self._aircraft[icao]
            return len(stale)


state_store = AircraftStateStore()
