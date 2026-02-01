"""Service for importing pilots from Adventurers League log CSV exports."""

import csv
import re
from io import StringIO
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ImportedLogEntry:
    """Parsed log entry from AL export."""

    title: str
    date: datetime | None
    manna_change: int
    downtime_change: int
    notes: str
    is_game_log: bool  # True if it's a game session, False if GM/trade


@dataclass
class ImportedGear:
    """Parsed exotic gear from AL export."""

    name: str
    rarity: str
    notes: str


@dataclass
class ImportedPilot:
    """Parsed pilot data from AL export."""

    name: str
    callsign: str | None
    license_level: int
    ll_clock_progress: int
    manna: int
    downtime: int
    avatar_url: str | None = None
    log_entries: list[ImportedLogEntry] = field(default_factory=list)
    exotic_gear: list[ImportedGear] = field(default_factory=list)


def parse_ll_from_notes(notes: str) -> tuple[int, int] | None:
    """
    Parse LL progression from notes like:
    - "LL1 (0/3 -> 1/3)" -> current state is LL1, 1/3
    - "LL1 -> LL2 (2/3 -> 3/3)" -> leveled up, now LL2, 0/3
    - "LL2 (0/3 -> 1/3)" -> LL2, 1/3

    Returns (license_level, clock_progress) or None if not found.
    """
    if not notes:
        return None

    # Pattern for level up: "LL1 -> LL2 (2/3 -> 3/3)"
    level_up_match = re.search(r"LL(\d+)\s*->\s*LL(\d+)", notes)
    if level_up_match:
        new_ll = int(level_up_match.group(2))
        # After level up, progress resets to 0
        return (new_ll, 0)

    # Pattern for progress: "LL2 (1/3 -> 2/3)"
    progress_match = re.search(r"LL(\d+)\s*\((\d+)/(\d+)\s*->\s*(\d+)/(\d+)\)", notes)
    if progress_match:
        ll = int(progress_match.group(1))
        new_progress = int(progress_match.group(4))
        return (ll, new_progress)

    # Pattern for simple state: "LL3 (1/3)"
    simple_match = re.search(r"LL(\d+)\s*\((\d+)/(\d+)\)", notes)
    if simple_match:
        ll = int(simple_match.group(1))
        progress = int(simple_match.group(2))
        return (ll, progress)

    return None


def parse_al_csv(csv_content: str) -> ImportedPilot:
    """
    Parse an Adventurers League log CSV export.

    CSV structure:
    - Row 0: Header with pilot info (name, race, class_and_levels, etc.)
    - Row 1: Pilot data
    - Row 2+: Headers and data rows for logs/items
    - Data rows start with: CharacterLogEntry, PurchaseLogEntry, MAGIC ITEM, etc.
    """
    reader = csv.reader(StringIO(csv_content))
    rows = list(reader)

    if len(rows) < 2:
        raise ValueError("CSV too short - missing pilot data")

    # Row 0: Header - parse dynamically to find column indices
    pilot_header = [col.lower().strip() for col in rows[0]]
    pilot_row = rows[1]

    # Find column indices dynamically
    def get_col_index(header: list[str], *possible_names: str) -> int:
        for name in possible_names:
            if name.lower() in header:
                return header.index(name.lower())
        return -1

    name_idx = get_col_index(pilot_header, "name")
    portrait_idx = get_col_index(pilot_header, "portrait_url", "avatar_url", "image_url")

    raw_name = pilot_row[name_idx] if name_idx >= 0 and len(pilot_row) > name_idx else "Unknown Pilot"

    # Parse name and callsign - format might be 'Lee "Bug"' or just 'Lee'
    callsign = None
    name = raw_name
    callsign_match = re.search(r'"([^"]+)"', raw_name)
    if callsign_match:
        callsign = callsign_match.group(1)
        name = re.sub(r'\s*"[^"]+"\s*', " ", raw_name).strip()

    # Parse portrait_url from dynamic index
    avatar_url = None
    if portrait_idx >= 0 and len(pilot_row) > portrait_idx and pilot_row[portrait_idx]:
        avatar_url = pilot_row[portrait_idx]

    # Initialize tracking variables
    log_entries: list[ImportedLogEntry] = []
    exotic_gear: list[ImportedGear] = []
    total_manna = 0
    total_downtime = 0
    current_ll = 2  # Default starting LL
    current_progress = 0

    # Find log entry header row to get column mappings
    log_header_idx = -1
    log_header: list[str] = []
    for i, row in enumerate(rows[2:], start=2):
        if row and row[0].lower() == "type":
            log_header_idx = i
            log_header = [col.lower().strip() for col in row]
            break

    # Column indices for log entries (relative to the row, not absolute)
    log_title_idx = get_col_index(log_header, "adventure_title", "title") if log_header else 1
    log_date_idx = get_col_index(log_header, "date_played", "date") if log_header else 3
    log_gp_idx = get_col_index(log_header, "gp_gained", "gold", "manna") if log_header else 7
    log_dt_idx = get_col_index(log_header, "downtime_gained", "downtime") if log_header else 8
    log_notes_idx = get_col_index(log_header, "notes") if log_header else 14

    # Process remaining rows (skip header rows)
    for row in rows[2:]:
        if not row or len(row) < 2:
            continue

        row_type = row[0].strip()

        if row_type in ("CharacterLogEntry", "PurchaseLogEntry"):
            # Log entry row - use dynamic column indices
            title = row[log_title_idx] if len(row) > log_title_idx and log_title_idx >= 0 else ""

            # Skip header rows
            if title.lower() in ("title", "adventure_title"):
                continue

            date_str = row[log_date_idx] if len(row) > log_date_idx and log_date_idx >= 0 else ""

            # Parse gp_gained as manna
            manna_change = 0
            if log_gp_idx >= 0 and len(row) > log_gp_idx and row[log_gp_idx]:
                try:
                    manna_change = int(float(row[log_gp_idx]))
                except (ValueError, TypeError):
                    pass

            # Parse downtime_gained
            downtime_change = 0
            if log_dt_idx >= 0 and len(row) > log_dt_idx and row[log_dt_idx]:
                try:
                    downtime_change = int(float(row[log_dt_idx]))
                except (ValueError, TypeError):
                    pass

            # Notes
            notes = ""
            if log_notes_idx >= 0 and len(row) > log_notes_idx and row[log_notes_idx]:
                notes = row[log_notes_idx]

            # Parse date
            entry_date = None
            if date_str:
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %Z")
                except ValueError:
                    try:
                        entry_date = datetime.strptime(date_str.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass

            # Determine if it's a game log or GM/trade
            # PurchaseLogEntry is always a trade, CharacterLogEntry depends on title
            is_game = row_type == "CharacterLogEntry" and not title.lower().startswith("gming")

            # Track totals
            total_manna += manna_change
            total_downtime += downtime_change

            # Parse LL from notes to track current state
            ll_state = parse_ll_from_notes(notes)
            if ll_state:
                current_ll, current_progress = ll_state

            log_entries.append(ImportedLogEntry(
                title=title if title else row_type,
                date=entry_date,
                manna_change=manna_change,
                downtime_change=downtime_change,
                notes=notes,
                is_game_log=is_game,
            ))

        elif row_type == "MAGIC ITEM":
            # MAGIC ITEM,name,rarity,location_found,table,table_result,notes
            item_name = row[1] if len(row) > 1 else ""
            rarity = row[2] if len(row) > 2 else ""
            location_found = row[3] if len(row) > 3 else ""
            item_notes = row[6] if len(row) > 6 else ""

            # Skip header row (where columns are "name", "rarity", etc.)
            if item_name.lower() == "name":
                continue

            # Use location_found as notes if notes is empty
            final_notes = item_notes if item_notes else location_found

            if item_name:
                exotic_gear.append(ImportedGear(
                    name=item_name,
                    rarity=rarity,
                    notes=final_notes,
                ))

    return ImportedPilot(
        name=name,
        callsign=callsign,
        license_level=current_ll,
        ll_clock_progress=current_progress,
        manna=total_manna,
        downtime=total_downtime,
        avatar_url=avatar_url,
        log_entries=log_entries,
        exotic_gear=exotic_gear,
    )
