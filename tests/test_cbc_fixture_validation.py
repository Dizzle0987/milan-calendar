"""CBC opt-in contract fixtures, not a claim about currently blocked HTML."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import requests

from milan_calendar import generator as g

ROOT = Path(__file__).parents[1]


def source():
    return next(s for s in g.load_broadcast_sources(ROOT / "data/broadcast_sources.json")
                if s["broadcaster"] == "CBC Sport")


def event(**changes):
    return {"home_team": "AFC Bournemouth", "away_team": "AC Milan", "event_kind": "match",
            "competition": "UEFA Europa League", "start": "2026-10-22T21:00:00+02:00",
            "title": "Bournemouth - AC Milan", "status": "Fixture", **changes}


def programme(teams="Bornmut - Milan", day="22.10.2026", clock="23:00",
              competition="Futbol. UEFA Avropa Liqası", tag="tr"):
    return (f'<{tag}><td>{day}</td><td>{clock}</td><td>{teams}</td>'
            f'<td>{competition}</td><td>CBC Sport canlı</td></{tag}>')


def confirms(html, fixture=None, strict=True, aliases=None, zone="Asia/Baku"):
    return g.page_confirms_fixture(html, fixture or event(), "CBC Sport", zone,
        True, aliases if aliases is not None else source()["team_aliases"], strict_programme=strict)


@pytest.mark.parametrize("teams", ["Bornmut - Milan", "Milan – AFC Bournemouth",
    "Bornmut (İngiltərə) — Milan (İtaliya)", "Bournemouth vs AC Milan"])
def test_single_programme_exact_teams_and_localized_aliases(teams):
    assert confirms(programme(teams=teams))


def test_inline_markup_and_leaf_record_not_whole_page():
    row = programme(teams='<span>Bornmut</span> – <b>Milan</b>', tag="article")
    assert confirms(f'<div class="schedule-item">{row}</div>')
    assert not confirms(programme(teams="Bornmut - Porto") + programme(teams="Milan - Benfica"))
    assert not confirms('<article>' + programme(teams="Bornmut - Porto")
                        + programme(teams="Milan - Benfica") + '</article>')


@pytest.mark.parametrize("change", [
    {"teams": "Bornmut - Inter Milan"}, {"teams": "Inter Milan - Bornmut"},
    {"teams": "Milan - Porto"}, {"teams": "NotBornmut - Milan"},
    {"teams": "Bornmut U19 - Milan U19"}, {"teams": "Bornmut - Milan (U18)"},
    {"teams": "Bornmut - Milan (Women)"}, {"teams": "Bornmut - Milan (qadınlar)"},
    {"teams": "Bornmut - Milan (Primavera)"},
    {"competition": "UEFA Champions League"}, {"competition": "Calcio"},
    {"competition": "UEFA Europa League / UEFA Champions League"},
    {"day": "22.10.2025"}, {"day": "22-10"}, {"day": "2026-10-23"},
    {"day": "31.02.2026"}, {"clock": "22:00"},
    {"competition": "UEFA Europa League highlights"},
])
def test_false_positives_rejected(change):
    assert not confirms(programme(**change))


def test_year_and_time_cannot_leak_from_adjacent_programmes_or_header():
    assert not confirms(programme(day="22-10", clock="") + programme(teams="Porto - Benfica"))
    assert not confirms('<h1>22.10.2026 23:00</h1>' + programme(day="", clock=""))
    assert not confirms(programme(day="22.10.2025") + programme(teams="Porto - Benfica"))


@pytest.mark.parametrize("day", ["2026-10-22", "22/10/2026", "22 oktyabr 2026"])
def test_complete_dates(day):
    assert confirms(programme(day=day))


def test_source_timezone_date_rollover_and_cet_cest():
    # Summer: Italy 21:00 -> Baku 23:00. Winter: Italy 21:00 -> next day 00:00.
    assert confirms(programme())
    winter = event(start="2026-10-29T21:00:00+01:00")
    assert confirms(programme(day="30.10.2026", clock="00:00"), winter)
    assert not confirms(programme(day="29.10.2026", clock="00:00"), winter)
    assert not confirms(programme(clock="21:00"))
    assert not confirms(programme(), zone="Unknown/Zone")


def test_iso_time_metadata_converts_to_baku_before_date_comparison():
    assert confirms(programme(day='<time datetime="2026-10-22T19:00:00Z"></time>', clock=""))
    winter = event(start="2026-10-29T21:00:00+01:00")
    assert confirms(programme(day='<time datetime="2026-10-29T20:00:00Z"></time>', clock=""), winter)
    assert not confirms(programme(day='<time datetime="2026-10-22T20:00:00Z"></time>', clock=""))


def test_ambiguous_aliases_and_non_matching_aliases_fail_closed():
    assert not confirms(programme(), aliases={})
    assert not confirms(programme(), aliases={"milan": ["Bornmut", "Bournemouth"]})


def test_unsupported_markup_scripts_and_missing_fields_are_not_confirmations():
    assert not confirms('22.10.2026 23:00 Bornmut - Milan UEFA Europa League CBC Sport live')
    assert not confirms('<script>' + programme() + '</script>')
    assert not confirms(programme(clock="TBC"))
    assert not confirms(programme(), event(all_day=True))


def test_other_broadcasters_keep_legacy_behavior():
    text = '22.10.2026 23:00 Bournemouth - Milan CBC Sport live'
    assert confirms(text, strict=False)
    assert not confirms(text, strict=True)


class Response:
    def __init__(self, html, status): self.text, self.status_code = html, status
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, html, status=200): self.html, self.status, self.calls = html, status, []
    def get(self, url, **kwargs):
        self.calls.append(url)
        assert url == source()["url"]
        assert kwargs == {"timeout": 10}
        return Response(self.html, self.status)


def resolve(monkeypatch, html, status=200, fixture=None, rights=True):
    monkeypatch.setattr(g, "identify_opponent_country", lambda *a: (None, None))
    selected = source()
    selected["rights_confirmed"] = rights
    session = Session(html, status)
    now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
    result, errors = g.apply_verified_broadcasts(session, [fixture or event()], [],
        [selected], now.isoformat(), now)
    assert session.calls == [selected["url"]]
    return result[0], errors


def test_runtime_strict_verification_and_no_web_free_inheritance(monkeypatch):
    resolved, errors = resolve(monkeypatch, programme())
    assert not errors
    candidate, = resolved["broadcast_candidates"]
    assert candidate["match_confirmed"] and candidate["confidence"] == 100
    assert candidate["priority"] == 110 and candidate["market_tier"] == 1
    assert candidate["watch_url"] == source()["watch_url"]
    assert candidate["web_stream_free"] == "unknown"
    assert candidate["availability_evidence"] == []
    assert candidate["source_schedule"] == source()["url"]


@pytest.mark.parametrize("rights", [True, False])
def test_missing_time_retains_candidate_and_can_be_rechecked(monkeypatch, rights):
    resolved, errors = resolve(monkeypatch, programme(clock="Da confermare"), rights=rights)
    assert not errors
    candidate, = resolved["broadcast_candidates"]
    assert candidate["match_confirmed"] is False
    assert candidate["status"] != "CONFIRMED_FREE" and candidate["web_stream_free"] == "unknown"
    assert resolved["broadcast_options"] == []
    updated, _ = resolve(monkeypatch, programme(), rights=rights)
    assert updated["broadcast_candidates"][0]["match_confirmed"] is True


def test_http_403_body_never_creates_new_match_evidence(monkeypatch):
    resolved, errors = resolve(monkeypatch, programme(), status=403)
    assert errors
    candidate, = resolved["broadcast_candidates"]
    assert not candidate["match_confirmed"] and candidate["evidence"] == []
    assert candidate["web_stream_free"] == "unknown"
    assert resolved["broadcast_options"] == []


def test_no_time_on_event_cannot_be_confirmed(monkeypatch):
    resolved, _ = resolve(monkeypatch, programme(), fixture=event(all_day=True))
    assert not resolved["broadcast_candidates"][0]["match_confirmed"]


def test_only_cbc_opts_in_and_existing_generated_ics_roundtrips():
    sources = g.load_broadcast_sources(ROOT / 'data/broadcast_sources.json')
    assert [s['broadcaster'] for s in sources if s.get('fixture_validation') == 'cbc_programme'] == ['CBC Sport']
    cbc = source()
    assert cbc['priority'] == 110 and cbc['market_tier'] == 1
    assert cbc['watch_url'] == 'https://cbcsport.az/live/'
    assert cbc['web_stream_free'] == 'unknown'
    events = json.loads((ROOT / 'data/events.json').read_text())['events']
    assert g.build_ical(events) == (ROOT / 'calendar.ics').read_bytes()
