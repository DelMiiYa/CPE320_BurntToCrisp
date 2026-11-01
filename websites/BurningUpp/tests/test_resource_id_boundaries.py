"""BUG-001 acceptance regression: scoped rejection before SQLite binding.

Host sets temporary APP_DATA_DIR before collection and runs:
    python -m pytest tests/ -q
Existing env/world fixtures create isolated temporary databases. These tests
provide no evidence about browser rendering or frontend session handling.
"""
import asyncio
from contextlib import AsyncExitStack

import pytest

from test_qa import env, client, req, world
from test_regression import snapshot


# Signed endpoints fit SQLite but cannot identify the small fixture records;
# adjacent and very large integers must also produce a controlled scoped 404.
IDS = (-(1 << 63) - 1, -(1 << 63), -1, 0,
       (1 << 63) - 1, 1 << 63, 10 ** 80)
TEAM_ROUTES = ('members', 'role', 'dashboard', 'list-followups',
               'create-followup', 'edit-followup')


def request_for(kind, team_id, subject, task_id):
    root = f'/api/teams/{team_id}'
    return {
        'members': ('GET', root + '/members', None),
        'role': ('PATCH', root + f'/members/{subject}', {'role': 'manager'}),
        'dashboard': ('GET', root + '/dashboard', None),
        'list-followups': ('GET', root + '/followups', None),
        'create-followup': ('POST', root + '/followups',
                            {'subject_user_id': subject, 'action': 'Support'}),
        'edit-followup': ('PATCH', root + f'/followups/{task_id}',
                          {'action': 'Support', 'status': 'done'}),
    }[kind]


async def rejected(c, app, method, path, body, status):
    before = snapshot(app)
    cookies = list(c.cookies.items())
    kwargs = {} if body is None else {'json': body}
    response = await req(c, method, path, status, **kwargs)
    assert isinstance(response.json().get('detail'), str)
    assert snapshot(app) == before
    assert list(c.cookies.items()) == cookies
    assert 'set-cookie' not in response.headers


@pytest.mark.parametrize('identifier', IDS)
def test_all_team_routes_reject_missing_boundary_ids_atomically(env, identifier):
    _, app, _ = env

    async def scenario():
        async with AsyncExitStack() as stack:
            clients, accounts, teams = await world(app, stack)
            subject = accounts['member']['user']['id']
            for kind in TEAM_ROUTES:
                method, path, body = request_for(kind, identifier, subject, 1)
                for role in ('a', 'manager', 'b'):
                    await rejected(clients[role], app, method, path, body, 404)
                # Authentication must precede resource lookup, even for huge IDs.
                await rejected(clients['anon'], app, method, path, body, 401)

    asyncio.run(scenario())


@pytest.mark.parametrize('identifier', IDS)
def test_nested_identifier_boundaries_and_authorization_order(env, identifier):
    _, app, _ = env

    async def scenario():
        async with AsyncExitStack() as stack:
            clients, accounts, teams = await world(app, stack)
            root = f"/api/teams/{teams['a1']['id']}"
            cases = [
                ('PATCH', root + f'/members/{identifier}', {'role': 'manager'}, 404),
                ('PATCH', root + f'/followups/{identifier}',
                 {'action': 'Support', 'status': 'done'}, 404),
                ('POST', root + '/followups',
                 {'subject_user_id': identifier, 'action': 'Support'},
                 422 if identifier <= 0 else 404),
            ]
            for method, path, body, expected in cases:
                await rejected(clients['a'], app, method, path, body, expected)
                await rejected(clients['anon'], app, method, path, body, 401)

            # For schema-valid subject IDs and all path IDs, foreign-team access
            # is denied before nested-resource lookup. A member can access the
            # team, but lacks permission for follow-up administration.
            for method, path, body, expected in cases:
                if method == 'POST' and identifier <= 0:
                    continue
                await rejected(clients['b'], app, method, path, body, 404)
                if '/followups' in path:
                    await rejected(clients['member'], app, method, path, body, 403)
                    await rejected(clients['manager'], app, method, path, body, 404)
                else:
                    # Missing scoped membership remains 404 before owner-only
                    # role mutation, as specified by the shared API contract.
                    await rejected(clients['manager'], app, method, path, body, 404)

    asyncio.run(scenario())


def test_boundary_rejections_do_not_break_subsequent_valid_work(env):
    _, app, _ = env

    async def scenario():
        async with AsyncExitStack() as stack:
            clients, accounts, teams = await world(app, stack)
            root = f"/api/teams/{teams['a1']['id']}"
            subject = accounts['member']['user']['id']
            await rejected(clients['manager'], app, 'POST', root + '/followups',
                           {'subject_user_id': 1 << 63, 'action': 'Rejected'}, 404)
            created = (await req(clients['manager'], 'POST', root + '/followups',
                                201, json={'subject_user_id': subject,
                                           'action': 'Valid support'})).json()
            await rejected(clients['a'], app, 'PATCH', root + f'/followups/{1 << 63}',
                           {'action': 'Rejected', 'status': 'done'}, 404)
            updated = (await req(clients['a'], 'PATCH',
                                root + f"/followups/{created['id']}",
                                json={'action': 'Completed support',
                                      'status': 'done'})).json()
            assert updated['id'] == created['id']
            assert updated['created_by'] == accounts['manager']['user']['id']
            assert updated['status'] == 'done'
            tasks = (await req(clients['manager'], 'GET',
                               root + '/followups')).json()['followups']
            assert tasks == [updated]

    asyncio.run(scenario())
