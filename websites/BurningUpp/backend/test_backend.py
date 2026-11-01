"""Proposed integration tests. Run with pytest; no pytest async plugin required."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
from pathlib import Path
import sqlite3

import httpx
import pytest


@pytest.fixture
def backend(tmp_path, monkeypatch):
    # Set before importing main so its required module-level app is isolated too.
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path / 'module-app'))
    module = importlib.import_module('backend.main')
    app = module.create_app(tmp_path / 'scenario')
    clock = [datetime(2026, 10, 20, 16, 59, tzinfo=timezone.utc)]
    app.state.clock = lambda: clock[0]
    return module, app, clock


def run(coroutine):
    return asyncio.run(coroutine)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver')


async def owner(c, email='owner@example.com'):
    response = await c.post('/api/auth/register-organization', json={
        'organization_name': ' Example ', 'display_name': ' Owner ',
        'email': email, 'password': 'correct horse battery'})
    assert response.status_code == 201, response.text
    return response.json()


async def team(c, name='Team'):
    response = await c.post('/api/teams', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()


async def member(c, code, email='member@example.com'):
    response = await c.post('/api/auth/register-member', json={
        'join_code': code, 'display_name': 'Member', 'email': email,
        'password': 'member password'})
    assert response.status_code == 201, response.text
    return response.json()


def test_sessions_validation_origin_and_reopen(backend, tmp_path):
    module, app, clock = backend

    async def scenario():
        async with client(app) as c:
            assert (await c.get('/api/me')).status_code == 401
            account = await owner(c)
            assert account['user']['display_name'] == 'Owner'
            assert account['today'] == '2026-10-20'
            token = c.cookies.get(module.COOKIE)
            assert len(token) >= 43
            with sqlite3.connect(app.state.db_path) as db:
                stored = db.execute('SELECT token_hash FROM sessions').fetchone()[0]
                password_hash = db.execute('SELECT password_hash FROM users').fetchone()[0]
            assert stored == hashlib.sha256(token.encode()).hexdigest()
            assert token != stored
            assert 'correct horse battery' not in password_hash
            assert module.verify_password('correct horse battery', password_hash)
            for mood in (True, 1.5, '2', -1, 5):
                r = await c.put('/api/checkins/today', json={'mood': mood})
                assert r.status_code == 422
                assert isinstance(r.json()['detail'], str)
            assert (await c.patch('/api/me', json={'display_name': 'X'})).status_code == 422
            assert (await c.put('/api/checkins/today', json={'mood': 2, 'user_id': 123})).status_code == 422
            assert (await c.post('/api/teams', json={'name': '   '})).status_code == 422
            r = await c.post('/api/auth/logout', headers={'Origin': 'https://evil.example'})
            assert r.status_code == 403
            assert (await c.get('/api/me')).status_code == 200
            r = await c.post('/api/teams', content='{"name":"X"}', headers={'Content-Type': 'text/plain'})
            assert r.status_code == 415
            reopened = module.create_app(app.state.db_path.parent)
            reopened.state.clock = lambda: clock[0]
            async with client(reopened) as c2:
                c2.cookies.set(module.COOKIE, token)
                assert (await c2.get('/api/me')).json()['user']['id'] == account['user']['id']
            clock[0] += timedelta(days=7)
            assert (await c.get('/api/me')).status_code == 401
            r = await c.post('/api/auth/login', json={'email': 'owner@example.com', 'password': 'correct horse battery'})
            assert r.status_code == 200
            cookie = r.headers['set-cookie'].lower()
            assert 'httponly' in cookie and 'secure' in cookie and 'samesite=lax' in cookie and 'path=/' in cookie
            assert (await c.post('/api/auth/logout', headers={'Origin': 'https://testserver'})).status_code == 200
            assert (await c.get('/api/me')).status_code == 401
            assert (await c.get('/api/unknown')).status_code == 404
    run(scenario())


def test_team_authorization_privacy_and_followup_scope(backend):
    module, app, clock = backend

    async def scenario():
        async with client(app) as a, client(app) as b, client(app) as outsider, client(app) as foreign:
            account = await owner(a)
            first = await team(a, 'First')
            second = await team(a, 'Second')
            m = await member(b, first['join_code'])
            await member(outsider, second['join_code'], 'other@example.com')
            await owner(foreign, 'foreign@example.com')
            foreign_team = await team(foreign, 'Foreign')
            root = '/api/teams/' + str(first['id'])
            assert (await b.get(root + '/members')).status_code == 403
            assert (await outsider.get(root + '/members')).status_code == 404
            assert (await foreign.get(root + '/dashboard')).status_code == 404
            assert (await b.post('/api/teams/join', json={'join_code': foreign_team['join_code']})).status_code == 404
            assert (await b.get('/api/teams')).json()['teams'][0]['join_code'] is None
            for _ in range(2):
                assert (await b.post('/api/teams/join', json={'join_code': first['join_code']})).status_code == 200
            roster = (await a.get(root + '/members')).json()['members']
            assert len(roster) == 2
            assert (await a.patch(root + '/members/' + str(m['user']['id']), json={'role': 'manager'})).status_code == 200
            assert (await b.get(root + '/members')).status_code == 200
            assert (await b.get('/api/teams/' + str(second['id']) + '/members')).status_code == 404
            assert (await b.patch(root + '/members/' + str(account['user']['id']), json={'role': 'member'})).status_code == 403
            await b.patch('/api/me', json={'display_name': 'Member', 'personal_goal': 'PRIVATE GOAL'})
            await b.put('/api/checkins/today', json={'mood': 1, 'activity': 'PRIVATE ACTIVITY', 'private_note': 'PRIVATE NOTE'})
            for suffix in ('/members', '/dashboard', '/followups'):
                result = await a.get(root + suffix)
                assert result.status_code == 200
                for secret in ('PRIVATE GOAL', 'PRIVATE ACTIVITY', 'PRIVATE NOTE', 'password_hash', 'token_hash'):
                    assert secret not in result.text
            r = await b.post(root + '/followups', json={'subject_user_id': m['user']['id'], 'action': ' Offer support '})
            assert r.status_code == 201
            task = r.json()
            assert task['created_by'] == m['user']['id'] and task['action'] == 'Offer support'
            assert (await a.patch('/api/teams/' + str(second['id']) + '/followups/' + str(task['id']),
                                  json={'action': 'Wrong scope', 'status': 'done'})).status_code == 404
            assert (await a.patch(root + '/followups/' + str(task['id']),
                                  json={'action': 'Support offered', 'status': 'done'})).json()['status'] == 'done'
            assert (await a.post(root + '/followups', json={'subject_user_id': 99999, 'action': 'X'})).status_code == 404
            assert (await b.get('/api/assessment')).json()['status'] == 'pending_rules'
    run(scenario())


def test_bangkok_upsert_windows_eligibility_and_percentage(backend):
    module, app, clock = backend

    async def scenario():
        async with client(app) as a, client(app) as b:
            await owner(a)
            t = await team(a)
            await member(b, t['join_code'])
            # Oct 20 16:59 UTC is Oct 20 Bangkok. One row per user/date.
            first = (await b.put('/api/checkins/today', json={'mood': 0})).json()
            second = (await b.put('/api/checkins/today', json={'mood': 2})).json()
            assert first['id'] == second['id']
            assert second['date'] == '2026-10-20'
            day = (await a.get('/api/teams/' + str(t['id']) + '/dashboard')).json()['days'][-1]
            assert day['eligible_members'] == 2
            assert day['participation_rate'] == 50.0
            assert day['checkin_count'] == 1 and day['mean_mood'] == 2
            clock[0] += timedelta(minutes=1)
            assert (await b.get('/api/me')).json()['today'] == '2026-10-21'
            third = (await b.put('/api/checkins/today', json={'mood': 4})).json()
            assert third['id'] != first['id']
            clock[0] += timedelta(days=6)
            # Oct 27: Oct 21 belongs to current window; Oct 20 to previous.
            r = await b.get('/api/checkins?from=2026-10-01&to=2026-10-01')
            assert r.status_code == 200 and r.json()['entries'] == []
            assert r.json()['insight'] == {'current_mean': 4.0, 'previous_mean': 2.0, 'delta': 2.0,
                                           'current_count': 1, 'previous_count': 1}
            for query in ('from=2026-10-28', 'from=2026-10-22&to=2026-10-21',
                          'from=2026-02-30', 'from=2026-1-01', 'from=2020-01-01'):
                assert (await b.get('/api/checkins?' + query)).status_code == 422
            # Distinct factory paths do not leak data.
            isolated = module.create_app(app.state.db_path.parent / 'isolated')
            isolated.state.clock = lambda: clock[0]
            async with client(isolated) as c:
                c.cookies.set(module.COOKIE, b.cookies.get(module.COOKIE))
                assert (await c.get('/api/me')).status_code == 401
    run(scenario())


def test_registration_rollback_and_composite_foreign_keys(backend):
    module, app, clock = backend

    async def scenario():
        async with client(app) as a, client(app) as b:
            first = await owner(a)
            t = await team(a)
            other = await owner(b, 'second@example.com')
            r = await b.post('/api/auth/register-organization', json={
                'organization_name': 'Must roll back', 'display_name': 'Duplicate',
                'email': 'owner@example.com', 'password': 'long password'})
            assert r.status_code == 409
            with module.connect(app.state.db_path) as db:
                assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
                assert db.execute('SELECT count(*) FROM organizations').fetchone()[0] == 2
                with pytest.raises(sqlite3.IntegrityError):
                    with db:
                        db.execute('INSERT INTO memberships(organization_id,team_id,user_id,role,joined_on) VALUES(?,?,?,?,?)',
                                   (first['organization']['id'], t['id'], other['user']['id'], 'member', '2026-10-20'))
                assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    run(scenario())


def test_static_routes_when_frontend_present(backend):
    module, app, clock = backend
    frontend = Path(module.__file__).resolve().parent.parent / 'frontend'

    async def scenario():
        async with client(app) as c:
            for url, filename, media in (('/', 'index.html', 'text/html'),
                                          ('/styles.css', 'styles.css', 'text/css'),
                                          ('/app.js', 'app.js', 'text/javascript')):
                r = await c.get(url)
                if (frontend / filename).is_file():
                    assert r.status_code == 200
                    assert r.content == (frontend / filename).read_bytes()
                    assert media in r.headers['content-type']
                else:
                    assert r.status_code == 404
            r = await c.get('/api/nonexistent')
            assert r.status_code == 404 and r.json() == {'detail': 'Not Found'}
    run(scenario())
