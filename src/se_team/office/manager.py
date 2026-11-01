"""A durable command queue and supervisor-led revisions of the same project."""
from __future__ import annotations

import concurrent.futures
import difflib
import hashlib
import json
import os
import threading
from pathlib import Path

from se_team.crew.runtime import (
    AntigravityUsageLimit,
    CodexUsageLimit,
    ProviderUsageLimit,
    runtime_proxy as agents,
)
from se_team.crew.job_events import JobCancelled, bind_job, check_cancelled
from se_team.models import SpecPackage, FinalSignOff
from se_team.tools.sandbox import SandboxManager
from .store import Store, now, uid

ROLE_NAMES = {'orchestrator': 'หัวหน้าทีม', 'frontend_specialist': 'Frontend', 'backend_specialist': 'Backend', 'qa_verifier': 'QA'}
TASK_NAMES = {
    'supervisor_edit_task': 'แบ่งงานแก้เฉพาะจุด',
    'supervisor_turn_task': 'วางแผนจากคำสั่งของคุณ', 'frontend_build_task': 'สร้างและปรับหน้าเว็บ',
    'backend_build_task': 'สร้างและปรับระบบข้อมูล', 'qa_verification_task': 'ออกแบบชุดทดสอบ',
    'qa_report_task': 'ตรวจผลทดสอบและข้อกำหนด', 'orchestrator_reprompt_task': 'แบ่งงานแก้ข้อผิดพลาด',
    'orchestrator_signoff_task': 'ตรวจรับเวอร์ชันเว็บ',
}


def source_files(root: Path) -> dict[str, str]:
    files = {}
    if not root.exists():
        return files
    box = SandboxManager(root)
    for name in box.list_files():
        path = Path(name)
        if path.parts[0] not in {'frontend', 'backend', 'tests'} or any(part.startswith('.') or part == '__pycache__' for part in path.parts):
            continue
        if path.suffix not in {'.html', '.js', '.css', '.py', '.json', '.md', '.txt', '.svg'}:
            continue
        target = box.validate_path(name)
        if target.stat().st_size <= 500_000:
            files[name] = target.read_text(encoding='utf-8')
    return files


def changes_between(before: Path | dict[str, str], after: Path) -> list[dict]:
    old, new = before if isinstance(before, dict) else source_files(before), source_files(after)
    changes = []
    for name in sorted(set(old) | set(new)):
        if old.get(name) == new.get(name):
            continue
        lines = list(difflib.unified_diff(old.get(name, '').splitlines(), new.get(name, '').splitlines(),
                                          fromfile=f'previous/{name}', tofile=f'current/{name}', lineterm=''))
        changes.append({'path': name, 'kind': 'added' if name not in old else 'deleted' if name not in new else 'modified',
                        'added': sum(line.startswith('+') and not line.startswith('+++') for line in lines),
                        'removed': sum(line.startswith('-') and not line.startswith('---') for line in lines),
                        'before_hash': hashlib.sha256(old[name].encode()).hexdigest() if name in old else None,
                        'after_hash': hashlib.sha256(new[name].encode()).hexdigest() if name in new else None})
    return changes


class OfficeRunner:
    def __init__(self, store: Store, preview=None, max_rounds: int = 3):
        self.store, self.preview = store, preview
        self.max_rounds = max_rounds
        self.wake = threading.Event()
        self.shutdown = threading.Event()
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.active_project = None
        self.thread = None

    def start(self):
        self.store.recover()
        self.store.compact_progress()
        self.thread = threading.Thread(target=self._loop, daemon=True, name='office-command-queue')
        self.thread.start()

    def close(self):
        self.shutdown.set()
        self.cancelled.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=8)

    def submit(self, project_id: str, instruction: str):
        command = self.store.enqueue(project_id, instruction)
        self.wake.set()
        return command

    def resume_provider(self):
        self.store.set_setting('provider_issue', None)
        self.wake.set()

    def cancel_project(self, project_id: str):
        self.store.project(project_id)
        self.store.execute("UPDATE commands SET status='cancelled' WHERE project_id=? AND status='queued'", (project_id,))
        with self.lock:
            if self.active_project == project_id:
                self.cancelled.set()
        self.store.event(project_id, 'command.stop_requested', {})

    def _loop(self):
        while not self.shutdown.is_set():
            if self.store.setting('provider_issue'):
                self.wake.wait(1)
                self.wake.clear()
                continue
            with self.lock:
                command = self.store.claim_command()
                if command:
                    self.active_project = command['project_id']
                    self.cancelled.clear()
            if not command:
                self.wake.wait(1)
                self.wake.clear()
                continue
            try:
                self.process(command)
            finally:
                with self.lock:
                    self.active_project = None

    def process(self, command: dict):
        project_id = command['project_id']
        revision = self.store.new_revision(command)
        revision_id = revision['id']
        task_ids = {}
        task_lock = threading.Lock()
        thread_state = threading.local()

        def events(kind, data):
            role = data.get('role') or getattr(thread_state, 'role', None)
            task_key = data.get('task')
            if kind.startswith('tests.'):
                role, task_key = 'qa_verifier', 'pytest'
            elif kind == 'files.changed':
                role = {'frontend': 'frontend_specialist', 'backend': 'backend_specialist', 'tests': 'qa_verifier'}.get(data.get('owner'))
            if kind in {'agent.started', 'tests.started'}:
                thread_state.role = role
                task_id = uid()
                with task_lock:
                    task_ids[(role, task_key)] = task_id
                self.store.execute('''INSERT INTO tasks(id,project_id,revision_id,role,task_key,title,status,started_at)
                                      VALUES(?,?,?,?,?,?,?,?)''',
                                   (task_id, project_id, revision_id, role, task_key, 'รันชุดทดสอบจริง' if task_key == 'pytest' else TASK_NAMES.get(task_key, task_key), 'running', now()))
            elif kind in {'agent.completed', 'agent.failed', 'tests.completed'}:
                with task_lock:
                    task_id = task_ids.get((role, task_key))
                if task_id:
                    self.store.execute('UPDATE tasks SET status=?,finished_at=?,summary=? WHERE id=?',
                                       ('cancelled' if self.cancelled.is_set() else 'completed' if kind.endswith('completed') else 'failed', now(), data.get('summary', data.get('error', ''))[:1600], task_id))
            elif kind in {'job.configured', 'job.usage', 'job.measured'}:
                with task_lock:
                    task_id = task_ids.get((role, task_key))
                if task_id:
                    old = self.store.one('SELECT metrics_json FROM tasks WHERE id=?', (task_id,))
                    metrics = json.loads(old['metrics_json'] or '{}')
                    metrics.update(data)
                    self.store.execute('UPDATE tasks SET metrics_json=? WHERE id=?', (json.dumps(metrics), task_id))
            if kind == 'files.changed':
                self.store.execute('UPDATE projects SET latest_revision_id=?,updated_at=? WHERE id=?', (revision_id, now(), project_id))
            self.store.event(project_id, kind, data, revision_id, role)

        def step(fn, *args, **kwargs):
            with bind_job(events, self.cancelled):
                return fn(*args, **kwargs)

        sandbox = SandboxManager(self.store.project_dir(project_id), retain_artifacts=False)
        baseline = source_files(sandbox.base_dir)
        try:
            self.store.event(project_id, 'revision.started', {'number': revision['number'], 'command_id': command['id']}, revision_id)
            project = self.store.project(project_id)
            previous_spec = SpecPackage.model_validate_json(project['spec_json']) if project['spec_json'] else None
            messages = self.store.rows('SELECT role,content FROM messages WHERE project_id=? ORDER BY id DESC LIMIT 30', (project_id,))[::-1]
            goal = self.store.project(project_id)['brief']
            history = [{'role': 'project_context', 'content': goal}] + messages
            decision = step(agents.run_supervisor_turn, command['instruction'], previous_spec, history, sandbox)
            self.store.message(project_id, 'assistant', decision.message, command['id'])
            if decision.action == 'reply':
                self._finish(command, revision, 'discussed')
                return
            spec = decision.spec
            self.store.set_spec(project_id, spec.model_dump_json())
            if self.preview and self.preview.status(project_id):
                self.preview.stop()
                self.store.event(project_id, 'preview.paused', {'message': 'ทีมกำลังแก้ไฟล์เว็บหลัก'}, revision_id)
            self.store.event(project_id, 'plan.created', {'target_agents': decision.target_agents, 'build_batches': spec.build_batches,
                                                        'acceptance_criteria': spec.acceptance_criteria,
                                                        'work_orders': {'frontend': spec.frontend_prompt.model_dump(), 'backend': spec.backend_prompt.model_dump(), 'qa': spec.qa_guidance}}, revision_id, 'orchestrator')

            def build(targets, extra=None):
                for batch in spec.build_batches:
                    selected = [owner for owner in batch if owner in targets]
                    if not selected:
                        continue
                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(selected)) as executor:
                        futures = [executor.submit(step, agents.run_build_step, spec, sandbox, owner, (extra or {}).get(owner)) for owner in selected]
                        for future in futures:
                            future.result()

            build(decision.target_agents)
            # A model cannot mark backend or test modifications as a cosmetic edit.
            changed_now = changes_between(baseline, sandbox.base_dir)
            if any(not c['path'].startswith('frontend/') or not c['path'].endswith(('.css', '.html', '.svg')) for c in changed_now):
                sandbox.verification = 'full'
            qa_report = None
            signoff = None
            for round_number in range(1, self.max_rounds + 1):
                step(check_cancelled)
                qa_report = step(agents.run_qa_step, spec, sandbox, round_number)
                self.store.execute('UPDATE revisions SET qa_json=?,round_number=? WHERE id=?',
                                   (json.dumps(self.store.brief_report(qa_report.model_dump()), ensure_ascii=False), round_number, revision_id))
                if qa_report.passed:
                    signoff = step(agents.run_signoff_step, spec, qa_report, sandbox)
                    break
                if not qa_report.bugs and qa_report.tests_executed > 0 and qa_report.tests_failed == 0:
                    signoff = FinalSignOff(approved=False, summary=qa_report.summary)
                    self.store.event(project_id, 'review.pending', {'message': 'ทดสอบอัตโนมัติผ่าน รอตรวจหลักฐานเพิ่มเติมตามผล QA'}, revision_id)
                    break
                if round_number == self.max_rounds:
                    break
                instructions = step(agents.run_reprompt_step, qa_report, spec, sandbox, round_number)
                self.store.execute('UPDATE revisions SET round_number=? WHERE id=?', (round_number + 1, revision_id))
                self.store.event(project_id, 'fix.assigned', {'targets': instructions.target_agents, 'round_number': round_number + 1,
                                                            'instructions': instructions.model_dump()}, revision_id, 'orchestrator')
                build(instructions.target_agents, {'frontend': instructions.frontend_fixes, 'backend': instructions.backend_fixes})
            step(check_cancelled)
            changes = changes_between(baseline, sandbox.base_dir)
            status = 'approved' if signoff and signoff.approved else 'needs_attention'
            self.store.execute('UPDATE revisions SET signoff_json=?,changes_json=? WHERE id=?',
                               (json.dumps(self.store.brief_report(signoff.model_dump()), ensure_ascii=False) if signoff else None, json.dumps(changes, ensure_ascii=False), revision_id))
            self.store.execute('UPDATE projects SET latest_revision_id=?,updated_at=? WHERE id=?', (revision_id, now(), project_id))
            note = signoff.summary if signoff else qa_report.summary
            prefix = "ปรับเว็บหลักเรียบร้อยและผ่านการตรวจรับแล้วครับ" if status == 'approved' else "ปรับเว็บหลักเรียบร้อย แต่ยังมีจุดที่ต้องตรวจหรือแก้ครับ"
            self.store.message(project_id, 'assistant', f'{prefix}\n\n{note}\n\nเปลี่ยนไฟล์ {len(changes)} ไฟล์ ดูรายละเอียดได้ที่บันทึกงาน และส่งสิ่งที่อยากปรับต่อได้เลยครับ', command['id'])
            self._finish(command, revision, status)
            if self.preview and (sandbox.base_dir / 'frontend' / 'index.html').is_file():
                try:
                    self.preview.start(project_id, revision_id, sandbox.base_dir)
                    self.store.event(project_id, 'preview.ready', {'revision_id': revision_id}, revision_id)
                except Exception as exc:
                    self.store.event(project_id, 'preview.failed', {'error': str(exc)[:1000]}, revision_id)
        except Exception as exc:
            status = 'cancelled' if isinstance(exc, JobCancelled) else 'failed'
            is_limit = isinstance(exc, (ProviderUsageLimit, CodexUsageLimit, AntigravityUsageLimit))
            provider_title = getattr(agents, "PROVIDER_NAME", "Google Antigravity")
            if is_limit:
                self.store.set_setting('provider_issue', {'message': f'{provider_title} แจ้งข้อจำกัดการใช้งานชั่วคราว งานที่รออยู่จะพักไว้ โดยยังเก็บคำสั่งและไฟล์ครบ', 'at': now()})
                self.store.event(project_id, 'provider.paused', {'message': f'{provider_title} แจ้งข้อจำกัดการใช้งานชั่วคราว'}, revision_id)
            changes = changes_between(baseline, sandbox.base_dir)
            self.store.execute('UPDATE revisions SET error=?,changes_json=? WHERE id=?', (str(exc)[:1800], json.dumps(changes, ensure_ascii=False), revision_id))
            if changes:
                self.store.execute('UPDATE projects SET latest_revision_id=?,updated_at=? WHERE id=?', (revision_id, now(), project_id))
            self.store.execute("UPDATE tasks SET status=?,finished_at=? WHERE revision_id=? AND status='running'", (status, now(), revision_id))
            self._finish(command, revision, status)
            explanation = 'เปิดรายละเอียดข้อผิดพลาดในบันทึกงานได้ ไฟล์ที่แก้ไปแล้วจะอยู่ในโฟลเดอร์เว็บหลัก'
            if is_limit:
                explanation = f'{provider_title} แจ้งข้อจำกัดการใช้งานชั่วคราว จึงพักงานในคิวไว้ กดตรวจการเชื่อมต่ออีกครั้งเมื่อพร้อมได้ครับ'
            if 'timed out' in str(exc).lower():
                explanation = 'Agent ทำงานเกินเวลาที่กำหนด ระบบจึงหยุดงานส่วนนี้ ดูขั้นตอนและเวลาที่ใช้จริงได้ใน Agent office แล้วส่งคำสั่งให้ทำต่อจากไฟล์ปัจจุบันได้ครับ'
            self.store.message(project_id, 'system', f"{'หยุดงานแล้วครับ' if status == 'cancelled' else 'ทีมติดปัญหาระหว่างทำงานครับ'}\n\n{explanation}\n\nประวัติคำสั่งและไฟล์ปัจจุบันยังอยู่ คุณส่งคำสั่งให้ทำต่อหรือแก้ไขได้ครับ", command['id'])

    def _finish(self, command, revision, status):
        self.store.execute('UPDATE revisions SET status=?,finished_at=? WHERE id=?', (status, now(), revision['id']))
        self.store.execute('UPDATE commands SET status=? WHERE id=?', ('completed' if status in {'approved', 'needs_attention', 'discussed'} else status, command['id']))
        self.store.event(command['project_id'], 'revision.finished', {'status': status, 'number': revision['number']}, revision['id'])
