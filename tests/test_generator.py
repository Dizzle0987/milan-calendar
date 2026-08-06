from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from icalendar import Calendar

from milan_calendar.generator import (
    FetchResult,
    UpdateError,
    build_ical,
    merge_manual_events,
    merge_remote_events,
    parse_espn_json,
    parse_thesportsdb_json,
    parse_official_html,
    update_calendar,
)


def test_parse_thesportsdb_json_finds_friendlies() -> None:
    payload = {
        "events": [
            {
                "idEvent": "2477373",
                "strTimestamp": "2026-08-08T12:00:00",
                "strHomeTeam": "Chelsea",
                "strAwayTeam": "AC Milan",
                "strLeague": "Club Friendlies",
                "intRound": "0",
                "strVenue": "Stamford Bridge",
                "strStatus": "NS",
            }
        ]
    }

    events = parse_thesportsdb_json(payload)

    assert len(events) == 1
    assert events[0]["source"] == "TheSportsDB"
    assert events[0]["start"] == "2026-08-08T12:00:00+00:00"
    assert events[0]["competition"] == "Club Friendlies"


def test_team_suffix_does_not_create_duplicate() -> None:
    remote = [
        {
            "source": "TheSportsDB",
            "home_team": "Chelsea",
            "away_team": "AC Milan",
            "competition": "Club Friendlies",
            "start": "2026-08-08T12:00:00+00:00",
        }
    ]
    manual = [
        {
            "source": "Manuale",
            "home_team": "Chelsea FC",
            "away_team": "AC Milan",
            "competition": "Amichevole",
            "start": "2026-08-08T14:00:00+02:00",
            "venue": "Gelora Bung Karno Stadium, Jakarta",
        }
    ]

    merged = merge_manual_events(remote, manual)

    assert len(merged) == 1
    assert merged[0]["home_team"] == "Chelsea FC"
    assert merged[0]["venue"] == "Gelora Bung Karno Stadium, Jakarta"


def official_html(matches: list[dict]) -> str:
    flight = '31:["$","div",null,{"initialMatches":' + json.dumps(matches) + "}]"
    return f"<html><script>self.__next_f.push({json.dumps([1, flight])})</script></html>"


def official_match(**overrides) -> dict:
    match = {
        "id": "cms-1",
        "providerId": "provider-1",
        "datetime": "2026-09-12T18:45:00Z",
        "datetimeTBC": "",
        "status": "Fixture",
        "matchDay": "3",
        "stadiumName": "Stadio San Siro",
        "gamePath": "milan-roma-provider-1",
        "competition": {"name": "Serie A"},
        "homeTeam": {"name": "Milan"},
        "awayTeam": {"name": "Roma"},
    }
    match.update(overrides)
    return match


def test_parse_official_embedded_json_and_tbc() -> None:
    matches = [
        official_match(),
        official_match(
            providerId="provider-2",
            datetime="2026-09-20T00:00:00Z",
            datetimeTBC="TBC",
            homeTeam={"name": "Inter"},
            awayTeam={"name": "Milan"},
        ),
    ]
    events = parse_official_html(official_html(matches), "https://www.acmilan.com/schedule")

    assert len(events) == 2
    assert events[0]["venue"] == "Stadio San Siro"
    assert events[0]["start"] == "2026-09-12T18:45:00+00:00"
    assert events[1]["all_day"] is True
    assert events[1]["start"] == "2026-09-20"


def test_parse_espn_structured_event() -> None:
    payload = {
        "events": [
            {
                "id": "espn-1",
                "date": "2026-07-25T14:00Z",
                "links": [{"href": "https://www.espn.com/match/espn-1"}],
                "league": {"name": "Club Friendly"},
                "status": {"type": {"name": "STATUS_SCHEDULED", "detail": "Sat, July 25"}},
                "competitions": [
                    {
                        "venue": {"fullName": "Celtic Park"},
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Celtic"}},
                            {"homeAway": "away", "team": {"displayName": "AC Milan"}},
                        ],
                    }
                ],
            }
        ]
    }
    events = parse_espn_json(payload, "Amichevole")
    assert len(events) == 1
    assert events[0]["away_team"] == "AC Milan"
    assert events[0]["venue"] == "Celtic Park"


def test_deduplication_prefers_official_and_uid_survives_time_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    official = parse_official_html(official_html([official_match()]), "https://www.acmilan.com/schedule")[0]
    espn = dict(official, source="ESPN", source_id="espn-1", venue="", start="2026-09-12T19:00:00+00:00")
    assert len(merge_remote_events([espn, official])) == 1

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manual_events.json").write_text('{"events": []}\n', encoding="utf-8")
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([official], ["AC Milan"], []),
    )
    first = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    changed = dict(official, start="2026-09-12T19:45:00+00:00", round="Giornata 3")
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([changed], ["AC Milan"], []),
    )
    second = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    assert first[0]["uid"] == second[0]["uid"]
    assert second[0]["start"] == "2026-09-12T19:45:00+00:00"
    assert second[0]["broadcast_it"] == "DAZN"


def test_ical_timezone_fields_and_alarm() -> None:
    event = {
        "uid": "test@milan-calendar",
        "title": "Milan - Roma",
        "home_team": "Milan",
        "away_team": "Roma",
        "home_away": "Casa",
        "competition": "Serie A",
        "round": "3",
        "venue": "Stadio San Siro",
        "broadcast_it": "DAZN",
        "broadcast_source_url": "https://www.dazn.com/it-IT",
        "source_url": "https://example.com/match",
        "start": "2026-09-12T18:45:00+00:00",
        "all_day": False,
        "last_modified": "2026-08-01T10:00:00Z",
    }
    payload = build_ical([event])
    calendar = Calendar.from_ical(payload)
    parsed = next(component for component in calendar.walk() if component.name == "VEVENT")
    alarm = next(component for component in parsed.subcomponents if component.name == "VALARM")

    assert parsed.decoded("dtstart").tzinfo is not None
    assert getattr(parsed.decoded("dtstart").tzinfo, "key", None) == "Europe/Rome"
    assert alarm.decoded("trigger").total_seconds() == -(2 * 60 + 30) * 60
    assert "Dove vederla in Italia: DAZN" in parsed.decoded("description").decode()
    assert b"X-WR-TIMEZONE:Europe/Rome" in payload


def test_manual_event_overrides_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote = parse_official_html(official_html([official_match()]), "https://www.acmilan.com/schedule")[0]
    (tmp_path / "data").mkdir()
    manual = {
        "events": [
            {
                "home_team": "Milan",
                "away_team": "Roma",
                "competition": "Serie A",
                "start": "2026-09-12T21:00:00+02:00",
                "venue": "San Siro - aggiornato manualmente",
                "broadcast_it": "Canale di prova",
                "broadcast_source_url": "https://example.com/palinsesto",
            }
        ]
    }
    (tmp_path / "data" / "manual_events.json").write_text(json.dumps(manual), encoding="utf-8")
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([remote], ["AC Milan"], []),
    )
    events = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    assert len(events) == 1
    assert events[0]["venue"] == "San Siro - aggiornato manualmente"
    assert events[0]["source"] == "Manuale"
    assert events[0]["broadcast_it"] == "Canale di prova"


def test_total_fetch_failure_preserves_previous_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "data").mkdir()
    events_path = tmp_path / "data" / "events.json"
    calendar_path = tmp_path / "calendar.ics"
    events_path.write_text('{"events": [{"sentinel": true}]}\n', encoding="utf-8")
    calendar_path.write_text("LAST VALID CALENDAR\n", encoding="utf-8")
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([], [], ["offline"]),
    )

    with pytest.raises(UpdateError):
        update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    assert events_path.read_text(encoding="utf-8") == '{"events": [{"sentinel": true}]}\n'
    assert calendar_path.read_text(encoding="utf-8") == "LAST VALID CALENDAR\n"


def test_subscription_page_has_iphone_fallback() -> None:
    html = (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8")
    assert "webcal://dizzle0987.github.io/milan-calendar/calendar.ics" in html
    assert "Aggiungi calendario con iscrizione" in html
    assert "navigator.clipboard.writeText(calendarUrl)" in html
