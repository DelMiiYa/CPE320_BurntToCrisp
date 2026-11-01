"""Independent contract tests. Only temporary databases are mutated.

No async plugin, production helpers as oracles, network service, or preview DB.
SQL seeding represents historical facts unreachable through today's-only PUT.
"""
import asyncio
from contextlib import AsyncExitStack
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3

import httpx
import pytest

UTC = timezone.utc
TODAY = date(2026, 10, 20)
PASSWORD = '  independent password  '
COOKIE = 'burningupp_session'
MARKER = 'QA_PRIVATE_754190'


def run(work):
    return asyncio.run(work)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://qa.test')


async def req(c, method, path, expected=200, **kwargs):
    r = await c.request(method, path, **kwargs)
    assert r.status_code == expected, (method, path, expected, r.status_code, r.text)
    return r


async def owner(c, email):
    return (await req(c, 'POST', '/api/auth/register-organization', 201, json={
        'organization_name': ' Org ', 'display_name': ' Owner ',
        'email': email, 'password': PASSWORD})).json()


async def team(c, name):
    return (await req(c, 'POST', '/api/teams', 201, json={'name': name})).json()


async def member(c, code, email):
    return (await req(c, 'POST', '/api/auth/register-member', 201, json={
        'join_code': code, 'display_name': email.split('@')[0],
        'email': email, 'password': PASSWORD})).json()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path / 'import-only'))
    module = importlib.import_module('backend.main')
    app = module.create_app(tmp_path / 'scenario')
    clock = [datetime(2026, 10, 20, 12, tzinfo=UTC)]
    app.state.clock = lambda: clock[0]
    return module, app, clock


def sql(app, statement, args=()):
    with sqlite3.connect(app.state.db_path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        result = db.execute(statement, args)
        return result.fetchall()


def seed(app, account, offset, mood):
    sql(app, 'INSERT INTO checkins(organization_id,user_id,date,mood,activity,private_note,updated_at) VALUES(?,?,?,?,?,?,?)',
        (account['organization']['id'], account['user']['id'],
         (TODAY + timedelta(days=offset)).isoformat(), mood, MARKER, MARKER,
         '2026-10-20T12:00:00Z'))


def joined(app, t, account, offset):
    sql(app, 'UPDATE memberships SET joined_on=? WHERE team_id=? AND user_id=?',
        ((TODAY + timedelta(days=offset)).isoformat(), t['id'], account['user']['id']))


async def world(app, stack):
    clients = {key: await stack.enter_async_context(client(app))
               for key in ('a', 'b', 'manager', 'member', 'anon')}
    accounts = {'a': await owner(clients['a'], 'a@example.test'),
                'b': await owner(clients['b'], 'b@example.test')}
    teams = {'a1': await team(clients['a'], 'A1'), 'a2': await team(clients['a'], 'A2'),
             'b1': await team(clients['b'], 'B1')}
    for key in ('manager', 'member'):
        accounts[key] = await member(clients[key], teams['a1']['join_code'], key + '@example.test')
    await req(clients['member'], 'POST', '/api/teams/join', json={'join_code': teams['a2']['join_code']})
    await req(clients['a'], 'PATCH', f"/api/teams/{teams['a1']['id']}/members/{accounts['manager']['user']['id']}", json={'role': 'manager'})
    return clients, accounts, teams


def assert_public(value):
    if isinstance(value, dict):
        assert not {'password', 'password_hash', 'token_hash', 'activity', 'private_note', 'personal_goal'} & value.keys(), value
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)
    elif isinstance(value, str):
        assert MARKER not in value


def test_both_import_modes_without_listener(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path / 'imports'))
    def forbidden(*args, **kwargs):
        pytest.fail('Import attempted to open a listener')
    monkeypatch.setattr(socket.socket, 'bind', forbidden)
    monkeypatch.setattr(socket.socket, 'listen', forbidden)
    # Execute fresh module objects even if another test already imported backend.main.
    for name in ('backend.main', 'main'):
        spec = importlib.util.find_spec('backend.main')
        fresh = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, spec.origin))
        fresh.__spec__.loader.exec_module(fresh)
        assert callable(fresh.create_app)
        assert fresh.app.state.db_path == (tmp_path / 'imports' / 'burningupp.sqlite3').resolve()
        assert fresh.create_app(tmp_path / name).state.db_path.parent == (tmp_path / name).resolve()


def test_required_static_assets_and_frontend_contract(env):
    module, app, _ = env
    root = Path(module.__file__).resolve().parents[1] / 'frontend'
    async def scenario():
        async with client(app) as c:
            for path, filename in (('/', 'index.html'), ('/styles.css', 'styles.css'), ('/app.js', 'app.js')):
                r = await req(c, 'GET', path)
                assert r.content == (root / filename).read_bytes()
            await req(c, 'GET', '/api/unknown', 404)
    run(scenario())
    js = (root / 'app.js').read_text()
    html = (root / 'index.html').read_text()
    assert 'พื้นที่เล็ก ๆ สำหรับวันที่ดีขึ้น' in js
    assert "fetch('/api'+path" in js
    assert "val(day.participation_rate,1)+'%'" in js
    assert 'innerHTML' not in js and 'localStorage' not in js
    assert "href='./styles.css'" in html and "src='./app.js'" in html
    assert "entry?'recorded':future?'future':'missing'" in js


def test_auth_transactions_hashes_cookie_revocation_expiry(env):
    module, app, clock = env
    async def scenario():
        async with client(app) as c, client(app) as other:
            account = await owner(c, '  OWNER@Example.Test  ')
            assert account['user']['email'] == 'owner@example.test'
            assert account['organization']['plan'] == 'trial'
            assert account['organization']['plan_status'] == 'active'
            assert_public(account)
            token = c.cookies.get(COOKIE)
            assert len(token) >= 43
            before = [sql(app, f'SELECT count(*) FROM {table}')[0][0]
                      for table in ('organizations', 'users', 'sessions')]
            await req(other, 'POST', '/api/auth/register-organization', 409, json={
                'organization_name': 'Rollback', 'display_name': 'Dup',
                'email': ' OWNER@example.test ', 'password': PASSWORD})
            assert before == [sql(app, f'SELECT count(*) FROM {table}')[0][0]
                              for table in ('organizations', 'users', 'sessions')]
            for password in ('incorrect password', PASSWORD.strip()):
                await req(other, 'POST', '/api/auth/login', 401, json={'email': 'owner@example.test', 'password': password})
            r = await req(other, 'POST', '/api/auth/login', json={'email': ' OWNER@EXAMPLE.TEST ', 'password': PASSWORD})
            cookie = r.headers['set-cookie'].lower()
            for flag in ('httponly', 'secure', 'samesite=lax', 'path=/'):
                assert flag in cookie
            stored = sql(app, 'SELECT token_hash FROM sessions')
            assert (hashlib.sha256(token.encode()).hexdigest(),) in stored
            assert all(token != row[0] for row in stored)
            encoded = sql(app, 'SELECT password_hash FROM users')[0][0]
            assert encoded.startswith('pbkdf2_sha256$') and PASSWORD not in encoded
            await req(c, 'POST', '/api/auth/logout', headers={'Origin': 'https://qa.test'})
            c.cookies.set(COOKIE, token)
            await req(c, 'GET', '/api/me', 401)
            clock[0] += timedelta(days=7)
            await req(other, 'GET', '/api/me', 401)
    run(scenario())


def test_join_transactions_codes_and_duplicates(env):
    _, app, _ = env
    async def scenario():
        async with AsyncExitStack() as stack:
            c, accounts, t = await world(app, stack)
            codes = [x['join_code'] for x in t.values()]
            assert len(set(codes)) == 3 and all(len(code) >= 12 for code in codes)
            counts = sql(app, 'SELECT count(*) FROM users')[0][0]
            await req(c['anon'], 'POST', '/api/auth/register-member', 404, json={
                'join_code': 'invalid', 'display_name': 'No orphan', 'email': 'retry@example.test', 'password': PASSWORD})
            assert sql(app, 'SELECT count(*) FROM users')[0][0] == counts
            await member(c['anon'], codes[0], 'retry@example.test')
            before = sql(app, 'SELECT count(*) FROM memberships')[0][0]
            for _ in range(2):
                await req(c['member'], 'POST', '/api/teams/join', json={'join_code': t['a2']['join_code']})
            assert sql(app, 'SELECT count(*) FROM memberships')[0][0] == before
            await req(c['member'], 'POST', '/api/teams/join', 404, json={'join_code': t['b1']['join_code']})
            teams = (await req(c['member'], 'GET', '/api/teams')).json()['teams']
            assert {x['id'] for x in teams} == {t['a1']['id'], t['a2']['id']}
            assert all(x['join_code'] is None for x in teams)
    run(scenario())


def test_protected_endpoint_role_matrix_and_foreign_resources(env):
    _, app, _ = env
    async def scenario():
        async with AsyncExitStack() as stack:
            c, a, t = await world(app, stack)
            root = f"/api/teams/{t['a1']['id']}"
            subject = a['member']['user']['id']
            task = (await req(c['a'], 'POST', root + '/followups', 201,
                              json={'subject_user_id': subject, 'action': 'Talk'})).json()
            routes = [('GET', '/api/me', None, 200, 200, 200),
                      ('PATCH', '/api/me', {'display_name': 'Self', 'personal_goal': ''}, 200, 200, 200),
                      ('GET', '/api/teams', None, 200, 200, 200),
                      ('POST', '/api/teams', {'name': 'Created'}, 201, 403, 403),
                      ('POST', '/api/teams/join', {'join_code': t['a1']['join_code']}, 200, 200, 200),
                      ('PUT', '/api/checkins/today', {'mood': 2}, 200, 200, 200),
                      ('GET', '/api/checkins', None, 200, 200, 200),
                      ('GET', '/api/assessment', None, 200, 200, 200),
                      ('GET', root + '/members', None, 200, 200, 403),
                      ('PATCH', root + f'/members/{subject}', {'role': 'member'}, 200, 403, 403),
                      ('GET', root + '/dashboard', None, 200, 200, 403),
                      ('GET', root + '/followups', None, 200, 200, 403),
                      ('POST', root + '/followups', {'subject_user_id': subject, 'action': 'Talk'}, 201, 201, 403),
                      ('PATCH', root + f"/followups/{task['id']}", {'action': 'Done', 'status': 'done'}, 200, 200, 403)]
            for method, path, body, *statuses in routes:
                kwargs = {} if body is None else {'json': body}
                for role, expected in zip(('a', 'manager', 'member'), statuses):
                    await req(c[role], method, path, expected, **kwargs)
                await req(c['anon'], method, path, 401, **kwargs)
            for key, target in (('manager', 'a2'), ('manager', 'b1'), ('a', 'b1'), ('b', 'a1')):
                foreign = f"/api/teams/{t[target]['id']}"
                for suffix in ('/members', '/dashboard', '/followups'):
                    await req(c[key], 'GET', foreign + suffix, 404)
                await req(c[key], 'POST', foreign + '/followups', 404, json={'subject_user_id': subject, 'action': 'No'})
                await req(c[key], 'PATCH', foreign + f"/followups/{task['id']}", 404, json={'action': 'No', 'status': 'done'})
                await req(c[key], 'PATCH', foreign + f'/members/{subject}', 404, json={'role': 'manager'})
            await req(c['a'], 'POST', root + '/followups', 404,
                      json={'subject_user_id': a['b']['user']['id'], 'action': 'Foreign'})
            await req(c['a'], 'PATCH', f"/api/teams/{t['a2']['id']}/followups/{task['id']}", 404,
                      json={'action': 'Wrong team', 'status': 'done'})
            await req(c['anon'], 'POST', '/api/auth/logout', 401)
            for role in ('a', 'manager', 'member'):
                await req(c[role], 'POST', '/api/auth/logout')
    run(scenario())


@pytest.mark.parametrize('mood', [-1, 5, 10**80, 1.5, True, False, '2', None])
def test_strict_mood_invalid(env, mood):
    _, app, _ = env
    async def scenario():
        async with client(app) as c:
            await owner(c, 'strict@example.test')
            await req(c, 'PUT', '/api/checkins/today', 422, json={'mood': mood})
            assert sql(app, 'SELECT count(*) FROM checkins')[0][0] == 0
    run(scenario())


def test_validation_trim_lengths_forgery_origin_and_media(env):
    _, app, _ = env
    async def scenario():
        async with client(app) as c:
            account = await owner(c, 'validation@example.test')
            t = await team(c, 'Team')
            root = f"/api/teams/{t['id']}"
            cases = [('PATCH', '/api/me', {'display_name': ' ', 'personal_goal': ''}),
                     ('PATCH', '/api/me', {'display_name': 'x', 'personal_goal': 'x' * 501}),
                     ('POST', '/api/teams', {'name': ' ' }),
                     ('POST', '/api/teams', {'name': 'x' * 121}),
                     ('POST', '/api/teams/join', {'join_code': ' '}),
                     ('PUT', '/api/checkins/today', {'mood': 2, 'activity': 'x' * 201}),
                     ('PUT', '/api/checkins/today', {'mood': 2, 'private_note': 'x' * 2001}),
                     ('POST', root + '/followups', {'subject_user_id': 0, 'action': 'x'}),
                     ('POST', root + '/followups', {'subject_user_id': -1, 'action': 'x'}),
                     ('POST', root + '/followups', {'subject_user_id': True, 'action': 'x'}),
                     ('POST', root + '/followups', {'subject_user_id': '1', 'action': 'x'}),
                     ('POST', root + '/followups', {'subject_user_id': account['user']['id'], 'action': ' '}),
                     ('POST', root + '/followups', {'subject_user_id': account['user']['id'], 'action': 'x' * 1001})]
            for method, path, body in cases:
                await req(c, method, path, 422, json=body)
            for extra in ('user_id', 'date', 'organization_id', 'role', 'unknown'):
                await req(c, 'PUT', '/api/checkins/today', 422, json={'mood': 2, extra: 'forged'})
                await req(c, 'PATCH', '/api/me', 422, json={'display_name': 'x', 'personal_goal': '', extra: 'forged'})
            mutations = [('POST', '/api/teams', {'name': 'ok'}),
                         ('PATCH', '/api/me', {'display_name': 'ok', 'personal_goal': ''}),
                         ('PUT', '/api/checkins/today', {'mood': 2}),
                         ('POST', '/api/auth/logout', {})]
            for method, path, body in mutations:
                await req(c, method, path, 403, json=body, headers={'Origin': 'https://evil.test'})
                await req(c, method, path, 415, content=json.dumps(body), headers={'Content-Type': 'text/plain'})
            r = await req(c, 'POST', '/api/teams', 201, json={'name': '  ' + 'x' * 120 + '  '}, headers={'Origin': 'https://qa.test'})
            assert r.json()['name'] == 'x' * 120
            r = await req(c, 'PUT', '/api/checkins/today', json={'mood': 0, 'activity': ' trimmed '})
            assert r.json()['activity'] == 'trimmed'
            first = r.json()
            r = await req(c, 'PUT', '/api/checkins/today', json={'mood': 4})
            assert r.json()['id'] == first['id']
            assert sql(app, 'SELECT count(*) FROM checkins')[0][0] == 1
            response = await c.options('/api/me', headers={'Origin': 'https://evil.test', 'Access-Control-Request-Method': 'GET'})
            assert 'access-control-allow-origin' not in response.headers
    run(scenario())


def test_history_ranges_fixed_insight_and_bangkok_rollover(env):
    _, app, clock = env
    async def scenario():
        async with client(app) as c:
            account = await owner(c, 'history@example.test')
            for offset, mood in [(-13, 1), (-7, 1), (-6, 0), (-2, 4), (0, 2)]:
                seed(app, account, offset, mood)
            expected = {'current_mean': 2.0, 'previous_mean': 1.0, 'delta': 1.0, 'current_count': 3, 'previous_count': 2}
            for query in ('', '?from=2026-10-01&to=2026-10-01'):
                body = (await req(c, 'GET', '/api/checkins' + query)).json()
                assert body['insight'] == expected
                assert [e['date'] for e in body['entries']] == sorted(e['date'] for e in body['entries'])
                if query:
                    assert body['entries'] == []
            for query in ('from=2026-10-21', 'from=2026-10-20&to=2026-10-19', 'from=2026-02-30', 'from=2026-1-01'):
                await req(c, 'GET', '/api/checkins?' + query, 422)
            for length, status in ((366, 200), (367, 422)):
                first = TODAY - timedelta(days=length - 1)
                await req(c, 'GET', f'/api/checkins?from={first}&to={TODAY}', status)
            clock[0] = datetime(2026, 10, 20, 16, 59, tzinfo=UTC)
            assert (await req(c, 'PUT', '/api/checkins/today', json={'mood': 0})).json()['date'] == '2026-10-20'
            clock[0] += timedelta(minutes=1)
            assert (await req(c, 'PUT', '/api/checkins/today', json={'mood': 4})).json()['date'] == '2026-10-21'
    run(scenario())


@pytest.mark.parametrize('previous,delta', [([0, 0, 0, 0, 0, 0, 1], 0.19), ([0, 0, 0, 0, 0, 1], 0.17)])
def test_raw_mean_delta_personal_and_team(env, previous, delta):
    _, app, _ = env
    async def scenario():
        async with client(app) as c:
            account = await owner(c, 'rounding@example.test')
            t = await team(c, 'Rounding')
            joined(app, t, account, -20)
            for offset, mood in zip((-6, -3, 0), (0, 0, 1)):
                seed(app, account, offset, mood)
            for offset, mood in zip(range(-13, -6), previous):
                seed(app, account, offset, mood)
            personal = (await req(c, 'GET', '/api/checkins')).json()['insight']
            aggregate = (await req(c, 'GET', f"/api/teams/{t['id']}/dashboard")).json()['trend']
            expected = {'current_mean': 0.33, 'previous_mean': 0.14 if len(previous) == 7 else 0.17,
                        'delta': delta, 'current_count': 3, 'previous_count': len(previous)}
            assert personal == aggregate == expected
    run(scenario())


def test_team_weighting_eligibility_nulls_percentage_and_boundaries(env):
    _, app, _ = env
    async def scenario():
        async with client(app) as a, client(app) as b, client(app) as c:
            oa = await owner(a, 'stats@example.test')
            t = await team(a, 'Stats')
            mb = await member(b, t['join_code'], 'stats-b@example.test')
            mc = await member(c, t['join_code'], 'stats-c@example.test')
            joined(app, t, oa, -13)
            joined(app, t, mb, -6)
            joined(app, t, mc, 0)
            for who, offset, mood in ((oa, -14, 4), (oa, -13, 1), (oa, -7, 1),
                                       (mb, -7, 4), (oa, -6, 0), (mb, -6, 4), (oa, 0, 2)):
                seed(app, who, offset, mood)
            d = (await req(a, 'GET', f"/api/teams/{t['id']}/dashboard")).json()
            assert [x['date'] for x in d['days']] == [(TODAY - timedelta(days=n)).isoformat() for n in range(6, -1, -1)]
            assert d['trend'] == {'current_mean': 2.0, 'previous_mean': 1.0, 'delta': 1.0, 'current_count': 3, 'previous_count': 2}
            assert d['days'][0]['eligible_members'] == 2
            assert d['days'][0]['checkin_count'] == 2
            assert d['days'][0]['mean_mood'] == 2.0
            assert d['days'][-1]['participation_rate'] == 33.3
            assert d['days'][1]['mean_mood'] is None
            assert d['days'][1]['participation_rate'] == 0.0
            # Uneven daily counts: [0,4] and [2] above; now [0,0] and [4].
            sql(app, 'UPDATE checkins SET mood=0 WHERE user_id=? AND date=?', (mb['user']['id'], '2026-10-14'))
            sql(app, 'UPDATE checkins SET mood=4 WHERE user_id=? AND date=?', (oa['user']['id'], '2026-10-20'))
            d = (await req(a, 'GET', f"/api/teams/{t['id']}/dashboard")).json()
            assert d['trend']['current_mean'] == 1.33
            empty = await team(a, 'No entries')
            d = (await req(a, 'GET', f"/api/teams/{empty['id']}/dashboard")).json()
            assert d['days'][0] == {'date': '2026-10-14', 'eligible_members': 0, 'checkin_count': 0, 'participation_rate': None, 'mean_mood': None}
            assert d['trend']['previous_mean'] is None and d['trend']['delta'] is None
            # Empty roster in isolated fixture, including absence of owner membership.
            sql(app, 'DELETE FROM memberships WHERE team_id=?', (empty['id'],))
            d = (await req(a, 'GET', f"/api/teams/{empty['id']}/dashboard")).json()
            assert d['member_count'] == 0
            assert d['trend'] == {'current_mean': None, 'previous_mean': None, 'delta': None, 'current_count': 0, 'previous_count': 0}
            assert all(day['participation_rate'] is None for day in d['days'])
    run(scenario())


@pytest.mark.parametrize('join_offset,entries,reasons', [
    (-10, [(0, 0)], ['low_mood']), (-10, [(-1, 1)], ['low_mood']),
    (-10, [(0, 2)], []), (-10, [(-1, 0), (0, 4)], []),
    (-10, [(-2, 0)], []), (-10, [(-3, 0)], ['missing_3_days']),
    (0, [], []), (-1, [], []), (-2, [], ['missing_3_days']),
    (-2, [(-2, 1)], []), (-1, [(-2, 0)], []),
    (-2, [(-3, 4)], ['missing_3_days'])])
def test_candidate_latest_join_and_missing_boundaries(env, join_offset, entries, reasons):
    _, app, _ = env
    async def scenario():
        async with client(app) as a, client(app) as b:
            oa = await owner(a, 'candidate-owner@example.test')
            t = await team(a, 'Candidates')
            other = await team(a, 'Different join date')
            mb = await member(b, t['join_code'], 'candidate@example.test')
            await req(b, 'POST', '/api/teams/join', json={'join_code': other['join_code']})
            joined(app, t, mb, join_offset)
            joined(app, other, mb, 1)
            for offset, mood in entries:
                seed(app, mb, offset, mood)
            d = (await req(a, 'GET', f"/api/teams/{t['id']}/dashboard")).json()
            candidates = d['followup_candidates']
            assert [x['user_id'] for x in candidates] == sorted(x['user_id'] for x in candidates)
            own = [x for x in candidates if x['user_id'] == mb['user']['id']]
            assert own == ([{'user_id': mb['user']['id'], 'display_name': 'candidate', 'reasons': reasons}] if reasons else [])
            assert all(len(x['reasons']) == 1 for x in candidates)
            other_d = (await req(a, 'GET', f"/api/teams/{other['id']}/dashboard")).json()
            assert mb['user']['id'] not in [x['user_id'] for x in other_d['followup_candidates']]
            assert_public(d)
    run(scenario())


def test_shared_followups_persistence_private_history_assessment(env):
    module, app, clock = env
    async def scenario():
        async with AsyncExitStack() as stack:
            c, accounts, t = await world(app, stack)
            root = f"/api/teams/{t['a1']['id']}"
            await req(c['member'], 'PATCH', '/api/me', json={'display_name': 'Member', 'personal_goal': MARKER})
            await req(c['member'], 'PUT', '/api/checkins/today', json={'mood': 1, 'activity': MARKER, 'private_note': MARKER})
            assert MARKER in (await req(c['member'], 'GET', '/api/checkins')).text
            assert MARKER not in (await req(c['a'], 'GET', '/api/checkins')).text
            task = (await req(c['manager'], 'POST', root + '/followups', 201,
                              json={'subject_user_id': accounts['member']['user']['id'], 'action': ' Offer support '})).json()
            assert task['action'] == 'Offer support' and task['status'] == 'open'
            assert task['created_by'] == accounts['manager']['user']['id']
            await req(c['a'], 'PATCH', root + f"/followups/{task['id']}", json={'action': 'Done', 'status': 'done'})
            assert (await req(c['manager'], 'GET', root + '/followups')).json()['followups'][0]['status'] == 'done'
            reopened = module.create_app(app.state.db_path.parent)
            reopened.state.clock = lambda: clock[0]
            async with client(reopened) as restored:
                restored.cookies.set(COOKIE, c['manager'].cookies.get(COOKIE))
                assert (await req(restored, 'GET', root + '/followups')).json()['followups'][0]['status'] == 'done'
                await req(restored, 'PATCH', root + f"/followups/{task['id']}", json={'action': 'Continue', 'status': 'open'})
            assert (await req(c['a'], 'GET', root + '/followups')).json()['followups'][0]['status'] == 'open'
            for role in ('a', 'manager'):
                for suffix in ('/members', '/dashboard', '/followups'):
                    assert_public((await req(c[role], 'GET', root + suffix)).json())
            assessment = (await req(c['member'], 'GET', '/api/assessment')).json()
            assert assessment == {'status': 'pending_rules', 'message': 'รอกำหนดกติกาการประเมิน ยังไม่มีการคำนวณคะแนน burnout'}
            isolated = module.create_app(app.state.db_path.parent / 'separate')
            isolated.state.clock = lambda: clock[0]
            async with client(isolated) as stranger:
                stranger.cookies.set(COOKIE, c['a'].cookies.get(COOKIE))
                await req(stranger, 'GET', '/api/me', 401)
    run(scenario())
