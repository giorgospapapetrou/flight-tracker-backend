"""Application configuration, loaded from environment variables or .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # dump1090 connection
    dump1090_host: str = "127.0.0.1"
    dump1090_port: int = 30003

    # HTTP server
    http_host: str = "0.0.0.0"
    http_port: int = 8000

    # How long before an aircraft is considered "gone" (seconds)
    aircraft_stale_seconds: int = 60

    # Gap between sightings that ends a flight (seconds)
    flight_gap_seconds: int = 600  # 10 minutes

    # Database file
    database_path: str = "data/flight_tracker.db"

    # Data retention
    retention_hours: int = 24


settings = Settings()
