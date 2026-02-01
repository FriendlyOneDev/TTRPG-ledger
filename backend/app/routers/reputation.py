from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from uuid import UUID
from app.db import get_db
from app.models.user import User
from app.models.reputation import PilotReputation, ReputationChange, ReputationChangeWithCorp
from app.routers.auth import get_current_user

router = APIRouter()


async def verify_pilot_ownership(
    pilot_id: UUID,
    current_user: User,
    db: Client,
) -> bool:
    """Verify that the current user owns the pilot."""
    result = (
        db.table("pilots")
        .select("id")
        .eq("id", str(pilot_id))
        .eq("user_id", str(current_user.id))
        .single()
        .execute()
    )
    return result.data is not None


@router.get("/pilots/{pilot_id}/reputation", response_model=list[PilotReputation])
async def list_pilot_reputation(
    pilot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """List aggregated corporation reputation for a pilot (from pilot_reputation view)."""
    if not await verify_pilot_ownership(pilot_id, current_user, db):
        raise HTTPException(status_code=404, detail="Pilot not found")

    # Query the pilot_reputation view which aggregates all changes
    result = (
        db.table("pilot_reputation")
        .select("*")
        .eq("pilot_id", str(pilot_id))
        .execute()
    )

    return [PilotReputation(**r) for r in result.data]


@router.get("/pilots/{pilot_id}/reputation/history", response_model=list[ReputationChangeWithCorp])
async def list_pilot_reputation_history(
    pilot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """List all reputation change history for a pilot."""
    if not await verify_pilot_ownership(pilot_id, current_user, db):
        raise HTTPException(status_code=404, detail="Pilot not found")

    result = (
        db.table("reputation_changes")
        .select("*, corporations(name)")
        .eq("pilot_id", str(pilot_id))
        .order("created_at", desc=True)
        .execute()
    )

    changes = []
    for r in result.data:
        corp_name = r.pop("corporations", {}).get("name", "Unknown")
        changes.append(ReputationChangeWithCorp(**r, corporation_name=corp_name))

    return changes


# Note: Reputation changes are now created through log entries.
# See the logs router for creating log entries with reputation_changes.
# The old direct create/update/delete endpoints are removed.
