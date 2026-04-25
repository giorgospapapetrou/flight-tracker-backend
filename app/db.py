"""Database setup using SQLAlchemy async with SQLite.

The database lives in a single file at the path configured via settings.
On startup we create tables if they don't exist.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class Aircraft(Base):
    __tablename__ = "aircraft"

    icao: Mapped[str] = mapped_column(String(6), primary_key=True)
    registration: Mapped[str | None] = mapped_column(String(16), nullable=True)
    aircraft_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    flights: Mapped[list["Flight"]] = relationship(back_populates="aircraft")


class Flight(Base):
    __tablename__ = "flights"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    aircraft_icao: Mapped[str] = mapped_column(
        ForeignKey("aircraft.icao"), index=True
    )
    callsign: Mapped[str | None] = mapped_column(String(16), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    aircraft: Mapped["Aircraft"] = relationship(back_populates="flights")
    positions: Mapped[list["Position"]] = relationship(
        back_populates="flight", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flight_id: Mapped[int] = mapped_column(
        ForeignKey("flights.id"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lon: Mapped[float | None] = mapped_column(nullable=True)
    altitude_ft: Mapped[int | None] = mapped_column(nullable=True)
    ground_speed_kt: Mapped[int | None] = mapped_column(nullable=True)
    heading_deg: Mapped[int | None] = mapped_column(nullable=True)
    vertical_rate_fpm: Mapped[int | None] = mapped_column(nullable=True)
    on_ground: Mapped[bool] = mapped_column(default=False)

    flight: Mapped["Flight"] = relationship(back_populates="positions")


# Engine + session factory
_db_path = Path(settings.database_path).resolve()
_db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    f"sqlite+aiosqlite:///{_db_path}",
    echo=False,
)

SessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
