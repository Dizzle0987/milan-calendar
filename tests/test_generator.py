from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import requests
from icalendar import Calendar

from milan_calendar.generator import (
    FetchResult,
    UpdateError,
    _broadcast_description_lines,
    _canonical_event,
    _is_official_international_match,
    apply_verified_broadcasts,
    build_ical,
    load_manual_events,
    load_calendar_events,
    find_lega_calendar_articles,
    merge_manual_events,
    merge_calendar_events,
    merge_remote_events,
    parse_espn_json,
    parse_espn_pending_recoveries_json,
    parse_espn_standings_json,
    parse_lega_standings_json,
    parse_uefa_draw_html,
    parse_lega_calendar_article,
    parse_schedule_html,
    parse_thesportsdb_json,
    parse_official_html,
    page_confirms_fixture,
    update_calendar,
)


def test_parse_uefa_draw_prefers_exact_localtime_timestamp() -> None:
    html = """
    <html><head><title>UEFA Europa League league phase draw | 2026/27</title></head>
    <body>
      <span data-plugin="tolocaltime"
            data-options="{&quot;targetDate&quot;:&quot;2026-08-28T11:00:00+00:00&quot;}"></span>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org", "@type": "SportsEvent",
        "@id": "https://www.uefa.com/draws/#draw-123",
        "name": "UEFA Europa League - League phase draw",
        "startDate": "2026-08-28T10:00:00+00:00",
        "location": [{"@type": "Place", "name": "Monaco", "address": "Monaco"}]
      }
      </script>
    </body></html>
    """

    events = parse_uefa_draw_html(
        html, "UEFA Europa League", "https://www.uefa.com/uefaeuropaleague/draws/"
    )

    assert len(events) == 1
    assert events[0]["source_id"] == "draw-123"
    assert events[0]["start"] == "2026-08-28T13:00:00+02:00"
    assert events[0]["title"] == "Sorteggio fase campionato UEFA Europa League 2026/27"


def test_lega_news_discovery_and_explicit_calendar_datetime() -> None:
    listing = """
      <a href="/serie-a/news/una-notizia">Notizia</a>
      <a href="/serie-a/news/sorteggio-coppa-italia-2027-28">Sorteggio</a>
      <a href="/serie-a/calendario-risultati">Risultati</a>
    """
    urls = find_lega_calendar_articles(listing)
    assert urls == [
        "https://www.legaseriea.it/serie-a/news/sorteggio-coppa-italia-2027-28"
    ]

    article = """
      <script type="application/ld+json">
      {
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": "Sorteggio Coppa Italia 2027/28",
        "datePublished": "2027-06-03T10:00:00Z"
      }
      </script>
      <p>Il sorteggio si terrà venerdì 4 giugno alle ore 18.30.</p>
    """
    events = parse_lega_calendar_article(article, urls[0])

    assert len(events) == 1
    assert events[0]["start"] == "2027-06-04T18:30:00+02:00"
    assert events[0]["title"] == "Sorteggio Coppa Italia 2027/28"


def test_automatic_draw_merges_with_configured_fallback_and_persists() -> None:
    automatic = {
        "source_id": "uefa-draw-123",
        "source": "UEFA",
        "source_url": "https://www.uefa.com/draws/",
        "event_kind": "draw",
        "title": "Sorteggio fase campionato UEFA Europa League 2026/27",
        "competition": "UEFA Europa League",
        "start": "2026-08-28T13:00:00+02:00",
        "all_day": False,
    }
    configured = {
        **automatic,
        "source_id": "configured-draw",
        "venue": "Grimaldi Forum",
        "notes": "Fallback verificato",
    }

    merged = merge_calendar_events([automatic], [configured], [configured])

    assert len(merged) == 1
    assert merged[0]["source_id"] == "uefa-draw-123"
    assert merged[0]["venue"] == "Grimaldi Forum"
    assert merged[0]["notes"] == "Fallback verificato"


def test_automatic_draw_reuses_uid_from_configured_fallback() -> None:
    previous = {
        "uid": "stable-draw@milan-calendar",
        "source_id": "configured-draw",
        "source": "Calendario ufficiale",
        "source_url": "https://www.uefa.com/draws/",
        "event_kind": "draw",
        "title": "Sorteggio fase campionato Europa League 2026/27",
        "competition": "UEFA Europa League",
        "start": "2026-08-28T13:00:00+02:00",
        "all_day": False,
        "last_modified": "2026-08-20T08:00:00Z",
        "sequence": 0,
    }
    automatic = {
        **previous,
        "uid": "",
        "source_id": "uefa-draw-123",
        "source": "UEFA",
        "title": "Sorteggio fase campionato UEFA Europa League 2026/27",
    }

    canonical = _canonical_event(
        automatic, [previous], "2026-08-28T08:00:00Z", set()
    )

    assert canonical["uid"] == "stable-draw@milan-calendar"
    assert canonical["sequence"] == 1


def test_calendar_events_are_filtered_by_milan_participation(tmp_path: Path) -> None:
    path = tmp_path / "calendar_events.json"
    path.write_text(
        json.dumps({
            "events": [
                {
                    "id": "uel-draw",
                    "title": "Sorteggio Europa League",
                    "competition": "UEFA Europa League",
                    "start": "2026-08-28T13:00:00+02:00",
                    "source_url": "https://www.uefa.com/uefaeuropaleague/draws/",
                    "participation_confirmed": True,
                },
                {
                    "id": "ucl-draw",
                    "title": "Sorteggio Champions League",
                    "competition": "UEFA Champions League",
                    "start": "2026-08-27T18:00:00+02:00",
                    "source_url": "https://www.uefa.com/uefachampionsleague/draws/",
                },
            ]
        }),
        encoding="utf-8",
    )

    events = load_calendar_events(path, set())

    assert [event["source_id"] for event in events] == ["uel-draw"]
    assert events[0]["event_kind"] == "draw"
    assert events[0]["reminder_minutes"] == 30


def test_draw_ical_has_distinct_summary_and_30_minute_alarm() -> None:
    event = {
        "uid": "uel-draw@milan-calendar",
        "event_kind": "draw",
        "title": "Sorteggio fase campionato Europa League 2026/27",
        "competition": "UEFA Europa League",
        "start": "2026-08-28T13:00:00+02:00",
        "all_day": False,
        "venue": "Grimaldi Forum",
        "location": "Monaco",
        "source_url": "https://www.uefa.com/uefaeuropaleague/draws/",
        "last_modified": "2026-08-28T08:00:00Z",
        "sequence": 0,
        "reminder_minutes": 30,
    }

    parsed = next(
        component
        for component in Calendar.from_ical(build_ical([event])).walk()
        if component.name == "VEVENT"
    )
    alarm = next(component for component in parsed.subcomponents if component.name == "VALARM")
    description = parsed.decoded("description").decode()

    assert parsed.decoded("summary").decode().startswith("🎲")
    assert "Tipo: Sorteggio" in description
    assert "Orario (Roma): 28/08/2026 13:00" in description
    assert "Milan:" not in description
    assert alarm.decoded("trigger").total_seconds() == -30 * 60


def test_parse_espn_standings_json_extracts_milan_row() -> None:
    def entry(team_id: str, name: str, rank: int, points: int) -> dict:
        return {
            "team": {"id": team_id, "displayName": name},
            "stats": [
                {"name": "rank", "value": rank},
                {"name": "points", "value": points},
                {"name": "gamesPlayed", "value": 10},
                {"name": "wins", "value": 5},
                {"name": "ties", "value": 3},
                {"name": "losses", "value": 2},
                {"name": "pointDifferential", "value": 7},
            ],
        }

    payload = {
        "children": [{
            "standings": {
                "entries": [
                    entry("1", "Inter", 2, 21),
                    entry("2", "Juventus", 3, 19),
                    entry("103", "AC Milan", 4, 18),
                    entry("3", "Roma", 5, 17),
                    entry("4", "Napoli", 6, 16),
                ]
            }
        }]
    }

    standing = parse_espn_standings_json(payload)

    assert standing == {
        "position": 4,
        "points": 18,
        "played": 10,
        "wins": 5,
        "draws": 3,
        "losses": 2,
        "goal_difference": 7,
        "context": [
            {"team": "Inter", "position": 2, "points": 21, "played": 10},
            {"team": "Juventus", "position": 3, "points": 19, "played": 10},
            {"team": "Milan", "position": 4, "points": 18, "played": 10},
            {"team": "Roma", "position": 5, "points": 17, "played": 10},
            {"team": "Napoli", "position": 6, "points": 16, "played": 10},
        ],
        "provisional": False,
        "source": "ESPN",
    }


def test_parse_official_lega_standings_json_extracts_milan_window() -> None:
    def team(name: str, rank: int, points: int) -> dict:
        return {
            "shortName": name,
            "officialName": "AC Milan" if name == "Milan" else name,
            "stats": [
                {"statsId": "rank", "statsValue": rank},
                {"statsId": "points", "statsValue": points},
                {"statsId": "matches-played", "statsValue": 10},
                {"statsId": "win", "statsValue": 5},
                {"statsId": "draw", "statsValue": 3},
                {"statsId": "lose", "statsValue": 2},
                {"statsId": "goal-difference", "statsValue": 7},
            ],
        }

    payload = {
        "standings": [{
            "teams": [
                team("Inter", 2, 21), team("Juventus", 3, 19),
                team("Milan", 4, 18), team("Roma", 5, 17),
                team("Napoli", 6, 16),
            ]
        }]
    }

    standing = parse_lega_standings_json(payload)

    assert standing is not None
    assert standing["position"] == 4
    assert standing["goal_difference"] == 7
    assert standing["provisional"] is False
    assert standing["source"] == "Lega Serie A"
    assert [row["team"] for row in standing["context"]] == [
        "Inter", "Juventus", "Milan", "Roma", "Napoli"
    ]


def test_parse_espn_pending_recoveries_json_names_postponed_matches() -> None:
    def event(home: str, away: str, status: str) -> dict:
        return {
            "status": {"type": {"name": status}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": home}},
                    {"homeAway": "away", "team": {"displayName": away}},
                ]
            }],
        }

    recoveries = parse_espn_pending_recoveries_json({
        "events": [
            event("SS Lazio", "AC Milan", "STATUS_POSTPONED"),
            event("Roma", "Inter", "STATUS_SCHEDULED"),
        ]
    })

    assert recoveries == ["SS Lazio–Milan"]


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


def test_milan_and_ac_milan_aliases_do_not_create_duplicates() -> None:
    base = {
        "home_team": "Torino",
        "away_team": "Milan",
        "competition": "Serie A",
        "start": "2026-08-23T20:45:00+02:00",
        "all_day": False,
        "source": "AC Milan",
        "source_url": "https://www.acmilan.com/schedule",
    }
    fallback = {
        **base,
        "away_team": "AC Milan",
        "competition": "Italian Serie A",
        "source": "ESPN",
        "source_url": "https://www.espn.com/match",
    }

    merged = merge_remote_events([base, fallback])

    assert len(merged) == 1


def test_now_overlay_keeps_dazn_as_primary_serie_a_broadcaster() -> None:
    official = parse_official_html(
        official_html(
            [
                official_match(
                    providerId="torino-milan",
                    datetime="2026-08-23T18:45:00Z",
                    matchDay="1",
                    homeTeam={"name": "Torino"},
                    awayTeam={"name": "Milan"},
                )
            ]
        ),
        "https://www.acmilan.com/schedule",
    )[0]
    overlay = parse_schedule_html(
        '<script type="application/ld+json">'
        '{"text":"Domenica 23 agosto ore 20:45 - Torino vs Milan."}'
        "</script>",
        "NOW",
        "https://www.nowtv.it/sport/calcio/milan",
        2026,
    )[0]

    merged = merge_remote_events([official, overlay])

    assert merged[0]["broadcast_it"] == "DAZN; Sky Sport e NOW"
    assert len(merged[0]["broadcast_source_urls"]) == 2


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
    assert second[0]["start"] == "2026-09-12T21:45:00+02:00"
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
    assert second[0]["start"] == "2026-08-20T20:45:00+02:00"


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
        "serie_a_standing": {
            "position": 4,
            "points": 18,
            "played": 10,
            "goal_difference": 7,
            "provisional": True,
            "pending_recoveries": ["Lazio–Milan"],
            "updated_at": "2026-08-24T10:00:00Z",
            "context": [
                {"team": "Inter", "position": 2, "points": 21, "played": 10},
                {"team": "Juventus", "position": 3, "points": 19, "played": 10},
                {"team": "Milan", "position": 4, "points": 18, "played": 10},
                {"team": "Roma", "position": 5, "points": 17, "played": 10},
                {"team": "Napoli", "position": 6, "points": 16, "played": 10},
            ],
        },
    }
    payload = build_ical([event])
    calendar = Calendar.from_ical(payload)
    parsed = next(component for component in calendar.walk() if component.name == "VEVENT")
    alarm = next(component for component in parsed.subcomponents if component.name == "VALARM")

    assert parsed.decoded("dtstart").tzinfo is not None
    assert getattr(parsed.decoded("dtstart").tzinfo, "key", None) == "Europe/Rome"
    assert alarm.decoded("trigger").total_seconds() == -(2 * 60 + 30) * 60
    description = parsed.decoded("description").decode()
    assert "Orario (Roma): 12/09/2026 20:45" in description
    assert "Dove vederla in Italia: DAZN" in description
    assert (
        "Classifica Serie A provvisoria — recupero Lazio–Milan ancora da disputare:"
        in description
    )
    assert "  2. Inter — 21 pt" in description
    assert "▶ 4. Milan — 18 pt — 10 PG — DR +7" in description
    assert "  6. Napoli — 16 pt" in description
    assert "https://" not in description
    assert parsed.decoded("url") == "https://example.com/match"
    assert parsed.decoded("sequence") == 3
    assert b"X-WR-TIMEZONE:Europe/Rome" in payload


def test_standing_is_attached_to_current_and_next_serie_a_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manual_events.json").write_text(
        '{"events": []}\n', encoding="utf-8"
    )
    previous, current, following = parse_official_html(
        official_html([
            official_match(
                providerId="previous",
                datetime="2026-07-25T18:45:00Z",
                homeTeam={"name": "Inter"},
                awayTeam={"name": "Milan"},
            ),
            official_match(
                providerId="current",
                datetime="2026-08-01T18:45:00Z",
                homeTeam={"name": "Milan"},
                awayTeam={"name": "Roma"},
            ),
            official_match(
                providerId="following",
                datetime="2026-09-20T18:45:00Z",
                homeTeam={"name": "Napoli"},
                awayTeam={"name": "Milan"},
            ),
        ]),
        "https://www.acmilan.com/schedule",
    )
    standing = {
        "position": 4, "points": 4, "played": 2, "goal_difference": 1,
        "source": "Lega Serie A",
        "context": [{"team": "Milan", "position": 4, "points": 4, "played": 2}],
    }
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult(
            [previous, current, following], ["AC Milan"], [], serie_a_standing=standing
        ),
    )

    events = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))

    assert "serie_a_standing" not in events[0]
    assert events[1]["serie_a_standing"]["source"] == "Lega Serie A"
    assert events[2]["serie_a_standing"]["source"] == "Lega Serie A"


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


def test_live_dazn_time_corrects_stale_manual_now() -> None:
    remote = {
        "source": "AC Milan",
        "source_id": "friendly-1",
        "source_url": "https://www.acmilan.com/",
        "home_team": "Manchester United",
        "away_team": "AC Milan",
        "competition": "Amichevole",
        "start": "2026-08-15T16:45:00+02:00",
        "all_day": False,
        "time_source": "DAZN",
        "time_source_url": "https://www.dazn.com/it-IT/schedule",
        "broadcast_it": "DAZN",
        "broadcast_source_url": "https://www.dazn.com/it-IT/schedule",
    }
    manual = {
        "source": "Manuale",
        "source_id": "friendly-manual",
        "home_team": "AC Milan",
        "away_team": "Manchester United",
        "competition": "Amichevole",
        "start": "2026-08-15T14:00:00+02:00",
        "all_day": False,
        "time_source": "NOW",
        "time_source_url": "https://www.nowtv.it/sport/calcio/milan",
        "broadcast_it": "Sky Sport e NOW",
        "venue": "Tarczyński Arena, Wrocław",
    }

    merged = merge_manual_events([remote], [manual])

    assert merged[0]["start"] == "2026-08-15T16:45:00+02:00"
    assert merged[0]["time_source"] == "DAZN"
    assert merged[0]["broadcast_it"] == "DAZN"
    assert merged[0]["venue"] == "Tarczyński Arena, Wrocław"


def test_explicitly_locked_manual_time_can_override_dazn() -> None:
    remote = {
        "source": "AC Milan",
        "source_id": "friendly-1",
        "home_team": "Manchester United",
        "away_team": "AC Milan",
        "competition": "Amichevole",
        "start": "2026-08-15T16:45:00+02:00",
        "all_day": False,
        "time_source": "DAZN",
    }
    manual = {
        "source": "Manuale",
        "source_id": "friendly-manual",
        "home_team": "Manchester United",
        "away_team": "AC Milan",
        "competition": "Amichevole",
        "start": "2026-08-15T17:00:00+02:00",
        "all_day": False,
        "time_source": "Organizzatore",
        "lock_time": True,
    }

    merged = merge_manual_events([remote], [manual])

    assert merged[0]["start"] == "2026-08-15T17:00:00+02:00"
    assert merged[0]["time_source"] == "Organizzatore"


def test_events_json_is_normalized_to_rome_with_dst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "manual_events.json").write_text('{"events": []}\n', encoding="utf-8")
    summer, winter = parse_official_html(
        official_html(
            [
                official_match(providerId="summer", datetime="2026-09-12T18:45:00Z"),
                official_match(
                    providerId="winter",
                    datetime="2027-01-12T19:45:00Z",
                    homeTeam={"name": "Napoli"},
                    awayTeam={"name": "AC Milan"},
                ),
            ]
        ),
        "https://www.acmilan.com/schedule",
    )
    monkeypatch.setattr(
        "milan_calendar.generator.fetch_remote_events",
        lambda session, today: FetchResult([summer, winter], ["AC Milan"], []),
    )

    events = update_calendar(tmp_path, session=object(), today=date(2026, 8, 1))

    assert [event["start"] for event in events] == [
        "2026-09-12T20:45:00+02:00",
        "2027-01-12T20:45:00+01:00",
    ]


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


def test_dazn_time_has_priority_over_now() -> None:
    base = parse_official_html(official_html([official_match()]), "https://www.acmilan.com/schedule")[0]
    now = dict(
        base,
        source="NOW",
        source_url="https://www.nowtv.it/sport/calcio/milan",
        start="2026-09-12T14:00:00+02:00",
        _time_overlay=True,
        _time_priority=50,
    )
    dazn = dict(
        base,
        source="DAZN",
        source_url="https://www.dazn.com/it-IT/schedule",
        start="2026-09-12T16:45:00+02:00",
        _time_overlay=True,
        _time_priority=60,
        broadcast_it="DAZN",
    )

    merged = merge_remote_events([base, dazn, now])

    assert merged[0]["start"] == "2026-09-12T16:45:00+02:00"
    assert merged[0]["time_source"] == "DAZN"
    assert merged[0]["broadcast_it"] == "DAZN"
    assert {item["source"] for item in merged[0]["time_conflicts"]} == {
        "AC Milan",
        "NOW",
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


def test_official_international_classifier_excludes_domestic_and_friendlies() -> None:
    base = {
        "event_kind": "match",
        "home_team": "Milan",
        "away_team": "Benfica",
        "title": "Milan - Benfica",
        "round": "League phase",
    }
    assert _is_official_international_match(
        dict(base, competition="UEFA Europa League")
    )
    assert _is_official_international_match(
        dict(base, competition="Future FIFA International Club Cup")
    )
    assert not _is_official_international_match(dict(base, competition="Serie A"))
    assert not _is_official_international_match(
        dict(base, competition="International Club Friendly", round="Pre-season tour")
    )


def test_broadcast_page_requires_exact_fixture_date_and_viewing_evidence() -> None:
    event = {
        "event_kind": "match",
        "home_team": "Milan",
        "away_team": "Benfica",
        "competition": "UEFA Europa League",
        "start": "2026-09-16T21:00:00+02:00",
    }
    assert page_confirms_fixture(
        "<p>Milan - Benfica, 16 settembre 2026: diretta TV8 e streaming.</p>",
        event,
        "TV8",
    )
    assert not page_confirms_fixture(
        "<p>TV8 ha i diritti dell'Europa League. Milan e Benfica partecipano.</p>",
        event,
        "TV8",
    )
    assert not page_confirms_fixture(
        "<p>Calendario: Milan-Benfica, 16 settembre 2026 alle 21.</p>",
        event,
        "Sky Sport / NOW",
    )


def test_confirmed_broadcast_survives_source_failure() -> None:
    event = {
        "event_kind": "match",
        "home_team": "Milan",
        "away_team": "Benfica",
        "competition": "UEFA Europa League",
        "round": "1",
        "start": "2026-09-16T21:00:00+02:00",
        "status": "Fixture",
    }
    option = {
        "country": "Italia",
        "country_code": "IT",
        "broadcaster": "TV8",
        "access": "free",
        "platforms": "TV + streaming",
        "language": "italiano",
        "registration_required": False,
        "url": "https://www.tv8.it/sport",
        "source_url": "https://www.tv8.it/sport",
        "status": "confirmed",
        "verified_at": "2026-08-31T10:00:00Z",
        "priority": 100,
    }
    previous = [dict(event, broadcast_options=[option])]

    class FailingSession:
        def get(self, url: str, timeout: int) -> None:
            raise requests.RequestException("temporaneamente non disponibile")

    updated, errors = apply_verified_broadcasts(
        FailingSession(),
        [event],
        previous,
        [{
            "country": "Italia", "country_code": "IT", "broadcaster": "TV8",
            "access": "free", "url": "https://www.tv8.it/sport",
        }],
        "2026-09-01T10:00:00Z",
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert errors
    assert updated[0]["broadcast_options"] == [option]
    assert updated[0]["broadcast_italy_tbc"] is False


def test_broadcast_verification_changes_only_international_broadcast_fields() -> None:
    international = {
        "event_kind": "match", "home_team": "Milan", "away_team": "Benfica",
        "competition": "UEFA Europa League", "round": "1", "venue": "San Siro",
        "start": "2026-09-16T21:00:00+02:00", "status": "Fixture",
        "source_url": "https://www.acmilan.com/", "uid": "stable@milan-calendar",
    }
    domestic = dict(
        international,
        away_team="Roma",
        competition="Serie A",
        uid="domestic@milan-calendar",
    )

    class Response:
        text = "Milan - Benfica, 16 settembre 2026: diretta TV8 e streaming."

        def raise_for_status(self) -> None:
            return None

    class Session:
        def get(self, url: str, timeout: int) -> Response:
            return Response()

    updated, errors = apply_verified_broadcasts(
        Session(),
        [international, domestic],
        [],
        [{
            "country": "Italia", "country_code": "IT", "broadcaster": "TV8",
            "access": "free", "platforms": "TV + streaming", "language": "italiano",
            "url": "https://www.tv8.it/sport", "priority": 100,
        }],
        "2026-09-01T10:00:00Z",
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert not errors
    assert "broadcast_options" in updated[0]
    assert updated[1] == domestic
    for key, value in international.items():
        assert updated[0][key] == value


def test_structured_broadcast_description_orders_italy_and_foreign_links() -> None:
    data = {
        "broadcast_options": [
            {
                "country": "Italia", "country_code": "IT", "broadcaster": "Prime Video",
                "access": "included", "platforms": "streaming", "language": "italiano",
                "registration_required": False, "url": "https://www.primevideo.com/sports",
            },
            {
                "country": "Austria", "country_code": "AT", "broadcaster": "ServusTV",
                "access": "free", "platforms": "TV + streaming", "language": "tedesco",
                "registration_required": False, "url": "https://www.servustv.com/sport/",
            },
        ],
        "broadcast_international_tbc": False,
    }
    text = "\n".join(_broadcast_description_lines(data))
    assert "🇮🇹 Italia — Prime Video" in text
    assert "Incluso nell'abbonamento · streaming · italiano" in text
    assert "🇦🇹 Austria — ServusTV" in text
    assert "https://www.servustv.com/sport/" in text


def test_subscription_page_has_iphone_fallback() -> None:
    html = (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8")
    assert "webcal://dizzle0987.github.io/milan-calendar/calendar.ics" in html
    assert "Aggiungi calendario con iscrizione" in html
    assert "navigator.clipboard.writeText(calendarUrl)" in html
    assert "Android — Google Calendar" in html
    assert "Mac — Calendario Apple" in html
    assert "PC Windows — Outlook" in html
    assert "Sottoscrivi dal Web" in html
