"""Bounded, role-scoped context and validated edits shared by local providers."""
from __future__ import annotations

import ast
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from se_team.crew.job_events import check_cancelled, emit
from se_team.models import SpecPackage

SOURCE_SUFFIXES = {'.py', '.js', '.css', '.html', '.json', '.md', '.txt', '.svg'}
MAX_CONTEXT_CHARS = 65000
_scope: ContextVar[list[str] | None] = ContextVar('source_scope', default=None)


class ProposedFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str
    content: str


class ProposedEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str
    search: str = Field(min_length=1, description='Exact, unique existing text, including whitespace')
    replace: str
    base_hash: str = Field(default='', description='SHA256 from the supplied source entry')


class FileBundle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(max_length=2000)
    files: list[ProposedFile] = Field(default_factory=list, description='New files or necessary complete rewrites only')
    edits: list[ProposedEdit] = Field(default_factory=list, description='Prefer exact search/replace edits to existing files')
    deleted_files: list[str] = Field(default_factory=list)
    need_files: list[str] = Field(default_factory=list, max_length=8, description='If required source is missing, request these paths instead of guessing; no modifications in this response')


class WorkOrder(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner: Literal['frontend', 'backend', 'qa']
    instructions: str = Field(min_length=1, max_length=4000)
    files: list[str] = Field(default_factory=list, max_length=12)


class EditDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(max_length=1600)
    action: Literal['build', 'reply']
    work_orders: list[WorkOrder] = Field(default_factory=list, max_length=3)
    acceptance_additions: list[str] = Field(default_factory=list, max_length=10)
    contract_changes_required: bool = False
    verification: Literal['regression', 'full'] = Field(default='full', description='regression only for cosmetic/copy changes with no new behavior or API changes; otherwise full')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@contextmanager
def source_scope(paths):
    token = _scope.set(paths)
    try:
        yield
    finally:
        _scope.reset(token)


def source_map(sandbox) -> dict[str, str]:
    result = {}
    for name in sorted(sandbox.list_files()):
        p = Path(name)
        if p.parts[0] not in {'frontend', 'backend', 'tests'} or p.suffix not in SOURCE_SUFFIXES:
            continue
        if any(part.startswith('.') or part == '__pycache__' for part in p.parts):
            continue
        target = sandbox.validate_path(name)
        if target.is_file() and not (sandbox.base_dir / name).is_symlink() and target.stat().st_size <= 500000:
            result[name] = target.read_text(encoding='utf-8')
    return result


def source_context(sandbox, role=None, task=None) -> str:
    sources = source_map(sandbox)
    inventory = [{'path': name, 'chars': len(content), 'hash': digest(content)} for name, content in sources.items()]
    if role is None:
        return dumps([{'path': p, 'content': s} for p, s in sources.items()])
    # Planning and reviewing test evidence need the index/contract, not every source file.
    if role == 'orchestrator' or task == 'qa_report_task':
        return dumps({'inventory': inventory, 'files': []})
    requested = _scope.get()
    if requested is None:
        owner = {'frontend_specialist': 'frontend', 'backend_specialist': 'backend', 'qa_verifier': 'tests'}.get(role)
        requested = [p for p in sources if p.startswith(owner + '/')]
        if role == 'qa_verifier':
            requested = [p for p in sources if p.startswith('backend/') and not Path(p).name.startswith('test_')] + requested
    selected, omitted, size = [], [], 0
    for name in dict.fromkeys(requested):
        if name not in sources:
            continue
        content = sources[name]
        if size + len(content) > MAX_CONTEXT_CHARS:
            omitted.append(name)
            continue
        selected.append({'path': name, 'hash': digest(content), 'content': content})
        size += len(content)
    return dumps({'inventory': inventory, 'files': selected, 'omitted': omitted,
                  'retrieval': 'Return need_files if a required file is absent. Never use filesystem tools.'})


def compact_spec(spec: SpecPackage, *, owner=None) -> dict:
    result = {'project': spec.project_name, 'brief': spec.brief_summary[:1400],
              'scope': spec.task_scope[:1600], 'acceptance': spec.acceptance_criteria}
    # Preserve exact API payloads for builders; the planner needs just the endpoint index.
    result['api'] = ([e.model_dump(exclude_none=True) for e in spec.api_contract]
                     if owner else [{'method': e.method, 'path': e.path, 'summary': e.summary} for e in spec.api_contract])
    if owner in {'backend', 'qa'}:
        result['data'] = [d.model_dump() for d in spec.data_schemas]
    return result


def compact_history(history: list[dict], instruction: str) -> str:
    result = []
    budget = 9000
    for message in reversed(history):
        text = str(message.get('content', ''))
        if text == instruction:
            continue
        cap = 1800 if message.get('role') in {'user', 'project_context'} else 850
        text = text[:cap]
        if sum(len(x['content']) for x in result) + len(text) > budget:
            break
        result.append({'role': message['role'], 'content': text})
    return dumps(list(reversed(result)))


def resolve_edit_plan(previous, decision: EditDecision):
    from se_team.crew.codex_runtime import SupervisorDecision
    if decision.action == 'reply':
        return SupervisorDecision(message=decision.message, action='reply')
    owners = [w.owner for w in decision.work_orders]
    if not owners or len(set(owners)) != len(owners) or ('qa' in owners and len(owners) > 1):
        raise ValueError('Assign each specialist once; QA alone requests verification')
    spec = previous.model_copy(deep=True)
    for work in decision.work_orders:
        if work.owner != 'qa':
            prompt = getattr(spec, f'{work.owner}_prompt')
            prompt.instructions = work.instructions
            prompt.files_to_produce = work.files
    spec.acceptance_criteria = list(dict.fromkeys(spec.acceptance_criteria + decision.acceptance_additions))
    # Existing contracts/data remain exact; a contract change is handled by full planning.
    return SupervisorDecision(message=decision.message, action='build', spec=spec, target_agents=owners,
                              verification='full' if decision.acceptance_additions else decision.verification)


def apply_bundle(bundle: FileBundle, owner: str, sandbox) -> None:
    """Validate the entire proposal and all exact-match preconditions before any writes."""
    if bundle.need_files:
        raise ValueError('A source request must be resolved before applying changes')
    staged, original, seen = {}, {}, set()

    def validate(name):
        p = Path(name)
        target = sandbox.validate_path(p)
        if p.is_absolute() or '..' in p.parts or len(p.parts) < 2 or p.parts[0] != owner or any(x.startswith('.') for x in p.parts):
            raise ValueError(f'{owner} agent cannot write {name!r}')
        try:
            target.relative_to(sandbox.base_dir / owner)
        except ValueError:
            raise ValueError(f'{owner} agent cannot write through a cross-role symbolic link: {name}')
        if owner == 'tests' and (p.suffix != '.py' or p.name == 'conftest.py'):
            raise ValueError('QA may propose Python test files, not pytest configuration overrides')
        return target

    for file in bundle.files:
        validate(file.path)
        if file.path in seen:
            raise ValueError(f'Duplicate proposed file: {file.path}')
        seen.add(file.path)
        staged[file.path] = file.content
    for edit in bundle.edits:
        target = validate(edit.path)
        if edit.path in seen:
            raise ValueError('Do not mix a full write and edits for one file')
        if edit.path not in original:
            original[edit.path] = target.read_text(encoding='utf-8')
        if edit.base_hash and digest(original[edit.path]) != edit.base_hash:
            raise ValueError(f'Stale edit: {edit.path}; source has changed')
        content = staged.get(edit.path, original[edit.path])
        if content.count(edit.search) != 1:
            raise ValueError(f'Edit must match exactly once: {edit.path}')
        staged[edit.path] = content.replace(edit.search, edit.replace, 1)
    deleted = set()
    for name in bundle.deleted_files:
        validate(name)
        if name in deleted or name in staged:
            raise ValueError(f'Duplicate proposed file: {name}')
        deleted.add(name)
    for name, content in staged.items():
        if name.endswith('.py'):
            ast.parse(content, filename=name)
    check_cancelled()
    # Proposals are staged in memory: a mismatched edit never partially writes a bundle.
    for name, content in staged.items():
        sandbox.write_file(name, content)
    for name in deleted:
        sandbox.validate_path(name).unlink(missing_ok=True)
    if staged or deleted:
        emit('files.changed', owner=owner, paths=list(staged), deleted=list(deleted),
             edit_count=len(bundle.edits), replacement_chars=sum(len(e.replace) for e in bundle.edits))


def obtain_bundle(run_job, role, task, values, sandbox, paths):
    """At most one extra source fetch, with no source cache persisted to disk."""
    with source_scope(paths):
        bundle = run_job(role, task, values, FileBundle, sandbox)
    if bundle.need_files:
        if bundle.files or bundle.edits or bundle.deleted_files:
            raise ValueError('Do not mix source requests with modifications')
        available = source_map(sandbox)
        if any(p not in available for p in bundle.need_files):
            raise ValueError('Requested source is missing or outside generated source')
        emit('agent.completed', role=role, task=task, summary='ส่งคำขอไฟล์เพิ่มเติมให้ระบบแล้ว')
        emit('context.expanded', paths=bundle.need_files)
        with source_scope(bundle.need_files + (paths or [])):
            bundle = run_job(role, task, values, FileBundle, sandbox)
        if bundle.need_files:
            raise ValueError('Source request limit reached; split this work order into smaller files')
    return bundle


EDIT_RULES = '''Prefer edits with exact unique search/replace for existing files. Copy search text exactly from supplied source; include its hash. Use files for new files or necessary major rewrites only. Never reproduce unchanged files. Return need_files only when essential source is absent; do not guess. Use empty arrays for unused fields. Keep summaries concise. You cannot inspect the actual website folder through tools; all source is attached as data.'''
