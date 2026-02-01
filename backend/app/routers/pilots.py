from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from supabase import Client
from uuid import UUID
from app.db import get_db
from app.models.user import User
from app.models.pilot import Pilot, PilotCreate, PilotUpdate, PilotWithDetails
from app.routers.auth import get_current_user
from app.services.import_al import parse_al_csv

router = APIRouter()


def get_ll_clock_segments(license_level: int) -> int:
    """Get the number of segments for an LL clock based on license level."""
    if 1 <= license_level <= 5:
        return 3
    elif 6 <= license_level <= 9:
        return 4
    elif 10 <= license_level <= 12:
        return 5
    return 3


@router.get("", response_model=list[PilotWithDetails])
async def list_pilots(
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """List all pilots for the current user."""
    result = (
        db.table("pilots")
        .select("*")
        .eq("user_id", str(current_user.id))
        .order("created_at", desc=True)
        .execute()
    )

    pilots = [Pilot(**p) for p in result.data]
    return [PilotWithDetails.from_pilot(p) for p in pilots]


@router.post("", response_model=PilotWithDetails)
async def create_pilot(
    pilot: PilotCreate,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Create a new pilot."""
    data = pilot.model_dump()
    data["user_id"] = str(current_user.id)

    result = db.table("pilots").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create pilot")

    created_pilot = Pilot(**result.data[0])
    return PilotWithDetails.from_pilot(created_pilot)


@router.get("/{pilot_id}", response_model=PilotWithDetails)
async def get_pilot(
    pilot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Get a specific pilot."""
    result = (
        db.table("pilots")
        .select("*")
        .eq("id", str(pilot_id))
        .eq("user_id", str(current_user.id))
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Pilot not found")

    pilot = Pilot(**result.data)
    return PilotWithDetails.from_pilot(pilot)


@router.put("/{pilot_id}", response_model=PilotWithDetails)
async def update_pilot(
    pilot_id: UUID,
    pilot_update: PilotUpdate,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Update a pilot."""
    # Check ownership
    existing = (
        db.table("pilots")
        .select("*")
        .eq("id", str(pilot_id))
        .eq("user_id", str(current_user.id))
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Pilot not found")

    # Update only provided fields
    update_data = pilot_update.model_dump(exclude_unset=True)
    if not update_data:
        pilot = Pilot(**existing.data)
        return PilotWithDetails.from_pilot(pilot)

    result = (
        db.table("pilots").update(update_data).eq("id", str(pilot_id)).execute()
    )

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to update pilot")

    pilot = Pilot(**result.data[0])
    return PilotWithDetails.from_pilot(pilot)


@router.delete("/{pilot_id}")
async def delete_pilot(
    pilot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Delete a pilot."""
    # Check ownership
    existing = (
        db.table("pilots")
        .select("id")
        .eq("id", str(pilot_id))
        .eq("user_id", str(current_user.id))
        .single()
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Pilot not found")

    db.table("pilots").delete().eq("id", str(pilot_id)).execute()

    return {"message": "Pilot deleted successfully"}


@router.post("/import", response_model=PilotWithDetails)
async def import_pilot_from_al(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """
    Import a pilot from an Adventurers League log CSV export.

    Creates the pilot with all their log entries and exotic gear.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    try:
        content = await file.read()
        csv_content = content.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    try:
        imported = parse_al_csv(csv_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    # Create the pilot
    pilot_data = {
        "user_id": str(current_user.id),
        "name": imported.name,
        "callsign": imported.callsign,
        "license_level": imported.license_level,
        "ll_clock_progress": imported.ll_clock_progress,
        "manna": imported.manna,
        "downtime": imported.downtime,
    }
    # Only include avatar_url if it has a value
    if imported.avatar_url:
        pilot_data["avatar_url"] = imported.avatar_url

    pilot_result = db.table("pilots").insert(pilot_data).execute()
    if not pilot_result.data:
        raise HTTPException(status_code=400, detail="Failed to create pilot")

    pilot_id = pilot_result.data[0]["id"]

    # Import log entries
    log_id_map: dict[int, str] = {}  # Map entry index to log_id for gear association
    for idx, entry in enumerate(imported.log_entries):
        log_data = {
            "pilot_id": pilot_id,
            "log_type": "game" if entry.is_game_log else "trade",
            "description": f"{entry.title}\n{entry.notes}".strip() if entry.notes else entry.title,
            "manna_change": entry.manna_change,
            "downtime_change": entry.downtime_change,
            "ll_clock_change": 1 if entry.is_game_log else 0,
        }
        if entry.date:
            log_data["created_at"] = entry.date.isoformat()

        log_result = db.table("log_entries").insert(log_data).execute()
        if log_result.data:
            log_id_map[idx] = log_result.data[0]["id"]

    # Import exotic gear (create a separate trade log for each gear item)
    # This ties gear acquisition to a traceable log entry
    for gear in imported.exotic_gear:
        # Create a trade log for the gear acquisition
        gear_log_data = {
            "pilot_id": pilot_id,
            "log_type": "trade",
            "description": f"Imported gear: {gear.name}",
            "manna_change": 0,
            "downtime_change": 0,
            "ll_clock_change": 0,
        }
        gear_log_result = db.table("log_entries").insert(gear_log_data).execute()

        if gear_log_result.data:
            gear_log_id = gear_log_result.data[0]["id"]
            gear_data = {
                "pilot_id": pilot_id,
                "name": gear.name,
                "description": f"Rarity: {gear.rarity}" if gear.rarity else None,
                "notes": gear.notes if gear.notes else None,
                "acquired_log_id": gear_log_id,
            }
            db.table("exotic_gear").insert(gear_data).execute()

    created_pilot = Pilot(**pilot_result.data[0])
    return PilotWithDetails.from_pilot(created_pilot)
