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
    load_manual_events,
    merge_manual_events,
    merge_remote_events,
    parse_espn_json,
    parse_schedule_html,
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


def test_parse_now_structured_schedule_time() -> None:
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Quali sono le amichevoli estive del Milan trasmesse su NOW?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Sabato 8 agosto ore 14:00 - Milan vs Chelsea. "
                        "Sabato 15 agosto ore 14:00 - Milan vs Manchester United."
                    ),
                },
            }
        ],
    }
    html = f'<script type="application/ld+json">{json.dumps(payload)}</script>'

    events = parse_schedule_html(html, "NOW", "https://www.nowtv.it/sport/calcio/milan", 2026)

    manchester = next(event for event in events if event["away_team"] == "Manchester United")
    assert manchester["start"] == "2026-08-15T14:00:00+02:00"
    assert manchester["broadcast_it"] == "Sky Sport e NOW"
    assert manchester["_time_overlay"] is True


def test_broadcaster_time_overrides_official_tbc_without_replacing_metadata() -> None:
    official = parse_official_html(
        official_html(
            [
                official_match(
                    providerId="man-utd",
                    datetime="2026-08-15T00:00:00Z",
                    datetimeTBC="TBC",
                    homeTeam={"name": "Milan"},
                    awayTeam={"name": "Manchester United"},
                    competition={"name": "Amichevole"},
                    stadiumName="Tarczyński Arena, Wrocław",
                )
            ]
        ),
        "https://www.acmilan.com/schedule",
    )[0]
    now_html = (
        '<script type="application/ld+json">'
        '{"text":"Sabato 15 agosto ore 14:00 - Milan vs Manchester United."}'
        "</script>"
    )
    overlay = parse_schedule_html(now_html, "NOW", "https://www.nowtv.it/sport/calcio/milan", 2026)[0]

    merged = merge_remote_events([overlay, official])

    assert len(merged) == 1
    assert merged[0]["start"] == "2026-08-15T14:00:00+02:00"
    assert merged[0]["all_day"] is False
    assert merged[0]["source"] == "AC Milan"
    assert merged[0]["source_url"] == "https://www.acmilan.com/schedule"
    assert merged[0]["time_source"] == "NOW"
    assert merged[0]["venue"] == "Tarczyński Arena, Wrocław"


def test_time_overlay_matches_reversed_teams_and_does_not_create_fixtures() -> None:
    base = {
        "source": "AC Milan",
        "source_url": "https://www.acmilan.com/schedule",
        "home_team": "Chelsea",
        "away_team": "Milan",
        "competition": "Amichevole",
        "start": "2026-08-08",
        "all_day": True,
    }
    overlay = parse_schedule_html(
        '<script type="application/ld+json">{"text":"Sabato 8 agosto ore 14:00 - Milan vs Chelsea."}</script>',
        "NOW",
        "https://www.nowtv.it/sport/calcio/milan",
        2026,
    )[0]
    unrelated = dict(overlay, home_team="Milan", away_team="Real Madrid")

    merged = merge_remote_events([base, overlay, unrelated])

    assert len(merged) == 1
    assert merged[0]["home_team"] == "Chelsea"
    assert merged[0]["start"] == "2026-08-08T14:00:00+02:00"


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


def test_filters_non_first_team_matches() -> None:
    matches = [
        official_match(providerId="men"),
        official_match(
            providerId="women",
            homeTeam={"name": "AC Milan Women"},
            awayTeam={"name": "Roma Femminile"},
        ),
        official_match(
            providerId="futuro",
            homeTeam={"name": "Milan Futuro"},
            awayTeam={"name": "Lecco"},
        ),
    ]
    events = parse_official_html(official_html(matches), "https://www.acmilan.com/schedule")
    assert [event["source_id"] for event in events] == ["men"]


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
    assert first[0]["sequence"] == 0
    assert second[0]["sequence"] == 1
    assert second[0]["start"] == "2026-09-12T19:45:00+00:00"
    assert second[0]["broadcast_it"] == "DAZN"


def test_uid_survives_multi_month_postponement_and_changed_source_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manual_events.json").write_text(
        '{"events": []}\n', encoding="utf-8"
    )
    original = parse_official_html(
        official_html(
            [
                official_match(
                    providerId="old-id",
                    datetime="2026-05-10T18:45:00Z",
                    matchDay="Finale",
                    competition={"name": "Coppa Italia"},
                )
            ]
        ),
        "https://www.acmilan.com/schedule",
    )[0]
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([original], ["AC Milan"], []),
    )
    first = update_calendar(tmp_path, session=object(), today=date(2026, 5, 1))

    postponed = dict(
        original,
        source_id="new-id",
        start="2026-08-20T18:45:00Z",
    )
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([postponed], ["AC Milan"], []),
    )
    second = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))

    assert first[0]["uid"] == second[0]["uid"]
    assert second[0]["sequence"] == 1
    assert second[0]["start"] == "2026-08-20T18:45:00Z"


def test_home_and_away_legs_have_unique_uids_and_legacy_collision_is_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manual_events.json").write_text(
        '{"events": []}\n', encoding="utf-8"
    )
    home_leg = parse_official_html(
        official_html([official_match(providerId="home-leg")]),
        "https://www.acmilan.com/schedule",
    )[0]
    away_leg = parse_official_html(
        official_html(
            [
                official_match(
                    providerId="away-leg",
                    datetime="2027-02-14T19:45:00Z",
                    matchDay="24",
                    homeTeam={"name": "Roma"},
                    awayTeam={"name": "Milan"},
                )
            ]
        ),
        "https://www.acmilan.com/schedule",
    )[0]
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([home_leg, away_leg], ["AC Milan"], []),
    )
    first = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    assert len({event["uid"] for event in first}) == 2

    events_path = tmp_path / "data" / "events.json"
    legacy_payload = json.loads(events_path.read_text(encoding="utf-8"))
    legacy_payload["events"][1]["uid"] = legacy_payload["events"][0]["uid"]
    events_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    migrated = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    assert len(migrated) == 2
    assert len({event["uid"] for event in migrated}) == 2
    calendar = Calendar.from_ical((tmp_path / "calendar.ics").read_bytes())
    uids = [str(component["uid"]) for component in calendar.walk() if component.name == "VEVENT"]
    assert len(uids) == len(set(uids)) == 2


def test_postponed_match_is_annotated_then_rescheduled_with_same_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manual_events.json").write_text(
        '{"events": []}\n', encoding="utf-8"
    )
    original = parse_official_html(
        official_html([official_match(providerId="rain-delay")]),
        "https://www.acmilan.com/schedule",
    )[0]
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([original], ["AC Milan"], []),
    )
    scheduled = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))[0]

    pending = dict(original, status="STATUS_POSTPONED")
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([pending], ["AC Milan"], []),
    )
    postponed = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))[0]
    pending_ical = Calendar.from_ical((tmp_path / "calendar.ics").read_bytes())
    pending_component = next(
        component for component in pending_ical.walk() if component.name == "VEVENT"
    )

    assert postponed["uid"] == scheduled["uid"]
    assert postponed["all_day"] is True
    assert "RINVIATA — DATA DA DESTINARSI" in postponed["title"]
    assert pending_component.decoded("status") == b"TENTATIVE"
    assert not any(item.name == "VALARM" for item in pending_component.subcomponents)

    new_start = "2027-01-20T19:45:00+01:00"
    rescheduled_source = dict(original, start=new_start, status="Fixture")
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([rescheduled_source], ["AC Milan"], []),
    )
    rescheduled = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))[0]

    assert rescheduled["uid"] == scheduled["uid"]
    assert rescheduled["start"] == new_start
    assert rescheduled["postponed_to"] == new_start
    assert "RINVIATA AL 20/01/2027" in rescheduled["title"]
    assert rescheduled["sequence"] == 2


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
        "sequence": 3,
    }
    payload = build_ical([event])
    calendar = Calendar.from_ical(payload)
    parsed = next(component for component in calendar.walk() if component.name == "VEVENT")
    alarm = next(component for component in parsed.subcomponents if component.name == "VALARM")

    assert parsed.decoded("dtstart").tzinfo is not None
    assert getattr(parsed.decoded("dtstart").tzinfo, "key", None) == "Europe/Rome"
    assert alarm.decoded("trigger").total_seconds() == -(2 * 60 + 30) * 60
    assert "Dove vederla in Italia: DAZN" in parsed.decoded("description").decode()
    assert parsed.decoded("sequence") == 3
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


def test_tv_only_success_preserves_previous_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "data").mkdir()
    events_path = tmp_path / "data" / "events.json"
    calendar_path = tmp_path / "calendar.ics"
    events_path.write_text('{"events": [{"sentinel": true}]}\n', encoding="utf-8")
    calendar_path.write_text("LAST VALID CALENDAR\n", encoding="utf-8")
    overlay = {
        "source": "DAZN",
        "source_url": "https://www.dazn.com/it-IT/schedule",
        "home_team": "Milan",
        "away_team": "Roma",
        "competition": "Partita",
        "start": "2026-09-12T20:45:00+02:00",
        "all_day": False,
        "_time_overlay": True,
    }
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([overlay], ["DAZN"], []),
    )

    with pytest.raises(UpdateError):
        update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))
    assert events_path.read_text(encoding="utf-8") == '{"events": [{"sentinel": true}]}\n'
    assert calendar_path.read_text(encoding="utf-8") == "LAST VALID CALENDAR\n"


def test_time_conflicts_are_recorded_and_highest_priority_wins() -> None:
    base = parse_official_html(official_html([official_match()]), "https://www.acmilan.com/schedule")[0]
    low = dict(
        base,
        source="Gazzetta dello Sport",
        source_url="https://www.gazzetta.it/",
        start="2026-09-12T20:45:00+02:00",
        _time_overlay=True,
        _time_priority=20,
    )
    high = dict(
        base,
        source="DAZN",
        source_url="https://www.dazn.com/it-IT/schedule",
        start="2026-09-12T21:00:00+02:00",
        _time_overlay=True,
        _time_priority=40,
    )
    merged = merge_remote_events([base, high, low])
    assert merged[0]["start"] == "2026-09-12T21:00:00+02:00"
    assert merged[0]["time_source"] == "DAZN"
    assert {item["source"] for item in merged[0]["time_conflicts"]} == {
        "Gazzetta dello Sport"
    }


def test_manual_event_can_be_disabled(tmp_path: Path) -> None:
    path = tmp_path / "manual_events.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "enabled": False,
                        "home_team": "Milan",
                        "away_team": "Roma",
                        "competition": "Serie A",
                        "start": "2026-09-12",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_manual_events(path) == []


def test_subscription_page_has_iphone_fallback() -> None:
    html = (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8")
    assert "webcal://dizzle0987.github.io/milan-calendar/calendar.ics" in html
    assert "Aggiungi calendario con iscrizione" in html
    assert "navigator.clipboard.writeText(calendarUrl)" in html
    assert "Android — Google Calendar" in html
    assert "Mac — Calendario Apple" in html
    assert "PC Windows — Outlook" in html
    assert "Sottoscrivi dal Web" in html
