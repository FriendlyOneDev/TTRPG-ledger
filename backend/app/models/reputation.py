from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class ReputationChangeCreate(BaseModel):
    """Model for creating a reputation change (tied to a log entry)."""

    corporation_id: UUID
    change_value: int  # Positive or negative change
    notes: str | None = None


class ReputationChange(ReputationChangeCreate):
    """Full reputation change model."""

    id: UUID
    log_entry_id: UUID
    pilot_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ReputationChangeWithCorp(ReputationChange):
    """Reputation change with corporation name."""

    corporation_name: str


class PilotReputation(BaseModel):
    """Aggregated reputation for a pilot-corporation pair (from pilot_reputation view)."""

    pilot_id: UUID
    corporation_id: UUID
    corporation_name: str
    reputation_value: int  # Sum of all changes
