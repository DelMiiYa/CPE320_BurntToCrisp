"""Additional acceptance boundaries; reuse existing isolated QA fixtures.

Host sets temporary APP_DATA_DIR before pytest collection. No preview data used.
These API tests do not establish interactive frontend behavior.
"""
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta

import pytest

from test_qa import (
    env, client, req, owner, team, world, sql, PASSWORD, COOKIE, MARKER,
)
from test_regression import snapshot


@pytest.mark.parametrize('field,value', [
    ('organization_name', ''), ('organization_name', '   '),
    ('organization_name', 'x' * 121), ('display_name', ' '),
    ('display_name', 'x' * 81), ('email', 'invalid'),
    ('email', 'a@b'), ('email', 'x' * 245 + '@example.test'),
    ('password', 'x' * 9), ('password', ' ' * 10),
    ('password', 'x' * 129), ('password', True),
])
def test_invalid_registration_is_atomic(env, field, value):
    _, app, _ = env

    async def scenario():
        async with client(app) as c:
            before = snapshot(app)
            body = {
                'organization_name': 'Valid organization',
                'display_name': 'Valid owner',
                'email': 'valid@example.test', 'password': PASSWORD,
            }
            body[field] = value
            response = await req(c, 'POST', '/api/auth/register-organization',
                                 422, json=body)
            assert snapshot(app) == before
            assert COOKIE not in c.cookies
            assert 'set-cookie' not in response.headers
            await req(c, 'GET', '/api/me', 401)

    asyncio.run(scenario())


@pytest.mark.parametrize('mood', range(5))
def test_every_allowed_mood_round_trips(env, mood):
    _, app, _ = env

    async def scenario():
        async with client(app) as c:
            await owner(c, 'allowed@example.test')
            saved = (await req(c, 'PUT', '/api/checkins/today', json={
                'mood': mood, 'activity': ' activity ',
                'private_note': ' note ',
            })).json()
            assert saved['mood'] == mood
            assert type(saved['mood']) is int
            assert saved['activity'] == 'activity'
            assert saved['private_note'] == 'note'
            entries = (await req(c, 'GET', '/api/checkins')).json()['entries']
            assert entries == [saved]

    asyncio.run(scenario())


def test_duplicate_join_preserves_manager_role_and_original_join_date(env):
    _, app, clock = env

    async def scenario():
        async with AsyncExitStack() as stack:
            clients, accounts, teams = await world(app, stack)
            t = teams['a1']
            uid = accounts['manager']['user']['id']
            before = sql(app, 'SELECT role,joined_on FROM memberships '
                         'WHERE team_id=? AND user_id=?', (t['id'], uid))
            clock[0] += timedelta(days=1)
            for _ in range(2):
                result = (await req(clients['manager'], 'POST',
                    '/api/teams/join', json={'join_code': t['join_code']})).json()
                assert result['my_role'] == 'manager'
                assert result['join_code'] == t['join_code']
            assert sql(app, 'SELECT role,joined_on FROM memberships '
                       'WHERE team_id=? AND user_id=?', (t['id'], uid)) == before

    asyncio.run(scenario())


def test_session_valid_immediately_before_expiry_invalid_at_expiry(env):
    _, app, clock = env

    async def scenario():
        async with client(app) as c:
            await owner(c, 'expiry-boundary@example.test')
            token = c.cookies.get(COOKIE)
            registered_at = clock[0]
            clock[0] = registered_at + timedelta(days=7, microseconds=-1)
            await req(c, 'GET', '/api/me')
            clock[0] += timedelta(microseconds=1)
            await req(c, 'GET', '/api/me', 401,
                      headers={'Cookie': f'{COOKIE}={token}'})

    asyncio.run(scenario())


def test_cross_organization_history_and_profile_remain_own(env):
    _, app, _ = env

    async def scenario():
        async with AsyncExitStack() as stack:
            clients, accounts, teams = await world(app, stack)
            await req(clients['member'], 'PATCH', '/api/me', json={
                'display_name': 'Private member', 'personal_goal': MARKER,
            })
            await req(clients['member'], 'PUT', '/api/checkins/today', json={
                'mood': 0, 'activity': MARKER, 'private_note': MARKER,
            })
            for role in ('a', 'b', 'manager'):
                history = (await req(clients[role], 'GET', '/api/checkins')).json()
                assert history['entries'] == []
                assert history['insight']['current_count'] == 0
                assert history['insight']['current_mean'] is None
                assert MARKER not in (await req(clients[role], 'GET', '/api/me')).text
            own = (await req(clients['member'], 'GET', '/api/checkins')).json()
            assert own['entries'][0]['private_note'] == MARKER
            assert (await req(clients['member'], 'GET', '/api/me')).json()['user']['personal_goal'] == MARKER

    asyncio.run(scenario())


def test_followups_newest_first_with_timestamp_ties(env):
    _, app, _ = env

    async def scenario():
        async with AsyncExitStack() as stack:
            clients, accounts, teams = await world(app, stack)
            root = f"/api/teams/{teams['a1']['id']}/followups"
            ids = []
            for action in ('First', 'Second', 'Third'):
                task = (await req(clients['manager'], 'POST', root, 201, json={
                    'subject_user_id': accounts['member']['user']['id'],
                    'action': action,
                })).json()
                ids.append(task['id'])
            tasks = (await req(clients['a'], 'GET', root)).json()['followups']
            assert [task['id'] for task in tasks] == ids[::-1]
            await req(clients['a'], 'PATCH', root + f'/{ids[0]}', json={
                'action': 'Edited oldest', 'status': 'done',
            })
            tasks = (await req(clients['manager'], 'GET', root)).json()['followups']
            assert [task['id'] for task in tasks] == ids[::-1]

    asyncio.run(scenario())


@pytest.mark.parametrize('resource', ['team', 'member', 'subject', 'followup'])
def test_huge_positive_resource_ids_return_scoped_not_found_atomically(env, resource):
    _, app, _ = env

    async def scenario():
        async with client(app) as c:
            account = await owner(c, 'huge-id@example.test')
            t = await team(c, 'Huge identifiers')
            root = f"/api/teams/{t['id']}"
            huge = 10 ** 80
            before = snapshot(app)
            if resource == 'team':
                await req(c, 'GET', f'/api/teams/{huge}/dashboard', 404)
            elif resource == 'member':
                await req(c, 'PATCH', root + f'/members/{huge}', 404,
                          json={'role': 'manager'})
            elif resource == 'subject':
                await req(c, 'POST', root + '/followups', 404,
                          json={'subject_user_id': huge, 'action': 'Support'})
            else:
                await req(c, 'PATCH', root + f'/followups/{huge}', 404,
                          json={'action': 'Support', 'status': 'done'})
            assert snapshot(app) == before

    asyncio.run(scenario())
