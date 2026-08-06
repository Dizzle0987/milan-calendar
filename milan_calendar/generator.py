from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from icalendar import Alarm, Calendar, Event
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")
MILAN_ALIASES = {"ac milan", "milan"}
OFFICIAL_URL = "https://www.acmilan.com/en/season/{season}/schedule/all"
ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/"
    "{competition}/teams/103/schedule?season={season}"
)
ESPN_COMPETITIONS = {
    "ita.1": "Serie A",
    "ita.coppa_italia": "Coppa Italia",
    "ita.super_cup": "Supercoppa Italiana",
    "uefa.champions": "UEFA Champions League",
    "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    "club.friendly": "Amichevole",
}


class UpdateError(RuntimeError):
    """Raised when every remote source fails and existing output must be kept."""


@dataclass
class FetchResult:
    events: list[dict[str, Any]]
    successful_sources: list[str]
    errors: list[str]


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "milan-calendar/1.0 (+https://github.com/Dizzle0987/milan-calendar)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
    )
    return session


def season_start(today: date) -> int:
    return today.year if today.month >= 7 else today.year - 1


def _normalize(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _competition_family(name: str) -> str:
    value = _normalize(name)
    mappings = (
        (("serie-a", "italian-serie-a"), "serie-a"),
        (("coppa-italia", "italian-coppa-italia"), "coppa-italia"),
        (("supercoppa", "italian-supercoppa"), "supercoppa-italiana"),
        (("champions",), "champions-league"),
        (("europa-conference", "conference-league"), "conference-league"),
        (("europa",), "europa-league"),
        (("friendly", "amichevole", "friendlies"), "amichevole"),
    )
    for needles, family in mappings:
        if any(needle in value for needle in needles):
            return family
    return value or "altra-competizione"


def _is_milan(team: str) -> bool:
    return _normalize(team).replace("-", " ") in MILAN_ALIASES


def _parse_flight_chunks(html: str) -> Iterable[str]:
    for script in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        marker = "self.__next_f.push("
        position = script.find(marker)
        if position < 0:
            continue
        raw = script[position + len(marker) :].strip()
        if raw.endswith(")"):
            raw = raw[:-1]
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if len(payload) > 1 and isinstance(payload[1], str):
            yield payload[1]


def parse_official_html(html: str, source_url: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    key = '"initialMatches":'
    for chunk in _parse_flight_chunks(html):
        cursor = 0
        while True:
            position = chunk.find(key, cursor)
            if position < 0:
                break
            start = chunk.find("[", position + len(key))
            if start < 0:
                break
            try:
                parsed, consumed = decoder.raw_decode(chunk[start:])
            except json.JSONDecodeError:
                cursor = position + len(key)
                continue
            if isinstance(parsed, list):
                matches.extend(item for item in parsed if isinstance(item, dict))
            cursor = start + consumed

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for match in matches:
        home = str((match.get("homeTeam") or {}).get("name") or "").strip()
        away = str((match.get("awayTeam") or {}).get("name") or "").strip()
        if not home or not away or not (_is_milan(home) or _is_milan(away)):
            continue
        source_id = str(match.get("providerId") or match.get("id") or "")
        if source_id and source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        raw_start = str(match.get("datetime") or "")
        if not raw_start:
            continue
        is_tbc = bool(str(match.get("datetimeTBC") or "").strip())
        parsed_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        competition = str((match.get("competition") or {}).get("name") or "Partita")
        events.append(
            {
                "source_id": source_id,
                "source": "AC Milan",
                "source_url": source_url,
                "home_team": home,
                "away_team": away,
                "competition": competition,
                "round": str(match.get("matchDay") or (match.get("stage") or {}).get("name") or ""),
                "venue": str(match.get("stadiumName") or ""),
                "start": parsed_start.astimezone(ROME).date().isoformat() if is_tbc else parsed_start.isoformat(),
                "all_day": is_tbc,
                "status": str(match.get("status") or "scheduled"),
            }
        )
    return events


def parse_espn_json(payload: dict[str, Any], default_competition: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in payload.get("events", []):
        competition_entry = ((item.get("competitions") or [{}])[0])
        competitors = competition_entry.get("competitors") or []
        home_entry = next((entry for entry in competitors if entry.get("homeAway") == "home"), None)
        away_entry = next((entry for entry in competitors if entry.get("homeAway") == "away"), None)
        if not home_entry or not away_entry:
            continue
        home = str((home_entry.get("team") or {}).get("displayName") or "").strip()
        away = str((away_entry.get("team") or {}).get("displayName") or "").strip()
        if not (_is_milan(home) or _is_milan(away)):
            continue
        raw_start = str(item.get("date") or "")
        if not raw_start:
            continue
        parsed_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        status_type = (item.get("status") or {}).get("type") or {}
        time_valid = status_type.get("detail") not in {"TBD", "TBA"}
        venue = (competition_entry.get("venue") or {}).get("fullName") or ""
        league = (item.get("league") or {}).get("name") or default_competition
        events.append(
            {
                "source_id": str(item.get("id") or ""),
                "source": "ESPN",
                "source_url": str((item.get("links") or [{}])[0].get("href") or "https://www.espn.com/soccer/team/fixtures/_/id/103/ac-milan"),
                "home_team": home,
                "away_team": away,
                "competition": str(league),
                "round": str(competition_entry.get("round") or ""),
                "venue": str(venue),
                "start": parsed_start.isoformat() if time_valid else parsed_start.astimezone(ROME).date().isoformat(),
                "all_day": not time_valid,
                "status": str(status_type.get("name") or "scheduled"),
            }
        )
    return events


def fetch_remote_events(session: requests.Session, today: date) -> FetchResult:
    events: list[dict[str, Any]] = []
    successful: list[str] = []
    errors: list[str] = []
    start_year = season_start(today)

    official_url = OFFICIAL_URL.format(season=start_year)
    try:
        response = session.get(official_url, timeout=30)
        response.raise_for_status()
        official_events = parse_official_html(response.text, official_url)
        if not official_events:
            raise ValueError("nessun evento valido nella risposta")
        events.extend(official_events)
        successful.append("AC Milan")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"AC Milan: {exc}")
        LOGGER.warning("Fonte ufficiale non disponibile: %s", exc)

    # ESPN labels a season by its ending year. Query both the active season and
    # the preceding label because summer friendlies may be attached to either.
    espn_ok = False
    for competition, default_name in ESPN_COMPETITIONS.items():
        for season in (start_year, start_year + 1):
            url = ESPN_URL.format(competition=competition, season=season)
            try:
                response = session.get(url, timeout=20)
                response.raise_for_status()
                payload = response.json()
                events.extend(parse_espn_json(payload, default_name))
                espn_ok = True
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"ESPN {competition}/{season}: {exc}")
    if espn_ok:
        successful.append("ESPN")

    return FetchResult(events=events, successful_sources=successful, errors=errors)


def _event_datetime(event: dict[str, Any]) -> datetime:
    raw = str(event["start"])
    if event.get("all_day"):
        return datetime.combine(date.fromisoformat(raw[:10]), time.min, tzinfo=ROME)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=ROME)


def _semantic_base(event: dict[str, Any]) -> str:
    start = _event_datetime(event).astimezone(ROME)
    active_season = start.year if start.month >= 7 else start.year - 1
    parts = (
        str(active_season),
        _normalize(str(event.get("home_team") or "")),
        _normalize(str(event.get("away_team") or "")),
        _competition_family(str(event.get("competition") or "")),
    )
    return "|".join(parts)


def _uid_for(event: dict[str, Any]) -> str:
    explicit = str(event.get("uid") or "").strip()
    if explicit:
        return explicit if "@" in explicit else f"{explicit}@milan-calendar"
    digest = hashlib.sha256(_semantic_base(event).encode()).hexdigest()[:24]
    return f"{digest}@milan-calendar"


def _same_fixture(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _normalize(str(left.get("home_team"))) != _normalize(str(right.get("home_team"))):
        return False
    if _normalize(str(left.get("away_team"))) != _normalize(str(right.get("away_team"))):
        return False
    if _competition_family(str(left.get("competition"))) != _competition_family(str(right.get("competition"))):
        return False
    return abs((_event_datetime(left) - _event_datetime(right)).total_seconds()) <= 60 * 60 * 48


def merge_remote_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    # Official data wins; ESPN still contributes competitions and friendlies
    # missing from the official page.
    priority = {"AC Milan": 0, "ESPN": 1}
    for candidate in sorted(events, key=lambda item: priority.get(str(item.get("source")), 9)):
        existing = next((event for event in merged if _same_fixture(event, candidate)), None)
        if existing is None:
            merged.append(deepcopy(candidate))
            continue
        for key, value in candidate.items():
            if not existing.get(key) and value:
                existing[key] = value
    return sorted(merged, key=_event_datetime)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_manual_events(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, [])
    events = payload.get("events", []) if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        raise ValueError("data/manual_events.json deve contenere una lista o un oggetto con 'events'")
    result: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"Evento manuale #{index + 1} non valido")
        required = {"home_team", "away_team", "competition", "start"}
        missing = sorted(required - event.keys())
        if missing:
            raise ValueError(f"Evento manuale #{index + 1}: campi mancanti: {', '.join(missing)}")
        normalized = deepcopy(event)
        normalized.setdefault("source", "Manuale")
        normalized.setdefault("source_url", "")
        normalized.setdefault("source_id", str(event.get("id") or f"manual-{index + 1}"))
        normalized.setdefault("round", "")
        normalized.setdefault("venue", "")
        normalized.setdefault("all_day", len(str(event["start"])) == 10)
        normalized.setdefault("status", "scheduled")
        result.append(normalized)
    return result


def _canonical_event(event: dict[str, Any], previous: list[dict[str, Any]], changed_at: str) -> dict[str, Any]:
    result = deepcopy(event)
    result["uid"] = _uid_for(result)
    result["home_away"] = "Casa" if _is_milan(str(result["home_team"])) else "Trasferta"
    result["title"] = f"{result['home_team']} - {result['away_team']}"
    comparable = {key: value for key, value in result.items() if key != "last_modified"}
    old = next((item for item in previous if item.get("uid") == result["uid"]), None)
    old_comparable = {key: value for key, value in (old or {}).items() if key != "last_modified"}
    result["last_modified"] = (
        str(old.get("last_modified")) if old and comparable == old_comparable else changed_at
    )
    return result


def merge_manual_events(remote: list[dict[str, Any]], manual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = deepcopy(remote)
    for candidate in manual:
        uid = _uid_for(candidate)
        existing_index = next(
            (index for index, event in enumerate(merged) if _uid_for(event) == uid or _same_fixture(event, candidate)),
            None,
        )
        if existing_index is None:
            merged.append(deepcopy(candidate))
        else:
            # Manual entries intentionally override fetched values.
            merged[existing_index].update(deepcopy(candidate))
    return sorted(merged, key=_event_datetime)


def build_ical(events: list[dict[str, Any]]) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Milan Calendar//Dizzle0987//IT")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "Milan Calendar")
    calendar.add("x-wr-timezone", "Europe/Rome")
    calendar.add("x-published-ttl", "PT6H")
    calendar.add("refresh-interval", "PT6H", parameters={"VALUE": "DURATION"})

    for data in events:
        component = Event()
        component.add("uid", data["uid"])
        component.add("summary", f"⚽ {data['title']}")
        start = _event_datetime(data).astimezone(ROME)
        if data.get("all_day"):
            component.add("dtstart", start.date())
            component.add("dtend", start.date() + timedelta(days=1))
        else:
            component.add("dtstart", start)
            component.add("dtend", start + timedelta(hours=2))
        modified = datetime.fromisoformat(str(data["last_modified"]).replace("Z", "+00:00"))
        component.add("dtstamp", modified.astimezone(timezone.utc))
        component.add("last-modified", modified.astimezone(timezone.utc))
        component.add("sequence", 0)
        if data.get("venue"):
            component.add("location", str(data["venue"]))
        if data.get("source_url"):
            component.add("url", str(data["source_url"]))
        details = [
            f"Competizione: {data['competition']}",
            f"Milan: {data['home_away']}",
        ]
        if data.get("round"):
            details.append(f"Turno: {data['round']}")
        if data.get("venue"):
            details.append(f"Stadio: {data['venue']}")
        if data.get("source_url"):
            details.append(f"Fonte: {data['source_url']}")
        component.add("description", "\n".join(details))
        component.add("categories", [str(data["competition"]), "AC Milan"])
        component.add("transp", "OPAQUE")
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"Tra 2 ore e 30 minuti: {data['title']}")
        alarm.add("trigger", timedelta(hours=-2, minutes=-30))
        component.add_component(alarm)
        calendar.add_component(component)
    return calendar.to_ical()


def _write_if_changed(path: Path, content: bytes) -> None:
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def update_calendar(root: Path, session: requests.Session | None = None, today: date | None = None) -> list[dict[str, Any]]:
    root = root.resolve()
    data_dir = root / "data"
    events_path = data_dir / "events.json"
    manual_path = data_dir / "manual_events.json"
    previous_payload = load_json(events_path, {"events": []})
    previous = previous_payload.get("events", []) if isinstance(previous_payload, dict) else []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    changed_at = now.isoformat().replace("+00:00", "Z")

    fetched = fetch_remote_events(session or build_session(), today or datetime.now(ROME).date())
    if not fetched.successful_sources or not fetched.events:
        raise UpdateError(
            "Nessuna fonte remota disponibile; calendar.ics e data/events.json sono rimasti invariati. "
            + "; ".join(fetched.errors[:3])
        )

    remote = merge_remote_events(fetched.events)
    manual = load_manual_events(manual_path)
    combined = merge_manual_events(remote, manual)
    canonical = [_canonical_event(event, previous, changed_at) for event in combined]

    old_without_meta = [{key: value for key, value in item.items() if key != "last_modified"} for item in previous]
    new_without_meta = [{key: value for key, value in item.items() if key != "last_modified"} for item in canonical]
    last_changed = (
        str(previous_payload.get("last_changed"))
        if isinstance(previous_payload, dict) and old_without_meta == new_without_meta and previous_payload.get("last_changed")
        else changed_at
    )
    payload = {
        "schema_version": 1,
        "timezone": "Europe/Rome",
        "last_changed": last_changed,
        "sources_used": fetched.successful_sources,
        "source_errors": fetched.errors,
        "event_count": len(canonical),
        "events": canonical,
    }
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    ical_bytes = build_ical(canonical)

    # Write only after every parsing and rendering step succeeds. A failed run
    # therefore cannot truncate or replace the last valid published calendar.
    _write_if_changed(events_path, json_bytes)
    _write_if_changed(root / "calendar.ics", ical_bytes)
    LOGGER.info("Generati %d eventi da %s", len(canonical), ", ".join(fetched.successful_sources))
    return canonical
