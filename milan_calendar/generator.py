from __future__ import annotations

import hashlib
import html as html_module
import json
import logging
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode, urljoin
from zoneinfo import ZoneInfo

import requests
from icalendar import Alarm, Calendar, Event
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")
MILAN_ALIASES = {"ac milan", "milan", "milan fc"}
EXCLUDED_SQUADS = (
    "women", "femminile", "primavera", "next gen", "futuro",
    "under 23", "u23", "under 20", "u20", "under 19", "u19",
)
TEAM_EQUIVALENTS = {
    "internazionale": "inter",
    "inter-milan": "inter",
    "manchester-utd": "manchester-united",
    "man-utd": "manchester-united",
    "psg": "paris-saint-germain",
}
OFFICIAL_URL = "https://www.acmilan.com/en/season/{season}/schedule/all"
ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/"
    "{competition}/teams/103/schedule?season={season}"
)
ESPN_STANDINGS_URL = (
    "https://site.api.espn.com/apis/v2/sports/soccer/ita.1/standings?season={season}"
)
ESPN_SERIE_A_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/scoreboard"
    "?dates={start_date}-{end_date}&limit=1000"
)
LEGA_STANDINGS_PAGE_URL = "https://www.legaseriea.it/serie-a/classifica"
LEGA_SDP_BASE_URL = "https://api-sdp.legaseriea.it/v1/serie-a/football"
LEGA_SERIE_A_COMPETITION_ID = (
    "serie-a::Football_Competition::ec93b94f74294dc98ab5bcfd67fc0d88"
)
UEFA_DRAW_URLS = {
    "champions-league": (
        "UEFA Champions League",
        "https://www.uefa.com/uefachampionsleague/draws/",
    ),
    "europa-league": (
        "UEFA Europa League",
        "https://www.uefa.com/uefaeuropaleague/draws/",
    ),
    "conference-league": (
        "UEFA Conference League",
        "https://www.uefa.com/uefaconferenceleague/draws/",
    ),
}
THESPORTSDB_URL = "https://www.thesportsdb.com/api/v1/json/123/eventsnext.php?id=133667"
NOW_MILAN_URL = "https://www.nowtv.it/sport/calcio/milan"
DAZN_SCHEDULE_URL = "https://www.dazn.com/it-IT/schedule"
GAZZETTA_FRIENDLIES_URL = (
    "https://www.gazzetta.it/Calcio/Serie-A/Milan/"
)
SKY_SERIE_A_URL = "https://sport.sky.it/calcio/serie-a"
MEDIASET_SPORT_URL = "https://mediasetinfinity.mediaset.it/sport"
PRIME_SPORT_URL = "https://www.primevideo.com/sports"
LEGA_NEWS_URL = "https://www.legaseriea.it/serie-a/news"
TIME_SOURCE_PRIORITY = {
    "AC Milan": 10,
    "Gazzetta dello Sport": 20,
    "DAZN": 60,
    "Sky Sport": 40,
    "Mediaset": 40,
    "Prime Video": 40,
    "NOW": 50,
}
ESPN_COMPETITIONS = {
    "ita.1": "Serie A",
    "ita.2": "Serie B",
    "ita.coppa_italia": "Coppa Italia",
    "ita.super_cup": "Supercoppa Italiana",
    "uefa.champions": "UEFA Champions League",
    "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League",
    "uefa.super_cup": "Supercoppa UEFA",
    "fifa.cwc": "Coppa del Mondo per Club FIFA",
    "fifa.intercontinental_cup": "Coppa Intercontinentale FIFA",
    "global.club_challenge": "UEFA-CONMEBOL Club Challenge",
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
INTERNATIONAL_COMPETITION_FAMILIES = {
    "champions-league",
    "europa-league",
    "conference-league",
    "supercoppa-uefa",
    "coppa-mondo-club-fifa",
    "coppa-intercontinentale-fifa",
    "uefa-conmebol-club-challenge",
}
BROADCAST_EVIDENCE_MARKERS = {
    "diretta", "live", "streaming", "tv", "televisione", "canale",
    "channel", "watch", "guarda", "vederla", "palinsesto", "programma",
    "programmazione", "broadcast", "ubertragung", "transmissao", "ao-vivo",
}
BROADCAST_GUIDE_HORIZON_DAYS = 21
TV8_PROGRAMMING_API = "https://www.tv8.it/api/programmingCarousel"
MONTH_NAMES = {
    1: ("gennaio", "january", "januar", "janvier", "enero", "janeiro"),
    2: ("febbraio", "february", "februar", "fevrier", "febrero", "fevereiro"),
    3: ("marzo", "march", "marz", "mars", "marzo", "marco"),
    4: ("aprile", "april", "avril", "abril"),
    5: ("maggio", "may", "mai", "mayo", "maio"),
    6: ("giugno", "june", "juni", "juin", "junio", "junho"),
    7: ("luglio", "july", "juli", "juillet", "julio", "julho"),
    8: ("agosto", "august", "aout", "agosto"),
    9: ("settembre", "september", "septembre", "septiembre", "setembro"),
    10: ("ottobre", "october", "oktober", "octobre", "octubre", "outubro"),
    11: ("novembre", "november", "noviembre"),
    12: ("dicembre", "december", "dezember", "decembre", "diciembre", "dezembro"),
}


class UpdateError(RuntimeError):
    """Raised when every remote source fails and existing output must be kept."""


@dataclass
class FetchResult:
    events: list[dict[str, Any]]
    successful_sources: list[str]
    errors: list[str]
    serie_a_standing: dict[str, Any] | None = None
    calendar_events: list[dict[str, Any]] | None = None


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
        (("serie-b", "italian-serie-b"), "serie-b"),
        (("coppa-italia", "italian-coppa-italia"), "coppa-italia"),
        (("supercoppa", "italian-supercoppa"), "supercoppa-italiana"),
        (("champions",), "champions-league"),
        (("europa-conference", "conference-league"), "conference-league"),
        (("europa",), "europa-league"),
        (("uefa-super-cup", "supercoppa-uefa"), "supercoppa-uefa"),
        (("club-world-cup", "coppa-del-mondo-per-club"), "coppa-mondo-club-fifa"),
        (("intercontinental",), "coppa-intercontinentale-fifa"),
        (("club-challenge",), "uefa-conmebol-club-challenge"),
        (("friendly", "amichevole", "friendlies"), "amichevole"),
    )
    for needles, family in mappings:
        if any(needle in value for needle in needles):
            return family
    return value or "altra-competizione"


def _is_milan(team: str) -> bool:
    return _normalize(team).replace("-", " ") in MILAN_ALIASES


def _team_match_key(team: str) -> str:
    if _is_milan(team):
        return "milan"
    tokens = _normalize(team).split("-")
    ignored = {"afc", "cf", "fc", "football", "club"}
    key = "-".join(token for token in tokens if token not in ignored)
    return TEAM_EQUIVALENTS.get(key, key)


def _is_official_international_match(event: dict[str, Any]) -> bool:
    if str(event.get("event_kind") or "match") != "match":
        return False
    searchable = _normalize(
        " ".join(
            str(event.get(key) or "")
            for key in ("competition", "round", "title", "organizer", "source_url")
        )
    )
    if any(marker in searchable for marker in ("friendly", "friendlies", "amichevole", "tournee", "pre-season")):
        return False
    family = _competition_family(str(event.get("competition") or ""))
    if family in INTERNATIONAL_COMPETITION_FAMILIES:
        return True
    if family in {"serie-a", "serie-b", "coppa-italia", "supercoppa-italiana", "amichevole"}:
        return False
    return any(
        marker in searchable
        for marker in ("uefa", "fifa", "conmebol", "intercontinental", "international-club", "world-club")
    )


def load_broadcast_sources(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, {"sources": []})
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    if not isinstance(sources, list):
        raise ValueError("data/broadcast_sources.json deve contenere una lista 'sources'")
    required = {"country", "country_code", "broadcaster", "access", "url"}
    normalized: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or required - source.keys():
            raise ValueError(f"Fonte broadcast #{index + 1} non valida")
        if source.get("access") not in {"free", "included", "paid"}:
            raise ValueError(f"Fonte broadcast #{index + 1}: access non valido")
        normalized.append(deepcopy(source))
    return normalized


def _fixture_date_markers(
    value: datetime, timezone_name: str = "Europe/Rome"
) -> set[str]:
    try:
        local = value.astimezone(ZoneInfo(timezone_name))
    except (KeyError, ValueError):
        local = value.astimezone(ROME)
    markers = {
        local.strftime("%Y-%m-%d"),
        local.strftime("%Y%m%d"),
        local.strftime("%d-%m-%Y"),
        local.strftime("%d-%m"),
        local.strftime("%d.%m.%Y"),
        local.strftime("%d/%m/%Y"),
    }
    for month in MONTH_NAMES[local.month]:
        markers.add(_normalize(f"{local.day} {month} {local.year}"))
        markers.add(_normalize(f"{local.day} {month}"))
    return markers


def page_confirms_fixture(
    html: str,
    event: dict[str, Any],
    broadcaster: str,
    timezone_name: str = "Europe/Rome",
) -> bool:
    """Require teams, exact date and viewing language in one nearby page fragment."""
    text = _normalize(html_module.unescape(re.sub(r"<[^>]+>", " ", html)))
    opponent = (
        str(event.get("away_team") or "")
        if _is_milan(str(event.get("home_team") or ""))
        else str(event.get("home_team") or "")
    )
    opponent_key = _team_match_key(opponent)
    opponent_tokens = [
        token for token in opponent_key.split("-") if len(token) >= 4 and token not in {"club", "calcio"}
    ]
    if not opponent_tokens:
        return False
    anchor = max(opponent_tokens, key=len)
    date_markers = _fixture_date_markers(_event_datetime(event), timezone_name)
    broadcaster_marker = _normalize(broadcaster)
    for match in re.finditer(re.escape(anchor), text):
        window = text[max(0, match.start() - 900) : match.end() + 900]
        if "milan" not in window or not any(marker in window for marker in date_markers):
            continue
        has_viewing_evidence = any(marker in window for marker in BROADCAST_EVIDENCE_MARKERS)
        distinctive_broadcaster_tokens = [
            token
            for token in broadcaster_marker.split("-")
            if len(token) >= 3 and token not in {"sport", "sports", "video", "tv", "play"}
        ]
        if has_viewing_evidence and (
            broadcaster_marker in window
            or any(token in window for token in distinctive_broadcaster_tokens)
        ):
            return True
    return False


def parse_servus_epg(html: str) -> list[dict[str, Any]]:
    """Extract the official server-rendered ServusTV EPG cards."""
    pattern = re.compile(
        r'\\"title\\":\\"(?P<title>(?:[^\\]|\\.)*?)\\"(?:(?!\},\{).)*?'
        r'\\"start_time\\":\\"(?P<start>[^\\"]+)\\"(?:(?!\},\{).)*?'
        r'\\"end_time\\":\\"(?P<end>[^\\"]+)\\"',
        re.DOTALL,
    )
    rows: list[dict[str, Any]] = []
    for match in pattern.finditer(html):
        try:
            title = json.loads('"' + match["title"] + '"')
        except json.JSONDecodeError:
            title = html_module.unescape(match["title"].replace('\\"', '"'))
        rows.append(
            {"title": title, "start": match["start"], "end": match["end"]}
        )
    return rows


def parse_tv8_epg(payload: dict[str, Any], event_date: date) -> list[dict[str, Any]]:
    """Normalise TV8's structured schedule into dated programme intervals."""
    rows: list[dict[str, Any]] = []
    range_pattern = re.compile(r"^(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})$")
    for programme in payload.get("programs") or []:
        badge = str(
            ((programme.get("badge") or {}).get("label") or {}).get("text") or ""
        )
        match = range_pattern.match(badge)
        if not match:
            continue
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        start = datetime.combine(event_date, time(start_hour, start_minute), ROME)
        end = datetime.combine(event_date, time(end_hour, end_minute), ROME)
        if end <= start:
            end += timedelta(days=1)
        title = str(((programme.get("title") or {}).get("text")) or "")
        description = str(((programme.get("description") or {}).get("text")) or "")
        rows.append(
            {
                "title": " ".join((title, description)).strip(),
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
    return rows


def _programme_confirms_fixture(
    programme: dict[str, Any], event: dict[str, Any]
) -> datetime | None:
    """Accept only a live-sized EPG block containing both clubs around kick-off."""
    title = _normalize(str(programme.get("title") or ""))
    if "milan" not in title:
        return None
    opponent = (
        str(event.get("away_team") or "")
        if _is_milan(str(event.get("home_team") or ""))
        else str(event.get("home_team") or "")
    )
    opponent_tokens = {
        token
        for token in _team_match_key(opponent).split("-")
        if len(token) >= 4 and token not in {"club", "calcio"}
    }
    if not opponent_tokens or not any(token in title for token in opponent_tokens):
        return None
    try:
        programme_start = datetime.fromisoformat(
            str(programme["start"]).replace("Z", "+00:00")
        ).astimezone(ROME)
        programme_end = datetime.fromisoformat(
            str(programme["end"]).replace("Z", "+00:00")
        ).astimezone(ROME)
    except (KeyError, TypeError, ValueError):
        return None
    kick_off = _event_datetime(event).astimezone(ROME)
    if programme_start.date() != kick_off.date():
        return None
    if not kick_off - timedelta(hours=2) <= programme_start <= kick_off + timedelta(minutes=10):
        return None
    # Requiring a long block rejects news, previews and highlights near kick-off.
    if programme_end < kick_off + timedelta(minutes=75):
        return None
    return programme_start


def _fixture_source_url(source: dict[str, Any], event: dict[str, Any]) -> str:
    family = _competition_family(str(event.get("competition") or ""))
    templates = source.get("url_templates") or {}
    template = str(templates.get(family) or source.get("url_template") or source["url"])
    values = {
        "home": _normalize(str(event.get("home_team") or "")),
        "away": _normalize(str(event.get("away_team") or "")),
    }
    return template.format(**values)


def _source_with_page_channels(source: dict[str, Any], html: str) -> dict[str, Any]:
    """Refine a confirmed source with channels explicitly named on its page."""
    if str(source.get("country_code") or "").upper() != "IT":
        return source
    visible = html_module.unescape(re.sub(r"<[^>]+>", " ", html))
    channels = list(
        dict.fromkeys(
            match.group(0)
            for match in re.finditer(
                r"Sky Sport(?: Uno| Calcio| Arena| Football| 4K| \d{3})",
                visible,
                re.IGNORECASE,
            )
        )
    )
    if "sky go" in visible.lower():
        channels.append("Sky Go")
    if not channels:
        return source
    refined = deepcopy(source)
    refined["broadcaster"] = " / ".join(channels)
    return refined


def _broadcast_option(
    source: dict[str, Any],
    checked_at: str,
    *,
    source_url: str | None = None,
    programme_start: datetime | None = None,
) -> dict[str, Any]:
    option = {
        "country": str(source["country"]),
        "country_code": str(source["country_code"]).upper(),
        "broadcaster": str(source["broadcaster"]),
        "access": str(source["access"]),
        "platforms": str(source.get("platforms") or "streaming"),
        "language": str(source.get("language") or ""),
        "registration_required": bool(source.get("registration_required")),
        "url": str(source.get("public_url") or source_url or source["url"]),
        "source_url": str(source_url or source["url"]),
        "status": "confirmed",
        "broadcast_type": "diretta",
        "verified_at": checked_at,
        "priority": int(source.get("priority") or 0),
    }
    if source.get("replaces_broadcasters"):
        option["_replaces_broadcasters"] = [
            _normalize(str(value)) for value in source["replaces_broadcasters"]
        ]
    if programme_start is not None:
        option["broadcast_start"] = programme_start.astimezone(ROME).isoformat()
        option["broadcast_start_rome"] = programme_start.astimezone(ROME).strftime("%H:%M")
    return option


def _fetch_epg_rows(
    requester: Any,
    source: dict[str, Any],
    relevant: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    source_type = str(source.get("source_type") or "page")
    url = str(source.get("endpoint") or source["url"])
    if source_type == "servus_epg":
        response = requester.get(url, timeout=10)
        response.raise_for_status()
        return parse_servus_epg(response.text), url
    if source_type == "tv8_api":
        rows: list[dict[str, Any]] = []
        for event_date in sorted({_event_datetime(event).astimezone(ROME).date() for event in relevant}):
            local_start = datetime.combine(event_date, time.min, ROME)
            local_end = datetime.combine(event_date, time.max, ROME)
            query = urlencode(
                {
                    "from": local_start.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "to": local_end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                }
            )
            response = requester.get(f"{url}?{query}", timeout=10)
            response.raise_for_status()
            rows.extend(parse_tv8_epg(response.json(), event_date))
        return rows, str(source.get("public_url") or source["url"])
    raise ValueError(f"tipo palinsesto non supportato: {source_type}")


def apply_verified_broadcasts(
    session: requests.Session,
    events: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    checked_at: str,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Verify exact fixtures and preserve previously confirmed options on failures."""
    result = deepcopy(events)
    targets = [
        event
        for event in result
        if _is_official_international_match(event)
        and _event_datetime(event).astimezone(timezone.utc) > now.astimezone(timezone.utc)
        and _normalize(str(event.get("status") or ""))
        not in {"played", "final", "full-time", "ft", "completed", "status-final"}
    ]
    errors: list[str] = []
    confirmations: dict[str, list[dict[str, Any]]] = {}
    optional_session: requests.Session | None = None
    requester: Any = session
    if isinstance(session, requests.Session):
        optional_session = requests.Session()
        optional_session.headers.update(session.headers)
        requester = optional_session
    try:
        for source in sources:
            keywords = {_normalize(str(item)) for item in source.get("team_keywords") or []}
            competition_families = {
                _normalize(str(item)) for item in source.get("competition_families") or []
            }
            horizon = int(source.get("lookahead_days") or BROADCAST_GUIDE_HORIZON_DAYS)
            relevant = [
                event
                for event in targets
                if _event_datetime(event).astimezone(ROME).date()
                <= now.astimezone(ROME).date() + timedelta(days=horizon)
                and int(source.get("rights_from_season") or 0)
                <= season_start(_event_datetime(event).astimezone(ROME).date())
                and int(source.get("rights_through_season") or 9999)
                >= season_start(_event_datetime(event).astimezone(ROME).date())
                and (
                    not competition_families
                    or _competition_family(str(event.get("competition") or ""))
                    in competition_families
                )
                and (
                    str(source.get("country_code") or "").upper() == "IT"
                    or not keywords
                    or any(
                        keyword in _team_match_key(str(event.get(key) or ""))
                        for keyword in keywords
                        for key in ("home_team", "away_team")
                    )
                )
            ]
            if not relevant:
                continue
            source_type = str(source.get("source_type") or "page")
            if source_type in {"servus_epg", "tv8_api"}:
                try:
                    programmes, guide_url = _fetch_epg_rows(requester, source, relevant)
                except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                    errors.append(f"{source['broadcaster']}: {exc}")
                    continue
                for event in relevant:
                    starts = [
                        start
                        for programme in programmes
                        if (start := _programme_confirms_fixture(programme, event))
                    ]
                    if starts:
                        confirmations.setdefault(_semantic_base(event), []).append(
                            _broadcast_option(
                                source,
                                checked_at,
                                source_url=guide_url,
                                programme_start=min(starts),
                            )
                        )
                continue

            for event in relevant:
                url = _fixture_source_url(source, event)
                try:
                    response = requester.get(url, timeout=10)
                    response.raise_for_status()
                except requests.RequestException as exc:
                    errors.append(f"{source['broadcaster']} ({event.get('title')}): {exc}")
                    continue
                if page_confirms_fixture(
                    response.text,
                    event,
                    str(source["broadcaster"]),
                    str(source.get("timezone") or "Europe/Rome"),
                ):
                    confirmations.setdefault(_semantic_base(event), []).append(
                        _broadcast_option(
                            _source_with_page_channels(source, response.text),
                            checked_at,
                            source_url=url,
                        )
                    )
    finally:
        if optional_session is not None:
            optional_session.close()

    access_order = {"free": 0, "included": 1, "paid": 2}
    for event in result:
        if not _is_official_international_match(event):
            continue
        old = next(
            (item for item in previous if _same_long_range_fixture(item, event)), None
        ) or next(
            (item for item in previous if _same_fixture(item, event, unordered=True)), None
        )
        old_options = deepcopy((old or {}).get("broadcast_options") or [])
        if _event_datetime(event).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
            if old_options:
                event["broadcast_options"] = old_options
                event["broadcast_international_tbc"] = bool(
                    (old or {}).get("broadcast_international_tbc")
                )
            continue
        merged: dict[tuple[str, str], dict[str, Any]] = {
            (str(option.get("country_code") or ""), _normalize(str(option.get("broadcaster") or ""))): option
            for option in old_options
            if option.get("status") == "confirmed"
        }
        for option in confirmations.get(_semantic_base(event), []):
            replacements = set(option.pop("_replaces_broadcasters", []))
            if replacements:
                merged = {
                    key: value
                    for key, value in merged.items()
                    if not (
                        key[0] == str(option["country_code"])
                        and _normalize(str(value.get("broadcaster") or "")) in replacements
                    )
                }
            key = (str(option["country_code"]), _normalize(str(option["broadcaster"])))
            previous_option = merged.get(key)
            if previous_option:
                comparable_old = {k: v for k, v in previous_option.items() if k != "verified_at"}
                comparable_new = {k: v for k, v in option.items() if k != "verified_at"}
                if comparable_old == comparable_new:
                    option["verified_at"] = str(previous_option.get("verified_at") or checked_at)
            merged[key] = option
        options = list(merged.values())
        italian = sorted(
            (option for option in options if option.get("country_code") == "IT"),
            key=lambda option: (access_order.get(str(option.get("access")), 9), -int(option.get("priority") or 0)),
        )
        foreign = sorted(
            (option for option in options if option.get("country_code") != "IT"),
            key=lambda option: (
                access_order.get(str(option.get("access")), 9),
                -int(option.get("priority") or 0),
            ),
        )[:3]
        event["broadcast_options"] = italian + foreign
        event["broadcast_international_tbc"] = not bool(foreign)
        event["broadcast_italy_tbc"] = not bool(italian)
    return result, errors


def _valid_first_team_fixture(home: str, away: str, *labels: str) -> bool:
    combined = " ".join((home, away, *labels)).lower()
    return (_is_milan(home) or _is_milan(away)) and not any(
        marker in combined for marker in EXCLUDED_SQUADS
    )


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
        if not home or not away or not _valid_first_team_fixture(
            home,
            away,
            str(match.get("teamCategory") or ""),
            str(match.get("category") or ""),
            str((match.get("competition") or {}).get("name") or ""),
        ):
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
                "location": str(match.get("stadiumCity") or match.get("city") or ""),
                "neutral": bool(match.get("neutralVenue") or match.get("isNeutralVenue")),
                "start": parsed_start.astimezone(ROME).date().isoformat() if is_tbc else parsed_start.isoformat(),
                "all_day": is_tbc,
                "status": str(match.get("status") or "scheduled"),
                "time_source": "" if is_tbc else "AC Milan",
                "time_source_url": "" if is_tbc else source_url,
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
        raw_start = str(item.get("date") or "")
        if not raw_start:
            continue
        parsed_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        status_type = (item.get("status") or {}).get("type") or {}
        time_valid = status_type.get("detail") not in {"TBD", "TBA"}
        venue = (competition_entry.get("venue") or {}).get("fullName") or ""
        league = (item.get("league") or {}).get("name") or default_competition
        if not _valid_first_team_fixture(home, away, str(league)):
            continue
        address = (competition_entry.get("venue") or {}).get("address") or {}
        event_url = str(
            (item.get("links") or [{}])[0].get("href")
            or "https://www.espn.com/soccer/team/fixtures/_/id/103/ac-milan"
        )
        events.append(
            {
                "source_id": str(item.get("id") or ""),
                "source": "ESPN",
                "source_url": event_url,
                "home_team": home,
                "away_team": away,
                "competition": str(league),
                "round": str(competition_entry.get("round") or ""),
                "venue": str(venue),
                "location": str(address.get("city") or ""),
                "neutral": bool(competition_entry.get("neutralSite")),
                "start": parsed_start.isoformat() if time_valid else parsed_start.astimezone(ROME).date().isoformat(),
                "all_day": not time_valid,
                "status": str(status_type.get("name") or "scheduled"),
                "time_source": "ESPN" if time_valid else "",
                "time_source_url": event_url if time_valid else "",
            }
        )
    return events


def parse_espn_standings_json(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract Milan and its nearest Serie A neighbours from ESPN standings."""
    entries: list[dict[str, Any]] = []
    for child in payload.get("children") or []:
        entries.extend(((child.get("standings") or {}).get("entries") or []))
    entries.extend(((payload.get("standings") or {}).get("entries") or []))

    rows: list[dict[str, Any]] = []
    milan_row: dict[str, Any] | None = None
    seen_teams: set[str] = set()
    for entry in entries:
        team = entry.get("team") or {}
        team_names = {
            _normalize(str(team.get(key) or ""))
            for key in ("displayName", "shortDisplayName", "name", "abbreviation")
        }
        is_milan = str(team.get("id") or "") == "103" or bool(
            {"ac-milan", "milan"} & team_names
        )

        stats: dict[str, Any] = {}
        for stat in entry.get("stats") or []:
            value = stat.get("value")
            if value is None:
                value = stat.get("displayValue")
            for key in (stat.get("name"), stat.get("abbreviation"), stat.get("shortDisplayName")):
                if key:
                    stats[_normalize(str(key))] = value

        def number(*names: str) -> int | None:
            for name in names:
                value = stats.get(_normalize(name))
                if value not in (None, ""):
                    try:
                        return int(float(str(value).replace(",", ".")))
                    except ValueError:
                        continue
            return None

        position = number("rank", "position", "rk")
        points = number("points", "pts")
        played = number("gamesPlayed", "games played", "gp")
        if position is None or points is None or played is None:
            continue
        team_name = str(
            team.get("shortDisplayName")
            or team.get("displayName")
            or team.get("name")
            or ""
        ).strip()
        team_key = str(team.get("id") or _normalize(team_name))
        if not team_name or team_key in seen_teams:
            continue
        seen_teams.add(team_key)
        row = {
            "team": "Milan" if is_milan else team_name,
            "position": position,
            "points": points,
            "played": played,
            "wins": number("wins", "w"),
            "draws": number("ties", "draws", "d"),
            "losses": number("losses", "l"),
            "goal_difference": number("pointDifferential", "goalDifference", "goal difference", "gd"),
        }
        rows.append(row)
        if is_milan:
            milan_row = row

    if not milan_row:
        return None
    rows.sort(key=lambda row: int(row["position"]))
    milan_index = rows.index(milan_row)
    window_start = max(0, min(milan_index - 2, len(rows) - 5))
    result = deepcopy(milan_row)
    result["context"] = [
        {
            "team": row["team"],
            "position": row["position"],
            "points": row["points"],
            "played": row["played"],
        }
        for row in rows[window_start : window_start + 5]
    ]
    result.pop("team", None)
    result["provisional"] = len({int(row["played"]) for row in rows}) > 1
    result["source"] = "ESPN"
    return result


def parse_lega_standings_json(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract Milan and its neighbours from the official Lega Serie A SDP feed."""
    tables = payload.get("standings") or []
    teams = (tables[0].get("teams") or []) if tables else []
    rows: list[dict[str, Any]] = []
    milan_row: dict[str, Any] | None = None
    for team in teams:
        stats = {
            str(item.get("statsId") or ""): item.get("statsValue")
            for item in team.get("stats") or []
        }

        def number(name: str) -> int | None:
            value = stats.get(name)
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        position = number("rank")
        points = number("points")
        played = number("matches-played")
        name = str(
            team.get("shortName")
            or team.get("mediaName")
            or team.get("officialName")
            or ""
        ).strip()
        if not name or position is None or points is None or played is None:
            continue
        is_milan = _is_milan(name) or _normalize(str(team.get("officialName") or "")) == "ac-milan"
        row = {
            "team": "Milan" if is_milan else name,
            "position": position,
            "points": points,
            "played": played,
            "wins": number("win"),
            "draws": number("draw"),
            "losses": number("lose"),
            "goal_difference": number("goal-difference"),
        }
        rows.append(row)
        if is_milan:
            milan_row = row
    if not milan_row:
        return None
    rows.sort(key=lambda row: int(row["position"]))
    milan_index = rows.index(milan_row)
    window_start = max(0, min(milan_index - 2, len(rows) - 5))
    result = deepcopy(milan_row)
    result["context"] = [
        {
            "team": row["team"],
            "position": row["position"],
            "points": row["points"],
            "played": row["played"],
        }
        for row in rows[window_start : window_start + 5]
    ]
    result.pop("team", None)
    result["provisional"] = len({int(row["played"]) for row in rows}) > 1
    result["source"] = "Lega Serie A"
    result["source_url"] = LEGA_STANDINGS_PAGE_URL
    return result


def parse_espn_pending_recoveries_json(payload: dict[str, Any]) -> list[str]:
    """Return postponed or suspended Serie A fixtures still awaiting completion."""
    recoveries: list[str] = []
    for event in payload.get("events") or []:
        status = (event.get("status") or {}).get("type") or {}
        normalized_status = _normalize(
            " ".join(
                str(status.get(key) or "")
                for key in ("name", "description", "detail", "shortDetail")
            )
        )
        if not any(
            marker in normalized_status
            for marker in ("postponed", "suspended", "abandoned", "rinviat", "sospes")
        ):
            continue
        competitions = event.get("competitions") or []
        competitors = (competitions[0].get("competitors") or []) if competitions else []
        names: dict[str, str] = {}
        for competitor in competitors:
            team = competitor.get("team") or {}
            name = str(
                team.get("shortDisplayName")
                or team.get("displayName")
                or team.get("name")
                or ""
            ).strip()
            if name:
                names[str(competitor.get("homeAway") or "")] = (
                    "Milan" if _is_milan(name) else name
                )
        home, away = names.get("home"), names.get("away")
        if home and away:
            title = f"{home}–{away}"
            if title not in recoveries:
                recoveries.append(title)
    return recoveries


def parse_uefa_draw_html(
    html: str, competition: str, source_url: str
) -> list[dict[str, Any]]:
    """Parse the current official UEFA draw from structured page metadata."""
    decoded_html = html_module.unescape(html)
    target_dates = re.findall(r'targetDate"\s*:\s*"([^"}]+)', decoded_html)
    structured_events: list[dict[str, Any]] = []
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            value = json.loads(html_module.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        structured_events.extend(
            item
            for item in values
            if isinstance(item, dict) and str(item.get("@type") or "") == "SportsEvent"
        )

    results: list[dict[str, Any]] = []
    for index, item in enumerate(structured_events):
        name = str(item.get("name") or item.get("description") or "").strip()
        if "draw" not in name.lower():
            continue
        raw_start = target_dates[index] if index < len(target_dates) else str(item.get("startDate") or "")
        if not raw_start:
            continue
        try:
            start = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).astimezone(ROME)
        except ValueError:
            continue
        page_title = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        season_match = re.search(
            r"(20\d{2})[/\\-](\d{2,4})", html_module.unescape(page_title.group(1) if page_title else "")
        )
        season = (
            f"{season_match.group(1)}/{season_match.group(2)[-2:]}"
            if season_match
            else f"{season_start(start.date())}/{str(season_start(start.date()) + 1)[-2:]}"
        )
        phase = re.sub(r"^UEFA\s+.+?\s+-\s+", "", name, flags=re.IGNORECASE)
        phase = re.sub(r"\s+draw$", "", phase, flags=re.IGNORECASE).strip()
        phase_it = {
            "league phase": "fase campionato",
            "knockout phase play-off": "play-off fase a eliminazione diretta",
            "round of 16": "ottavi di finale",
        }.get(phase.lower(), phase)
        location = item.get("location") or []
        places = location if isinstance(location, list) else [location]
        place = next(
            (
                value
                for value in places
                if isinstance(value, dict) and str(value.get("@type") or "") == "Place"
            ),
            {},
        )
        source_id = str(item.get("@id") or "").rsplit("#", 1)[-1]
        results.append(
            {
                "source_id": source_id or f"uefa-draw-{_normalize(competition)}-{season}-{_normalize(phase)}",
                "source": "UEFA",
                "source_url": source_url,
                "event_kind": "draw",
                "title": f"Sorteggio {phase_it} {competition} {season}",
                "competition": competition,
                "start": start.isoformat(),
                "all_day": False,
                "venue": str(place.get("name") or ""),
                "location": str(place.get("address") or place.get("name") or ""),
                "status": "scheduled",
                "reminder_minutes": 30,
                "notes": "Data e orario recuperati automaticamente dalla pagina ufficiale UEFA.",
            }
        )
    return results


def find_lega_calendar_articles(html: str, source_url: str = LEGA_NEWS_URL) -> list[str]:
    """Find recent official Lega articles that may announce a calendar event."""
    links: list[str] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        url = urljoin(source_url, html_module.unescape(href))
        slug = _normalize(url.rsplit("/", 1)[-1])
        if "/serie-a/news/" not in url or not any(
            word in slug for word in ("sorteggio", "calendario", "tabellone")
        ):
            continue
        if url not in links:
            links.append(url)
    return links


def parse_lega_calendar_article(html: str, source_url: str) -> list[dict[str, Any]]:
    """Parse only explicit dates from an official Lega calendar/draw article."""
    headline = ""
    published_year: int | None = None
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            value = json.loads(html_module.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        article = next(
            (
                item
                for item in values
                if isinstance(item, dict) and str(item.get("@type") or "") == "NewsArticle"
            ),
            None,
        )
        if not article:
            continue
        headline = str(article.get("headline") or "")
        published = str(article.get("datePublished") or "")
        if published[:4].isdigit():
            published_year = int(published[:4])
        break
    normalized_headline = _normalize(headline)
    if not headline or not any(
        word in normalized_headline for word in ("sorteggio", "calendario", "tabellone")
    ):
        return []
    if "coppa-italia" in normalized_headline:
        competition = "Coppa Italia"
    elif "supercoppa" in normalized_headline:
        competition = "Supercoppa Italiana"
    elif "serie-a" in normalized_headline:
        competition = "Serie A"
    else:
        return []

    text = html_module.unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    months = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
        "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
        "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    }
    match = re.search(
        rf"(?P<day>\d{{1,2}})\s+(?P<month>{'|'.join(months)})"
        r"(?:\s+(?P<year>20\d{2}))?"
        r"(?:.{0,45}?(?:alle\s+ore|ore)\s*(?P<hour>\d{1,2})[.:](?P<minute>\d{2}))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return []
    year = int(match.group("year") or published_year or 0)
    if not year:
        return []
    month = months[match.group("month").lower()]
    if match.group("hour") is not None:
        start = datetime(
            year, month, int(match.group("day")),
            int(match.group("hour")), int(match.group("minute")), tzinfo=ROME,
        )
        start_value = start.isoformat()
        all_day = False
    else:
        start_value = date(year, month, int(match.group("day"))).isoformat()
        all_day = True
    season_match = re.search(r"(20\d{2})[/\\-](\d{2,4})", headline)
    season = (
        f"{season_match.group(1)}/{season_match.group(2)[-2:]}" if season_match else str(year)
    )
    if "sorteggio" in normalized_headline:
        kind = "draw"
        title = f"Sorteggio {competition} {season}"
    else:
        kind = "calendar_publication"
        title = (
            f"Presentazione calendario {competition} {season}"
            if competition == "Serie A"
            else f"Pubblicazione tabellone {competition} {season}"
        )
    return [{
        "source_id": f"lega-{_normalize(source_url.rsplit('/', 1)[-1])}",
        "source": "Lega Serie A",
        "source_url": source_url,
        "event_kind": kind,
        "title": title,
        "competition": competition,
        "start": start_value,
        "all_day": all_day,
        "venue": "",
        "location": "",
        "status": "scheduled",
        "reminder_minutes": 30,
        "notes": "Data e orario recuperati automaticamente da un annuncio ufficiale Lega Serie A.",
    }]


def parse_thesportsdb_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in payload.get("events") or []:
        home = str(item.get("strHomeTeam") or "").strip()
        away = str(item.get("strAwayTeam") or "").strip()
        if not home or not away or not _valid_first_team_fixture(
            home, away, str(item.get("strLeague") or ""), str(item.get("strSeason") or "")
        ):
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
                "location": ", ".join(
                    value
                    for value in (str(item.get("strCity") or ""), str(item.get("strCountry") or ""))
                    if value
                ),
                "neutral": False,
                "start": start,
                "all_day": all_day,
                "status": str(item.get("strStatus") or "scheduled"),
                "time_source": "TheSportsDB" if not all_day else "",
                "time_source_url": (
                    f"https://www.thesportsdb.com/event/{event_id}" if not all_day and event_id else ""
                ),
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


def parse_schedule_html(
    html: str,
    source: str,
    source_url: str,
    year: int,
    priority: int | None = None,
    broadcaster: str = "",
) -> list[dict[str, Any]]:
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
            if not _valid_first_team_fixture(home, away):
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
                "competition": "Partita",
                "round": "",
                "venue": "",
                "start": start.isoformat(),
                "all_day": False,
                "status": "scheduled",
                "_time_overlay": True,
                "_time_priority": TIME_SOURCE_PRIORITY.get(source, 0) if priority is None else priority,
            }
            inferred_broadcaster = broadcaster or {
                "NOW": "Sky Sport e NOW",
                "Sky Sport": "Sky Sport e NOW",
                "DAZN": "DAZN",
                "Mediaset": "Mediaset e Mediaset Infinity",
                "Prime Video": "Prime Video",
            }.get(source, "")
            if inferred_broadcaster:
                event.update(
                    {"broadcast_it": inferred_broadcaster, "broadcast_source_url": source_url}
                )
            events.append(event)
    return events


def fetch_remote_events(session: requests.Session, today: date) -> FetchResult:
    events: list[dict[str, Any]] = []
    successful: list[str] = []
    errors: list[str] = []
    start_year = season_start(today)
    serie_a_standing: dict[str, Any] | None = None
    calendar_events: list[dict[str, Any]] = []

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
                parsed = parse_espn_json(payload, default_name)
                events.extend(parsed)
                espn_ok = espn_ok or bool(parsed)
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"ESPN {competition}/{season}: {exc}")
    if espn_ok:
        successful.append("ESPN")

    standings_url = ESPN_STANDINGS_URL.format(season=start_year)
    try:
        response = session.get(standings_url, timeout=20)
        response.raise_for_status()
        serie_a_standing = parse_espn_standings_json(response.json())
        if not serie_a_standing:
            raise ValueError("classifica Milan non presente nella risposta")
        serie_a_standing["source_url"] = standings_url
        successful.append("ESPN classifica")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"ESPN classifica: {exc}")
        LOGGER.info("Classifica ESPN non disponibile: %s", exc)

    # The public SDP feed powers the official Lega Serie A standings page.
    # Prefer it when available; ESPN remains the fast fallback.
    try:
        seasons_url = (
            f"{LEGA_SDP_BASE_URL}/competitions/"
            f"{quote(LEGA_SERIE_A_COMPETITION_ID, safe='')}/seasons?locale=it-IT"
        )
        response = session.get(seasons_url, timeout=20)
        response.raise_for_status()
        season_name = f"{start_year}/{start_year + 1}"
        season = next(
            (
                item
                for item in response.json().get("seasons") or []
                if str(item.get("seasonName") or "") == season_name
            ),
            None,
        )
        if not season or not season.get("seasonId"):
            raise ValueError(f"stagione ufficiale {season_name} non trovata")
        official_standings_url = (
            f"{LEGA_SDP_BASE_URL}/seasons/"
            f"{quote(str(season['seasonId']), safe='')}/standings/overall?locale=it-IT"
        )
        response = session.get(official_standings_url, timeout=20)
        response.raise_for_status()
        official_standing = parse_lega_standings_json(response.json())
        if not official_standing:
            raise ValueError("classifica Milan non presente nella risposta ufficiale")
        serie_a_standing = official_standing
        successful.append("Lega Serie A classifica")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Lega Serie A classifica: {exc}")
        LOGGER.info("Classifica ufficiale Lega Serie A non disponibile: %s", exc)

    if serie_a_standing and serie_a_standing.get("provisional") is True:
        scoreboard_url = ESPN_SERIE_A_SCOREBOARD_URL.format(
            start_date=f"{start_year}0801", end_date=f"{start_year + 1}0630"
        )
        try:
            response = session.get(scoreboard_url, timeout=20)
            response.raise_for_status()
            serie_a_standing["pending_recoveries"] = parse_espn_pending_recoveries_json(
                response.json()
            )
            successful.append("ESPN recuperi Serie A")
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"ESPN recuperi Serie A: {exc}")
            LOGGER.info("Recuperi Serie A ESPN non disponibili: %s", exc)

    try:
        response = session.get(THESPORTSDB_URL, timeout=20)
        response.raise_for_status()
        parsed = parse_thesportsdb_json(response.json())
        if not parsed:
            raise ValueError("nessun evento valido nella risposta")
        events.extend(parsed)
        successful.append("TheSportsDB")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"TheSportsDB: {exc}")
        LOGGER.warning("Fonte TheSportsDB non disponibile: %s", exc)

    time_sources = (
        ("AC Milan", official_url, 10, ""),
        ("Gazzetta dello Sport", GAZZETTA_FRIENDLIES_URL, 20, ""),
        ("DAZN", DAZN_SCHEDULE_URL, 60, "DAZN"),
        ("Sky Sport", SKY_SERIE_A_URL, 40, "Sky Sport e NOW"),
        ("Mediaset", MEDIASET_SPORT_URL, 40, "Mediaset e Mediaset Infinity"),
        ("Prime Video", PRIME_SPORT_URL, 40, "Prime Video"),
        ("NOW", NOW_MILAN_URL, 50, "Sky Sport e NOW"),
    )
    for source, url, source_priority, broadcaster in time_sources:
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            schedule_events = parse_schedule_html(
                response.text, source, url, start_year, source_priority, broadcaster
            )
            if not schedule_events:
                raise ValueError("nessun orario esplicito per il Milan")
            events.extend(schedule_events)
            successful.append(source)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{source}: {exc}")
            LOGGER.info("Fonte orari %s non disponibile: %s", source, exc)

    uefa_draws_ok = False
    for competition, url in UEFA_DRAW_URLS.values():
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            parsed_draws = parse_uefa_draw_html(response.text, competition, url)
            if not parsed_draws:
                raise ValueError("nessun sorteggio strutturato disponibile")
            calendar_events.extend(parsed_draws)
            uefa_draws_ok = True
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"UEFA sorteggi {competition}: {exc}")
            LOGGER.info("Fonte sorteggi UEFA %s non disponibile: %s", competition, exc)
    if uefa_draws_ok:
        successful.append("UEFA sorteggi")

    try:
        response = session.get(LEGA_NEWS_URL, timeout=20)
        response.raise_for_status()
        lega_events: list[dict[str, Any]] = []
        for article_url in find_lega_calendar_articles(response.text)[:8]:
            try:
                article = session.get(article_url, timeout=20)
                article.raise_for_status()
                lega_events.extend(parse_lega_calendar_article(article.text, article_url))
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"Lega calendario {article_url}: {exc}")
        if lega_events:
            calendar_events.extend(lega_events)
            successful.append("Lega calendario")
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Lega calendario: {exc}")
        LOGGER.info("Fonte calendario Lega Serie A non disponibile: %s", exc)

    if (
        serie_a_standing
        and serie_a_standing.get("provisional") is True
        and "pending_recoveries" not in serie_a_standing
    ):
        fallback_recoveries: list[str] = []
        for event in events:
            if (
                _competition_family(str(event.get("competition") or "")) == "serie-a"
                and _is_postponed(event)
            ):
                home = str(event.get("home_team") or "").strip()
                away = str(event.get("away_team") or "").strip()
                if home and away:
                    title = f"{home}–{away}"
                    if title not in fallback_recoveries:
                        fallback_recoveries.append(title)
        serie_a_standing["pending_recoveries"] = fallback_recoveries

    return FetchResult(
        events=events,
        successful_sources=successful,
        errors=errors,
        serie_a_standing=serie_a_standing,
        calendar_events=calendar_events,
    )


def _event_datetime(event: dict[str, Any]) -> datetime:
    raw = str(event["start"])
    if event.get("all_day"):
        return datetime.combine(date.fromisoformat(raw[:10]), time.min, tzinfo=ROME)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=ROME)


def _event_time_priority(event: dict[str, Any]) -> int:
    explicit = event.get("_time_priority")
    if explicit is not None:
        return int(explicit)
    source = str(event.get("time_source") or event.get("source") or "")
    return TIME_SOURCE_PRIORITY.get(source, 0)


def _semantic_base(event: dict[str, Any]) -> str:
    start = _event_datetime(event).astimezone(ROME)
    active_season = start.year if start.month >= 7 else start.year - 1
    if str(event.get("event_kind") or "match") != "match":
        parts = (
            str(active_season),
            str(event.get("event_kind") or "calendar-event"),
            _normalize(str(event.get("source_id") or event.get("id") or event.get("title") or "")),
            _competition_family(str(event.get("competition") or "")),
        )
        return "|".join(parts)
    parts = (
        str(active_season),
        _team_match_key(str(event.get("home_team") or "")),
        _team_match_key(str(event.get("away_team") or "")),
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
    if str(event.get("event_kind") or "match") != "match":
        return
    if event.get("broadcast_it"):
        return
    broadcaster, source_url = BROADCASTERS_IT.get(
        _competition_family(str(event.get("competition") or "")),
        ("Da definire", ""),
    )
    event["broadcast_it"] = broadcaster
    event.setdefault("broadcast_source_url", source_url)


def _merge_broadcaster_overlay(event: dict[str, Any], overlay: dict[str, Any]) -> None:
    rights = BROADCASTERS_IT.get(
        _competition_family(str(event.get("competition") or ""))
    )
    if rights and not event.get("broadcast_it"):
        event["broadcast_it"], event["broadcast_source_url"] = rights

    candidate = str(overlay.get("broadcast_it") or "").strip()
    existing = str(event.get("broadcast_it") or "").strip()
    if candidate:
        if not existing:
            event["broadcast_it"] = candidate
        elif candidate.lower() not in existing.lower() and existing.lower() not in candidate.lower():
            event["broadcast_it"] = f"{existing}; {candidate}"

    source_urls = [
        str(value)
        for value in (
            event.get("broadcast_source_url"),
            overlay.get("broadcast_source_url"),
        )
        if value
    ]
    if source_urls:
        event["broadcast_source_urls"] = list(dict.fromkeys(source_urls))
        event["broadcast_source_url"] = event["broadcast_source_urls"][-1]


def _same_source_id(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(
        left.get("source")
        and left.get("source") == right.get("source")
        and left.get("source_id")
        and str(left.get("source_id")) == str(right.get("source_id"))
    )


def _is_postponed(event: dict[str, Any]) -> bool:
    if event.get("postponed") is True:
        return True
    status = _normalize(str(event.get("status") or ""))
    return status in {"pst", "ppd"} or any(
        marker in status for marker in ("postponed", "rinviat", "suspended")
    )


def _same_fixture(
    left: dict[str, Any], right: dict[str, Any], *, unordered: bool = False
) -> bool:
    if any(str(event.get("event_kind") or "match") != "match" for event in (left, right)):
        return False
    left_teams = (
        _team_match_key(str(left.get("home_team") or "")),
        _team_match_key(str(left.get("away_team") or "")),
    )
    right_teams = (
        _team_match_key(str(right.get("home_team") or "")),
        _team_match_key(str(right.get("away_team") or "")),
    )
    if (sorted(left_teams) if unordered else left_teams) != (
        sorted(right_teams) if unordered else right_teams
    ):
        return False
    left_family = _competition_family(str(left.get("competition") or ""))
    right_family = _competition_family(str(right.get("competition") or ""))
    generic = {"partita", "altra-competizione"}
    if left_family != right_family and not ({left_family, right_family} & generic):
        return False
    return abs((_event_datetime(left) - _event_datetime(right)).total_seconds()) <= 60 * 60 * 72


def _same_long_range_fixture(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Recognize a uniquely identifiable postponement even across season boundaries."""
    if any(str(event.get("event_kind") or "match") != "match" for event in (left, right)):
        return False
    left_teams = tuple(
        _team_match_key(str(left.get(key) or "")) for key in ("home_team", "away_team")
    )
    right_teams = tuple(
        _team_match_key(str(right.get(key) or "")) for key in ("home_team", "away_team")
    )
    if left_teams != right_teams:
        return False
    left_family = _competition_family(str(left.get("competition") or ""))
    right_family = _competition_family(str(right.get("competition") or ""))
    if left_family != right_family or left_family in {"partita", "altra-competizione"}:
        return False
    left_round = _normalize(str(left.get("round") or ""))
    right_round = _normalize(str(right.get("round") or ""))
    if left_round and right_round and left_round != right_round:
        return False
    return abs((_event_datetime(left) - _event_datetime(right)).total_seconds()) <= 60 * 60 * 24 * 240


def merge_remote_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = list(events)
    merged: list[dict[str, Any]] = []
    # Official data wins; ESPN still contributes competitions and friendlies
    # missing from the official page.
    priority = {"AC Milan": 0, "ESPN": 1, "TheSportsDB": 2}
    base_events = [event for event in candidates if not event.get("_time_overlay")]
    time_overlays = [event for event in candidates if event.get("_time_overlay")]
    for candidate in sorted(base_events, key=lambda item: priority.get(str(item.get("source")), 9)):
        existing = next(
            (
                event
                for event in merged
                if _same_source_id(event, candidate) or _same_fixture(event, candidate)
            ),
            None,
        )
        if existing is None:
            long_range_matches = [
                event for event in merged if _same_long_range_fixture(event, candidate)
            ]
            existing = long_range_matches[0] if len(long_range_matches) == 1 else None
        if existing is None:
            merged.append(deepcopy(candidate))
            continue
        for key, value in candidate.items():
            if not existing.get(key) and value:
                existing[key] = value

    # Apply time-only sources after fixture discovery. Broadcasters can update
    # the kick-off and TV fields without replacing club metadata such as venue.
    for candidate in sorted(time_overlays, key=lambda item: int(item.get("_time_priority") or 0)):
        existing = next(
            (event for event in merged if _same_fixture(event, candidate, unordered=True)), None
        )
        if existing is None:
            # Palinsesti ed articoli servono ad arricchire incontri già
            # scoperti dalle fonti sportive, non a creare nuove partite.
            continue
        previous_start = str(existing.get("start") or "")
        candidate_start = str(candidate.get("start") or "")
        same_instant = (
            previous_start
            and candidate_start
            and not existing.get("all_day")
            and _event_datetime(existing).astimezone(timezone.utc)
            == _event_datetime(candidate).astimezone(timezone.utc)
        )
        if previous_start and not existing.get("all_day") and not same_instant:
            conflict = {
                "source": str(existing.get("time_source") or existing.get("source") or ""),
                "source_url": str(existing.get("time_source_url") or existing.get("source_url") or ""),
                "start": previous_start,
            }
            conflicts = existing.setdefault("time_conflicts", [])
            if conflict not in conflicts:
                conflicts.append(conflict)
        existing["start"] = candidate_start
        existing["all_day"] = False
        existing["time_source"] = candidate["source"]
        existing["time_source_url"] = candidate["source_url"]
        if candidate.get("broadcast_it"):
            _merge_broadcaster_overlay(existing, candidate)
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
        if event.get("enabled") is False:
            continue
        required = {"home_team", "away_team", "competition", "start"}
        missing = sorted(required - event.keys())
        if missing:
            raise ValueError(f"Evento manuale #{index + 1}: campi mancanti: {', '.join(missing)}")
        normalized = deepcopy(event)
        normalized.pop("enabled", None)
        normalized.setdefault("source", "Manuale")
        normalized.setdefault("source_url", "")
        normalized.setdefault("source_id", str(event.get("id") or f"manual-{index + 1}"))
        normalized.setdefault("round", "")
        normalized.setdefault("venue", "")
        normalized.setdefault("location", "")
        normalized.setdefault("neutral", False)
        normalized.setdefault("all_day", len(str(event["start"])) == 10)
        normalized.setdefault("status", "scheduled")
        result.append(normalized)
    return result


def load_calendar_events(
    path: Path, participating_competitions: set[str]
) -> list[dict[str, Any]]:
    """Load official non-match dates, filtering competitions Milan does not play."""
    payload = load_json(path, {"events": []})
    events = payload.get("events", []) if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        raise ValueError("data/calendar_events.json deve contenere una lista o un oggetto con 'events'")
    result: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"Evento calendario #{index + 1} non valido")
        if event.get("enabled") is False:
            continue
        required = {"title", "competition", "start", "source_url"}
        missing = sorted(required - event.keys())
        if missing:
            raise ValueError(
                f"Evento calendario #{index + 1}: campi mancanti: {', '.join(missing)}"
            )
        family = _competition_family(str(event["competition"]))
        if (
            event.get("requires_participation", True)
            and not event.get("participation_confirmed", False)
            and family not in participating_competitions
        ):
            continue
        normalized = deepcopy(event)
        normalized.pop("enabled", None)
        normalized.pop("requires_participation", None)
        normalized.pop("participation_confirmed", None)
        normalized.setdefault("event_kind", "draw")
        normalized.setdefault("source", "Calendario ufficiale")
        normalized.setdefault("source_id", str(event.get("id") or f"calendar-{index + 1}"))
        normalized.setdefault("round", "")
        normalized.setdefault("venue", "")
        normalized.setdefault("location", "")
        normalized.setdefault("all_day", len(str(event["start"])) == 10)
        normalized.setdefault("status", "scheduled")
        normalized.setdefault("reminder_minutes", 30)
        result.append(normalized)
    return sorted(result, key=_event_datetime)


def _same_calendar_event(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("event_kind") or "match") == "match" or str(
        right.get("event_kind") or "match"
    ) == "match":
        return False
    return (
        str(left.get("event_kind") or "") == str(right.get("event_kind") or "")
        and _competition_family(str(left.get("competition") or ""))
        == _competition_family(str(right.get("competition") or ""))
        and abs((_event_datetime(left) - _event_datetime(right)).total_seconds())
        <= 36 * 60 * 60
    )


def merge_calendar_events(*sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge automatic, configured and previously discovered non-match events."""
    merged: list[dict[str, Any]] = []
    for source in sources:
        for candidate in source:
            family = _competition_family(str(candidate.get("competition") or ""))
            existing = next(
                (
                    event
                    for event in merged
                    if _same_source_id(event, candidate)
                    or _same_calendar_event(event, candidate)
                ),
                None,
            )
            if existing is None:
                merged.append(deepcopy(candidate))
                continue
            for key, value in candidate.items():
                if not existing.get(key) and value:
                    existing[key] = deepcopy(value)
    return sorted(merged, key=_event_datetime)


def _canonical_event(
    event: dict[str, Any],
    previous: list[dict[str, Any]],
    changed_at: str,
    used_uids: set[str] | None = None,
) -> dict[str, Any]:
    result = deepcopy(event)
    result.pop("_time_overlay", None)
    result.pop("_time_priority", None)
    result.pop("lock_time", None)
    result.setdefault("location", "")
    result.setdefault("neutral", False)
    result.setdefault("time_source", "")
    result.setdefault("time_source_url", "")
    is_match = str(result.get("event_kind") or "match") == "match"
    if result.get("all_day"):
        result["start"] = str(result["start"])[:10]
    else:
        # Persist the debug snapshot in the same timezone used by the ICS.
        # This prevents source-specific UTC/local offsets from leaking into
        # data/events.json and makes DST conversion explicit and testable.
        result["start"] = _event_datetime(result).astimezone(ROME).isoformat()
    _add_italian_broadcaster(result)
    result["uid"] = _uid_for(result)
    generated_uid = result["uid"]
    if is_match:
        result["home_away"] = (
            "Campo neutro"
            if result.get("neutral")
            else ("Casa" if _is_milan(str(result["home_team"])) else "Trasferta")
        )
        base_title = f"{result['home_team']} - {result['away_team']}"
    else:
        result["home_away"] = ""
        base_title = str(result["title"])
    old = next((item for item in previous if _same_source_id(item, result)), None)
    if old is None and not is_match:
        old = next(
            (item for item in previous if _same_calendar_event(item, result)), None
        )
    if old is None and is_match:
        long_range_matches = [
            item for item in previous if _same_long_range_fixture(item, result)
        ]
        old = long_range_matches[0] if len(long_range_matches) == 1 else None
    if old is None and is_match:
        old = next(
            (item for item in previous if _same_fixture(item, result, unordered=True)), None
        )
    if old is None:
        old = next((item for item in previous if item.get("uid") == generated_uid), None)
    if old is not None:
        if old.get("uid") and str(old["uid"]) not in (used_uids or set()):
            result["uid"] = str(old["uid"])
        else:
            # Migrate legacy feeds where home and away legs accidentally shared
            # one UID. The ordered semantic UID remains stable on later runs.
            result["uid"] = generated_uid
    if used_uids is not None and result["uid"] in used_uids:
        collision_base = "|".join(
            (
                _semantic_base(result),
                str(result.get("source") or ""),
                str(result.get("source_id") or ""),
                str(result.get("start") or ""),
            )
        )
        result["uid"] = f"{hashlib.sha256(collision_base.encode()).hexdigest()[:24]}@milan-calendar"

    explicitly_cleared = result.get("postponed") is False
    if is_match and not explicitly_cleared and _is_postponed(result):
        result["postponed"] = True
        result.setdefault(
            "postponed_from",
            str((old or {}).get("postponed_from") or (old or {}).get("start") or result["start"]),
        )
        result.setdefault("postponed_to", "")
    elif is_match and not explicitly_cleared and old and old.get("postponed"):
        if str(result.get("start")) != str(old.get("start")):
            result["postponed"] = True
            result["postponed_from"] = str(old.get("postponed_from") or old.get("start") or "")
            result["postponed_to"] = str(result["start"])
            if old.get("postponement_reason") and not result.get("postponement_reason"):
                result["postponement_reason"] = old["postponement_reason"]
        elif old.get("postponed_to"):
            for key in ("postponed", "postponed_from", "postponed_to", "postponement_reason"):
                if old.get(key) and not result.get(key):
                    result[key] = old[key]

    if is_match and result.get("postponed"):
        postponed_to = str(result.get("postponed_to") or "")
        if postponed_to:
            new_date = date.fromisoformat(postponed_to[:10]).strftime("%d/%m/%Y")
            result["title"] = f"RINVIATA AL {new_date} — {base_title}"
        else:
            result["title"] = f"RINVIATA — DATA DA DESTINARSI — {base_title}"
            result["start"] = str(result.get("postponed_from") or result["start"])[:10]
            result["all_day"] = True
    else:
        result.pop("postponed", None)
        result["title"] = base_title
    ignored = {"last_modified", "sequence"}
    comparable = {key: value for key, value in result.items() if key not in ignored}
    old_comparable = {key: value for key, value in (old or {}).items() if key not in ignored}
    changed = old is None or comparable != old_comparable
    result["sequence"] = int((old or {}).get("sequence") or 0) + (1 if old and changed else 0)
    result["last_modified"] = (
        str(old.get("last_modified")) if old and not changed else changed_at
    )
    if used_uids is not None:
        if result["uid"] in used_uids:
            raise ValueError(f"UID duplicato non risolvibile: {result['uid']}")
        used_uids.add(result["uid"])
    return result


def merge_manual_events(remote: list[dict[str, Any]], manual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = deepcopy(remote)
    for candidate in manual:
        uid = _uid_for(candidate)
        existing_index = next(
            (
                index
                for index, event in enumerate(merged)
                if _uid_for(event) == uid
                or _same_source_id(event, candidate)
                or _same_fixture(event, candidate, unordered=True)
            ),
            None,
        )
        if existing_index is None:
            long_range_matches = [
                index
                for index, event in enumerate(merged)
                if _same_long_range_fixture(event, candidate)
            ]
            existing_index = long_range_matches[0] if len(long_range_matches) == 1 else None
        if existing_index is None:
            merged.append(deepcopy(candidate))
        else:
            existing = merged[existing_index]
            candidate_copy = deepcopy(candidate)
            # A static manual fixture may be needed before broadcasters list
            # it. Once a freshly fetched broadcaster publishes the same match,
            # let an equal/higher-priority live source correct the manual time.
            # `lock_time` remains available for exceptional, explicitly
            # verified manual corrections.
            manual_time_source = str(candidate.get("time_source") or "")
            prefer_live_time = (
                not candidate.get("lock_time")
                and bool(manual_time_source)
                and bool(existing.get("time_source"))
                and _event_time_priority(existing) >= _event_time_priority(candidate)
            )
            preserved: dict[str, Any] = {}
            if prefer_live_time:
                for key in (
                    "start",
                    "all_day",
                    "time_source",
                    "time_source_url",
                    "time_conflicts",
                    "broadcast_it",
                    "broadcast_source_url",
                    "broadcast_source_urls",
                ):
                    if key in existing:
                        preserved[key] = deepcopy(existing[key])
            existing.update(candidate_copy)
            existing.update(preserved)
    return sorted(merged, key=_event_datetime)


def _country_flag(country_code: str) -> str:
    code = country_code.upper()
    if len(code) != 2 or not code.isalpha():
        return "🌍"
    return "".join(chr(127397 + ord(character)) for character in code)


def _broadcast_description_lines(data: dict[str, Any]) -> list[str]:
    options = data.get("broadcast_options") or []
    italian = [option for option in options if option.get("country_code") == "IT"]
    foreign = [option for option in options if option.get("country_code") != "IT"][:3]
    lines = ["Dove vederla:"]
    if not italian:
        lines.append("🇮🇹 Italia — Da confermare")
    for option in italian:
        lines.append(f"🇮🇹 Italia — {option['broadcaster']}")
        access = {
            "free": "GRATIS",
            "included": "Incluso nell'abbonamento",
            "paid": "A pagamento",
        }.get(str(option.get("access") or ""), "Da verificare")
        attributes = [access, str(option.get("platforms") or "")]
        if option.get("language"):
            attributes.append(str(option["language"]))
        if option.get("registration_required"):
            attributes.append("registrazione richiesta")
        if option.get("broadcast_start_rome"):
            attributes.append(
                f"diretta dalle {option['broadcast_start_rome']} (ora di Roma)"
            )
        lines.extend((" · ".join(item for item in attributes if item), str(option["url"])))
    if foreign:
        lines.append("ALTERNATIVE UFFICIALI ALL'ESTERO:")
        for option in foreign:
            lines.append(
                f"{_country_flag(str(option.get('country_code') or ''))} "
                f"{option['country']} — {option['broadcaster']}"
            )
            access = {
                "free": "GRATIS",
                "included": "Incluso nell'abbonamento",
                "paid": "A pagamento",
            }.get(str(option.get("access") or ""), "Da verificare")
            attributes = [access, str(option.get("platforms") or "")]
            if option.get("language"):
                attributes.append(str(option["language"]))
            if option.get("registration_required"):
                attributes.append("registrazione richiesta")
            if option.get("broadcast_start_rome"):
                attributes.append(
                    f"diretta dalle {option['broadcast_start_rome']} (ora di Roma)"
                )
            lines.extend((" · ".join(item for item in attributes if item), str(option["url"])))
    elif data.get("broadcast_international_tbc"):
        lines.append("🌍 In chiaro all'estero — Da confermare")
    return lines


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
        is_match = str(data.get("event_kind") or "match") == "match"
        summary_icon = (
            "⚽"
            if is_match
            else ("🎲" if data.get("event_kind") == "draw" else "🗓️")
        )
        component.add(
            "summary",
            f"⏸ {data['title']}" if data.get("postponed") else f"{summary_icon} {data['title']}",
        )
        start = _event_datetime(data).astimezone(ROME)
        if data.get("all_day"):
            component.add("dtstart", start.date())
            component.add("dtend", start.date() + timedelta(days=1))
        else:
            component.add("dtstart", start)
            component.add("dtend", start + timedelta(hours=2 if is_match else 1))
        modified = datetime.fromisoformat(str(data["last_modified"]).replace("Z", "+00:00"))
        component.add("dtstamp", modified.astimezone(timezone.utc))
        component.add("last-modified", modified.astimezone(timezone.utc))
        component.add("sequence", int(data.get("sequence") or 0))
        if data.get("postponed"):
            component.add("status", "CONFIRMED" if data.get("postponed_to") else "TENTATIVE")
        place = ", ".join(
            dict.fromkeys(
                value for value in (str(data.get("venue") or ""), str(data.get("location") or "")) if value
            )
        )
        if place:
            component.add("location", place)
        if data.get("source_url"):
            component.add("url", str(data["source_url"]))
        details = [f"Competizione: {data['competition']}"]
        if is_match:
            details.append(f"Milan: {data['home_away']}")
        else:
            details.append(
                "Tipo: Sorteggio"
                if data.get("event_kind") == "draw"
                else "Tipo: Pubblicazione calendario/tabellone"
            )
        details.append(
            "Orario: da confermare"
            if data.get("all_day")
            else f"Orario (Roma): {start.strftime('%d/%m/%Y %H:%M')}"
        )
        if data.get("round"):
            details.append(f"Turno: {data['round']}")
        if data.get("postponed"):
            details.append(
                "Rinvio: "
                + (
                    f"nuova data {str(data['postponed_to'])[:10]}"
                    if data.get("postponed_to")
                    else "data da destinarsi"
                )
            )
            if data.get("postponed_from"):
                details.append(f"Data originaria: {str(data['postponed_from'])[:10]}")
            if data.get("postponement_reason"):
                details.append(f"Motivo: {data['postponement_reason']}")
        if data.get("venue"):
            details.append(f"Stadio: {data['venue']}")
        if data.get("location"):
            details.append(f"Località: {data['location']}")
        if is_match and _is_official_international_match(data) and "broadcast_options" in data:
            details.extend(_broadcast_description_lines(data))
        elif is_match and data.get("broadcast_it"):
            details.append(f"Dove vederla in Italia: {data['broadcast_it']}")
        if is_match and data.get("time_source"):
            details.append(f"Fonte orario: {data['time_source']}")
        if not is_match and data.get("notes"):
            details.append(str(data["notes"]))
        standing = data.get("serie_a_standing") or {}
        if is_match and _competition_family(str(data.get("competition") or "")) == "serie-a" and standing:
            goal_difference = standing.get("goal_difference")
            goal_difference_text = (
                f" — DR {int(goal_difference):+d}" if goal_difference is not None else ""
            )
            context = standing.get("context") or []
            if context:
                if standing.get("provisional") is True:
                    pending_recoveries = standing.get("pending_recoveries") or []
                    if len(pending_recoveries) == 1:
                        details.append(
                            "Classifica Serie A provvisoria — recupero "
                            f"{pending_recoveries[0]} ancora da disputare:"
                        )
                    elif pending_recoveries:
                        details.append(
                            "Classifica Serie A provvisoria — recuperi "
                            f"{', '.join(str(item) for item in pending_recoveries)} "
                            "ancora da disputare:"
                        )
                    else:
                        details.append("Classifica Serie A provvisoria — giornata in corso:")
                elif standing.get("provisional") is False:
                    details.append("Classifica Serie A aggiornata — giornata completata:")
                else:
                    details.append("Classifica Serie A:")
                for row in context:
                    is_milan_row = _is_milan(str(row.get("team") or ""))
                    marker = "▶" if is_milan_row else " "
                    extra = (
                        f" — {standing['played']} PG{goal_difference_text}"
                        if is_milan_row
                        else ""
                    )
                    details.append(
                        f"{marker} {row['position']}. {row['team']} — {row['points']} pt{extra}"
                    )
            else:
                details.append(
                    f"Classifica Milan: {standing['position']}º — {standing['points']} pt — "
                    f"{standing['played']} PG{goal_difference_text}"
                )
            if standing.get("updated_at"):
                updated = datetime.fromisoformat(str(standing["updated_at"]).replace("Z", "+00:00"))
                details.append(
                    f"Classifica aggiornata: {updated.astimezone(ROME).strftime('%d/%m/%Y %H:%M')}"
                )
            if standing.get("source"):
                details.append(f"Fonte classifica: {standing['source']}")
        component.add("description", "\n".join(details))
        component.add("categories", [str(data["competition"]), "AC Milan"])
        component.add("transp", "OPAQUE")
        if not data.get("postponed") or data.get("postponed_to"):
            reminder_minutes = int(data.get("reminder_minutes") or (150 if is_match else 30))
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", f"Tra {reminder_minutes} minuti: {data['title']}")
            alarm.add("trigger", timedelta(minutes=-reminder_minutes))
            component.add_component(alarm)
        calendar.add_component(component)
    return calendar.to_ical()


def _atomic_write_many(outputs: list[tuple[Path, bytes]]) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for path, content in outputs:
            if path.exists() and path.read_bytes() == content:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", dir=path.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temporary, path))
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def update_calendar(root: Path, session: requests.Session | None = None, today: date | None = None) -> list[dict[str, Any]]:
    root = root.resolve()
    data_dir = root / "data"
    events_path = data_dir / "events.json"
    manual_path = data_dir / "manual_events.json"
    calendar_events_path = data_dir / "calendar_events.json"
    previous_payload = load_json(events_path, {"events": []})
    previous = previous_payload.get("events", []) if isinstance(previous_payload, dict) else []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    changed_at = now.isoformat().replace("+00:00", "Z")

    reference_today = today or datetime.now(ROME).date()
    active_session = session or build_session()
    fetched = fetch_remote_events(active_session, reference_today)
    discovery_sources = {"AC Milan", "ESPN", "TheSportsDB"}
    discovered_events = [event for event in fetched.events if not event.get("_time_overlay")]
    if not discovery_sources.intersection(fetched.successful_sources) or not discovered_events:
        raise UpdateError(
            "Nessuna fonte remota disponibile; calendar.ics e data/events.json sono rimasti invariati. "
            + "; ".join(fetched.errors[:3])
        )

    remote = merge_remote_events(fetched.events)
    manual = load_manual_events(manual_path)
    combined = merge_manual_events(remote, manual)
    broadcast_sources = load_broadcast_sources(data_dir / "broadcast_sources.json")
    combined, broadcast_errors = apply_verified_broadcasts(
        active_session,
        combined,
        previous,
        broadcast_sources,
        changed_at,
        now,
    )
    fetched.errors.extend(f"Broadcast {error}" for error in broadcast_errors)
    participating_competitions = {
        _competition_family(str(event.get("competition") or ""))
        for event in combined
        if str(event.get("event_kind") or "match") == "match"
    }
    configured_calendar_events = load_calendar_events(
        calendar_events_path, participating_competitions
    )
    participating_competitions.update(
        _competition_family(str(event.get("competition") or ""))
        for event in configured_calendar_events
    )
    automatic_calendar_events = [
        event
        for event in (fetched.calendar_events or [])
        if (
            _competition_family(str(event.get("competition") or ""))
            in participating_competitions
            or (
                _competition_family(str(event.get("competition") or "")) == "coppa-italia"
                and "serie-a" in participating_competitions
            )
        )
    ]
    previous_calendar_events = [
        event
        for event in previous
        if str(event.get("event_kind") or "match") != "match"
    ]
    combined.extend(
        merge_calendar_events(
            automatic_calendar_events,
            configured_calendar_events,
            previous_calendar_events,
        )
    )
    combined.sort(key=_event_datetime)
    standing_with_timestamp: dict[str, Any] | None = None
    if fetched.serie_a_standing:
        standing_with_timestamp = deepcopy(fetched.serie_a_standing)
        previous_standing = (
            previous_payload.get("serie_a_standing")
            if isinstance(previous_payload, dict)
            else None
        )
        previous_without_timestamp = {
            key: value
            for key, value in (previous_standing or {}).items()
            if key != "updated_at"
        }
        standing_with_timestamp["updated_at"] = (
            str(previous_standing["updated_at"])
            if previous_standing
            and previous_without_timestamp == fetched.serie_a_standing
            and previous_standing.get("updated_at")
            else changed_at
        )
    serie_a_matches = [
        event
        for event in combined
        if str(event.get("event_kind") or "match") == "match"
        and _competition_family(str(event.get("competition") or "")) == "serie-a"
    ]
    matches_today = [
        event for event in serie_a_matches if _event_datetime(event).date() == reference_today
    ]
    current_or_previous_serie_a_match = (
        matches_today[-1]
        if matches_today
        else next(
            (
                event
                for event in reversed(serie_a_matches)
                if _event_datetime(event).date() < reference_today
            ),
            None,
        )
    )
    next_serie_a_match = next(
        (
            event for event in serie_a_matches
            if _event_datetime(event).date() > reference_today
            and _normalize(str(event.get("status") or ""))
            not in {"played", "final", "full-time", "ft", "completed", "status-final"}
        ),
        None,
    )
    canonical: list[dict[str, Any]] = []
    used_uids: set[str] = set()
    for event in combined:
        if (
            (event is current_or_previous_serie_a_match or event is next_serie_a_match)
            and standing_with_timestamp
        ):
            event = deepcopy(event)
            event["serie_a_standing"] = deepcopy(standing_with_timestamp)
        canonical.append(_canonical_event(event, previous, changed_at, used_uids))
    if len({event["uid"] for event in canonical}) != len(canonical):
        raise ValueError("Il calendario contiene UID duplicati; output precedente conservato")

    ignored = {"last_modified", "sequence"}
    old_without_meta = [{key: value for key, value in item.items() if key not in ignored} for item in previous]
    new_without_meta = [{key: value for key, value in item.items() if key not in ignored} for item in canonical]
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
        "serie_a_standing": standing_with_timestamp,
        "event_count": len(canonical),
        "events": canonical,
    }
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    ical_bytes = build_ical(canonical)

    # Write only after every parsing and rendering step succeeds. A failed run
    # therefore cannot truncate or replace the last valid published calendar.
    _atomic_write_many([(events_path, json_bytes), (root / "calendar.ics", ical_bytes)])
    LOGGER.info("Generati %d eventi da %s", len(canonical), ", ".join(fetched.successful_sources))
    return canonical
