"""WebSocket endpoint for live aircraft updates.

Clients connect with `Authorization: Bearer <key>` header (Android/desktop)
or `?token=<key>` query parameter (browsers, since browser WebSocket APIs
can't set custom headers).

After connection, clients receive a stream of JSON envelopes:
  {"type": "position_update", "data": {...}}
  {"type": "ping"}  -- every 30s, client should reply with {"type": "pong"}
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.broadcaster import broadcaster
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

PING_INTERVAL_SECONDS = 30


def _is_authorized(websocket: WebSocket, query_token: str | None) -> bool:
    """Check API key from header or query param."""
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        provided = auth_header[7:]
        if hmac.compare_digest(provided, settings.api_key):
            return True

    if query_token and hmac.compare_digest(query_token, settings.api_key):
        return True

    return False


@router.websocket("/stream")
async def stream(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    if not _is_authorized(websocket, token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    queue = broadcaster.subscribe()
    logger.info("WebSocket client connected")

    async def send_ping_loop() -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                return

    ping_task = asyncio.create_task(send_ping_loop())

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except RuntimeError as e:
        # Client closed mid-send; not an error, just a cleanup race.
        logger.info("WebSocket closed during send: %s", e)
    except Exception:
        logger.exception("WebSocket error")

    finally:
        ping_task.cancel()
        broadcaster.unsubscribe(queue)
        try:
            await asyncio.wait_for(websocket.close(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass 
