"""User flows: durable chat, queued edits, one current website and local-only preview."""
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from se_team.crew import codex_runtime as agents
from se_team.crew.job_events import JobCancelled, bind_job, check_cancelled, emit
from se_team.models import FinalSignOff, QAReport
from se_team.office.manager import OfficeRunner
from se_team.office.preview import create_preview
from se_team.office.server import create_app
from se_team.office.store import Store
from tests.test_flow_smoke import make_dummy_spec


@pytest.fixture
def office(tmp_path):
    app = create_app(tmp_path / 'office', start_worker=False, max_rounds=1)
    with TestClient(app) as client:
        token = client.get('/office-api/bootstrap').json()['token']
        yield app, client, {'X-Office-Token': token}


def new_project(client, headers, name='Project'):
    response = client.post('/office-api/projects', json={'name': name, 'brief': 'a calculator'}, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_chat_and_queue_survive_reopening_database(office):
    app, client, headers = office
    project = new_project(client, headers)
    command = client.post(f"/office-api/projects/{project['id']}/messages", json={'content': 'สร้างเว็บให้หน่อย'}, headers=headers)
    assert command.status_code == 202
    reopened = Store(app.state.store.root)
    snapshot = reopened.snapshot(project['id'])
    assert snapshot['messages'][-1]['content'] == 'สร้างเว็บให้หน่อย'
    assert snapshot['commands'][0]['status'] == 'queued'
    assert len(reopened.events(project['id'])) == 2


def test_office_rejects_cross_origin_writes_and_untrusted_hosts(office):
    _, client, headers = office
    assert client.post('/office-api/projects', json={'name': 'x'}).status_code == 403
    assert client.post('/office-api/projects', json={'name': 'x'}, headers={**headers, 'Origin': 'http://malicious.example'}).status_code == 403
    assert client.get('/office-api/bootstrap', headers={'Origin': 'http://malicious.example'}).status_code == 403
    assert client.get('/office-api/bootstrap', headers={'Host': 'untrusted.example'}).status_code == 403
    assert client.post('/office-api/projects', json={'name': 'x'}, headers={**headers, 'Origin': 'http://testserver'}).status_code == 201


def test_initial_office_and_assets_serve_without_external_dependencies(office):
    _, client, _ = office
    page = client.get('/')
    assert page.status_code == 200 and 'Burnt Studio' in page.text
    assert "frame-ancestors 'none'" in page.headers['content-security-policy']
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/assets/app.js').headers['cache-control'] == 'no-store'
    assert client.get('/assets/style.css').status_code == 200


def test_file_reads_cannot_cross_project_or_read_env(office):
    app, client, headers = office
    first, second = new_project(client, headers, 'A'), new_project(client, headers, 'B')
    command = app.state.store.enqueue(first['id'], 'build')
    revision = app.state.store.new_revision(command)
    source = app.state.store.revision_dir(revision)
    (source / 'frontend').mkdir(parents=True)
    (source / 'frontend' / 'index.html').write_text('<h1>Hello</h1>')
    (source / '.env').write_text('SECRET=do-not-return')
    base = f"/office-api/projects/{first['id']}"
    assert client.get(base + '/file', params={'path': 'frontend/index.html'}).json()['content'] == '<h1>Hello</h1>'
    assert client.get(base + '/file', params={'path': '../.env'}).status_code == 404
    assert client.get(base + '/file', params={'path': '.env'}).status_code == 404
    assert client.get(f"/office-api/projects/{second['id']}/revisions/{revision['id']}/files").status_code == 404


def test_recovery_marks_interrupted_work_and_keeps_instructions(tmp_path):
    store = Store(tmp_path)
    project = store.create_project('A', 'brief')
    store.enqueue(project['id'], 'add a chart')
    command = store.claim_command()
    revision = store.new_revision(command)
    store.recover()
    snapshot = store.snapshot(project['id'])
    assert snapshot['commands'][0]['status'] == 'interrupted'
    assert snapshot['revisions'][0]['status'] == 'interrupted'
    assert snapshot['messages'][1]['content'] == 'add a chart'
    assert snapshot['revisions'][0]['id'] == revision['id']


def test_edits_update_one_folder_and_keep_only_brief_logs(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create_project('Calculator', 'Keep the app')
    runner = OfficeRunner(store, max_rounds=1)
    seen = []
    spec = make_dummy_spec('calculator')

    def supervisor(instruction, previous, history, sandbox):
        emit('agent.started', role='orchestrator', task='supervisor_turn_task')
        seen.append((instruction, previous, history))
        emit('agent.completed', role='orchestrator', task='supervisor_turn_task', summary='assigned')
        return agents.SupervisorDecision(message='เริ่มแก้ให้ครับ', action='build', spec=spec,
                                         target_agents=['frontend'] if previous else ['frontend', 'backend'])

    def build(spec, sandbox, owner, extra=None):
        emit('agent.started', role=f'{owner}_specialist', task=f'{owner}_build_task')
        if owner == 'backend':
            path, text = 'backend/main.py', 'def calculate(x):\n    return x * 2\n'
        else:
            path = 'frontend/index.html'
            text = '<h1>Version two</h1>' if sandbox.validate_path(path).exists() else '<h1>Version one</h1>'
        agents.apply_bundle(agents.FileBundle(summary='done', files=[agents.ProposedFile(path=path, content=text)]), owner, sandbox)
        emit('agent.completed', role=f'{owner}_specialist', task=f'{owner}_build_task', summary='done')
        return 'done'

    def qa(spec, sandbox, round_number):
        result = sandbox.run_tests(test_code='from backend.main import calculate\ndef test_double():\n    assert calculate(5)==10\n')
        assert result['passed']
        return QAReport(passed=True, summary='real pytest', tests_executed=result['tests_executed'],
                        tests_passed=result['tests_passed'], raw_test_output=result['output'])

    monkeypatch.setattr(agents, 'run_supervisor_turn', supervisor)
    monkeypatch.setattr(agents, 'run_build_step', build)
    monkeypatch.setattr(agents, 'run_qa_step', qa)
    monkeypatch.setattr(agents, 'run_signoff_step', lambda *a: FinalSignOff(approved=True, summary='verified', acceptance_criteria_verified=spec.acceptance_criteria))
    store.enqueue(project['id'], 'make the first version')
    store.enqueue(project['id'], 'change the heading only')
    runner.process(store.claim_command())
    first = store.snapshot(project['id'])['revisions'][0]
    first_dir = store.revision_dir(first)
    runner.process(store.claim_command())
    snapshot = store.snapshot(project['id'])
    second = snapshot['revisions'][0]
    assert first['status'] == second['status'] == 'approved'
    assert second['parent_id'] == first['id']
    assert first_dir == store.project_dir(project['id'])
    second_dir = store.revision_dir(second)
    assert (second_dir / 'frontend/index.html').read_text() == '<h1>Version two</h1>'
    assert first_dir == second_dir
    assert (second_dir / 'backend/main.py').read_text() == 'def calculate(x):\n    return x * 2\n'
    assert not (store.root / 'projects').exists()
    assert not (second_dir / 'artifacts').exists()
    assert not list(second_dir.rglob('round_*'))
    assert not list(second_dir.rglob('__pycache__'))
    assert 'raw_test_output' not in second['qa']
    assert all('diff' not in change for change in second['changes'])
    assert [change['path'] for change in second['changes']] == ['frontend/index.html']
    assert seen[1][1].project_name == spec.project_name
    assert any('first version' in message['content'] for message in seen[1][2])
    assert len(snapshot['tasks']) == 5  # two supervisor jobs, two initial builders, one edit
    assert all(task['status'] == 'completed' for task in snapshot['tasks'])
    assert snapshot['project']['latest_revision_id'] == second['id']


def test_questions_do_not_replace_latest_website(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create_project('A', 'brief')
    monkeypatch.setattr(agents, 'run_supervisor_turn', lambda *a: agents.SupervisorDecision(message='ตอบคำถามครับ', action='reply'))
    runner = OfficeRunner(store)
    store.enqueue(project['id'], 'อธิบายก่อน')
    runner.process(store.claim_command())
    snapshot = store.snapshot(project['id'])
    assert snapshot['revisions'][0]['status'] == 'discussed'
    assert snapshot['project']['latest_revision_id'] is None
    assert snapshot['messages'][-1]['content'] == 'ตอบคำถามครับ'


def test_failed_revision_does_not_become_latest(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create_project('A', 'brief')
    def fail(*args):
        raise RuntimeError('Codex unavailable')
    monkeypatch.setattr(agents, 'run_supervisor_turn', fail)
    store.enqueue(project['id'], 'build')
    OfficeRunner(store).process(store.claim_command())
    snapshot = store.snapshot(project['id'])
    assert snapshot['revisions'][0]['status'] == 'failed'
    assert snapshot['project']['latest_revision_id'] is None
    assert snapshot['revisions'][0]['error'] == 'Codex unavailable'
    assert 'ประวัติคำสั่ง' in snapshot['messages'][-1]['content']


def test_cancelled_jobs_and_queued_commands_stop(tmp_path):
    store = Store(tmp_path)
    project = store.create_project('A', 'brief')
    runner = OfficeRunner(store)
    runner.submit(project['id'], 'one')
    runner.submit(project['id'], 'two')
    runner.active_project = project['id']
    runner.cancel_project(project['id'])
    assert store.claim_command() is None
    with bind_job(lambda *a: None, threading.Event()):
        check_cancelled()
    with pytest.raises(JobCancelled):
        with bind_job(lambda *a: None, runner.cancelled):
            check_cancelled()


def test_export_has_chat_commands_and_actual_event_history(office):
    app, client, headers = office
    project = new_project(client, headers)
    app.state.runner.submit(project['id'], 'make it green')
    response = client.get(f"/office-api/projects/{project['id']}/export")
    assert response.status_code == 200
    history = response.json()
    assert history['commands'][0]['instruction'] == 'make it green'
    assert history['messages'][-1]['content'] == 'make it green'
    assert history['events'][-1]['type'] == 'command.queued'
    assert 'attachment' in response.headers['content-disposition']


def test_preview_serves_frontend_at_root_and_backend_at_api(tmp_path):
    source = tmp_path / 'version'
    (source / 'frontend').mkdir(parents=True)
    (source / 'backend').mkdir()
    (source / 'frontend/index.html').write_text('<h1>Generated website</h1>')
    (source / 'backend/main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\n@app.get("/")\ndef root(): return {"wrong":"root"}\n@app.get("/api/ping")\ndef ping(): return {"message":"pong"}\n')
    with TestClient(create_preview(source)) as client:
        assert '<h1>Generated website</h1>' in client.get('/').text
        assert client.get('/api/ping').json() == {'message': 'pong'}


def test_retry_recovers_partial_source_without_publishing_failed_version(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create_project('A', 'brief')
    store.enqueue(project['id'], 'first attempt')
    command = store.claim_command()
    partial = store.new_revision(command)
    directory = store.revision_dir(partial)
    (directory / 'frontend').mkdir(parents=True)
    (directory / 'frontend/index.html').write_text('<h1>Keep this partial work</h1>')
    store.execute("UPDATE revisions SET status='failed' WHERE id=?", (partial['id'],))
    store.set_spec(project['id'], make_dummy_spec('x').model_dump_json())
    store.execute('UPDATE projects SET latest_revision_id=? WHERE id=?', (partial['id'], project['id']))
    store.execute("UPDATE commands SET status='failed' WHERE id=?", (command['id'],))
    def supervisor(instruction, previous, history, sandbox):
        assert previous.project_name == 'DiscountCalculatorApp'
        assert 'Keep this partial work' in sandbox.read_file('frontend/index.html')
        return agents.SupervisorDecision(action='reply', message='พบไฟล์เดิมแล้วครับ')
    monkeypatch.setattr(agents, 'run_supervisor_turn', supervisor)
    store.enqueue(project['id'], 'continue from partial work')
    OfficeRunner(store).process(store.claim_command())
    snapshot = store.snapshot(project['id'])
    assert snapshot['revisions'][0]['parent_id'] == partial['id']
    assert snapshot['project']['latest_revision_id'] == partial['id']


def test_usage_limit_pauses_future_work_without_losing_queue(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create_project('A', 'brief')
    runner = OfficeRunner(store)
    runner.submit(project['id'], 'first')
    runner.submit(project['id'], 'second')
    def unavailable(*args):
        raise agents.CodexUsageLimit('You have hit your usage limit')
    monkeypatch.setattr(agents, 'run_supervisor_turn', unavailable)
    runner.process(store.claim_command())
    assert store.setting('provider_issue') is not None
    commands = store.rows('SELECT * FROM commands ORDER BY created_at')
    assert [command['status'] for command in commands] == ['failed', 'queued']
    assert store.snapshot(project['id'])['messages'][-1]['role'] == 'system'
    runner.resume_provider()
    assert store.setting('provider_issue') is None
    assert store.claim_command()['instruction'] == 'second'


def test_provider_recheck_is_explicit_and_preserves_queued_commands(office, monkeypatch):
    app, client, headers = office
    project = new_project(client, headers)
    app.state.runner.submit(project['id'], 'continue later')
    app.state.store.set_setting('provider_issue', {'message':'provider usage limit','at':'test'})
    assert client.get('/office-api/codex').json()['ready'] is False
    assert client.post('/office-api/codex/recheck', json={}).status_code == 403
    monkeypatch.setattr('se_team.office.server.inspect_codex', lambda: {'ready':True,'message':'connected'})
    response = client.post('/office-api/codex/recheck', json={}, headers=headers)
    assert response.json()['ready']
    assert app.state.store.setting('provider_issue') is None
    assert app.state.store.snapshot(project['id'])['commands'][0]['status'] == 'queued'


def test_generated_preview_does_not_cache_old_version_assets(tmp_path):
    source = tmp_path / 'version'
    (source / 'frontend').mkdir(parents=True)
    (source / 'frontend/index.html').write_text('<h1>Fresh version</h1>')
    (source / 'frontend/app.js').write_text('const version=2;')
    with TestClient(create_preview(source)) as client:
        assert client.get('/').headers['cache-control'] == 'no-store'
        script = client.get('/app.js')
        assert script.headers['cache-control'] == 'no-store'
        assert 'version=2' in script.text


def test_history_never_presents_current_source_as_old_version(office):
    app, client, headers = office
    project = new_project(client, headers)
    store = app.state.store
    first = store.new_revision(store.enqueue(project['id'], 'first'))
    second = store.new_revision(store.enqueue(project['id'], 'second'))
    store.execute('UPDATE projects SET latest_revision_id=? WHERE id=?', (second['id'], project['id']))
    base = f"/office-api/projects/{project['id']}"
    assert client.get(base + f"/revisions/{first['id']}/files").status_code == 410
    assert client.get(base + f"/revisions/{second['id']}/file", params={'path':'frontend/index.html'}).status_code == 410
    assert client.post(base + '/preview', json={'revision_id':first['id']}, headers=headers).status_code == 410
    assert client.get(base).json()['storage_mode'] == 'single_folder'
    assert client.get(base).json()['history_has_source'] is False


def test_open_folder_uses_project_path_and_requires_token(office, monkeypatch):
    app, client, headers = office
    project = new_project(client, headers, 'เว็บของฉัน')
    calls = []
    monkeypatch.setattr('se_team.office.server.subprocess.Popen', lambda args, **kwargs: calls.append(args))
    url = f"/office-api/projects/{project['id']}/open-folder"
    assert client.post(url, json={}).status_code == 403
    response = client.post(url, json={}, headers=headers)
    assert response.status_code == 200
    assert calls[0][1] == str(app.state.store.project_dir(project['id']))


def test_readable_folders_are_unique_and_stay_inside_websites(tmp_path):
    store = Store(tmp_path / 'workspace/office')
    a = store.create_project('BurningUpp', '')
    b = store.create_project('BurningUpp', '')
    c = store.create_project('../../เว็บ ทดสอบ', '')
    assert store.project_dir(a['id']) == tmp_path / 'websites/BurningUpp'
    assert store.project_dir(b['id']) == tmp_path / 'websites/BurningUpp-2'
    assert store.project_dir(c['id']).parent == tmp_path / 'websites'
    store.execute('UPDATE projects SET folder_name=? WHERE id=?', ('../escape', c['id']))
    with pytest.raises(ValueError):
        store.project_dir(c['id'])


def test_migration_moves_only_latest_website_and_preserves_data_and_chat(tmp_path):
    from se_team.office.migrate import migrate_storage, manifest
    store = Store(tmp_path / 'workspace/office')
    project = store.create_project('BurningUpp', 'brief')
    revisions = []
    for n in (1, 2):
        row = store.new_revision(store.enqueue(project['id'], f'edit {n}'))
        source = store.legacy_revision_dir(row)
        for name, content in {'frontend/index.html':f'<h1>{n}</h1>', 'backend/main.py':'app=object()', 'tests/test_app.py':'def test_ok(): pass', 'artifacts/result.json':'FULL OLD SOURCE'}.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        store.execute("UPDATE revisions SET status='approved',spec_json=?,qa_json=?,changes_json=? WHERE id=?", (make_dummy_spec('x').model_dump_json(), json.dumps({'summary':'passed','tests_passed':2,'tests_executed':2,'raw_test_output':'LONG OUTPUT', 'bugs':[{'id':'B','title':'bug','description':'FULL CODE'}]}), json.dumps([{'path':'frontend/index.html','kind':'modified','added':1,'removed':1,'diff':'FULL OLD SOURCE'}]), row['id']))
        revisions.append(row)
    store.execute('UPDATE projects SET latest_revision_id=? WHERE id=?', (revisions[-1]['id'], project['id']))
    discussion = store.new_revision(store.enqueue(project['id'], 'question only'))
    store.execute("UPDATE revisions SET status='discussed' WHERE id=?", (discussion['id'],))
    old_project = store.root / 'projects' / project['id']
    data = old_project / 'data/users.sqlite3'
    data.parent.mkdir();data.write_bytes(b'actual user data')
    source_before = manifest(store.legacy_revision_dir(revisions[-1]) / 'frontend')
    chat_before = store.rows('SELECT * FROM messages')
    store.event(project['id'], 'plan.created', {'target_agents':['frontend'],'work_orders':{'full':'SOURCE'}})
    report = migrate_storage(store)
    current = store.project_dir(project['id'])
    assert manifest(current / 'frontend') == source_before
    assert (current / 'data/users.sqlite3').read_bytes() == b'actual user data'
    assert store.rows('SELECT * FROM messages')[:len(chat_before)] == chat_before
    assert store.rows('SELECT * FROM messages')[-1]['role'] == 'system'
    assert not old_project.exists()
    assert not (current / 'artifacts').exists()
    assert report['projects'][0]['verified_files'] == 4
    assert store.project(project['id'])['spec_json'] is not None
    assert all(r['spec_json'] is None for r in store.rows('SELECT * FROM revisions'))
    logs = json.dumps(store.rows('SELECT * FROM revisions') + store.rows('SELECT * FROM events'))
    assert all(value not in logs for value in ('FULL OLD SOURCE','LONG OUTPUT','FULL CODE','work_orders'))
    migrate_storage(store)
    assert (current / 'frontend/index.html').read_text() == '<h1>2</h1>'


def test_migration_refuses_conflicting_source_and_keeps_old_copies(tmp_path):
    from se_team.office.migrate import migrate_storage
    store = Store(tmp_path)
    project = store.create_project('A', '')
    row = store.new_revision(store.enqueue(project['id'], 'edit'))
    legacy = store.legacy_revision_dir(row) / 'frontend/index.html'
    legacy.parent.mkdir(parents=True);legacy.write_text('source')
    current = store.project_dir(project['id']) / 'frontend/index.html'
    current.parent.mkdir();current.write_text('different')
    with pytest.raises(ValueError, match='overwrite'):
        migrate_storage(store)
    assert legacy.read_text() == 'source'
    assert current.read_text() == 'different'
    assert not (current.parent.parent / '.office-layout.json').exists()
