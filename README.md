# Flight Tracker — Backend

A FastAPI service that ingests live ADS-B aircraft data from a local `dump1090` instance and exposes it through REST and WebSocket APIs. Designed to pair with the Android client at [flight-tracker-android](https://github.com/giorgospapapetrou/flight-tracker-android).

## What it does

- Continuously polls a running `dump1090-fa` instance for nearby aircraft positions
- Stores recent observations in a local SQLite database with a 7-day retention window
- Serves current aircraft and historical flight data over REST
- Pushes live aircraft updates and removals over WebSocket
- Authenticates clients with a shared bearer token

## Stack

- Python 3.14
- FastAPI + uvicorn
- SQLAlchemy (async) + aiosqlite
- pydantic-settings for configuration
- ruff, mypy, pytest for tooling
- [uv](https://docs.astral.sh/uv/) as the package manager

## Requirements

- Python 3.14 (managed by `uv`)
- A working `dump1090-fa` install (or compatible `dump1090` fork) reachable over HTTP. For ADS-B reception you also need an SDR — this project was developed with a HackRF One.

## Setup

```bash
# Clone
git clone https://github.com/giorgospapapetrou/flight-tracker-backend.git
cd flight-tracker-backend

# Create a .env from the example
cp .env.example .env

# Generate an API key and put it in .env
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Install dependencies
uv sync
```

Edit `.env` to set:

- `API_KEY` — the bearer token clients must send
- `DUMP1090_URL` — typically `http://localhost:8080/data/aircraft.json`
- `DATABASE_URL` — defaults to a local SQLite file
- `RETENTION_DAYS` — defaults to 7

## Running

Start `dump1090` first (in its own terminal):

```bash
dump1090-fa --device-type hackrf --interactive --net
```

Then start the backend:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 5
```

The API is now available at `http://localhost:8000/api/v1`.

## API

All endpoints require an `Authorization: Bearer <API_KEY>` header.

| Method | Path                              | Description                                     |
|--------|-----------------------------------|-------------------------------------------------|
| GET    | `/api/v1/health`                  | Health check, returns aircraft count            |
| GET    | `/api/v1/aircraft/current`        | Aircraft observed in the last few minutes       |
| GET    | `/api/v1/flights`                 | Flight summaries within the retention window    |
| GET    | `/api/v1/flights/{id}/positions`  | Position history for a single flight            |
| WS     | `/api/v1/stream`                  | Live aircraft updates and removals              |

WebSocket message types include `aircraft_updated`, `aircraft_removed`, and a periodic heartbeat. Timestamps are ISO 8601 with a `Z` suffix.

## Exposing the backend over the internet

The backend listens on the local network by default. To make it reachable from a phone on cellular (for example, when demoing the Android app), put a tunnel in front of it. [ngrok](https://ngrok.com/) handles WebSocket upgrades reliably on its free tier:

```bash
ngrok http 8000
```

Cloudflare *Quick* Tunnels are not recommended — they sometimes return `400 Bad Request` on the WebSocket upgrade handshake. A Cloudflare *Named* Tunnel works fine but requires a domain.

## Project layout

```
app/
├── api/          # FastAPI routes
├── core/         # config, auth, lifespan
├── ingest/       # dump1090 polling loop
├── persistence/  # SQLAlchemy models, prune loop
└── stream/       # WebSocket broadcaster
tests/            # pytest suite
```

## Known limitations

- **History depth depends on uptime.** The 7-day retention is a deletion policy, not a collection guarantee. The database holds at most as much history as the backend has been continuously running.
- **No aircraft type registry.** Aircraft type fields are always `null` in the current build; ICAO-to-type lookup is not implemented.
- **Single tenant.** API key auth is shared across all clients. There is no per-user state.
- **No HTTPS in-process.** TLS is expected to be handled by a reverse proxy or a tunnel like ngrok.

## Companion app

The Android client lives at [flight-tracker-android](https://github.com/giorgospapapetrou/flight-tracker-android).
