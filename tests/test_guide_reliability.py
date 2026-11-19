from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest
import requests

from milan_calendar import generator as g

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('broadcast_health', ROOT / 'scripts/broadcast_health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
URL = 'https://www.sporekrani.com/home/match/491830/2026/11/26/olympiakos-milan-uefa-avrupa-ligi-hangi-kanalda'


def source():
    return next(s for s in g.load_broadcast_sources(ROOT / 'data/broadcast_sources.json') if s['broadcaster'] == 'Spor Ekranı')


def fixture():
    return {'home_team': 'Olympiacos', 'away_team': 'AC Milan', 'competition': 'UEFA Europa League',
            'start': '2026-11-26T18:45:00+01:00', 'uid': 'olympiacos-milan', 'home_away': 'Trasferta',
            'title': 'Olympiacos - AC Milan', 'last_modified': '2026-11-19T08:00:00Z'}


def current(**changes):
    # Minimal fields from the actual current-event payload observed 19 Nov.
    return {'sport_id': 1, 'event_type_name': 'match', 'home_name': 'Olympiakos',
            'away_name': 'Milan', 'league_name': 'UEFA Avrupa Ligi',
            'date_time': '2026-11-26 20:45:00',
            'channels': [{'name': 'tabii Spor', 'active': 1}], **changes}


def page(data=None):
    return '<nav>CBC Sport</nav><script>window.__INITIAL_STATE__ = ' + json.dumps(
        {'common': {'curr': {'event': data if data is not None else current()}}}) + ';</script>'


class Response:
    status_code = 200
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


class Session:
    def __init__(self, match_page=None): self.calls, self.match_page = [], match_page or page()
    def get(self, url, **kw):
        self.calls.append(url)
        if url == URL:
            return Response(self.match_page)
        # Listing has many unrelated matches before the real link, and no exact
        # current-event payload. It must not be trusted as match confirmation.
        links = ''.join(f'<a href="/home/match/{i}/2026/11/22/milan-frosinone">x</a>' for i in range(10))
        return Response(links + f'<a href="{URL}">Olympiakos - Milan</a>' * 2)


def test_real_structured_event_not_navigation_is_evidence():
    parsed = g.parse_sporekrani_guide(page(), fixture(), source())
    assert parsed == [{'broadcaster': 'tabii Spor', 'country_code': 'ZZ', 'programme_start': '2026-11-26T18:45:00+01:00'}]
    assert 'CBC Sport' not in str(parsed)


@pytest.mark.parametrize('changes', [
    {'home_name': 'Porto'}, {'away_name': 'Inter Milan'}, {'home_name': 'Olympiakos U19'},
    {'away_name': 'Milan Women'}, {'league_name': 'UEFA Şampiyonlar Ligi'},
    {'date_time': '2025-11-26 20:45:00'}, {'date_time': '2026-11-27 20:45:00'},
    {'date_time': '2026-11-26 21:45:00'}, {'sport_id': 2}, {'event_type_name': 'highlights'},
    {'channels': []}, {'channels': [{'name': 'CBC Sport', 'active': 0}]}, {'channels': None},
])
def test_structured_event_mismatch_never_confirms(changes):
    assert g.parse_sporekrani_guide(page(current(**changes)), fixture(), source()) == []


@pytest.mark.parametrize('html', ['CBC Sport Milan Olympiacos 26/11/2026 18:45', '<script>window.__INITIAL_STATE__ = null;</script>', '<script>window.__INITIAL_STATE__ = {};</script>'])
def test_missing_or_malformed_state_is_not_text_confirmation(html):
    assert g.parse_sporekrani_guide(html, fixture(), source()) == []


def test_discovery_follows_actual_matching_permalink_not_listing_or_first_links():
    session = Session()
    assert g._fetch_guide_documents(session, source(), fixture()) == [(page(), URL)]
    assert session.calls[-1] == URL and len(session.calls) <= 3
    assert sum('/home/match/' in url for url in session.calls) == 1


def test_match_page_schema_failure_is_reported_not_silently_no_results():
    with pytest.raises(ValueError, match='dati strutturati'):
        g._fetch_guide_documents(Session('<title>Error</title>'), source(), fixture())


@pytest.mark.parametrize('status', [403, 429, 503])
def test_match_http_errors_are_not_silently_returned_as_missing_schedule(status):
    class Broken(Session):
        def get(self, url, **kw):
            if url == URL:
                self.calls.append(url)
                response = requests.Response()
                response.status_code, response.url = status, url
                response._content = b''
                return response
            return super().get(url, **kw)
    session = Broken()
    with pytest.raises(requests.HTTPError):
        g._fetch_guide_documents(session, source(), fixture())
    assert session.calls.count(URL) == 1
    if status in (403, 429):
        assert len(session.calls) <= 2  # Stop this source; no alternate access attempt.


def test_negative_listing_is_not_a_technical_failure():
    class Empty(Session):
        def get(self, url, **kw): return Response('<h1>Milan</h1>No published matches')
    assert g._fetch_guide_documents(Empty(), source(), fixture()) == []


def test_runtime_new_channel_is_unknown_and_cbc_navigation_never_confirmed(monkeypatch):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Grecia', 'country_code': 'GR', 'source': 'fixture'}, None))
    sources = g.load_broadcast_sources(ROOT / 'data/broadcast_sources.json')
    cbc = deepcopy(next(s for s in sources if s['broadcaster'] == 'CBC Sport'))
    cbc['source_type'] = 'registry_only'
    now = datetime(2026, 11, 19, 8, tzinfo=timezone.utc)
    result, errors = g.apply_verified_broadcasts(Session(), [fixture()], [], [cbc, source()], now.isoformat(), now)
    assert not errors
    tabii, = result[0]['broadcast_candidates']
    assert tabii['broadcaster'] == 'tabii Spor' and tabii['match_confirmed']
    assert tabii['status'] == 'UNKNOWN' and tabii['confidence'] == 70
    assert tabii['watch_url'] is None and tabii['web_stream_free'] == 'unknown'
    assert tabii['source_schedule'] == URL
    assert not result[0]['foreign_free_broadcasts']


def test_health_only_reports_technical_errors_in_monitored_sources_near_a_match():
    now = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
    event = {**fixture(), 'broadcast_show_possible': True}
    config = {'sources': [source()]}
    payload = {'events': [event], 'source_errors': ['Broadcast Spor Ekranı (Olympiacos - AC Milan): 503', 'Broadcast CBC Sport: 403']}
    assert health.evaluate(payload, config, now) == payload['source_errors'][:1]
    assert health.evaluate({**payload, 'source_errors': []}, config, now) == []
    assert health.evaluate({**payload, 'events': [{**event, 'start': '2026-12-10T21:00:00+01:00'}]}, config, now) == []
    assert health.evaluate({**payload, 'events': [{**event, 'broadcast_show_possible': False}]}, config, now) == []


def test_notification_does_not_spam_an_already_open_issue(monkeypatch):
    calls = []
    def fake(args, **kw):
        calls.append(args)
        if 'list' in args:
            return json.dumps([{'number': 7, 'title': health.TITLE, 'body': 'old'}])
        return ''
    monkeypatch.setattr(health.subprocess, 'check_output', fake)
    health.notify(['HTTP 503'], 'owner/repo', 'https://github.com/run/1')
    assert not any('create' in call or 'comment' in call for call in calls)
    assert sum('edit' in call for call in calls) == 1
    calls.clear()
    health.notify([], 'owner/repo', 'https://github.com/run/2')
    assert any('close' in call for call in calls)
