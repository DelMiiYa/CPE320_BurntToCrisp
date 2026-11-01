"""Provider-independent planning, targeted work orders and evidence-based QA."""
from pathlib import Path

from se_team.crew.job_events import check_cancelled, emit
from se_team.crew.performance import (
    EditDecision, apply_bundle, compact_history, compact_spec, dumps,
    obtain_bundle, resolve_edit_plan, source_map, source_scope,
)
from se_team.models import BugReport, FinalSignOff, QAReport, RePromptPackage


def supervisor(job, config, decision_type, instruction, previous, history, sandbox):
    if previous:
        edit = job('orchestrator', 'supervisor_edit_task', {
            'instruction': instruction, 'conversation': compact_history(history, instruction),
            'current_spec': dumps(compact_spec(previous)),
        }, EditDecision, sandbox)
        if not edit.contract_changes_required or edit.action == 'reply':
            decision = resolve_edit_plan(previous, edit)
            sandbox.edit_plan = edit
            sandbox.verification = decision.verification
            return decision
        emit('plan.expanded', reason='API or data contract changes require full planning')
    decision = job('orchestrator', 'supervisor_turn_task', {
        'instruction': instruction, 'previous_spec': previous.model_dump_json() if previous else 'null',
        'conversation': (dumps(history) if previous is None else compact_history(history, instruction)),
        'platform_guidance': config('tasks.yaml')['orchestrator_spec_task']['description'].format(project_brief=instruction),
    }, decision_type, sandbox)
    if decision.action == 'build':
        if not decision.spec or not decision.target_agents or not set(decision.target_agents) <= {'frontend','backend','qa'}:
            raise ValueError('Supervisor must supply a specification and valid specialist work orders')
        if len(set(decision.target_agents)) != len(decision.target_agents):
            raise ValueError('Supervisor assigned a specialist twice')
        if previous is None and not {'frontend','backend'} <= set(decision.target_agents):
            raise ValueError('The first build must assign both frontend and backend')
    sandbox.verification = 'full'
    return decision


def build(job, spec, sandbox, owner, extra=None):
    order = getattr(spec, f'{owner}_prompt')
    values = {f'{owner}_instructions': order.instructions + (f'\nCorrection: {extra}' if extra else '')
                  + '\nShared acceptance criteria (preserve unrelated behavior):\n' + dumps(spec.acceptance_criteria),
              'api_contract_summary': dumps([e.model_dump(exclude_none=True) for e in spec.api_contract]),
              'data_schema_summary': dumps([d.model_dump() for d in spec.data_schemas]) if owner=='backend' else '[]',
              'shared_requirements': dumps({'scope':spec.task_scope[:1600], 'acceptance':spec.acceptance_criteria})}
    paths = order.files_to_produce or [p for p in source_map(sandbox) if p.startswith(owner+'/')]
    bundle = obtain_bundle(job, f'{owner}_specialist', f'{owner}_build_task', values, sandbox, paths)
    try:
        apply_bundle(bundle, owner, sandbox)
    except Exception as exc:
        emit('agent.failed', role=f'{owner}_specialist', task=f'{owner}_build_task', error=str(exc))
        raise
    emit('agent.completed', role=f'{owner}_specialist', task=f'{owner}_build_task', summary=bundle.summary)
    return bundle.summary


def qa(job, spec, sandbox, round_number):
    regression = getattr(sandbox, 'verification', 'full') == 'regression'
    has_tests = any(p.startswith('tests/') and p.endswith('.py') for p in source_map(sandbox))
    if not has_tests or (not regression and round_number == 1):
        values = {'qa_guidance': spec.qa_guidance[:5000]+'\nAcceptance criteria:\n'+dumps(spec.acceptance_criteria),
                  'api_contract_summary': dumps([e.model_dump(exclude_none=True) for e in spec.api_contract])}
        bundle = obtain_bundle(job, 'qa_verifier', 'qa_verification_task', values, sandbox, None)
        try:
            apply_bundle(bundle, 'tests', sandbox)
        except Exception as exc:
            emit('agent.failed', role='qa_verifier', task='qa_verification_task', error=str(exc))
            raise
        emit('agent.completed', role='qa_verifier', task='qa_verification_task', summary=bundle.summary)
    else:
        emit('qa.reused', message='รันทดสอบเดิมก่อน ตรวจเฉพาะส่วนที่แก้ ไม่สร้างชุดทดสอบใหม่ทั้งเว็บ')
    check_cancelled()
    emit('tests.started', round_number=round_number)
    result = sandbox.run_tests(test_path='tests', timeout=60)
    check_cancelled()
    emit('tests.completed', **result)
    # Do not send stdout three times (stdout+stderr+output) or all source to an evidence review.
    evidence = {k:result[k] for k in ('tests_executed','tests_passed','tests_failed','exit_code','passed')}
    evidence['command'] = result.get('command', [])
    evidence['output'] = result.get('output','')[-10000:]
    report = job('qa_verifier', 'qa_report_task', {
        'spec_json': dumps(compact_spec(spec)), 'test_result_json': dumps(evidence), 'round_number':round_number,
    }, QAReport, sandbox)
    report.round_number=round_number
    for key in ('tests_executed','tests_passed','tests_failed'):
        setattr(report, key, result[key])
    report.raw_test_output=result['output']
    report.passed=bool(result['passed'] and report.tests_executed>0 and report.passed and not report.bugs)
    if not report.passed and not report.bugs and not (result['passed'] and report.tests_executed>0):
        report.bugs=[BugReport(id='QA-EXECUTION',title='QA did not establish acceptance',
            description=result['output'][-6000:] or report.summary,severity='high',owning_agent='both',
            edge_case_category='contract mismatch',suggested_fix='Resolve the reproduced test failure.')]
    owners=set()
    for bug in report.bugs:
        owners.update(('frontend','backend') if bug.owning_agent=='both' else (bug.owning_agent,))
    report.owning_agents_needing_fixes=sorted(owners)
    sandbox.write_artifact('qa_report.json',report.model_dump_json(indent=2))
    return report


def report_summary(report):
    return report.model_dump(exclude={'raw_test_output'})


def reprompt(job, qa_report, spec, sandbox, round_number):
    package=job('orchestrator','orchestrator_reprompt_task',{
        'round_number':round_number,'qa_report_summary':dumps(report_summary(qa_report)),
        'bugs_list':dumps([b.model_dump() for b in qa_report.bugs]),
        'owning_agents':', '.join(qa_report.owning_agents_needing_fixes), 'spec_json':dumps(compact_spec(spec)),
    },RePromptPackage,sandbox)
    owners=set(qa_report.owning_agents_needing_fixes)
    if not owners or set(package.target_agents)!=owners:
        raise ValueError('Supervisor corrections must target exactly the reported defect owners')
    for owner in owners:
        if not getattr(package,f'{owner}_fixes'):
            raise ValueError(f'Supervisor omitted correction instructions for {owner}')
    sandbox.verification='full'
    return package


def signoff(job,spec,qa_report,sandbox):
    if qa_report.tests_executed<1 or qa_report.tests_failed>0 or qa_report.bugs:
        raise ValueError('Cannot sign off without successful executed tests and resolved defects')
    decision=job('orchestrator','orchestrator_signoff_task',{
        'round_number':qa_report.round_number,'qa_report_summary':dumps(report_summary(qa_report)),
        'spec_json':dumps(compact_spec(spec)),
    },FinalSignOff,sandbox)
    missing=set(spec.acceptance_criteria)-set(decision.acceptance_criteria_verified)
    if not qa_report.passed:
        decision.approved=False
    if decision.approved and missing:
        decision.approved=False
        decision.summary+='\nUnverified acceptance criteria: '+'; '.join(sorted(missing))
    sandbox.write_artifact('orchestrator_signoff_task.json',decision.model_dump_json(indent=2))
    return decision
