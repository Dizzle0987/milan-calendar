from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import requests
from icalendar import Calendar

from milan_calendar import generator as g

ROOT = Path(__file__).parents[1]
ENDPOINT = 'https://m4sport.hu/wp-content/plugins/hms-global-widgets/widgets/programGuide/programGuideInterface.php'


def source():
    return next(s for s in g.load_broadcast_sources(ROOT / 'data/broadcast_sources.json') if s['broadcaster'] == 'M4 Sport')


def fixture(**kw):
    return {'home_team': 'AC Milan', 'away_team': 'Ferencváros',
            'start': '2026-11-05T18:45:00+01:00', 'competition': 'UEFA Europa League',
            'event_kind': 'match', 'home_away': 'Casa', 'title': 'AC Milan - Ferencváros', 'uid': 'milan-ftc@example',
            'broadcast_it': 'Sky Sport e NOW', 'broadcast_options': [], 'broadcast_source_url': 'https://www.nowtv.it/sport/calcio/milan',
            'last_modified': '2026-11-03T08:00:00Z', **kw}


def row(start, end, teams='AC Milan - Ferencvárosi TC mérkőzés', title='UEFA Labdarúgó Európa Liga', channel='m4', prefix='30'):
    # Reduced real programme markup observed on the official guide, 2026-11-03.
    return f'''<li class="program_body {channel} disabled" data-from="{start}" data-till="{end}">
      <div class="time"><div class="elo {channel}" style="display:none">Élő</div></div>
      <div class="program_info"><h1 id="pg{prefix}d20261105i24h">{title}<span style="display:none">, élő adásban</span></h1>
      <p id="pg{prefix}d20261105i24p">{teams}</p></div></li>'''


def guide():
    return ''.join(row(a, b) for a, b in [
        ('2026-11-05 18:42:00+0100', '2026-11-05 19:36:30+0100'),
        ('2026-11-05 19:36:30+0100', '2026-11-05 19:44:00+0100'),
        ('2026-11-05 19:44:00+0100', '2026-11-05 20:45:00+0100')])


def test_real_segmented_tv_listing_is_merged_without_inferring_free_web():
    parsed = g.parse_m4_epg(guide(), fixture(), source())
    assert parsed == [{'title': 'AC Milan - Ferencváros', 'start': '2026-11-05T18:42:00+01:00', 'end': '2026-11-05T20:45:00+01:00'}]
    assert g._programme_confirms_fixture(parsed[0], fixture()).isoformat() == '2026-11-05T18:42:00+01:00'


@pytest.mark.parametrize('change', [
    {'teams': 'Inter Milan - Ferencvárosi TC mérkőzés'},
    {'teams': 'AC Milan - Porto mérkőzés'},
    {'teams': 'AC Milan U19 - Ferencvárosi TC mérkőzés'},
    {'title': 'UEFA Labdarúgó Európa Liga összefoglaló'},
    {'title': 'UEFA Labdarúgó Európa Liga női'},
    {'title': 'UEFA Champions League'},
    {'channel': 'm4plus', 'prefix': '34'},
    {'prefix': '3'},
])
def test_m4_rejects_wrong_fixture_replays_competitions_and_channels(change):
    html = row('2026-11-05 18:42:00+0100', '2026-11-05 20:45:00+0100', **change)
    assert g.parse_m4_epg(html, fixture(), source()) == []


@pytest.mark.parametrize(('start', 'end'), [
    ('2025-11-05 18:42:00+0100', '2025-11-05 20:45:00+0100'),
    ('2026-11-05 18:42:00', '2026-11-05 20:45:00'),
    ('2026-11-05 18:42:00+0200', '2026-11-05 20:45:00+0200'),
    ('2026-11-05 21:00:00+0100', '2026-11-05 23:00:00+0100'),
])
def test_m4_rejects_wrong_date_time_or_missing_timezone(start, end):
    assert g.parse_m4_epg(row(start, end), fixture(), source()) == []


def test_m4_cest_and_budapest_rome_equivalence():
    event = fixture(start='2026-07-05T18:45:00+02:00')
    parsed = g.parse_m4_epg(row('2026-07-05 18:42:00+0200', '2026-07-05 20:45:00+0200'), event, source())
    assert g._programme_confirms_fixture(parsed[0], event).hour == 18


class Response:
    def __init__(self, text, status=200): self.text, self.status_code = text, status
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, status=200): self.calls, self.status = [], status
    def get(self, url, **kw):
        self.calls.append(('GET', url))
        assert kw == {'timeout': 10, 'allow_redirects': False}
        if url.endswith('robots.txt'): return Response('User-agent: *\nDisallow:\n')
        assert url == 'https://m4sport.hu/musor'
        return Response('programGuideController = programGuide(' + json.dumps({'programGuideInterfaceUrl': ENDPOINT}) + ')')
    def post(self, url, **kw):
        self.calls.append(('POST', url))
        assert url == ENDPOINT
        assert kw['data']['ChannelIds'] == '30,' and kw['data']['Date'] == '2026-11-05'
        assert kw['timeout'] == 10 and kw['allow_redirects'] is False
        return Response(guide(), self.status)


def resolve(monkeypatch, session, events=None):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Ungheria', 'country_code': 'HU', 'source': 'fixture'}, None))
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    return g.apply_verified_broadcasts(session, events or [fixture()], [], [source()], now.isoformat(), now)


def test_runtime_m4_tv_confirmation_stays_unknown_web_and_appears_as_possible(monkeypatch):
    session = Session()
    result, errors = resolve(monkeypatch, session)
    assert errors == [] and len(session.calls) == 3
    candidate, = result[0]['broadcast_candidates']
    assert candidate['match_confirmed'] is True and candidate['confidence'] == 95
    assert candidate['status'] == 'UNKNOWN' and candidate['web_stream_free'] == 'unknown'
    assert candidate['broadcast_free'] == 'unknown'
    assert candidate['watch_url'] == 'https://mediaklikk.hu/elo/mtv4live'
    assert result[0]['foreign_free_broadcasts'] == []
    text = '\n'.join(g._broadcast_description_lines(result[0]))
    assert 'Possibili alternative estere — da confermare:' in text
    assert 'M4 Sport — Ungheria — VPN — https://mediaklikk.hu/elo/mtv4live' in text
    assert 'TV confermata · Streaming web da verificare' in text
    assert text.index('Sky Sport') < text.index('M4 Sport')


@pytest.mark.parametrize('status', [403, 404, 429, 500])
def test_m4_http_failure_never_creates_confirmation(monkeypatch, status):
    result, errors = resolve(monkeypatch, Session(status))
    assert errors and not result[0]['broadcast_candidates']


@pytest.mark.parametrize('kind', ['robots', 'external_endpoint', 'redirect', 'timeout', 'no_results'])
def test_m4_restrictions_errors_and_missing_results_fail_closed(monkeypatch, kind):
    class RestrictedSession(Session):
        def get(self, url, **kw):
            if kind == 'timeout':
                raise requests.Timeout('fixture timeout')
            response = super().get(url, **kw)
            if url.endswith('robots.txt') and kind == 'robots':
                response.text = 'User-agent: *\nDisallow: /\n'
            elif not url.endswith('robots.txt'):
                if kind == 'external_endpoint':
                    response.text = response.text.replace('https://m4sport.hu/', 'https://unapproved.example/')
                elif kind == 'redirect':
                    response.status_code = 302
                elif kind == 'no_results':
                    response.text = '<html>No programme widget</html>'
            return response
    session = RestrictedSession()
    result, errors = resolve(monkeypatch, session)
    assert not result[0]['broadcast_candidates']
    assert all(method != 'POST' for method, _ in session.calls)
    if kind != 'no_results':
        assert errors


def test_rights_only_cbc_hidden_until_match_confirmation_without_mutating_data():
    event = fixture(broadcast_notes_compact=True, broadcast_show_possible=True)
    cbc = {'broadcaster': 'CBC Sport', 'country': 'Azerbaijan', 'country_code': 'AZ',
           'free_or_pay': 'free', 'status': 'POSSIBLE_FREE', 'match_confirmed': False,
           'watch_url': 'https://cbcsport.az/live/', 'web_stream_free': 'unknown'}
    event['foreign_possible_broadcasts'] = [cbc]
    event['broadcast_candidates'] = [cbc, {**cbc, 'broadcaster': 'Premium', 'free_or_pay': 'paid'},
        {**cbc, 'broadcaster': 'YouTube', 'watch_url': 'https://www.youtube.com/watch?v=video'}]
    before = deepcopy(event)
    text = str(Calendar.from_ical(g.build_ical([event])).walk('VEVENT')[0]['description'])
    assert 'CBC Sport' not in text
    assert 'Premium' not in text and 'YouTube' not in text
    assert 'confidence' not in text and 'POSSIBLE_FREE' not in text
    assert event == before
    cbc['match_confirmed'] = True
    text = str(Calendar.from_ical(g.build_ical([event])).walk('VEVENT')[0]['description'])
    assert text.count('CBC Sport') == 1
    assert 'TV confermata · Streaming web da verificare' in text


def test_no_new_notes_for_historical_events_without_opt_in():
    event = fixture(broadcast_notes_compact=True)
    event['foreign_possible_broadcasts'] = [{'broadcaster': 'CBC Sport', 'country_code': 'AZ', 'country': 'Azerbaijan',
        'status': 'POSSIBLE_FREE', 'match_confirmed': False, 'watch_url': 'https://cbcsport.az/live/'}]
    assert 'CBC Sport' not in '\n'.join(g._broadcast_description_lines(event))


def test_mixed_calendar_national_events_unchanged(monkeypatch):
    domestic = fixture(competition='Serie A', away_team='Roma', start='2026-11-08T20:45:00+01:00')
    result, _ = resolve(monkeypatch, Session(), [domestic, fixture()])
    assert result[0] == domestic
