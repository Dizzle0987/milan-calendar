from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import requests

from milan_calendar.generator import apply_verified_broadcasts, build_ical, next_international_match

ROOT = Path(__file__).parents[1]
UID = "3dada53d30468e73c19eae6d@milan-calendar"


def events():
    return json.loads((ROOT / "data/events.json").read_text())["events"]


def cbc(event):
    return next(c for c in event["broadcast_candidates"] if c["broadcaster"] == "CBC Sport" and c["country_code"] == "AZ")


def test_historical_confirmation_identifies_the_actual_fixture():
    event = next(e for e in events() if e["uid"] == UID)
    assert (event["home_team"], event["away_team"], event["start"]) == (
        "Salzburg", "AC Milan", "2026-10-15T18:45:00+02:00")
    candidate = cbc(event)
    assert candidate["status"] == "CONFIRMED_FREE"
    assert candidate["web_stream_free"] is True
    assert candidate["web_subscription_required"] is False
    assert candidate["watch_url"] == "https://www.cbcsport.az/live/"
    evidence, = candidate["availability_evidence"]
    assert evidence["source_type"] == "user_confirmation"
    assert evidence["scope"] == "fixture"
    assert evidence["fixture_start"] == event["start"]
    assert evidence["fixture_home_team"] == event["home_team"]
    assert evidence["fixture_away_team"] == event["away_team"]
    assert evidence["subscription_required"] is False


def test_historical_confirmation_leaves_the_entire_ics_unchanged():
    assert build_ical(events()) == (ROOT / "calendar.ics").read_bytes()


def test_cbc_remains_priority_source_without_inheriting_past_confirmation():
    sources = json.loads((ROOT / "data/broadcast_sources.json").read_text())["sources"]
    source = next(s for s in sources if s["broadcaster"] == "CBC Sport")
    assert source["priority"] == 110
    assert source["market_tier"] == 1
    assert source["require_kickoff_time"] is True
    assert source["web_stream_free"] == "unknown"

    class OfflineSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("fixture: no new match evidence")

    snapshot = events()
    historical = next(e for e in snapshot if e["uid"] == UID)
    now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    upcoming = deepcopy(next_international_match(snapshot, now))
    assert upcoming is not None and upcoming["uid"] != UID
    result, _ = apply_verified_broadcasts(
        OfflineSession(), [historical, upcoming], [historical, upcoming], [source], now.isoformat(), now)
    retained = next(e for e in result if e["uid"] == UID)
    assert cbc(retained) == cbc(historical)
    future = next(e for e in result if e["uid"] == upcoming["uid"])
    assert all(c["status"] != "CONFIRMED_FREE" and c["web_stream_free"] != True
               for c in future.get("broadcast_candidates", []) if c["broadcaster"] == "CBC Sport")
