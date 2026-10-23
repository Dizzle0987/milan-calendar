from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from milan_calendar import generator

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def registry():
    return generator.load_broadcast_sources(ROOT / "data/broadcast_sources.json")


def fixture():
    return {"event_kind": "match", "home_team": "Milan", "away_team": "Porto",
            "competition": "UEFA Europa League", "start": "2026-11-05T21:00:00+01:00",
            "title": "Milan - Porto", "status": "Fixture"}


def guide(name, code="KZ", host="guide.example"):
    return {"country": "Internazionale", "country_code": "ZZ", "broadcaster": name,
            "access": "free", "source_type": "guide", "guide_parser": "sport_tv_guide",
            "discover_broadcasters": True, "url": f"https://{host}/event/milan-porto/42",
            "timezone": "Europe/Rome"}


def session_for(channel, code):
    # Same station/date/time card structure observed by the existing guide adapter.
    html = f'''<title>Milan - Porto : Europa League</title>
      <div id="channelInfo"><div class="time full"><strong>21:00</strong></div>
      <div class="date full">Giovedi, 11-05-2026</div>
      <div class="station full">{channel} / {code}</div></div>
      <h3>Dove vedere in tv o diretta streaming</h3>
      <div class="liveOtherStations clearfix"><div class="stationLive active col-wrap"
      title="{channel} [{code}] - Live: Milan - Porto">{channel} [{code}]</div></div>'''

    class Response:
        text = html
        def raise_for_status(self): pass
        def json(self): return []

    class Session:
        def get(self, url, **kwargs):
            assert "servustv.com" not in url
            assert "qazsporttv.kz" not in url
            return Response()

    return Session()


def opponent_portugal(monkeypatch):
    monkeypatch.setattr(generator, "identify_opponent_country", lambda *a: (
        {"country": "Portogallo", "country_code": "PT", "source": "fixture"}, None))


@pytest.mark.parametrize("guides", [1, 2])
def test_qazsport_reconciles_for_two_non_kazakh_teams_without_claiming_free_web(monkeypatch, guides):
    opponent_portugal(monkeypatch)
    qaz = next(s for s in registry() if s["broadcaster"] == "Qazsport")
    assert qaz["monitor_international"] is True
    feeds = [guide("Guide A", host="a.example")]
    if guides == 2:
        feeds.append(guide("Guide B", host="b.example"))
    result, errors = generator.apply_verified_broadcasts(
        session_for("QAZSPORT", "KZ"), [fixture()], [], [qaz, *feeds], NOW.isoformat(), NOW)
    assert errors == []
    candidate, = result[0]["broadcast_candidates"]
    assert candidate["broadcaster"] == "Qazsport"
    assert candidate["country_code"] == "KZ"
    assert candidate["priority"] == 110
    assert candidate["watch_url"] == "https://qazsporttv.kz/ru/live"
    assert candidate["confidence"] == (70 if guides == 1 else 90)
    assert candidate["status"] == "UNKNOWN"
    assert candidate["web_stream_free"] == "unknown"
    assert result[0]["foreign_free_broadcasts"] == []


def test_qazsport_opt_in_does_not_disable_other_broadcasters_territorial_filter(monkeypatch):
    opponent_portugal(monkeypatch)
    qaz = next(s for s in registry() if s["broadcaster"] == "Qazsport")
    unrelated = {**deepcopy(qaz), "broadcaster": "Other KZ channel", "priority": 999,
                 "match_terms": ["Other KZ channel"]}
    unrelated.pop("monitor_international")
    result, _ = generator.apply_verified_broadcasts(
        session_for("Other KZ channel", "KZ"), [fixture()], [], [qaz, unrelated, guide("Guide")], NOW.isoformat(), NOW)
    candidate, = result[0]["broadcast_candidates"]
    assert candidate["discovered_dynamically"] is True
    assert candidate["priority"] == 0  # No identity/priority inheritance from excluded station.
    assert candidate["watch_url"] is None


def test_ambiguous_servus_epg_cannot_be_enabled_accidentally():
    source = next(s for s in registry() if s["broadcaster"] == "ServusTV / ServusTV On")
    assert source["source_type"] == "registry_only"
    assert source["epg_identity_verified"] is False
    assert source["access"] == "unknown" and source["web_stream_free"] == "unknown"

    class MixedStreamSession:
        def get(self, *args, **kwargs):
            raise AssertionError("Ambiguous Red Bull / thematic EPG must not be downloaded")

    with pytest.raises(ValueError, match="Austria non verificata"):
        generator._fetch_epg_rows(MixedStreamSession(), {**source, "source_type": "servus_epg"}, [fixture()])


def test_servus_guide_evidence_remains_unknown_without_web_access_proof(monkeypatch):
    opponent_portugal(monkeypatch)
    servus = next(s for s in registry() if s["broadcaster"] == "ServusTV / ServusTV On")
    feed = {**guide("Guide"), "country": "Austria", "country_code": "AT"}
    result, _ = generator.apply_verified_broadcasts(
        session_for("ServusTV", "AT"), [fixture()], [], [servus, feed], NOW.isoformat(), NOW)
    candidate, = result[0]["broadcast_candidates"]
    assert candidate["country_code"] == "AT"
    assert candidate["status"] == "UNKNOWN"
    assert candidate["web_stream_free"] == "unknown"
    assert candidate["watch_url"] == "https://www.servustv.com/jetzt-live/"
