"""Additional independent acceptance coverage; requires supplied test_qa.py.

Host executes python -m pytest tests/ -q. Never accesses preview data.
"""
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from test_qa import env, client, req, world, owner, team, member, joined, seed, sql


def snapshot(app):
    with sqlite3.connect(app.state.db_path) as db:
        return tuple(db.iterdump())


def test_actual_import_modes_and_safe_default_persistence(tmp_path):
    source = Path(__file__).resolve().parents[1]
    copied = tmp_path / 'copy'
    backend = copied / 'backend'
    backend.mkdir(parents=True)
    # Copy source only: never copy, import against, or alter preview data.
    for name in ('main.py', '__init__.py'):
        shutil.copyfile(source / 'backend' / name, backend / name)
    script = '''
import importlib, os, socket, sqlite3
from pathlib import Path

def forbidden(*args, **kwargs):
    raise AssertionError('Import opened a listener')
socket.socket.bind = forbidden
socket.socket.listen = forbidden
m = importlib.import_module(os.environ['QA_IMPORT_MODE'])
assert callable(m.create_app)
expected = Path(os.environ['QA_EXPECTED_DB']).resolve()
assert m.app.state.db_path == expected, (m.app.state.db_path, expected)
with sqlite3.connect(expected) as db:
    db.execute("INSERT INTO organizations(name,created_at) VALUES('persistent sentinel','2026-10-20T00:00:00Z')")
again = m.create_app()
assert again.state.db_path == expected
with sqlite3.connect(again.state.db_path) as db:
    assert db.execute("SELECT name FROM organizations").fetchall() == [('persistent sentinel',)]
'''
    for mode, explicit in (('backend.main', True), ('main', True), ('backend.main', False)):
        process_env = os.environ.copy()
        process_env.pop('APP_DATA_DIR', None)
        process_env['PYTHONDONTWRITEBYTECODE'] = '1'
        process_env['PYTHONPATH'] = str(copied if mode == 'backend.main' else backend)
        process_env['QA_IMPORT_MODE'] = mode
        if explicit:
            directory = tmp_path / ('explicit-' + mode)
            process_env['APP_DATA_DIR'] = str(directory)
        else:
            directory = backend / 'data'
        process_env['QA_EXPECTED_DB'] = str(directory / 'burningupp.sqlite3')
        result = subprocess.run([sys.executable, '-c', script], cwd=copied,
                                env=process_env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, (mode, explicit, result.stdout, result.stderr)


# Every API mutation has a valid same-origin request, hostile-Origin rejection,
# supplied non-JSON rejection, and persisted-state comparison after rejection.
MUTATIONS = ('register-organization', 'register-member', 'login', 'logout',
             'profile', 'create-team', 'join', 'role', 'checkin',
             'create-followup', 'edit-followup')


async def mutation_context(app, stack, kind):
    clients, accounts, teams = await world(app, stack)
    c = clients['a']
    root = f"/api/teams/{teams['a1']['id']}"
    subject = accounts['member']['user']['id']
    task = (await req(c, 'POST', root + '/followups', 201,
                      json={'subject_user_id': subject, 'action': 'Initial'})).json()
    cases = {
        'register-organization': ('POST', '/api/auth/register-organization',
            {'organization_name': 'New', 'display_name': 'New',
             'email': 'new-owner@example.test', 'password': 'long password'}, 201),
        'register-member': ('POST', '/api/auth/register-member',
            {'join_code': teams['a1']['join_code'], 'display_name': 'New',
             'email': 'new-member@example.test', 'password': 'long password'}, 201),
        'login': ('POST', '/api/auth/login',
            {'email': 'a@example.test', 'password': '  independent password  '}, 200),
        'logout': ('POST', '/api/auth/logout', {}, 200),
        'profile': ('PATCH', '/api/me', {'display_name': 'Changed', 'personal_goal': 'Goal'}, 200),
        'create-team': ('POST', '/api/teams', {'name': 'New team'}, 201),
        'join': ('POST', '/api/teams/join', {'join_code': teams['a2']['join_code']}, 200),
        'role': ('PATCH', root + f'/members/{subject}', {'role': 'manager'}, 200),
        'checkin': ('PUT', '/api/checkins/today', {'mood': 4}, 200),
        'create-followup': ('POST', root + '/followups', {'subject_user_id': subject, 'action': 'Support'}, 201),
        'edit-followup': ('PATCH', root + f"/followups/{task['id']}", {'action': 'Finished', 'status': 'done'}, 200),
    }
    if kind in ('register-organization', 'register-member', 'login'):
        c = clients['anon']
    if kind == 'join':
        c = clients['manager']  # Actual new membership, rather than an existing join.
    return c, cases[kind]


@pytest.mark.parametrize('kind', MUTATIONS)
def test_every_mutation_origin_media_and_rejected_write_atomicity(env, kind):
    _, app, _ = env
    async def scenario():
        async with AsyncExitStack() as stack:
            c, (method, path, body, success) = await mutation_context(app, stack, kind)
            before = snapshot(app)
            cookies = list(c.cookies.items())
            await req(c, method, path, 403, json=body, headers={'Origin': 'https://foreign.test'})
            assert snapshot(app) == before
            assert list(c.cookies.items()) == cookies
            await req(c, method, path, 415, content=json.dumps(body),
                      headers={'Origin': 'https://qa.test', 'Content-Type': 'text/plain'})
            assert snapshot(app) == before
            assert list(c.cookies.items()) == cookies
            await req(c, method, path, success, json=body, headers={'Origin': 'https://qa.test'})
    asyncio.run(scenario())


FORGED = {
    'register-organization': ('role', 'organization_id', 'user_id'),
    'register-member': ('role', 'organization_id', 'user_id'),
    'login': ('role', 'organization_id'),
    'profile': ('role', 'organization_id', 'user_id'),
    'create-team': ('role', 'organization_id', 'team_id'),
    'join': ('role', 'organization_id', 'team_id'),
    'role': ('organization_id', 'user_id', 'team_id'),
    'checkin': ('role', 'organization_id', 'user_id', 'date', 'team_id'),
    'create-followup': ('user_id', 'team_id', 'organization_id', 'created_by', 'status'),
    'edit-followup': ('subject_user_id', 'team_id', 'organization_id', 'created_by'),
}


@pytest.mark.parametrize('kind,extra', [(kind, extra) for kind, extras in FORGED.items() for extra in extras])
def test_forged_fields_rejected_without_mutation(env, kind, extra):
    _, app, _ = env
    async def scenario():
        async with AsyncExitStack() as stack:
            c, (method, path, body, _) = await mutation_context(app, stack, kind)
            before = snapshot(app)
            await req(c, method, path, 422, json={**body, extra: 'forged'})
            assert snapshot(app) == before
    asyncio.run(scenario())


@pytest.mark.parametrize('offset', [-7, 0])
def test_one_nonempty_window_has_null_delta_personal_and_team(env, offset):
    _, app, _ = env
    async def scenario():
        async with client(app) as c:
            account = await owner(c, 'one-window@example.test')
            t = await team(c, 'One window')
            joined(app, t, account, -20)
            seed(app, account, offset, 4)
            personal = (await req(c, 'GET', '/api/checkins')).json()['insight']
            aggregate = (await req(c, 'GET', f"/api/teams/{t['id']}/dashboard")).json()['trend']
            expected = {'current_mean': 4.0 if offset == 0 else None,
                        'previous_mean': 4.0 if offset == -7 else None,
                        'delta': None, 'current_count': int(offset == 0),
                        'previous_count': int(offset == -7)}
            assert personal == aggregate == expected
    asyncio.run(scenario())


def test_daily_mean_rounds_two_places_and_half_participation(env):
    _, app, _ = env
    async def scenario():
        async with AsyncExitStack() as stack:
            a = await stack.enter_async_context(client(app))
            account = await owner(a, 'daily-owner@example.test')
            t = await team(a, 'Daily rounding')
            people = [account]
            for index in range(5):
                c = await stack.enter_async_context(client(app))
                people.append(await member(c, t['join_code'], f'daily-{index}@example.test'))
            for person, mood in zip(people, (0, 0, 1)):
                seed(app, person, 0, mood)
            d = (await req(a, 'GET', f"/api/teams/{t['id']}/dashboard")).json()
            assert d['days'][-1] == {'date': '2026-10-20', 'eligible_members': 6,
                'checkin_count': 3, 'participation_rate': 50.0, 'mean_mood': 0.33}
    asyncio.run(scenario())
