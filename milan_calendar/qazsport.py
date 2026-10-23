"""Read Qazsport's public, dated Livewire snapshot; never infer web access."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

ALMATY = ZoneInfo("Asia/Almaty")
ROME = ZoneInfo("Europe/Rome")


class _Snapshots(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        value = dict(attrs).get("wire:snapshot")
        if value:
            self.values.append(value)


def parse_qazsport_epg(html: str, requested_date: date) -> list[dict[str, Any]]:
    """Fail closed if the server returned another day or changed its schema.

    The ordered broadcast day can cross midnight once. End times come from the
    next programme, never an invented duration.
    Only the timetable component (not currentProgram or navigation) is read.
    """
    parser = _Snapshots()
    parser.feed(html)
    rows: dict[datetime, dict[str, Any]] = {}
    for value in parser.values:
        try:
            snapshot = json.loads(value)
            memo, data = snapshot["memo"], snapshot["data"]
            if (memo.get("name") != "app.timetable.schedule"
                    or memo.get("path") not in {
                        f"kz/program/{requested_date}", f"ru/program/{requested_date}"}
                    or data.get("selectedDate") != requested_date.isoformat()):
                continue
            schedule, metadata = data["schedule"]
            if metadata.get("s") != "clctn" or not isinstance(schedule, list):
                continue
            day_rows: dict[datetime, dict[str, Any]] = {}
            civil_date = requested_date
            previous_clock = None
            for wrapped in schedule:
                row, row_metadata = wrapped
                if row_metadata.get("s") != "std":
                    raise ValueError("Unknown programme schema")
                clock = time.fromisoformat(row["time"])
                if clock.tzinfo is not None:
                    raise ValueError("Unexpected embedded timezone")
                if previous_clock is not None and clock < previous_clock:
                    if civil_date != requested_date or previous_clock.hour - clock.hour < 12:
                        raise ValueError("Unordered schedule")
                    civil_date += timedelta(days=1)
                previous_clock = clock
                start = datetime.combine(civil_date, clock, ALMATY)
                if start in day_rows:
                    raise ValueError("Ambiguous simultaneous programmes")
                day_rows[start] = {"title": str(row["title"]),
                    "description": str(row.get("description") or ""),
                    "live": row.get("format") == "LIVE", "start": start,
                    "schedule_date": requested_date.isoformat()}
            ordered = sorted(day_rows)
            for start, end in zip(ordered, ordered[1:]):
                row = {**day_rows[start], "end": end}
                if start in rows and rows[start] != row:
                    return []
                rows[start] = row
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return list(rows.values())


def _name(value: str) -> str:
    plain = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(t for t in re.findall(r"[^\W_]+", plain)
                    if t not in {"ac", "afc", "fc", "cf"})


def qazsport_fixture_start(row: dict[str, Any], event: dict[str, Any],
                          source: dict[str, Any], family: str) -> datetime | None:
    """Exact team-side aliases + explicit competition + live kickoff window."""
    if not row.get("live"):
        return None
    description = _name(row["description"])
    families = {key for key, terms in source.get("competition_terms", {}).items()
                if any(_name(term) in description for term in terms)}
    if families != {family}:
        return None
    # Strip country qualifiers only; youth/women/reserve qualifiers outside
    # parentheses remain part of the name and therefore cannot match seniors.
    title = row["title"]
    if re.search(r"\b(?:u\s*[-–]?\s*\d{2}|under\s*\d+|youth|women|жастар|әйелдер|женщины|юнош\w*|молод\w*)\b",
                 title, re.I):
        return None
    sides = re.split(r"\s*[-–—]\s*", re.sub(r"\([^()]*\)", "", title))
    if len(sides) != 2:
        return None
    aliases = source.get("team_aliases", {})

    def names(team: str) -> set[str]:
        values = {_name(team)}
        for canonical, localized in aliases.items():
            choices = {_name(canonical), *(_name(v) for v in localized)}
            if _name(team) in choices:
                values.update(choices)
        return values

    home, away = names(event["home_team"]), names(event["away_team"])
    left, right = map(_name, sides)
    if not ((left in home and right in away) or (right in home and left in away)):
        return None
    kickoff = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
    if kickoff.tzinfo is None:
        return None
    start, end = row["start"], row["end"]
    if (kickoff - timedelta(minutes=20) <= start <= kickoff + timedelta(minutes=10)
            and end >= kickoff + timedelta(minutes=75)):
        return start.astimezone(ROME)
    return None
