from copy import deepcopy
import json
from pathlib import Path

import pytest
from icalendar import Calendar

from milan_calendar.generator import (
    apply_manual_international_tv_options, _broadcast_description_lines, build_ical,
)
from milan_calendar import generator

ROOT = Path(__file__).parents[1]


def configuration():
    return json.loads((ROOT / "data/manual_events.json").read_text())


def fixture():
    return {
        "home_team": "AFC Bournemouth", "away_team": "AC Milan",
        "competition": "UEFA Europa League", "start": "2026-10-22T21:00:00+02:00",
        "title": "AFC Bournemouth - AC Milan", "uid": "unchanged@example",
        "last_modified": "2026-10-20T12:00:00Z", "sequence": 1, "home_away": "Trasferta",
        "broadcast_options": [{"country_code": "IT", "country": "Italia",
            "broadcaster": "Sky Sport e NOW", "access": "paid"}],
        "broadcast_international_tbc": True,
    }


def test_qazsport_manual_tv_option_is_not_a_free_stream_confirmation():
    event = fixture()
    before = deepcopy(event)
    result, = apply_manual_international_tv_options([event], configuration())
    option, = result["foreign_tv_broadcasts"]
    assert option["broadcaster"] == "Qazsport"
    assert option["country_code"] == "KZ"
    assert option["status"] == "UNKNOWN"
    assert option["access"] == "unknown"
    assert option["match_confirmed"] is True
    assert option["web_match_confirmed"] is False
    assert option["web_stream_free"] == "unknown"
    assert option["broadcast_free"] == "unknown"
    assert option["watch_url"] == "https://qazsporttv.kz/kz/live"
    assert option["source_schedule"].endswith("/2026-10-22")
    assert {k: v for k, v in result.items() if k != "foreign_tv_broadcasts"} == before
    assert event == before
    assert apply_manual_international_tv_options([result], configuration()) == [result]


@pytest.mark.parametrize("change", [
    {"start": "2026-10-29T21:00:00+01:00"},
    {"home_team": "Salzburg"},
    {"home_team": "AC Milan", "away_team": "AFC Bournemouth"},
    {"competition": "UEFA Champions League"},
    {"competition": "Serie A"},
    {"competition": "Coppa Italia"},
    {"competition": "Supercoppa Italiana"},
    {"event_kind": "draw"},
])
def test_manual_tv_option_does_not_touch_other_fixtures(change):
    event = {**fixture(), **change}
    assert apply_manual_international_tv_options([event], configuration()) == [event]


def test_manual_tv_option_requires_official_links():
    payload = configuration()
    payload["international_tv_options"][0]["watch_url"] = "https://untrusted.example/live"
    event = fixture()
    assert apply_manual_international_tv_options([event], payload) == [event]


def test_ics_presents_qazsport_separately_and_keeps_italian_priority():
    event = fixture()
    result, = apply_manual_international_tv_options([event], configuration())
    text = "\n".join(_broadcast_description_lines(result))
    assert text.index("Sky Sport e NOW") < text.index("Qazsport")
    assert "TV confermata: Qazsport — Kazakistan" in text
    assert "Player web funzionante (verifica utente)" in text
    assert "Gratuità web della partita da confermare" in text
    assert "Sito ufficiale: https://qazsporttv.kz/kz/live" in text
    assert "ALTERNATIVE GRATUITE ALL'ESTERO" not in text
    assert "Streaming web gratuito" not in text
    component, = Calendar.from_ical(build_ical([result])).walk("VEVENT")
    assert "Qazsport" in str(component["description"])
    assert str(component["uid"]) == event["uid"]
    assert component.decoded("dtstart").isoformat() == event["start"]


def test_existing_calendar_only_gets_the_target_annotation():
    events = json.loads((ROOT / "data/events.json").read_text())["events"]
    # Exercise addition even after the checked-in snapshot includes this note.
    for event in events:
        event.pop("foreign_tv_broadcasts", None)
    result = apply_manual_international_tv_options(events, configuration())
    changed = [(old, new) for old, new in zip(events, result) if old != new]
    assert len(changed) == 1
    old, new = changed[0]
    assert "Bournemouth" in old["home_team"]
    assert old["start"].startswith("2026-10-22")
    assert {k: v for k, v in new.items() if k != "foreign_tv_broadcasts"} == old
    unchanged_old = [e for e in events if e != old]
    unchanged_new = [e for e in result if e != new]
    assert build_ical(unchanged_old) == build_ical(unchanged_new)


def test_normal_generation_keeps_qazsport_after_fresh_broadcast_resolution(tmp_path, monkeypatch):
    """Run the normal writer twice, offline and exclusively in pytest's temp dir."""
    data = tmp_path / "data"
    data.mkdir()
    payload = configuration()
    payload["events"] = []
    (data / "manual_events.json").write_text(json.dumps(payload))
    event = fixture()

    def fetch(*args, **kwargs):
        return generator.FetchResult(events=[deepcopy(event)], successful_sources=["AC Milan"], errors=[])

    def resolve(session, events, *args):
        fresh = deepcopy(events)
        for item in fresh:
            item.pop("foreign_tv_broadcasts", None)
        return fresh, []

    monkeypatch.setattr(generator, "fetch_remote_events", fetch)
    monkeypatch.setattr(generator, "apply_verified_broadcasts", resolve)
    first = generator.update_calendar(tmp_path)
    second = generator.update_calendar(tmp_path)
    assert first == second
    saved = json.loads((data / "events.json").read_text())["events"][0]
    assert saved["foreign_tv_broadcasts"][0]["status"] == "UNKNOWN"
    assert saved["foreign_tv_broadcasts"][0]["web_stream_free"] == "unknown"
    assert saved["start"] == event["start"]
    assert saved["uid"] == event["uid"]
    assert saved["broadcast_options"] == event["broadcast_options"]
    component, = Calendar.from_ical((tmp_path / "calendar.ics").read_bytes()).walk("VEVENT")
    assert "Qazsport" in str(component["description"])
    assert component.decoded("dtstart").isoformat() == event["start"]
