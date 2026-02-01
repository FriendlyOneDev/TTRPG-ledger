from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from uuid import UUID
from app.db import get_db
from app.models.user import User
from app.models.log_entry import LogEntry, LogEntryCreate, LogEntryUpdate, LogType
from app.routers.auth import get_current_user

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


async def verify_pilot_ownership(
    pilot_id: UUID,
    current_user: User,
    db: Client,
) -> dict | None:
    """Verify that the current user owns the pilot and return pilot data."""
    result = (
        db.table("pilots")
        .select("*")
        .eq("id", str(pilot_id))
        .eq("user_id", str(current_user.id))
        .single()
        .execute()
    )
    return result.data


@router.get("/pilots/{pilot_id}/logs", response_model=list[LogEntry])
async def list_pilot_logs(
    pilot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """List all log entries for a pilot."""
    if not await verify_pilot_ownership(pilot_id, current_user, db):
        raise HTTPException(status_code=404, detail="Pilot not found")

    result = (
        db.table("log_entries")
        .select("*")
        .eq("pilot_id", str(pilot_id))
        .order("created_at", desc=True)
        .execute()
    )

    return [LogEntry(**log) for log in result.data]


@router.post("/pilots/{pilot_id}/logs", response_model=LogEntry)
async def create_log_entry(
    pilot_id: UUID,
    log_entry: LogEntryCreate,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Create a new log entry for a pilot."""
    pilot_data = await verify_pilot_ownership(pilot_id, current_user, db)
    if not pilot_data:
        raise HTTPException(status_code=404, detail="Pilot not found")

    # Calculate LL clock change for game logs
    ll_clock_change = 0
    if log_entry.log_type == LogType.GAME and log_entry.tick_ll_clock:
        ll_clock_change = 1

    # Create the log entry
    log_data = {
        "pilot_id": str(pilot_id),
        "log_type": log_entry.log_type.value,
        "description": log_entry.description,
        "manna_change": log_entry.manna_change,
        "downtime_change": log_entry.downtime_change,
        "ll_clock_change": ll_clock_change,
    }

    log_result = db.table("log_entries").insert(log_data).execute()

    if not log_result.data:
        raise HTTPException(status_code=400, detail="Failed to create log entry")

    created_log = log_result.data[0]
    log_id = created_log["id"]

    # Handle LL clock progression for game logs
    if ll_clock_change > 0:
        current_ll = pilot_data["license_level"]
        current_progress = pilot_data["ll_clock_progress"]
        segments = get_ll_clock_segments(current_ll)

        # Tick the LL clock
        new_progress = current_progress + ll_clock_change

        if new_progress >= segments and current_ll < 12:
            # Level up!
            new_ll = current_ll + 1
            db.table("pilots").update({
                "license_level": new_ll,
                "ll_clock_progress": 0,
            }).eq("id", str(pilot_id)).execute()
        elif current_ll >= 12:
            # At max level, cap progress
            new_progress = min(new_progress, segments)
            db.table("pilots").update({
                "ll_clock_progress": new_progress,
            }).eq("id", str(pilot_id)).execute()
        else:
            db.table("pilots").update({
                "ll_clock_progress": new_progress,
            }).eq("id", str(pilot_id)).execute()

    # Handle personal clock progress
    for progress in log_entry.clock_progress:
        # Verify clock belongs to pilot
        clock_result = (
            db.table("clocks")
            .select("*")
            .eq("id", str(progress.clock_id))
            .eq("pilot_id", str(pilot_id))
            .single()
            .execute()
        )

        if clock_result.data:
            clock = clock_result.data
            new_filled = min(
                clock["filled"] + (progress.ticks_applied * clock["tick_amount"]),
                clock["segments"],
            )
            is_completed = new_filled >= clock["segments"]

            db.table("clocks").update({
                "filled": new_filled,
                "is_completed": is_completed,
            }).eq("id", str(progress.clock_id)).execute()

            # Record the clock progress
            db.table("clock_progress").insert({
                "log_entry_id": log_id,
                "clock_id": str(progress.clock_id),
                "ticks_applied": progress.ticks_applied,
            }).execute()

    # Handle gear acquired
    for gear in log_entry.gear_acquired:
        db.table("exotic_gear").insert({
            "pilot_id": str(pilot_id),
            "name": gear.name,
            "description": gear.description,
            "notes": gear.notes,
            "acquired_log_id": log_id,
        }).execute()

    # Handle gear lost
    for gear_lost in log_entry.gear_lost:
        # Verify gear belongs to pilot and is not already lost
        gear_result = (
            db.table("exotic_gear")
            .select("*")
            .eq("id", str(gear_lost.gear_id))
            .eq("pilot_id", str(pilot_id))
            .is_("lost_log_id", "null")
            .single()
            .execute()
        )

        if gear_result.data:
            db.table("exotic_gear").update({
                "lost_log_id": log_id,
            }).eq("id", str(gear_lost.gear_id)).execute()

    # Handle reputation changes
    for rep_change in log_entry.reputation_changes:
        db.table("reputation_changes").insert({
            "log_entry_id": log_id,
            "pilot_id": str(pilot_id),
            "corporation_id": str(rep_change.corporation_id),
            "change_value": rep_change.change_value,
            "notes": rep_change.notes,
        }).execute()

    # Update pilot's manna and downtime
    if log_entry.manna_change != 0 or log_entry.downtime_change != 0:
        db.table("pilots").update({
            "manna": pilot_data["manna"] + log_entry.manna_change,
            "downtime": pilot_data["downtime"] + log_entry.downtime_change,
        }).eq("id", str(pilot_id)).execute()

    return LogEntry(**created_log)


@router.get("/logs/{log_id}", response_model=LogEntry)
async def get_log_entry(
    log_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Get a specific log entry."""
    result = (
        db.table("log_entries")
        .select("*, pilots(user_id)")
        .eq("id", str(log_id))
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Log entry not found")

    if result.data["pilots"]["user_id"] != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")

    return LogEntry(**result.data)


@router.put("/logs/{log_id}", response_model=LogEntry)
async def update_log_entry(
    log_id: UUID,
    log_update: LogEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Update a log entry (only description can be updated)."""
    # Get log and verify ownership
    log_result = (
        db.table("log_entries")
        .select("*, pilots(user_id)")
        .eq("id", str(log_id))
        .single()
        .execute()
    )

    if not log_result.data:
        raise HTTPException(status_code=404, detail="Log entry not found")

    if log_result.data["pilots"]["user_id"] != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Only allow updating description (not resource changes after creation)
    update_data = {"description": log_update.description}

    result = (
        db.table("log_entries").update(update_data).eq("id", str(log_id)).execute()
    )

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to update log entry")

    return LogEntry(**result.data[0])


@router.delete("/logs/{log_id}")
async def delete_log_entry(
    log_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Delete a log entry (note: this does NOT reverse resource changes)."""
    # Get log and verify ownership
    log_result = (
        db.table("log_entries")
        .select("*, pilots(user_id)")
        .eq("id", str(log_id))
        .single()
        .execute()
    )

    if not log_result.data:
        raise HTTPException(status_code=404, detail="Log entry not found")

    if log_result.data["pilots"]["user_id"] != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")

    db.table("log_entries").delete().eq("id", str(log_id)).execute()

    return {"message": "Log entry deleted successfully"}
