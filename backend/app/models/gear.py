from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class GearBase(BaseModel):
    """Base exotic gear model."""

    name: str
    description: str | None = None
    notes: str | None = None


class GearCreate(GearBase):
    """Model for creating an exotic gear entry (must be tied to a log entry)."""

    pass


class GearUpdate(BaseModel):
    """Model for updating an exotic gear entry."""

    name: str | None = None
    description: str | None = None
    notes: str | None = None


class GearLose(BaseModel):
    """Model for marking gear as lost (tied to a log entry)."""

    pass


class ExoticGear(GearBase):
    """Full exotic gear model with all fields."""

    id: UUID
    pilot_id: UUID
    acquired_date: datetime
    acquired_log_id: UUID | None = None  # The log entry when gear was obtained
    lost_log_id: UUID | None = None  # The log entry when gear was lost (null = still owned)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExoticGearWithLogInfo(ExoticGear):
    """Gear with additional log information."""

    is_lost: bool = False  # Convenience field: True if lost_log_id is not None
