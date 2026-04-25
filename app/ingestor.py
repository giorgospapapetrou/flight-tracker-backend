"""Connects to dump1090 and feeds ADS-B messages into the state store.

dump1090 SBS/BaseStation format is documented here:
http://woodair.net/sbs/article/barebones42_socket_data.htm

Each line is comma-separated. We only care about MSG rows; transmission
types 1-8 each convey different fields. We parse what's there and merge.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.state import state_store
from app.broadcaster import broadcaster
from app import persistence

logger = logging.getLogger(__name__)


def _parse_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_bool(value: str) -> bool | None:
    value = value.strip()
    if value == "1":
        return True
    if value == "0":
        return False
    return None

async def _handle_line(line: str) -> None:
    """Parse one SBS line, update state, persist, and broadcast."""
    parts = line.strip().split(",")
    if len(parts) < 22 or parts[0] != "MSG":
        return

    icao = parts[4].strip().upper()
    if not icao:
        return

    updates: dict = {}

    callsign = parts[10].strip()
    if callsign:
        updates["callsign"] = callsign

    altitude = _parse_int(parts[11])
    if altitude is not None:
        updates["altitude_ft"] = altitude

    speed = _parse_int(parts[12])
    if speed is not None:
        updates["ground_speed_kt"] = speed

    heading = _parse_int(parts[13])
    if heading is not None:
        updates["heading_deg"] = heading

    lat = _parse_float(parts[14])
    lon = _parse_float(parts[15])
    if lat is not None and lon is not None:
        updates["lat"] = lat
        updates["lon"] = lon

    vr = _parse_int(parts[16])
    if vr is not None:
        updates["vertical_rate_fpm"] = vr

    on_ground = _parse_bool(parts[21])
    if on_ground is not None:
        updates["on_ground"] = on_ground

    if not updates:
        return

    # Update in-memory state
    aircraft = await state_store.upsert(icao, **updates)

    # Persist to DB
    try:
        await persistence.record_position(
            icao=icao,
            callsign=updates.get("callsign"),
            lat=updates.get("lat"),
            lon=updates.get("lon"),
            altitude_ft=updates.get("altitude_ft"),
            ground_speed_kt=updates.get("ground_speed_kt"),
            heading_deg=updates.get("heading_deg"),
            vertical_rate_fpm=updates.get("vertical_rate_fpm"),
            on_ground=updates.get("on_ground", False),
        )
    except Exception:
        logger.exception("Failed to persist position for %s", icao)

    # Broadcast to WebSocket subscribers
    await broadcaster.publish({
        "type": "position_update",
        "data": {
            "icao": aircraft.icao,
            "callsign": aircraft.callsign,
            "registration": aircraft.registration,
            "aircraft_type": aircraft.aircraft_type,
            "lat": aircraft.lat,
            "lon": aircraft.lon,
            "altitude_ft": aircraft.altitude_ft,
            "ground_speed_kt": aircraft.ground_speed_kt,
            "heading_deg": aircraft.heading_deg,
            "vertical_rate_fpm": aircraft.vertical_rate_fpm,
            "on_ground": aircraft.on_ground,
            "last_position_at": (
                aircraft.last_position_at.isoformat().replace("+00:00", "Z")
                if aircraft.last_position_at else None
            ),
        },
    })

async def _ingest_loop() -> None:
    """Connect to dump1090 and read lines. Reconnect on failure."""
    host = settings.dump1090_host
    port = settings.dump1090_port
    backoff = 1.0

    while True:
        try:
            logger.info("Connecting to dump1090 at %s:%d", host, port)
            reader, writer = await asyncio.open_connection(host, port)
            logger.info("Connected to dump1090")
            backoff = 1.0

            while True:
                raw = await reader.readline()
                if not raw:
                    logger.warning("dump1090 closed the connection")
                    break
                try:
                    line = raw.decode("ascii", errors="replace")
                    await _handle_line(line)
                except Exception:
                    logger.exception("Failed to process line: %r", raw[:120])

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        except (ConnectionRefusedError, OSError) as exc:
            logger.warning("dump1090 connection failed: %s", exc)

        except asyncio.CancelledError:
            logger.info("Ingestor cancelled")
            raise

        except Exception:
            logger.exception("Unexpected ingestor error")

        logger.info("Reconnecting to dump1090 in %.1fs", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)

async def _prune_loop() -> None:
    """Periodically remove stale aircraft from in-memory store + close stale flights."""
    while True:
        try:
            await asyncio.sleep(15)
            removed = await state_store.prune_stale(
                settings.aircraft_stale_seconds
            )
            if removed:
                logger.debug("Pruned %d stale aircraft from memory", removed)
            await persistence.close_stale_flights()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Prune loop error")


async def _cleanup_loop() -> None:
    """Periodically delete data older than retention period."""
    while True:
        try:
            await asyncio.sleep(3600)  # every hour
            await persistence.cleanup_old_data()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cleanup loop error")


def start_background_tasks() -> list[asyncio.Task]:
    """Launch the ingestor, pruner, and cleanup as background tasks."""
    return [
        asyncio.create_task(_ingest_loop(), name="ingestor"),
        asyncio.create_task(_prune_loop(), name="pruner"),
        asyncio.create_task(_cleanup_loop(), name="cleanup"),
    ]
