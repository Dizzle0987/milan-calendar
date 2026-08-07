from __future__ import annotations

import hashlib
import html as html_module
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
THESPORTSDB_URL = "https://www.thesportsdb.com/api/v1/json/123/eventsnext.php?id=133667"
NOW_MILAN_URL = "https://www.nowtv.it/sport/calcio/milan"
DAZN_SCHEDULE_URL = "https://www.dazn.com/it-IT/schedule"
GAZZETTA_FRIENDLIES_URL = (
    "https://www.gazzetta.it/Calcio/Serie-A/storie/01-07-2026/"
    "raduni-ritiri-e-amichevoli-delle-20-squadre-di-serie-a/milan.shtml"
)
TIME_SOURCE_PRIORITY = {
    "Gazzetta dello Sport": 10,
    "DAZN": 20,
    "NOW": 30,
}
ESPN_COMPETITIONS = {
    "ita.1": "Serie A",
    "ita.coppa_italia": "Coppa Italia",
    "ita.super_cup": "Supercoppa Italiana",
    "uefa.champions": "UEFA Champions League",
    "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    "club.friendly": "Amichevole",
}
BROADCASTERS_IT = {
    "serie-a": (
        "DAZN",
        "https://www.dazn.com/it-IT/help/articles/19177098524573-modello-di-organizzazione-gestione-e-controllo-modello-231",
    ),
    "coppa-italia": (
        "Mediaset (canali in chiaro), Mediaset Infinity e SportMediaset.it",
        "https://mediasetinfinity.mediaset.it/calcio-e-sport/coppaitaliacalcio_SE000000001529",
    ),
    "supercoppa-italiana": (
        "Mediaset (canali in chiaro), Mediaset Infinity e SportMediaset.it",
        "https://mediasetinfinity.mediaset.it/calcio-e-sport/supercoppaditaliacalcio_SE000000001643",
    ),
    "champions-league": (
        "Sky Sport/NOW; possibile esclusiva Prime Video da verificare",
        "https://sport.sky.it/calcio/champions-league/2025/11/20/champions-league-2027-2031-su-sky",
    ),
    "europa-league": (
        "Sky Sport e NOW",
        "https://sport.sky.it/calcio/champions-league/2025/11/20/champions-league-2027-2031-su-sky",
    ),
    "conference-league": (
        "Sky Sport e NOW",
        "https://sport.sky.it/calcio/champions-league/2025/11/20/champions-league-2027-2031-su-sky",
    ),
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


def _team_match_key(team: str) -> str:
    tokens = _normalize(team).split("-")
    ignored = {"afc", "cf", "fc", "football", "club"}
    return "-".join(token for token in tokens if token not in ignored)


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


def parse_thesportsdb_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in payload.get("events") or []:
        home = str(item.get("strHomeTeam") or "").strip()
        away = str(item.get("strAwayTeam") or "").strip()
        if not home or not away or not (_is_milan(home) or _is_milan(away)):
            continue

        raw_timestamp = str(item.get("strTimestamp") or "").strip()
        if raw_timestamp:
            parsed_start = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            if parsed_start.tzinfo is None:
                parsed_start = parsed_start.replace(tzinfo=timezone.utc)
            start = parsed_start.isoformat()
            all_day = False
        else:
            raw_date = str(item.get("dateEvent") or "").strip()
            if not raw_date:
                continue
            start = raw_date
            all_day = True

        event_id = str(item.get("idEvent") or "")
        events.append(
            {
                "source_id": event_id,
                "source": "TheSportsDB",
                "source_url": f"https://www.thesportsdb.com/event/{event_id}" if event_id else "https://www.thesportsdb.com/",
                "home_team": home,
                "away_team": away,
                "competition": str(item.get("strLeague") or "Partita"),
                "round": str(item.get("intRound") or ""),
                "venue": str(item.get("strVenue") or ""),
                "start": start,
                "all_day": all_day,
                "status": str(item.get("strStatus") or "scheduled"),
            }
        )
    return events


def _json_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _json_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_strings(child)


def parse_schedule_html(html: str, source: str, source_url: str, year: int) -> list[dict[str, Any]]:
    """Read explicit Milan kick-off times from structured broadcaster/editorial pages."""
    fragments: list[str] = []
    for raw in re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            fragments.extend(_json_strings(json.loads(html_module.unescape(raw))))
        except (json.JSONDecodeError, TypeError):
            continue

    # Some publishers embed the same structured copy in application state
    # rather than JSON-LD. Tags are removed only as a fallback; match parsing
    # still requires a full date, explicit time and both teams.
    fragments.append(html_module.unescape(re.sub(r"<[^>]+>", " ", html)))
    text = " ".join(re.sub(r"\s+", " ", item) for item in fragments)
    months = {
        "gennaio": 1,
        "febbraio": 2,
        "marzo": 3,
        "aprile": 4,
        "maggio": 5,
        "giugno": 6,
        "luglio": 7,
        "agosto": 8,
        "settembre": 9,
        "ottobre": 10,
        "novembre": 11,
        "dicembre": 12,
    }
    weekday = r"(?:lun(?:ed[iì])?|mar(?:ted[iì])?|mer(?:coled[iì])?|gio(?:ved[iì])?|ven(?:erd[iì])?|sab(?:ato)?|dom(?:enica)?)"
    date_then_match = re.compile(
        rf"(?:{weekday}\s+)?(?P<day>\d{{1,2}})\s+(?P<month>{'|'.join(months)})"
        r"\s*[,\-]?\s*(?:ore\s*)?(?P<hour>\d{1,2})[:.](?P<minute>\d{2})"
        r"\s*[-–:]\s*(?P<home>[A-Za-zÀ-ÿ .']+?)\s+(?:vs|[-–])\s+(?P<away>[A-Za-zÀ-ÿ .']+?)(?=[.;]|\s{2,}|$)",
        re.IGNORECASE,
    )
    match_then_date = re.compile(
        rf"(?P<home>[A-Za-zÀ-ÿ .']+?)\s+(?:vs|[-–])\s+(?P<away>[A-Za-zÀ-ÿ .']+?)"
        rf"\s*[:,\-]\s*(?:{weekday}\s+)?(?P<day>\d{{1,2}})\s+(?P<month>{'|'.join(months)})"
        r"\s*[,\-]?\s*(?:ore\s*)?(?P<hour>\d{1,2})[:.](?P<minute>\d{2})",
        re.IGNORECASE,
    )

    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for pattern in (date_then_match, match_then_date):
        for match in pattern.finditer(text):
            home = match.group("home").strip(" .,-–")
            away = match.group("away").strip(" .,-–")
            if not (_is_milan(home) or _is_milan(away)):
                continue
            month = months[match.group("month").lower()]
            start = datetime(
                year,
                month,
                int(match.group("day")),
                int(match.group("hour")),
                int(match.group("minute")),
                tzinfo=ROME,
            )
            key = (_team_match_key(home), _team_match_key(away), start.isoformat())
            if key in seen:
                continue
            seen.add(key)
            event = {
                "source_id": f"{_normalize(source)}-{start.date()}-{_team_match_key(home)}-{_team_match_key(away)}",
                "source": source,
                "source_url": source_url,
                "home_team": home,
                "away_team": away,
                "competition": "Amichevole",
                "round": "",
                "venue": "",
                "start": start.isoformat(),
                "all_day": False,
                "status": "scheduled",
                "_time_overlay": True,
                "_time_priority": TIME_SOURCE_PRIORITY.get(source, 0),
            }
            if source == "NOW":
                event.update(
                    {
                        "broadcast_it": "Sky Sport e NOW",
                        "broadcast_source_url": source_url,
                    }
                )
            elif source == "DAZN":
                event.update({"broadcast_it": "DAZN", "broadcast_source_url": source_url})
            events.append(event)
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

    try:
        response = session.get(THESPORTSDB_URL, timeout=20)
        response.raise_for_status()
        events.extend(parse_thesportsdb_json(response.json()))
        successful.append("TheSportsDB")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"TheSportsDB: {exc}")
        LOGGER.warning("Fonte TheSportsDB non disponibile: %s", exc)

    time_sources = (
        ("Gazzetta dello Sport", GAZZETTA_FRIENDLIES_URL),
        ("DAZN", DAZN_SCHEDULE_URL),
        ("NOW", NOW_MILAN_URL),
    )
    for source, url in time_sources:
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            schedule_events = parse_schedule_html(response.text, source, url, start_year)
            if not schedule_events:
                raise ValueError("nessun orario esplicito per il Milan")
            events.extend(schedule_events)
            successful.append(source)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{source}: {exc}")
            LOGGER.info("Fonte orari %s non disponibile: %s", source, exc)

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


def _add_italian_broadcaster(event: dict[str, Any]) -> None:
    if event.get("broadcast_it"):
        return
    broadcaster, source_url = BROADCASTERS_IT.get(
        _competition_family(str(event.get("competition") or "")),
        ("Da definire", ""),
    )
    event["broadcast_it"] = broadcaster
    event.setdefault("broadcast_source_url", source_url)


def _same_fixture(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _team_match_key(str(left.get("home_team"))) != _team_match_key(str(right.get("home_team"))):
        return False
    if _team_match_key(str(left.get("away_team"))) != _team_match_key(str(right.get("away_team"))):
        return False
    if _competition_family(str(left.get("competition"))) != _competition_family(str(right.get("competition"))):
        return False
    return abs((_event_datetime(left) - _event_datetime(right)).total_seconds()) <= 60 * 60 * 48


def _same_fixture_for_time(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_teams = sorted(
        (_team_match_key(str(left.get("home_team"))), _team_match_key(str(left.get("away_team"))))
    )
    right_teams = sorted(
        (_team_match_key(str(right.get("home_team"))), _team_match_key(str(right.get("away_team"))))
    )
    if left_teams != right_teams:
        return False
    return abs((_event_datetime(left) - _event_datetime(right)).total_seconds()) <= 60 * 60 * 48


def merge_remote_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = list(events)
    merged: list[dict[str, Any]] = []
    # Official data wins; ESPN still contributes competitions and friendlies
    # missing from the official page.
    priority = {"AC Milan": 0, "ESPN": 1, "TheSportsDB": 2}
    base_events = [event for event in candidates if not event.get("_time_overlay")]
    time_overlays = [event for event in candidates if event.get("_time_overlay")]
    for candidate in sorted(base_events, key=lambda item: priority.get(str(item.get("source")), 9)):
        existing = next((event for event in merged if _same_fixture(event, candidate)), None)
        if existing is None:
            merged.append(deepcopy(candidate))
            continue
        for key, value in candidate.items():
            if not existing.get(key) and value:
                existing[key] = value

    # Apply time-only sources after fixture discovery. Broadcasters can update
    # the kick-off and TV fields without replacing club metadata such as venue.
    for candidate in sorted(time_overlays, key=lambda item: int(item.get("_time_priority") or 0)):
        existing = next((event for event in merged if _same_fixture_for_time(event, candidate)), None)
        if existing is None:
            # Palinsesti ed articoli servono ad arricchire incontri già
            # scoperti dalle fonti sportive, non a creare nuove partite.
            continue
        existing["start"] = candidate["start"]
        existing["all_day"] = False
        existing["time_source"] = candidate["source"]
        existing["time_source_url"] = candidate["source_url"]
        if candidate.get("broadcast_it"):
            existing["broadcast_it"] = candidate["broadcast_it"]
            existing["broadcast_source_url"] = candidate.get("broadcast_source_url", "")
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
    result.pop("_time_overlay", None)
    result.pop("_time_priority", None)
    _add_italian_broadcaster(result)
    result["uid"] = _uid_for(result)
    result["home_away"] = "Casa" if _is_milan(str(result["home_team"])) else "Trasferta"
    result["title"] = f"{result['home_team']} - {result['away_team']}"
    comparable = {key: value for key, value in result.items() if key != "last_modified"}
    old = next((item for item in previous if item.get("uid") == result["uid"]), None)
    if old is None:
        old = next((item for item in previous if _same_fixture(item, result)), None)
        if old and old.get("uid"):
            result["uid"] = str(old["uid"])
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
        if data.get("broadcast_it"):
            details.append(f"Dove vederla in Italia: {data['broadcast_it']}")
        if data.get("broadcast_source_url"):
            details.append(f"Fonte TV: {data['broadcast_source_url']}")
        if data.get("time_source"):
            details.append(f"Fonte orario: {data['time_source']}")
        if data.get("time_source_url"):
            details.append(f"Link orario: {data['time_source_url']}")
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
