"""Meaningful regression checks for scoped work, exact edits and bounded orchestration."""
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from se_team.crew import antigravity_runtime as agy, codex_runtime as codex
from se_team.crew.job_events import bind_job
from se_team.crew.performance import (FileBundle, ProposedFile, ProposedEdit, EditDecision, WorkOrder,
    source_context, source_scope, apply_bundle, digest, obtain_bundle)
from se_team.crew.steps import supervisor, qa
from se_team.models import QAReport
from se_team.tools.sandbox import SandboxManager
from tests.test_flow_smoke import make_dummy_spec


def test_role_context_excludes_unrelated_source_and_credentials(tmp_path):
    box=SandboxManager(tmp_path)
    box.write_file('frontend/app.js','const ui=1;')
    box.write_file('backend/main.py','SECRET_BACKEND')
    box.write_file('tests/test_app.py','TEST_BODY')
    box.write_file('.env','PRIVATE_CREDENTIAL')
    builder=json.loads(source_context(box,'frontend_specialist','frontend_build_task'))
    assert [f['path'] for f in builder['files']]==['frontend/app.js']
    assert 'SECRET_BACKEND' not in json.dumps(builder)
    assert 'PRIVATE_CREDENTIAL' not in json.dumps(builder)
    assert builder['files'][0]['hash']==digest('const ui=1;')
    planner=json.loads(source_context(box,'orchestrator','supervisor_edit_task'))
    assert planner['files']==[] and len(planner['inventory'])==3
    with source_scope(['backend/main.py']):
        selected=json.loads(source_context(box,'qa_verifier','qa_verification_task'))
    assert [f['path'] for f in selected['files']]==['backend/main.py']


@pytest.mark.parametrize('runtime',[agy,codex])
def test_exact_edits_preserve_unrelated_bytes_and_validate_before_writing(tmp_path,runtime):
    box=SandboxManager(tmp_path)
    box.write_file('frontend/app.js','const x=1;\nconst y=2;\n')
    before=box.read_file('frontend/app.js')
    bundle=runtime.FileBundle(summary='small',edits=[ProposedEdit(path='frontend/app.js',search='x=1',replace='x=3',base_hash=digest(before))])
    runtime.apply_bundle(bundle,'frontend',box)
    assert box.read_file('frontend/app.js')=='const x=3;\nconst y=2;\n'
    bad=FileBundle(summary='stale',files=[ProposedFile(path='frontend/new.js',content='new')],
        edits=[ProposedEdit(path='frontend/app.js',search='x=3',replace='x=9',base_hash=digest(before))])
    with pytest.raises(ValueError,match='Stale edit'):
        runtime.apply_bundle(bad,'frontend',box)
    assert not (tmp_path/'frontend/new.js').exists()
    assert box.read_file('frontend/app.js')=='const x=3;\nconst y=2;\n'


def test_ambiguous_edits_and_invalid_python_do_not_change_any_files(tmp_path):
    box=SandboxManager(tmp_path)
    box.write_file('backend/main.py','x=1\ny=1\n')
    with pytest.raises(ValueError,match='exactly once'):
        apply_bundle(FileBundle(summary='bad',edits=[ProposedEdit(path='backend/main.py',search='=1',replace='=2')]),'backend',box)
    with pytest.raises(SyntaxError):
        apply_bundle(FileBundle(summary='bad',files=[ProposedFile(path='backend/new.py',content='def x(:')]),'backend',box)
    assert not (tmp_path/'backend/new.py').exists()
    assert box.read_file('backend/main.py')=='x=1\ny=1\n'


def test_internal_symlink_cannot_bypass_role_ownership(tmp_path):
    box=SandboxManager(tmp_path)
    box.write_file('backend/main.py','x=1')
    (tmp_path/'frontend').mkdir()
    (tmp_path/'frontend/link.py').symlink_to(tmp_path/'backend/main.py')
    with pytest.raises(ValueError,match='symbolic link'):
        apply_bundle(FileBundle(summary='bad',files=[ProposedFile(path='frontend/link.py',content='x=2')]),'frontend',box)
    assert box.read_file('backend/main.py')=='x=1'


def test_edit_planner_returns_small_work_order_and_preserves_exact_contract(tmp_path):
    box=SandboxManager(tmp_path)
    spec=make_dummy_spec('x')
    calls=[]
    def job(role,task,values,output,sandbox):
        calls.append((task,values))
        return EditDecision(message='แก้สีครับ',action='build',verification='regression',work_orders=[
            WorkOrder(owner='frontend',instructions='Change the button color only',files=['frontend/styles.css'])])
    decision=supervisor(job,None,codex.SupervisorDecision,'แก้สี',spec,[{'role':'assistant','content':'verbose '*20000}],box)
    assert len(calls)==1 and calls[0][0]=='supervisor_edit_task'
    assert len(calls[0][1]['conversation'])<1500
    assert decision.spec.api_contract==spec.api_contract
    assert decision.spec.data_schemas==spec.data_schemas
    assert decision.spec.frontend_prompt.instructions=='Change the button color only'
    assert decision.target_agents==['frontend']
    assert spec.frontend_prompt.instructions!=decision.spec.frontend_prompt.instructions


def test_source_retrieval_is_bounded_and_does_not_apply_partial_response(tmp_path):
    box=SandboxManager(tmp_path)
    box.write_file('frontend/app.js','const x=1')
    calls=[]
    def job(role,task,values,output,sandbox):
        calls.append(json.loads(source_context(sandbox,role,task)))
        if len(calls)==1:return FileBundle(summary='need source',need_files=['frontend/app.js'])
        return FileBundle(summary='patch',edits=[ProposedEdit(path='frontend/app.js',search='x=1',replace='x=2')])
    bundle=obtain_bundle(job,'frontend_specialist','frontend_build_task',{},box,[])
    assert calls[0]['files']==[]
    assert calls[1]['files'][0]['path']=='frontend/app.js'
    assert box.read_file('frontend/app.js')=='const x=1'
    apply_bundle(bundle,'frontend',box)
    assert box.read_file('frontend/app.js')=='const x=2'
    with pytest.raises(ValueError,match='limit'):
        obtain_bundle(lambda *args:FileBundle(summary='more',need_files=['frontend/app.js']),
                      'frontend_specialist','frontend_build_task',{},box,[])


def test_regression_reuses_tests_but_real_counts_override_model_claim(tmp_path):
    box=SandboxManager(tmp_path,retain_artifacts=False);box.verification='regression'
    box.write_file('tests/test_existing.py','def test_x():\n    assert False\n')
    calls=[]
    def job(role,task,values,output,sandbox):
        calls.append(task)
        assert 'stdout' not in values['test_result_json']
        return QAReport(passed=True,summary='claim',tests_executed=999,tests_passed=999)
    report=qa(job,make_dummy_spec('x'),box,1)
    assert calls==['qa_report_task']
    assert report.tests_executed==1 and report.tests_failed==1 and not report.passed


def test_stream_deduplicates_deltas_and_finishes_on_terminal_result(monkeypatch,tmp_path):
    active=json.dumps({'event':'step_update','step_update':{'step_index':1,'state':'ACTIVE','step_type':'agent_response'}})+'\n'
    done=json.dumps({'event':'result','result':{'status':'SUCCESS','structured_output':{'ok':True}}})+'\n'
    class Process:
        pid=999999
        stdin=SimpleNamespace(write=lambda s:None,close=lambda:None)
        stdout=[active]*2000+[done]
        stderr=[]
        def wait(self,timeout=None):return 0
        def poll(self):return 0
    monkeypatch.setattr(agy.subprocess,'Popen',lambda *a,**k:Process())
    events=[]
    with bind_job(lambda kind,data:events.append((kind,data)),threading.Event()):
        result=agy._stream_process(['agy'],'input',10,str(tmp_path))
    assert result['result']['structured_output']=={'ok':True}
    assert len([e for e in events if e[0]=='agent.progress'])==1


def test_manager_records_metrics_and_avoids_redundant_signoff_for_manual_gaps(tmp_path,monkeypatch):
    from se_team.office.store import Store
    from se_team.office.manager import OfficeRunner
    from se_team.crew.job_events import emit
    store=Store(tmp_path)
    p=store.create_project('A','brief')
    def head(*args):
        emit('agent.started',role='orchestrator',task='supervisor_edit_task')
        emit('job.configured',task='supervisor_edit_task',prompt_chars=1200,model='test')
        emit('job.measured',task='supervisor_edit_task',duration_seconds=2.5)
        emit('agent.completed',role='orchestrator',task='supervisor_edit_task',summary='planned')
        return codex.SupervisorDecision(action='build',message='plan',spec=make_dummy_spec('x'),target_agents=['frontend'])
    monkeypatch.setattr(codex,'run_supervisor_turn',head)
    monkeypatch.setattr(codex,'run_build_step',lambda *a:None)
    monkeypatch.setattr(codex,'run_qa_step',lambda *a:QAReport(passed=False,summary='Manual browser check pending',tests_executed=2,tests_passed=2))
    monkeypatch.setattr(codex,'run_signoff_step',lambda *a:pytest.fail('A second model cannot manufacture missing browser evidence'))
    monkeypatch.delenv('AGENT_BACKEND',raising=False)
    store.enqueue(p['id'],'color')
    OfficeRunner(store).process(store.claim_command())
    state=store.snapshot(p['id'])
    assert state['revisions'][0]['status']=='needs_attention'
    assert state['tasks'][0]['metrics']['prompt_chars']==1200
    assert state['tasks'][0]['metrics']['duration_seconds']==2.5


@pytest.mark.parametrize('task,expected_effort',[('supervisor_edit_task','low'),('backend_build_task','medium')])
def test_default_flash_slug_matches_effort(monkeypatch,tmp_path,task,expected_effort):
    from pydantic import BaseModel
    class Reply(BaseModel):ok:bool
    def fake(command,**kwargs):
        model=command[command.index('--model')+1]
        assert model.endswith('-'+expected_effort)
        assert command[command.index('--effort')+1]==expected_effort
        settings=json.loads(command[command.index('--settings')+1])
        assert 'command(*)' in settings['permissions']['deny']
        assert '--dangerously-skip-permissions' not in command
        return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'SUCCESS','structured_output':{'ok':True}}),stderr='')
    for key in ('AGY_MODEL','AGY_EFFORT','ORCHESTRATOR_AGY_MODEL','BACKEND_AGY_MODEL','ORCHESTRATOR_AGY_EFFORT','BACKEND_AGY_EFFORT'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setattr(agy,'antigravity_binary',lambda:'/fake/agy')
    monkeypatch.setattr(agy.subprocess,'run',fake)
    role='orchestrator' if task=='supervisor_edit_task' else 'backend_specialist'
    values={'instruction':'x','conversation':'[]','current_spec':'{}'} if task=='supervisor_edit_task' else {'backend_instructions':'x','api_contract_summary':'[]','data_schema_summary':'[]'}
    assert agy.run_job(role,task,values,Reply,SandboxManager(tmp_path)).ok


def test_old_duplicate_progress_is_compacted_without_removing_chat_or_test_evidence(tmp_path):
    from se_team.office.store import Store
    store=Store(tmp_path);p=store.create_project('A','brief')
    r=store.new_revision(store.enqueue(p['id'],'edit'))
    for _ in range(10):store.event(p['id'],'agent.progress',{'phase':'turn.started'},r['id'],'frontend_specialist')
    store.event(p['id'],'tests.completed',{'passed':True,'tests_executed':2},r['id'])
    store.compact_progress()
    assert len([e for e in store.events(p['id']) if e['type']=='agent.progress'])==10
    store.execute("UPDATE revisions SET status='failed' WHERE id=?",(r['id'],))
    messages=store.rows('SELECT * FROM messages')
    store.compact_progress()
    assert store.rows('SELECT * FROM messages')==messages
    assert len([e for e in store.events(p['id']) if e['type']=='agent.progress'])==1
    assert any(e['type']=='tests.completed' for e in store.events(p['id']))


def test_noncosmetic_write_escalates_qa_even_when_planner_requested_regression(tmp_path,monkeypatch):
    from se_team.office.store import Store
    from se_team.office.manager import OfficeRunner
    store=Store(tmp_path);p=store.create_project('A','brief')
    def head(instruction,previous,history,box):
        box.verification='regression'
        return codex.SupervisorDecision(action='build',message='plan',spec=make_dummy_spec('x'),target_agents=['frontend'])
    def build(spec,box,owner,extra=None):box.write_file('frontend/app.js','const changedBehavior=1;')
    def verify(spec,box,n):
        assert box.verification=='full'
        return QAReport(passed=False,summary='manual check needed',tests_executed=1,tests_passed=1)
    monkeypatch.setattr(codex,'run_supervisor_turn',head)
    monkeypatch.setattr(codex,'run_build_step',build)
    monkeypatch.setattr(codex,'run_qa_step',verify)
    monkeypatch.delenv('AGENT_BACKEND',raising=False)
    store.enqueue(p['id'],'change behavior')
    OfficeRunner(store).process(store.claim_command())
    assert store.snapshot(p['id'])['revisions'][0]['status']=='needs_attention'


def test_stream_returns_terminal_result_without_waiting_for_lingering_cli(tmp_path):
    import sys,time
    script=tmp_path/'terminal_result.py'
    script.write_text('import json,time\nprint(json.dumps({"event":"result","result":{"status":"SUCCESS","structured_output":{"ok":True}}}),flush=True)\ntime.sleep(30)\n')
    started=time.monotonic()
    result=agy._stream_process([sys.executable,str(script)],'input',10,str(tmp_path))
    assert result['result']['structured_output']=={'ok':True}
    assert time.monotonic()-started<5


def test_first_build_keeps_complete_project_brief(tmp_path):
    box=SandboxManager(tmp_path);brief='requirement '*2500+'FINAL_REQUIRED_FEATURE'
    def job(role,task,values,output,sandbox):
        assert 'FINAL_REQUIRED_FEATURE' in values['conversation']
        return codex.SupervisorDecision(action='reply',message='understood')
    config=lambda _: {'orchestrator_spec_task':{'description':'{project_brief}'}}
    supervisor(job,config,codex.SupervisorDecision,'start',None,[{'role':'project_context','content':brief}],box)
