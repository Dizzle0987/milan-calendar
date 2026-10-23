import json
from datetime import datetime, timezone
from pathlib import Path

import requests
import pytest

from milan_calendar.generator import (
    apply_verified_broadcasts, classify_broadcast_candidate, load_broadcast_sources,
    _broadcast_description_lines, _verified_official_url,
)

ROOT = Path(__file__).parents[1]
ADDED = {"Rai 1", "Rai 2", "Rai Sport", "Canale 5", "Italia 1", "Rete 4",
         "20 Mediaset", "ORF 1", "ORF Sport+", "Qazsport"}


def sources():
    return load_broadcast_sources(ROOT / "data/broadcast_sources.json")


def fixture():
    return {"event_kind": "match", "home_team": "Milan", "away_team": "Porto",
            "competition": "UEFA Europa League", "start": "2026-11-05T21:00:00+01:00",
            "title": "Milan - Porto", "status": "Fixture", "broadcast_it": "Sky Sport e NOW"}


def test_official_channels_are_unique_and_do_not_infer_free_web_access():
    registry = sources()
    keys = [(s["country_code"], s["broadcaster"]) for s in registry]
    assert len(keys) == len(set(keys))
    assert ADDED <= {s["broadcaster"] for s in registry}
    for source in registry:
        if source["broadcaster"] not in ADDED:
            continue
        assert source["source_type"] == (
            "qazsport_epg" if source["broadcaster"] == "Qazsport" else "registry_only")
        assert source["access"] == "unknown"
        assert source["web_stream_free"] == "unknown"
        assert source["priority"] == 110
        assert _verified_official_url(source, "watch_url") == source["watch_url"]
        assert "youtube" not in source["watch_url"]
        assert classify_broadcast_candidate(source["access"], 100,
            rights_confirmed=True, match_confirmed=True) == "UNKNOWN"


def test_existing_epg_adapters_and_priority_sources_are_preserved():
    registry = sources()
    tv8 = next(s for s in registry if s["broadcaster"] == "TV8")
    servus = next(s for s in registry if s["broadcaster"] == "ServusTV / ServusTV On")
    cbc = next(s for s in registry if s["broadcaster"] == "CBC Sport")
    assert tv8["source_type"] == "tv8_api" and tv8["priority"] == 110
    assert tv8["watch_url"] == "https://www.tv8.it/streaming"
    assert servus["source_type"] == "registry_only" and servus["priority"] == 100
    assert servus["epg_identity_verified"] is False
    assert servus["country_code"] == "AT" and servus["access"] == "unknown"
    assert cbc["priority"] == 110 and cbc["market_tier"] == 1
    assert cbc["web_stream_free"] == "unknown"
    assert tv8["web_stream_free"] == servus["web_stream_free"] == "unknown"
    assert next(s for s in registry if s["broadcaster"] == "Sky Sport / Sky Go")["italian_primary"] is True


def test_registry_entries_do_not_probe_generic_players_or_confirm_a_future_match():
    class Offline:
        def __init__(self): self.urls = []
        def get(self, url, **kwargs):
            self.urls.append(url)
            raise requests.ConnectionError("fixture offline")

    session = Offline()
    registry = sources()
    selected = [s for s in registry if s["broadcaster"] in ADDED | {"TV8", "ServusTV / ServusTV On"}]
    now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    result, _ = apply_verified_broadcasts(session, [fixture()], [], selected, now.isoformat(), now)
    assert result[0]["broadcast_options"] == []
    assert not any(c["status"] == "CONFIRMED_FREE" for c in result[0]["broadcast_candidates"])
    assert not any(s["watch_url"] in session.urls for s in selected if s["broadcaster"] in ADDED)
    assert result[0]["broadcast_notes_compact"] is True
    assert "Sky Sport e NOW" in _broadcast_description_lines(result[0])[1]


def test_new_registry_channels_are_reconciled_by_existing_match_specific_guide():
    guide = {"country": "Austria", "country_code": "AT", "broadcaster": "Fixture guide",
        "access": "free", "url": "https://guide.example/event/milan-porto/42", "source_type": "guide",
        "guide_parser": "sport_tv_guide", "discover_broadcasters": True,
        "timezone": "Europe/Rome", "priority": 70}
    html = '''<title>Milan - Porto : Europa League</title>
      <div id="channelInfo"><div class="time full"><strong>21:00</strong></div>
      <div class="date full">Giovedi, 11-05-2026</div>
      <div class="station full">Rai 1 / Italia</div></div>
      <h3>Dove vedere in tv o diretta streaming</h3>
      <div class="liveOtherStations clearfix">
        <div class="stationLive active col-wrap" title="Rai 1 [IT] - Live: Milan - Porto">Rai 1 [IT]</div>
        <div class="stationLive col-wrap" title="ORF 1 [AT] - Live: Milan - Porto">ORF 1 [AT]</div>
      </div>'''

    class Response:
        text = html
        def raise_for_status(self): pass
        def json(self): return []

    class Session:
        def get(self, url, **kwargs): return Response()

    registry = [s for s in sources() if s["broadcaster"] in {"Rai 1", "ORF 1"}]
    now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    result, _ = apply_verified_broadcasts(Session(), [fixture()], [], [guide, *registry], now.isoformat(), now)
    candidates = {c["broadcaster"]: c for c in result[0]["broadcast_candidates"]}
    assert {"Rai 1", "ORF 1"} <= candidates.keys()
    for name in ["Rai 1", "ORF 1"]:
        assert candidates[name]["match_confirmed"] is True
        assert candidates[name]["status"] == "UNKNOWN"
        assert candidates[name]["web_stream_free"] == "unknown"
        assert candidates[name]["watch_url"] == next(s["watch_url"] for s in registry if s["broadcaster"] == name)


@pytest.mark.parametrize("competition", ["Serie A", "Coppa Italia", "Supercoppa Italiana"])
def test_domestic_fixtures_are_untouched(competition):
    event = {**fixture(), "competition": competition}

    class NoNetwork:
        def get(self, *args, **kwargs):
            raise AssertionError("Domestic fixture must not query international sources")

    now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    result, errors = apply_verified_broadcasts(NoNetwork(), [event], [], sources(), now.isoformat(), now)
    assert result == [event]
    assert errors == []
