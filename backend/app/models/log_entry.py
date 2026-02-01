from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from enum import Enum


class LogType(str, Enum):
    """Type of log entry."""

    GAME = "game"
    TRADE = "trade"


class ClockProgressEntry(BaseModel):
    """Model for clock progress within a log entry."""

    clock_id: UUID
    ticks_applied: int = 1


class GearAcquiredEntry(BaseModel):
    """Model for gear acquired in a log entry."""

    name: str
    description: str | None = None
    notes: str | None = None


class GearLostEntry(BaseModel):
    """Model for gear lost in a log entry."""

    gear_id: UUID  # Reference to existing gear


class ReputationChangeEntry(BaseModel):
    """Model for reputation change in a log entry."""

    corporation_id: UUID
    change_value: int  # Positive or negative
    notes: str | None = None


class LogEntryBase(BaseModel):
    """Base log entry model."""

    log_type: LogType
    description: str | None = None
    manna_change: int = 0
    downtime_change: int = 0
    ll_clock_change: int = 0  # LL clock progress for this log


class LogEntryCreate(LogEntryBase):
    """Model for creating a log entry."""

    clock_progress: list[ClockProgressEntry] = []
    tick_ll_clock: bool = True  # For game logs, auto-tick LL clock
    gear_acquired: list[GearAcquiredEntry] = []  # Gear obtained in this log
    gear_lost: list[GearLostEntry] = []  # Gear lost in this log
    reputation_changes: list[ReputationChangeEntry] = []  # Rep changes in this log


class LogEntryUpdate(BaseModel):
    """Model for updating a log entry."""

    description: str | None = None
    # Note: resource changes are immutable after creation


class LogEntry(LogEntryBase):
    """Full log entry model with all fields."""

    id: UUID
    pilot_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LogEntryWithDetails(LogEntry):
    """Log entry with all associated changes."""

    clock_progress: list[ClockProgressEntry] = []
    gear_acquired: list[GearAcquiredEntry] = []
    gear_lost: list[GearLostEntry] = []
    reputation_changes: list[ReputationChangeEntry] = []


# Keep for backwards compatibility
class LogEntryWithProgress(LogEntry):
    """Log entry with associated clock progress."""

    clock_progress: list[ClockProgressEntry] = []
