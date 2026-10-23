"""Local fixtures follow the public ru/kz Livewire schedule observed 2026-10-23."""
from datetime import date, datetime, timezone
from html import escape
import json
from pathlib import Path

import pytest
import requests

from milan_calendar import generator
from milan_calendar.qazsport import parse_qazsport_epg, qazsport_fixture_start

ROOT = Path(__file__).parents[1]


def source():
    return next(s for s in generator.load_broadcast_sources(ROOT / "data/broadcast_sources.json")
                if s["broadcaster"] == "Qazsport")


def event(**changes):
    return {"event_kind": "match", "home_team": "AFC Bournemouth", "away_team": "AC Milan",
            "competition": "UEFA Europa League", "start": "2026-10-22T21:00:00+02:00",
            "title": "Bournemouth - Milan", "status": "Fixture", "uid": "unchanged",
            "broadcast_it": "Sky Sport e NOW", **changes}


def snapshot(day="2026-10-22", locale="kz", **changes):
    # Reduced real structured rows: titles, descriptions, times and LIVE flag.
    row = {"id": 9389, "title": "Борнмут (Англия) – Милан (Италия)",
           "description": "Футбол. УЕФА Еуропа Лигасы. 3 тур",
           "time": "23:50", "format": "LIVE", **changes}
    schedule = [[{"id": 9388, "time": "21:35", "title": "Ювентус – Ренн",
                 "description": "Футбол. УЕФА Еуропа Лигасы. 3 тур", "format": "LIVE"}, {"s": "std"}],
                [row, {"s": "std"}], [{"id": 9390, "time": "02:00",
        "title": "УЕФА Чемпиондар Лигасының шолуы", "description": "Футбол", "format": ""}, {"s": "std"}]]
    payload = {"data": {"selectedDate": day, "schedule": [schedule, {"s": "clctn"}]},
               "memo": {"name": "app.timetable.schedule", "path": f"{locale}/program/{day}"}}
    return f'<main wire:snapshot="{escape(json.dumps(payload, ensure_ascii=False), quote=True)}"></main>'


def matched(html=None, fixture=None):
    return [start for row in parse_qazsport_epg(html or snapshot(), date(2026, 10, 22))
            if (start := qazsport_fixture_start(row, fixture or event(), source(), "europa-league"))]


@pytest.mark.parametrize("locale", ["ru", "kz"])
def test_real_structured_schedule_and_midnight_rollover(locale):
    rows = parse_qazsport_epg(snapshot(locale=locale), date(2026, 10, 22))
    assert len(rows) == 2
    assert rows[-1]["end"].isoformat() == "2026-10-23T02:00:00+05:00"
    assert matched(snapshot(locale=locale))[0].isoformat() == "2026-10-22T20:50:00+02:00"


@pytest.mark.parametrize("change", [
    {"title": "Ювентус – Милан"}, {"title": "Борнмут – Интер Милан"},
    {"title": "Борнмут – Милан U19"}, {"title": "Борнмут – Милан (U19)"},
    {"description": "Футбол. УЕФА Чемпиондар Лигасы"},
    {"description": "Обзор футбола"}, {"format": ""}, {"time": "22:00"},
    {"description": "УЕФА Еуропа Лигасы / УЕФА Чемпиондар Лигасы"},
    {"title": "Борнмут – Милан – Обзор"},
])
def test_reject_wrong_teams_competition_replay_youth_and_time(change):
    assert matched(snapshot(**change)) == []


def test_missing_alias_is_not_guessed_and_reverse_order_works():
    assert matched(snapshot(title="Милан (Италия) - Борнмут (Англия)"))
    assert matched(snapshot(title="Незнакомый клуб – Милан")) == []


def test_wrong_date_schema_and_duplicate_snapshots():
    assert parse_qazsport_epg(snapshot(day="2026-10-21"), date(2026, 10, 22)) == []
    assert parse_qazsport_epg('<main wire:snapshot="not-json">', date(2026, 10, 22)) == []
    assert parse_qazsport_epg("<html>No schedule yet</html>", date(2026, 10, 22)) == []
    assert len(matched(snapshot() * 2)) == 1
    assert matched(fixture=event(start="2026-10-23T21:00:00+02:00")) == []


@pytest.mark.parametrize(("kickoff", "local_time", "expected"), [
    ("2026-10-22T21:00:00+02:00", "23:50", "2026-10-22T20:50:00+02:00"),
    ("2026-10-22T20:00:00+01:00", "23:50", "2026-10-22T20:50:00+02:00"),
])
def test_equivalent_absolute_times(kickoff, local_time, expected):
    assert matched(snapshot(time=local_time), event(start=kickoff))[0].isoformat() == expected


def test_cet_after_dst_and_local_date_crossing():
    fixture = event(start="2026-10-29T21:00:00+01:00")
    # 00:50 on the 30th belongs to the broadcast day of the 29th.
    html = snapshot(day="2026-10-29", time="00:50")
    rows = parse_qazsport_epg(html, date(2026, 10, 29))
    start = qazsport_fixture_start(rows[-1], fixture, source(), "europa-league")
    # Next programme at 02:00 gives only 60 minutes after kickoff: reject.
    assert start is None
    html = html.replace("02:00", "03:00")
    row = parse_qazsport_epg(html, date(2026, 10, 29))[-1]
    assert qazsport_fixture_start(row, fixture, source(), "europa-league").isoformat() == "2026-10-29T20:50:00+01:00"


class Response:
    def __init__(self, text, status=200): self.text, self.status_code = text, status
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, html=None, robots="User-agent: *\nDisallow:\n", status=200):
        self.calls, self.html, self.robots, self.status = [], html or snapshot(), robots, status
    def get(self, url, **kwargs):
        self.calls.append(url)
        assert kwargs == {"timeout": 10, "allow_redirects": False}
        if url.endswith("robots.txt"): return Response(self.robots)
        return Response(self.html, self.status)


def run(session, fixture=None):
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    return generator.apply_verified_broadcasts(session, [fixture or event()], [], [source()], now.isoformat(), now)


def test_runtime_tv_only_reconciles_registry_without_free_claim(monkeypatch):
    monkeypatch.setattr(generator, "identify_opponent_country", lambda *a: (
        {"country_code": "GB", "country": "Regno Unito", "source": "fixture"}, None))
    session = Session()
    original = event()
    result, errors = run(session, original)
    assert not errors
    candidate, = result[0]["broadcast_candidates"]
    assert candidate["broadcaster"] == "Qazsport"
    assert candidate["country_code"] == "KZ" and candidate["priority"] == 110
    assert candidate["watch_url"] == "https://qazsporttv.kz/ru/live"
    assert candidate["confidence"] == 95 and candidate["match_confirmed"] is True
    assert candidate["status"] == "UNKNOWN"
    assert candidate["web_stream_free"] == candidate["broadcast_free"] == "unknown"
    assert candidate["source_schedule"] == "https://qazsporttv.kz/kz/program/2026-10-22"
    assert result[0]["foreign_free_broadcasts"] == []
    assert result[0]["start"] == original["start"] and result[0]["uid"] == original["uid"]
    assert original == event()
    assert session.calls == ["https://qazsporttv.kz/robots.txt", "https://qazsporttv.kz/kz/program/2026-10-22",
                             "https://qazsporttv.kz/kz/program/2026-10-23"]


@pytest.mark.parametrize("status", [302, 403, 404, 429, 500])
def test_http_failures_never_confirm(status, monkeypatch):
    monkeypatch.setattr(generator, "identify_opponent_country", lambda *a: (None, None))
    result, errors = run(Session(status=status))
    assert errors and not result[0]["broadcast_candidates"]


@pytest.mark.parametrize("robots", ["User-agent: *\nDisallow: /kz/program", "<html>Error</html>"])
def test_robots_restrictions_fail_closed(robots):
    session = Session(robots=robots)
    with pytest.raises(ValueError): generator._fetch_epg_rows(session, source(), [event()])
    assert len(session.calls) == 1


def test_timeout_is_nonblocking(monkeypatch):
    monkeypatch.setattr(generator, "identify_opponent_country", lambda *a: (None, None))
    class Offline:
        def get(self, *a, **kw): raise requests.Timeout("offline")
    result, errors = run(Offline())
    assert errors and not result[0]["broadcast_candidates"]


@pytest.mark.parametrize("competition", ["Serie A", "Coppa Italia", "Supercoppa Italiana"])
def test_domestic_output_identical_and_no_network(competition):
    fixture = event(competition=competition)
    class Offline:
        def get(self, *a, **kw): raise AssertionError("No domestic probing")
    result, errors = run(Offline(), fixture)
    assert not errors and result == [fixture]


def test_published_ics_and_historical_confirmation_are_unchanged():
    events = json.loads((ROOT / "data/events.json").read_text())["events"]
    assert generator.build_ical(events) == (ROOT / "calendar.ics").read_bytes()
    # Historical state is independent of the registry's conservative defaults.
    historical = [e for e in events if "2026-10-22" in str(e.get("start")) and "Bournemouth" in str(e)]
    assert historical


def test_mixed_calendar_retains_national_data_and_existing_italian_option(monkeypatch):
    monkeypatch.setattr(generator, "identify_opponent_country", lambda *a: (None, None))
    domestic = event(competition="Serie A", home_team="AC Milan", away_team="Torino",
                     start="2026-10-25T20:45:00+01:00", uid="domestic")
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    result, errors = generator.apply_verified_broadcasts(
        Session(), [domestic, event()], [], [source()], now.isoformat(), now)
    assert not errors and result[0] == domestic
    assert result[1]["broadcast_it"] == "Sky Sport e NOW"


def test_missing_end_and_malformed_json_do_not_supply_invented_duration():
    html = snapshot().replace('02:00', 'n/a')
    assert parse_qazsport_epg(html, date(2026, 10, 22)) == []


def test_missing_schedule_is_nonblocking_and_never_confirms(monkeypatch):
    monkeypatch.setattr(generator, "identify_opponent_country", lambda *a: (None, None))
    result, errors = run(Session(html="<html>No future schedule yet</html>"))
    assert not errors and result[0]["broadcast_candidates"] == []
