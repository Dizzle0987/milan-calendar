#!/usr/bin/env python3
"""Generate an iCalendar feed from AC Milan's official men's first-team schedule.

Primary source: https://www.acmilan.com/it/stagione/attiva/calendario/completo
Optional manual additions/overrides: data/manual_events.json

The parser first reads structured JSON/JSON-LD embedded in the official page. It is
intentionally defensive because the website can change its internal field names.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

SOURCE_URL = os.getenv(
    "MILAN_SCHEDULE_URL",
    "https://www.acmilan.com/it/stagione/attiva/calendario/completo",
)
OUT = Path(os.getenv("ICS_OUTPUT", "calendar.ics"))
CACHE = Path("data/events.json")
MANUAL = Path("data/manual_events.json")
TZ = ZoneInfo("Europe/Rome")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
MILAN_NAMES = {"milan", "ac milan", "a.c. milan", "acm"}

ITALIAN_MONTHS = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}
DATE_LINE_RE = re.compile(
    r"^(?:lun|mar|mer|gio|ven|sab|dom)\\.?\\s*(\\d{1,2})\\s+"
    r"(gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\\s*-\\s*"
    r"(\\d{1,2}):(\\d{2})(?:\\s+GMT[+-]\\d+)?$",
    re.IGNORECASE,
)


def clean_text_lines(soup: BeautifulSoup) -> list[str]:
    """Return visible text as compact one-value-per-line tokens."""
    lines: list[str] = []
    for raw in soup.get_text("\\n").splitlines():
        value = re.sub(r"\\s+", " ", raw).strip()
        if value:
            lines.append(value)
    return lines


def season_years(lines: list[str]) -> tuple[int, int]:
    for line in lines:
        m = re.search(r"Calendario e risultati AC Milan\\s+(20\\d{2})/(\\d{2})", line, re.I)
        if m:
            first = int(m.group(1))
            return first, first + 1
    now = datetime.now(TZ)
    first = now.year if now.month >= 7 else now.year - 1
    return first, first + 1


def looks_like_team(value: str) -> bool:
    low = value.lower()
    blocked = {
        "home", "away", "v", "acquista biglietti", "prossime partite",
        "tutti", "shop", "biglietti", "mymilan", "ricerca",
    }
    if low in blocked or len(value) < 2:
        return False
    if re.fullmatch(r"[A-Z]{2,4}", value):
        return False
    if "giornata" in low or low.startswith("serie ") or low.startswith("coppa "):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÿ]", value))


def parse_visible_schedule(soup: BeautifulSoup) -> list[Match]:
    """Fallback parser for the server-rendered official schedule cards."""
    lines = clean_text_lines(soup)
    season_start, season_end = season_years(lines)
    found: dict[str, Match] = {}

    for i, line in enumerate(lines):
        m = DATE_LINE_RE.match(line.lower())
        if not m:
            continue
        day, mon_name, hour, minute = m.groups()
        month = ITALIAN_MONTHS[mon_name.lower()]
        year = season_start if month >= 7 else season_end
        start = datetime(year, month, int(day), int(hour), int(minute), tzinfo=TZ)

        # One card normally ends at the next repeated date token.
        block: list[str] = []
        for candidate in lines[i + 1:i + 22]:
            if DATE_LINE_RE.match(candidate.lower()):
                break
            block.append(candidate)

        competition = "Partita"
        round_name = ""
        venue = ""
        for token in block:
            if " - " in token and any(word in token.lower() for word in (
                "serie", "coppa", "champions", "europa", "conference",
                "supercoppa", "amichevole", "friendly", "trofeo"
            )):
                parts = token.split(" - ", 1)
                competition = parts[0].strip()
                round_name = parts[1].strip() if len(parts) > 1 else ""
                break
            if any(word in token.lower() for word in (
                "serie a", "coppa italia", "champions league", "europa league",
                "conference league", "supercoppa", "amichevole", "friendly", "trofeo"
            )):
                competition = token.strip()

        for token in block:
            if any(word in token.lower() for word in ("stadio", "stadium", "arena")):
                venue = token
                break

        # Team names sit around HOME/AWAY and the standalone V separator.
        teams: list[str] = []
        for token in block:
            if looks_like_team(token) and token != venue and token != competition and token != round_name:
                teams.append(token)
        # Prefer a pair that includes Milan; remove common duplicate/noise values.
        pair: tuple[str, str] | None = None
        compact: list[str] = []
        for token in teams:
            if token not in compact:
                compact.append(token)
        for a, b in zip(compact, compact[1:]):
            if is_milan(a) or is_milan(b):
                pair = (a, b)
                break
        if not pair:
            continue
        home, away = pair
        stable = f"{start.date()}|{home.lower()}|{away.lower()}|{competition.lower()}"
        uid = "acmilan-" + hashlib.sha1(stable.encode("utf-8")).hexdigest()[:20]
        key = f"{start.isoformat()}|{home.lower()}|{away.lower()}"
        found[key] = Match(
            uid=uid, start=start, home=home, away=away,
            competition=competition, round_name=round_name,
            venue=venue, source_url=SOURCE_URL,
        )
    return sorted(found.values(), key=lambda match: match.start)



@dataclass(frozen=True)
class Match:
    uid: str
    start: datetime
    home: str
    away: str
    competition: str = "Partita"
    round_name: str = ""
    venue: str = ""
    city: str = ""
    status: str = "CONFIRMED"
    source_url: str = SOURCE_URL
    home_score: str | None = None
    away_score: str | None = None
    all_day: bool = False


def fetch_text(url: str, retries: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(req, timeout=45) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"Impossibile leggere la pagina ufficiale: {last}")


def norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("name", "title", "label", "value", "shortName", "displayName"):
            if value.get(key):
                return str(value[key]).strip()
        return ""
    return str(value).strip()


def is_milan(name: str) -> bool:
    cleaned = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return cleaned in MILAN_NAMES or cleaned.endswith(" milan") or cleaned.startswith("ac milan")


def first_value(obj: dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
            return lowered[key.lower()]
    return None


def parse_datetime(value: Any, obj: dict[str, Any]) -> tuple[datetime, bool] | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # milliseconds or seconds
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, timezone.utc).astimezone(TZ), False
    text = str(value).strip()
    try:
        dt = dateparser.parse(text)
    except (ValueError, OverflowError, TypeError):
        return None
    if dt is None:
        return None
    has_time = bool(re.search(r"(?:T|\s)\d{1,2}:\d{2}", text))
    if not has_time:
        separate_time = first_value(obj, ("time", "startTime", "kickoffTime", "hour"))
        if separate_time:
            m = re.search(r"(\d{1,2}):(\d{2})", str(separate_time))
            if m:
                dt = dt.replace(hour=int(m.group(1)), minute=int(m.group(2)))
                has_time = True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    else:
        dt = dt.astimezone(TZ)
    return dt, not has_time


def recursive_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from recursive_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_dicts(child)


def candidate_from_dict(obj: dict[str, Any]) -> Match | None:
    home_raw = first_value(obj, ("homeTeam", "home", "teamHome", "homeClub", "home_team"))
    away_raw = first_value(obj, ("awayTeam", "away", "teamAway", "awayClub", "away_team"))
    home, away = norm(home_raw), norm(away_raw)

    # Schema.org SportsEvent sometimes uses competitor array instead of home/away.
    if not home or not away:
        competitors = first_value(obj, ("competitor", "competitors", "teams", "participants"))
        if isinstance(competitors, list) and len(competitors) >= 2:
            home, away = norm(competitors[0]), norm(competitors[1])

    if not home or not away or not (is_milan(home) or is_milan(away)):
        return None

    raw_start = first_value(
        obj,
        (
            "startDate", "start", "startTime", "date", "datetime", "kickoff",
            "kickOff", "kickoffDate", "matchDate", "utcDate", "timestamp",
            "startTimestamp", "scheduledAt",
        ),
    )
    parsed = parse_datetime(raw_start, obj)
    if not parsed:
        return None
    start, all_day = parsed

    competition = norm(first_value(obj, ("competition", "tournament", "league", "category", "eventType"))) or "Partita"
    round_name = norm(first_value(obj, ("round", "roundName", "matchday", "stage", "phase")))
    venue_raw = first_value(obj, ("location", "venue", "stadium", "place"))
    venue, city = "", ""
    if isinstance(venue_raw, dict):
        venue = norm(venue_raw)
        address = venue_raw.get("address")
        if isinstance(address, dict):
            city = norm(first_value(address, ("addressLocality", "city", "locality")))
        city = city or norm(first_value(venue_raw, ("city", "addressLocality")))
    else:
        venue = norm(venue_raw)

    raw_id = first_value(obj, ("id", "eventId", "matchId", "slug", "url", "@id"))
    stable = str(raw_id or f"{start.isoformat()}|{home}|{away}|{competition}")
    uid = "acmilan-" + hashlib.sha1(stable.encode("utf-8")).hexdigest()[:20]
    source = norm(first_value(obj, ("url", "sourceUrl", "link"))) or SOURCE_URL
    status = norm(first_value(obj, ("status", "eventStatus", "matchStatus"))) or "CONFIRMED"
    home_score = norm(first_value(obj, ("homeScore", "scoreHome", "home_score"))) or None
    away_score = norm(first_value(obj, ("awayScore", "scoreAway", "away_score"))) or None
    return Match(
        uid=uid,
        start=start,
        home=home,
        away=away,
        competition=competition,
        round_name=round_name,
        venue=venue,
        city=city,
        status=status,
        source_url=source,
        home_score=home_score,
        away_score=away_score,
        all_day=all_day,
    )


def parse_official_page(html: str) -> list[Match]:
    soup = BeautifulSoup(html, "html.parser")
    matches: dict[str, Match] = {}

    # Structured JSON is the most stable extraction route.
    for script in soup.find_all("script"):
        raw = script.string or script.get_text("", strip=True)
        if not raw or len(raw) < 2:
            continue
        raw = raw.strip()
        candidates: list[Any] = []
        try:
            candidates.append(json.loads(raw))
        except json.JSONDecodeError:
            # Some frameworks embed a JSON object after an assignment.
            if "{" in raw and "}" in raw:
                piece = raw[raw.find("{"): raw.rfind("}") + 1]
                try:
                    candidates.append(json.loads(piece))
                except json.JSONDecodeError:
                    pass
        for data in candidates:
            for obj in recursive_dicts(data):
                match = candidate_from_dict(obj)
                if match:
                    key = f"{match.start.isoformat()}|{match.home.lower()}|{match.away.lower()}"
                    matches[key] = match

    structured = sorted(matches.values(), key=lambda m: m.start)
    if structured:
        return structured
    return parse_visible_schedule(soup)


def load_manual() -> list[Match]:
    if not MANUAL.exists():
        return []
    data = json.loads(MANUAL.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("data/manual_events.json deve contenere una lista JSON")
    result: list[Match] = []
    for i, obj in enumerate(data):
        if obj.get("enabled", True) is False:
            continue
        parsed = parse_datetime(obj.get("start"), obj)
        if not parsed:
            raise RuntimeError(f"Evento manuale #{i + 1}: data non valida")
        start, all_day = parsed
        home, away = str(obj["home"]).strip(), str(obj["away"]).strip()
        stable = str(obj.get("uid") or f"manual|{start.isoformat()}|{home}|{away}")
        uid = "acmilan-" + hashlib.sha1(stable.encode()).hexdigest()[:20]
        result.append(Match(
            uid=uid,
            start=start,
            home=home,
            away=away,
            competition=str(obj.get("competition", "Amichevole")),
            round_name=str(obj.get("round_name", "")),
            venue=str(obj.get("venue", "")),
            city=str(obj.get("city", "")),
            status=str(obj.get("status", "CONFIRMED")),
            source_url=str(obj.get("source_url", SOURCE_URL)),
            all_day=bool(obj.get("all_day", all_day)),
        ))
    return result


def merge_matches(official: list[Match], manual: list[Match]) -> list[Match]:
    merged: dict[str, Match] = {}
    for match in official + manual:
        # Manual event replaces an official event with same date and opponents.
        key = f"{match.start.date()}|{match.home.lower()}|{match.away.lower()}"
        merged[key] = match
    return sorted(merged.values(), key=lambda m: m.start)


def esc(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;")
                 .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str, limit: int = 73) -> str:
    chunks: list[str] = []
    current = ""
    for char in line:
        if len((current + char).encode("utf-8")) > limit and current:
            chunks.append(current)
            current = " " + char
        else:
            current += char
    chunks.append(current)
    return "\r\n".join(chunks)


def event_lines(match: Match, generated: datetime) -> list[str]:
    summary = f"🔴⚫ {match.home} - {match.away}"
    result = ""
    if match.home_score is not None and match.away_score is not None:
        result = f"Risultato: {match.home_score}-{match.away_score}"
    description = [match.competition]
    if match.round_name:
        description.append(match.round_name)
    if result:
        description.append(result)
    description.extend([
        "Calendario automatico non ufficiale.",
        f"Fonte: {match.source_url}",
    ])
    location = ", ".join(x for x in (match.venue, match.city) if x)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{match.uid}@milan-calendar",
        f"DTSTAMP:{generated.strftime('%Y%m%dT%H%M%SZ')}",
    ]
    if match.all_day:
        lines.extend([
            f"DTSTART;VALUE=DATE:{match.start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(match.start + timedelta(days=1)).strftime('%Y%m%d')}",
            "TRANSP:TRANSPARENT",
        ])
    else:
        end = match.start + timedelta(hours=2)
        lines.extend([
            f"DTSTART;TZID=Europe/Rome:{match.start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Rome:{end.strftime('%Y%m%dT%H%M%S')}",
        ])
    lines.extend([
        f"SUMMARY:{esc(summary)}",
        f"CATEGORIES:{esc(match.competition)}",
        f"DESCRIPTION:{esc(chr(10).join(description))}",
        f"LOCATION:{esc(location)}" if location else "LOCATION:",
        f"URL:{match.source_url}",
        "STATUS:CONFIRMED",
    ])
    if not match.all_day:
        lines.extend([
            "BEGIN:VALARM", "TRIGGER:-PT2H", "ACTION:DISPLAY",
            "DESCRIPTION:Il Milan gioca tra 2 ore", "END:VALARM",
            "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY",
            "DESCRIPTION:Il Milan gioca tra 30 minuti", "END:VALARM",
        ])
    lines.append("END:VEVENT")
    return lines


def build_calendar(matches: list[Match]) -> str:
    generated = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Patric//Calendario AC Milan//IT",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:AC Milan - Tutte le partite",
        "X-WR-CALDESC:Prima Squadra maschile: campionato, coppe e amichevoli",
        "X-WR-TIMEZONE:Europe/Rome",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    for match in matches:
        lines.extend(event_lines(match, generated))
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def main() -> int:
    try:
        html = fetch_text(SOURCE_URL)
        official = parse_official_page(html)
        manual = load_manual()
        matches = merge_matches(official, manual)
        if not matches:
            raise RuntimeError(
                "Nessuna partita trovata. Il calendario esistente non viene sovrascritto. "
                "Il sito ufficiale potrebbe avere cambiato struttura."
            )
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps([
            {
                "uid": m.uid, "start": m.start.isoformat(), "home": m.home,
                "away": m.away, "competition": m.competition,
                "round_name": m.round_name, "venue": m.venue, "city": m.city,
                "source_url": m.source_url, "all_day": m.all_day,
            } for m in matches
        ], ensure_ascii=False, indent=2), encoding="utf-8")
        content = build_calendar(matches)
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        OUT.write_text(content, encoding="utf-8", newline="")
        digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        print(
            f"Creato {OUT}: {len(matches)} partite "
            f"({len(official)} ufficiali, {len(manual)} manuali), "
            f"sha256={digest}, modificato={old != content}"
        )
        return 0
    except Exception as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
