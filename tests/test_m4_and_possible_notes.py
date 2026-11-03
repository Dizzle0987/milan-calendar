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


class MultiDateSession(Session):
    """Local M4 fixture: the second schedule can be published between runs."""
    def __init__(self, missing=(), status=200):
        super().__init__(status)
        self.missing = set(missing)
        self.days = []

    def post(self, url, **kw):
        self.calls.append(('POST', url))
        day = kw['data']['Date']
        self.days.append(day)
        return Response('' if day in self.missing else guide().replace('2026-11-05', day), self.status)


def test_three_future_fixtures_rechecked_with_shared_reads_and_hard_limits(monkeypatch, caplog):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Ungheria', 'country_code': 'HU', 'source': 'fixture'}, None))
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    events = [fixture(start=f'2026-11-{day:02}T18:45:00+01:00', uid=f'fixture-{day}') for day in (5, 8, 12, 15, 27)]
    domestic = fixture(competition='Serie A', away_team='Roma')
    historic = fixture(start='2026-10-05T18:45:00+02:00', broadcast_candidates=[{'broadcaster': 'Historical'}])
    session = MultiDateSession()
    with caplog.at_level('INFO', logger=g.__name__):
        result, errors = g.apply_verified_broadcasts(session, [domestic, historic, *events], [], [source()], now.isoformat(), now)
    assert not errors and session.days == ['2026-11-05', '2026-11-08', '2026-11-12']
    assert len(session.calls) == 5  # robots + guide once; one dated POST per fixture
    assert result[:2] == [domestic, historic]
    assert result[-2:] == events[-2:]
    for event in result[2:5]:
        candidate, = event['broadcast_candidates']
        assert candidate['match_confirmed'] and candidate['confidence'] == 95
        assert candidate['status'] == 'UNKNOWN' and candidate['web_stream_free'] == 'unknown'
    assert caplog.text.count('Broadcast result ') == 3
    assert 'Broadcast HTTP POST' in caplog.text


def test_unpublished_second_fixture_is_retried_next_run_and_becomes_confirmed(monkeypatch):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Ungheria', 'country_code': 'HU', 'source': 'fixture'}, None))
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    events = [fixture(uid='first'), fixture(start='2026-11-12T18:45:00+01:00', uid='second')]
    first, errors = g.apply_verified_broadcasts(MultiDateSession(missing=['2026-11-12']), events, [], [source()], now.isoformat(), now)
    assert not errors and not first[1]['broadcast_candidates']
    second_session = MultiDateSession()
    second, errors = g.apply_verified_broadcasts(second_session, events, first, [source()], now.isoformat(), now)
    assert not errors and '2026-11-12' in second_session.days
    assert second[1]['broadcast_candidates'][0]['match_confirmed']
    assert first[0] == second[0]


def test_source_window_is_respected_and_logged_not_mistaken_for_no_listing(monkeypatch, caplog):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Ungheria', 'country_code': 'HU', 'source': 'fixture'}, None))
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    session = MultiDateSession()
    with caplog.at_level('INFO', logger=g.__name__):
        result, errors = g.apply_verified_broadcasts(session, [fixture(start='2026-11-19T18:45:00+01:00')], [], [source()], now.isoformat(), now)
    assert not errors and not session.calls and not result[0]['broadcast_candidates']
    assert 'outside scope' in caplog.text


def test_failure_cached_within_run_but_retried_next_run(monkeypatch, caplog):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Ungheria', 'country_code': 'HU', 'source': 'fixture'}, None))
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    class Blocked(Session):
        def get(self, url, **kwargs):
            self.calls.append(('GET', url))
            return Response('', 403)
    events = [fixture(), fixture(start='2026-11-12T18:45:00+01:00')]
    session = Blocked()
    with caplog.at_level('INFO', logger=g.__name__):
        result, errors = g.apply_verified_broadcasts(session, events, [], [source()], now.isoformat(), now)
    assert len(session.calls) == 1 and len(errors) == 2
    assert all(not e['broadcast_candidates'] for e in result)
    assert '403' in caplog.text and 'Broadcast source error' in caplog.text
    g.apply_verified_broadcasts(session, events, result, [source()], now.isoformat(), now)
    assert len(session.calls) == 2


def test_previous_international_enrichment_preserved_outside_window_only():
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    future = fixture(start='2026-12-03T18:45:00+01:00')
    old = {**future, 'foreign_tv_broadcasts': [{'broadcaster': 'Verified fixture annotation'}],
           'foreign_possible_broadcasts': [], 'broadcast_notes_compact': True}
    domestic = fixture(competition='Serie A')
    old_domestic = {**domestic, 'broadcast_it': 'Obsolete value'}
    result, errors = g.apply_verified_broadcasts(Session(), [future, domestic], [old, old_domestic], [], now.isoformat(), now)
    assert not errors and result == [old, domestic]


def test_broken_source_does_not_block_later_official_confirmation(monkeypatch):
    monkeypatch.setattr(g, 'identify_opponent_country', lambda *a: ({'country': 'Ungheria', 'country_code': 'HU', 'source': 'fixture'}, None))
    now = datetime(2026, 11, 3, 8, tzinfo=timezone.utc)
    class SessionWithBrokenSource(MultiDateSession):
        def get(self, url, **kwargs):
            if url == 'https://blocked.example/schedule':
                return Response('', 403)
            return super().get(url, **kwargs)
    broken = {**source(), 'broadcaster': 'Broken', 'url': 'https://blocked.example/schedule',
              'source_type': 'fixture_page', 'priority': 999}
    result, errors = g.apply_verified_broadcasts(SessionWithBrokenSource(), [fixture()], [], [broken, source()], now.isoformat(), now)
    assert len(errors) == 1 and 'Broken' in errors[0]
    assert result[0]['broadcast_candidates'][0]['broadcaster'] == 'M4 Sport'
    assert result[0]['broadcast_candidates'][0]['match_confirmed']


def test_post_cache_separates_dates_and_reuses_identical_requests():
    session = MultiDateSession()
    cached = g._BroadcastRequestCache(session)
    for day in ['2026-11-05', '2026-11-05', '2026-11-12']:
        cached.post(ENDPOINT, data={'Date': day}, timeout=10, allow_redirects=False)
    assert session.days == ['2026-11-05', '2026-11-12']


def test_all_automatic_generations_are_followed_by_success_gated_pages_deploy():
    pages = (ROOT / '.github/workflows/pages.yml').read_text()
    assert 'workflows: ["Update calendar", "Refresh Serie A standings"]' in pages
    assert "github.event.workflow_run.conclusion == 'success'" in pages
    assert 'ref: main' in pages
    for filename in ['update.yml', 'standings.yml']:
        assert 'python update_calendar.py' in (ROOT / '.github/workflows' / filename).read_text()


def test_raw_feed_without_title_logs_team_names(monkeypatch, caplog):
    event = fixture()
    del event['title']
    with caplog.at_level('INFO', logger=g.__name__):
        result, errors = resolve(monkeypatch, Session(), [event])
    assert not errors
    assert 'Broadcast result AC Milan - Ferencváros [' in caplog.text
    assert 'Broadcast EPG M4 Sport [AC Milan - Ferencváros]' in caplog.text
    assert 'Broadcast result None' not in caplog.text
    assert 'title' not in result[0]  # Logging must not alter raw fixture metadata.
