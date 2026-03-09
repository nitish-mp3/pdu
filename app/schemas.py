from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    action: Literal["on", "off", "reboot"]


class LockRequest(BaseModel):
    locked: bool = Field(..., description="True to prevent remote off or reboot actions.")


class HistoryItem(BaseModel):
    id: int
    outlet_id: int
    outlet_name: str
    device_name: str
    action: str
    source: str
    previous_state: str | None
    next_state: str | None
    message: str | None
    created_at: datetime


class OutletView(BaseModel):
    id: int
    outlet_index: int
    name: str
    current_state: str
    raw_state: int | None
    is_locked: bool
    last_changed_at: datetime | None


class DeviceView(BaseModel):
    id: int
    name: str
    host: str
    model: str | None
    status: str
    last_seen_at: datetime | None
    last_polled_at: datetime | None
    outlets: list[OutletView]


class OverviewResponse(BaseModel):
    devices: list[DeviceView]
    history: list[HistoryItem]
    summary: dict[str, int]
