"""Verify provider routing, scoped handoffs and independently measured QA facts."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from se_team.crew import codex_runtime as runtime
from se_team.crew import crew
from se_team.models import FinalSignOff, QAReport, RePromptPackage
from se_team.tools.sandbox import SandboxManager
from tests.test_flow_smoke import make_dummy_spec


@pytest.fixture
def sandbox(tmp_path):
    return SandboxManager(tmp_path)


def test_codex_ignores_old_swu_key(monkeypatch, sandbox):
    monkeypatch.setenv('AGENT_BACKEND', 'codex')
    monkeypatch.setenv('SWU_API_KEY', 'stale-swu-value')
    expected = make_dummy_spec('calculator')
    monkeypatch.setattr(runtime, 'run_spec_step', lambda brief, box: expected)
    monkeypatch.setattr(crew, 'create_orchestrator_agent', lambda *a: pytest.fail('legacy provider invoked'))
    assert crew.run_spec_step('calculator', sandbox) is expected


def test_codex_subprocess_contract(monkeypatch, sandbox):
    class Reply(BaseModel):
        ok: bool

    def fake_run(command, **kwargs):
        assert command[1] == 'exec'
        assert '--ignore-user-config' in command
        assert command[command.index('--sandbox') + 1] == 'read-only'
        assert kwargs['input'] and kwargs['timeout'] > 0
        result_file = Path(command[command.index('--output-last-message') + 1])
        result_file.write_text(json.dumps({'result_json': '{"ok":true}'}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime, 'codex_binary', lambda: '/fake/codex')
    monkeypatch.setattr(runtime.subprocess, 'run', fake_run)
    assert runtime.run_job('orchestrator', 'orchestrator_spec_task', {'project_brief': 'x'}, Reply, sandbox).ok
    assert json.loads(sandbox.read_file('artifacts/orchestrator_spec_task.json')) == {'ok': True}


@pytest.mark.parametrize('failure', ['exit', 'missing', 'invalid', 'timeout'])
def test_codex_failed_or_invalid_result_is_not_accepted(monkeypatch, sandbox, failure):
    class Reply(BaseModel):
        ok: bool

    def fake_run(command, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 1)
        if failure == 'invalid':
            Path(command[command.index('--output-last-message') + 1]).write_text('{"result_json":"{}"}')
        return SimpleNamespace(returncode=1 if failure == 'exit' else 0, stderr='failure')

    monkeypatch.setattr(runtime, 'codex_binary', lambda: '/fake/codex')
    monkeypatch.setattr(runtime.subprocess, 'run', fake_run)
    with pytest.raises((RuntimeError, ValidationError)):
        runtime.run_job('orchestrator', 'orchestrator_spec_task', {'project_brief': 'x'}, Reply, sandbox)


def test_bundle_validates_all_ownership_before_writing(sandbox):
    bundle = runtime.FileBundle(summary='bad', files=[
        runtime.ProposedFile(path='frontend/index.html', content='allowed'),
        runtime.ProposedFile(path='backend/main.py', content='wrong owner'),
    ])
    with pytest.raises(ValueError, match='cannot write'):
        runtime.apply_bundle(bundle, 'frontend', sandbox)
    assert not sandbox.validate_path('frontend/index.html').exists()
    for path in ('../outside.py', 'tests/../backend/main.py'):
        with pytest.raises(ValueError):
            runtime.apply_bundle(runtime.FileBundle(summary='bad', files=[runtime.ProposedFile(path=path, content='x')]), 'tests', sandbox)


def test_qa_cannot_claim_success_when_real_tests_fail(monkeypatch, sandbox):
    spec = make_dummy_spec('calculator')
    bundle = runtime.FileBundle(summary='one test', files=[runtime.ProposedFile(
        path='tests/test_regression.py', content='def test_failure():\n    assert 1 == 2\n',
    )])
    def fake_job(role, task, values, output, box):
        if task == 'qa_verification_task':
            return bundle
        return QAReport(passed=True, summary='claimed pass', tests_executed=999, tests_passed=999)
    monkeypatch.setattr(runtime, 'run_job', fake_job)
    report = runtime.run_qa_step(spec, sandbox)
    assert not report.passed
    assert report.tests_executed == 1 and report.tests_failed == 1 and report.tests_passed == 0
    assert 'assert 1 == 2' in report.raw_test_output
    assert report.bugs and report.owning_agents_needing_fixes


def test_qa_rejects_skipped_only_tests(monkeypatch, sandbox):
    spec = make_dummy_spec('calculator')
    def fake_job(role, task, values, output, box):
        if task == 'qa_verification_task':
            return runtime.FileBundle(summary='skipped', files=[runtime.ProposedFile(
                path='tests/test_skipped.py', content="import pytest\n@pytest.mark.skip(reason='unimplemented')\ndef test_x(): pass\n",
            )])
        return QAReport(passed=True, summary='claimed pass')
    monkeypatch.setattr(runtime, 'run_job', fake_job)
    report = runtime.run_qa_step(spec, sandbox)
    assert not report.passed and report.tests_executed == 0


def test_signoff_requires_executed_evidence(sandbox):
    with pytest.raises(ValueError, match='successful executed tests'):
        runtime.run_signoff_step(make_dummy_spec('x'), QAReport(passed=True, summary='no evidence'), sandbox)


def test_signoff_rejects_omitted_acceptance_criteria(monkeypatch, sandbox):
    monkeypatch.setattr(runtime, 'run_job', lambda *a: FinalSignOff(approved=True, summary='claimed complete'))
    decision = runtime.run_signoff_step(
        make_dummy_spec('x'), QAReport(passed=True, summary='one test passed', tests_executed=1), sandbox,
    )
    assert not decision.approved
    assert 'Unverified acceptance criteria' in decision.summary


def test_reprompt_cannot_target_unrelated_owner(monkeypatch, sandbox):
    monkeypatch.setattr(runtime, 'run_job', lambda *args: RePromptPackage(
        round_number=1, target_agents=['frontend'], frontend_fixes='change UI', reasons='wrong target',
    ))
    with pytest.raises(ValueError, match='exactly'):
        runtime.run_reprompt_step(QAReport(passed=False, summary='backend failure', owning_agents_needing_fixes=['backend']),
                                  make_dummy_spec('x'), sandbox, 1)


def test_supervisor_plan_rejects_duplicate_or_missing_owners():
    data = make_dummy_spec('x').model_dump()
    for batches in ([['frontend']], [['backend'], ['backend']], [[], ['frontend', 'backend']]):
        with pytest.raises(ValidationError):
            type(make_dummy_spec('x')).model_validate({**data, 'build_batches': batches})


def test_supervisor_order_is_obeyed(monkeypatch, tmp_path):
    from se_team.flow import SoftwareTeamFlow
    calls = []
    spec = make_dummy_spec('x')
    spec.build_batches = [['backend'], ['frontend']]
    monkeypatch.setattr('se_team.flow.run_spec_step', lambda *a: spec)
    monkeypatch.setattr('se_team.flow.run_backend_step', lambda *a: calls.append('backend'))
    monkeypatch.setattr('se_team.flow.run_frontend_step', lambda *a: calls.append('frontend'))
    monkeypatch.setattr('se_team.flow.run_qa_step', lambda *a, **kw: QAReport(passed=True, summary='ok', tests_executed=1))
    monkeypatch.setattr('se_team.flow.run_signoff_step', lambda *a: FinalSignOff(approved=True, summary='ok'))
    flow = SoftwareTeamFlow('x', workspace_root=str(tmp_path))
    flow.kickoff()
    assert calls == ['backend', 'frontend']
    assert flow.state.status == 'SUCCESS'


def test_supervisor_rejection_is_not_success(monkeypatch, tmp_path):
    from se_team.flow import SoftwareTeamFlow
    flow = SoftwareTeamFlow('x', workspace_root=str(tmp_path))
    flow.state.spec_package = make_dummy_spec('x')
    flow.state.qa_report = QAReport(passed=True, summary='tests passed', tests_executed=1)
    monkeypatch.setattr('se_team.flow.run_signoff_step', lambda *a: FinalSignOff(approved=False, summary='UI evidence missing'))
    assert flow.handle_sign_off_action() == 'SIGNOFF_REJECTED'
    assert flow.state.status == 'SIGNOFF_REJECTED'


def test_fix_worker_failure_surfaces(monkeypatch, tmp_path):
    from se_team.flow import SoftwareTeamFlow
    flow = SoftwareTeamFlow('x', max_rounds=2, workspace_root=str(tmp_path))
    flow.state.spec_package = make_dummy_spec('x')
    flow.state.qa_report = QAReport(passed=False, summary='broken', owning_agents_needing_fixes=['backend'])
    monkeypatch.setattr('se_team.flow.run_reprompt_step', lambda *a, **kw: RePromptPackage(
        round_number=1, target_agents=['backend'], backend_fixes='fix', reasons='bug',
    ))
    def fail(*args):
        raise RuntimeError('worker failed')
    monkeypatch.setattr('se_team.flow.run_backend_step', fail)
    with pytest.raises(RuntimeError, match='worker failed'):
        flow.handle_reprompt_loop()


def test_file_code_uses_direct_structured_output_without_double_json(monkeypatch, sandbox):
    source = 'import re\npattern = r"\\s+\\d"\n'
    def fake_run(command, **kwargs):
        schema = json.loads(Path(command[command.index('--output-schema') + 1]).read_text())
        assert 'result_json' not in schema['properties']
        assert schema['additionalProperties'] is False
        result = runtime.FileBundle(summary='code', files=[runtime.ProposedFile(path='backend/main.py', content=source)])
        Path(command[command.index('--output-last-message') + 1]).write_text(result.model_dump_json())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runtime, 'codex_binary', lambda: '/fake/codex')
    monkeypatch.setattr(runtime.subprocess, 'run', fake_run)
    result = runtime.run_job('backend_specialist', 'backend_build_task', {
        'backend_instructions':'build', 'api_contract_summary':'[]', 'data_schema_summary':'[]',
    }, runtime.FileBundle, sandbox)
    assert result.files[0].content == source


def test_public_stream_events_do_not_include_private_reasoning(tmp_path):
    import os
    import sys
    import threading
    from se_team.crew.job_events import bind_job
    if os.name != 'posix':
        pytest.skip('executable fixture uses a POSIX shebang')
    script = tmp_path / 'fake-codex'
    script.write_text(f'#!{sys.executable}\nimport sys,json\nsys.stdin.read()\n'
                      'print(json.dumps({"type":"turn.started"}),flush=True)\n'
                      'print(json.dumps({"type":"item.completed","item":{"type":"reasoning","text":"PRIVATE CONTENT"}}),flush=True)\n'
                      'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":5}}),flush=True)\n')
    script.chmod(0o700)
    events = []
    with bind_job(lambda kind, data: events.append((kind,data)), threading.Event()):
        result = runtime._stream_process([str(script), '-'], 'hello', 5)
    assert result.returncode == 0
    assert [item[1]['phase'] for item in events] == ['turn.started','turn.completed']
    assert 'PRIVATE CONTENT' not in json.dumps(events)


def test_running_codex_process_honors_stop_request(tmp_path):
    import os
    import sys
    import threading
    import time
    from se_team.crew.job_events import JobCancelled, bind_job
    if os.name != 'posix':
        pytest.skip('executable fixture uses a POSIX shebang')
    script = tmp_path / 'fake-codex'
    script.write_text(f'#!{sys.executable}\nimport sys,json,time\nsys.stdin.read()\n'
                      'print(json.dumps({"type":"turn.started"}),flush=True)\n'
                      'time.sleep(30)\n')
    script.chmod(0o700)
    stopped = threading.Event()
    def events(kind,data):
        stopped.set()
    started = time.monotonic()
    with pytest.raises(JobCancelled):
        with bind_job(events, stopped):
            runtime._stream_process([str(script), '-'], 'hello', 5)
    assert time.monotonic() - started < 5


def test_missing_manual_evidence_does_not_invent_builder_defects(monkeypatch, sandbox):
    def fake_job(role, task, values, output, box):
        if task == 'qa_verification_task':
            return runtime.FileBundle(summary='one test', files=[runtime.ProposedFile(
                path='tests/test_ok.py', content='def test_ok():\n    assert True\n',
            )])
        return QAReport(passed=False, summary='Browser review still required', bugs=[])
    monkeypatch.setattr(runtime, 'run_job', fake_job)
    report = runtime.run_qa_step(make_dummy_spec('x'), sandbox)
    assert report.tests_executed == report.tests_passed == 1
    assert not report.passed and report.bugs == [] and report.owning_agents_needing_fixes == []


def test_supervisor_cannot_approve_missing_manual_evidence(monkeypatch, sandbox):
    spec = make_dummy_spec('x')
    monkeypatch.setattr(runtime, 'run_job', lambda *a: FinalSignOff(
        approved=True, summary='claim', acceptance_criteria_verified=spec.acceptance_criteria,
    ))
    decision = runtime.run_signoff_step(spec, QAReport(passed=False, summary='manual review missing', tests_executed=1, tests_passed=1), sandbox)
    assert not decision.approved


def test_provider_usage_limit_is_distinct_from_other_job_failures(monkeypatch, sandbox):
    class Reply(BaseModel):
        ok: bool
    monkeypatch.setattr(runtime, 'codex_binary', lambda: '/fake/codex')
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=1, stderr="You've hit your usage limit. Try again later.",
    ))
    with pytest.raises(runtime.CodexUsageLimit):
        runtime.run_job('orchestrator', 'orchestrator_spec_task', {'project_brief':'x'}, Reply, sandbox)


def test_office_handoffs_stay_in_memory_without_full_result_copies(tmp_path, monkeypatch):
    box = SandboxManager(tmp_path, retain_artifacts=False)
    def fake_run(command, **kwargs):
        assert 'single current website folder' in kwargs['input']
        assert 'historical website source and rollback are unavailable' in kwargs['input']
        result = Path(command[command.index('--output-last-message') + 1])
        result.write_text(json.dumps({'summary':'frontend complete', 'files':[{'path':'frontend/index.html','content':'<h1>Current website</h1>'}], 'deleted_files':[]}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runtime, 'codex_binary', lambda: '/fake/codex')
    monkeypatch.setattr(runtime.subprocess, 'run', fake_run)
    bundle = runtime.run_job('frontend_specialist', 'frontend_build_task', {'frontend_instructions':'build', 'api_contract_summary':'[]'}, runtime.FileBundle, box)
    runtime.apply_bundle(bundle, 'frontend', box)
    assert box.read_file('frontend/index.html') == '<h1>Current website</h1>'
    assert not (tmp_path / 'artifacts').exists()
    assert json.loads(runtime.handoff_context(box))['frontend_build_task'] == 'frontend complete'
