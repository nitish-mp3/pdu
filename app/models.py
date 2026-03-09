from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Unnamed PDU")
    host: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    outlets: Mapped[list[Outlet]] = relationship(back_populates="device", cascade="all, delete-orphan")


class Outlet(Base):
    __tablename__ = "outlets"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    outlet_index: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Outlet")
    current_state: Mapped[str] = mapped_column(String(24), default="unknown")
    raw_state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    device: Mapped[Device] = relationship(back_populates="outlets")
    events: Mapped[list[OutletEvent]] = relationship(back_populates="outlet", cascade="all, delete-orphan")


class OutletEvent(Base):
    __tablename__ = "outlet_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlets.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="system")
    previous_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    next_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    outlet: Mapped[Outlet] = relationship(back_populates="events")
