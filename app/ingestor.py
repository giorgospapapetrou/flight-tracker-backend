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
    """Parse one SBS line and update state."""
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

    if updates:
        await state_store.upsert(icao, **updates)


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
    """Periodically remove stale aircraft from the state store."""
    while True:
        try:
            await asyncio.sleep(15)
            removed = await state_store.prune_stale(
                settings.aircraft_stale_seconds
            )
            if removed:
                logger.debug("Pruned %d stale aircraft", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Prune loop error")


def start_background_tasks() -> list[asyncio.Task]:
    """Launch the ingestor and pruner as background tasks."""
    return [
        asyncio.create_task(_ingest_loop(), name="ingestor"),
        asyncio.create_task(_prune_loop(), name="pruner"),
    ]
