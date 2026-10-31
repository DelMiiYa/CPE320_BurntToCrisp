"""Durable project, conversation, work and event records in SQLite."""
from __future__ import annotations

import json
import sqlite3
import uuid
import re
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, root: Path, websites_root: Path | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'office.sqlite3'
        default_websites = self.root.parent.parent / 'websites' if self.root.name == 'office' and self.root.parent.name == 'workspace' else self.root / 'websites'
        self.websites_root = Path(websites_root or default_websites).resolve()
        self.websites_root.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, brief TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, latest_revision_id TEXT
                );
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    instruction TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    revision_id TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id),
                    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL, command_id TEXT
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    command_id TEXT NOT NULL REFERENCES commands(id), number INTEGER NOT NULL,
                    parent_id TEXT, status TEXT NOT NULL, instruction TEXT NOT NULL,
                    created_at TEXT NOT NULL, finished_at TEXT, round_number INTEGER NOT NULL DEFAULT 1,
                    spec_json TEXT, qa_json TEXT, signoff_json TEXT, changes_json TEXT,
                    error TEXT, UNIQUE(project_id, number)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    revision_id TEXT NOT NULL REFERENCES revisions(id), role TEXT NOT NULL,
                    task_key TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, summary TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id),
                    revision_id TEXT, role TEXT, type TEXT NOT NULL, data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_project ON events(project_id, id);
                CREATE INDEX IF NOT EXISTS commands_queue ON commands(status, created_at);
                CREATE TABLE IF NOT EXISTS runtime_state (
                    name TEXT PRIMARY KEY, value_json TEXT NOT NULL
                );
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(projects)')}
            for name in ('folder_name', 'spec_json'):
                if name not in columns:
                    db.execute(f'ALTER TABLE projects ADD COLUMN {name} TEXT')
            used = {row[0].casefold() for row in db.execute('SELECT folder_name FROM projects WHERE folder_name IS NOT NULL')}
            for row in db.execute('SELECT id,name FROM projects WHERE folder_name IS NULL').fetchall():
                folder = self._available_folder(row['name'], used)
                used.add(folder.casefold())
                db.execute('UPDATE projects SET folder_name=? WHERE id=?', (folder, row['id']))
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS projects_folder ON projects(folder_name COLLATE NOCASE)')

    def _available_folder(self, name: str, used: set[str]) -> str:
        name = unicodedata.normalize('NFKC', name)
        cleaned = ''.join(ch if unicodedata.category(ch)[0] in 'LNM' or ch in ' _-' else '-' for ch in name)
        base = re.sub(r'[-\s]+', '-', cleaned).strip('-_ ')[:70] or 'Project'
        if base.casefold() in {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}:
            base = 'Project-' + base
        candidate, suffix = base, 2
        while candidate.casefold() in used or (self.websites_root / candidate).exists():
            candidate = f'{base}-{suffix}'
            suffix += 1
        return candidate

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql: str, values=()) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, values).fetchall()]

    def one(self, sql: str, values=()) -> dict | None:
        rows = self.rows(sql, values)
        return rows[0] if rows else None

    def execute(self, sql: str, values=()):
        with self.connection() as db:
            db.execute(sql, values)

    def project(self, project_id: str) -> dict:
        project = self.one('SELECT * FROM projects WHERE id=?', (project_id,))
        if not project:
            raise KeyError('Project not found')
        return project

    def setting(self, name: str):
        row = self.one('SELECT value_json FROM runtime_state WHERE name=?', (name,))
        return json.loads(row['value_json']) if row else None

    def set_setting(self, name: str, value):
        self.execute('INSERT INTO runtime_state(name,value_json) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json',
                     (name, json.dumps(value, ensure_ascii=False)))

    def create_project(self, name: str, brief: str) -> dict:
        project_id, stamp = uid(), now()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            used = {row[0].casefold() for row in db.execute('SELECT folder_name FROM projects')}
            folder = self._available_folder(name, used)
            db.execute('INSERT INTO projects(id,name,brief,created_at,updated_at,folder_name) VALUES(?,?,?,?,?,?)',
                       (project_id, name, brief, stamp, stamp, folder))
        self.project_dir(project_id).mkdir(parents=True, exist_ok=True)
        self.message(project_id, 'assistant', 'สวัสดีครับ ผมเป็นหัวหน้าทีม บอกสิ่งที่อยากสร้างหรือแก้ได้เลย ผมจะแบ่งงานให้ทีมและเก็บประวัติให้ครับ')
        self.event(project_id, 'project.created', {'name': name})
        return self.project(project_id)

    def message(self, project_id: str, role: str, content: str, command_id: str | None = None):
        self.execute('INSERT INTO messages(project_id,role,content,created_at,command_id) VALUES(?,?,?,?,?)',
                     (project_id, role, content, now(), command_id))

    def enqueue(self, project_id: str, instruction: str) -> dict:
        self.project(project_id)
        command_id = uid()
        with self.connection() as db:
            db.execute('INSERT INTO commands VALUES(?,?,?,?,?,NULL)', (command_id, project_id, instruction, 'queued', now()))
            db.execute('INSERT INTO messages(project_id,role,content,created_at,command_id) VALUES(?,?,?,?,?)',
                       (project_id, 'user', instruction, now(), command_id))
            db.execute('UPDATE projects SET updated_at=? WHERE id=?', (now(), project_id))
        self.event(project_id, 'command.queued', {'command_id': command_id, 'instruction': instruction})
        return self.one('SELECT * FROM commands WHERE id=?', (command_id,))

    def claim_command(self) -> dict | None:
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM commands WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE commands SET status='running' WHERE id=?", (row['id'],))
            return {**dict(row), 'status': 'running'}

    def new_revision(self, command: dict) -> dict:
        project = self.project(command['project_id'])
        revision_id = uid()
        with self.connection() as db:
            number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM revisions WHERE project_id=?', (project['id'],)).fetchone()[0]
            db.execute('''INSERT INTO revisions(id,project_id,command_id,number,parent_id,status,instruction,created_at)
                          VALUES(?,?,?,?,?,?,?,?)''',
                       (revision_id, project['id'], command['id'], number, project['latest_revision_id'], 'running', command['instruction'], now()))
            db.execute('UPDATE commands SET revision_id=? WHERE id=?', (revision_id, command['id']))
        return self.revision(project['id'], revision_id)

    def revision(self, project_id: str, revision_id: str) -> dict:
        row = self.one('SELECT * FROM revisions WHERE project_id=? AND id=?', (project_id, revision_id))
        if not row:
            raise KeyError('Version not found')
        return row

    def legacy_revision_dir(self, revision: dict) -> Path:
        return self.root / 'projects' / revision['project_id'] / 'revisions' / revision['id'] / f"round_{revision['round_number']}"

    def project_dir(self, project_id: str) -> Path:
        folder = self.project(project_id)['folder_name']
        if not folder or Path(folder).name != folder or folder in {'.', '..'} or '/' in folder or '\\' in folder:
            raise ValueError('Invalid project folder')
        path = (self.websites_root / folder).resolve()
        path.relative_to(self.websites_root)
        return path

    def revision_dir(self, revision: dict) -> Path:
        """Compatibility alias: every work log now refers to the same current folder."""
        return self.project_dir(revision['project_id'])

    def set_spec(self, project_id: str, spec_json: str):
        self.execute('UPDATE projects SET spec_json=? WHERE id=?', (spec_json, project_id))

    @staticmethod
    def brief_report(report: dict | None):
        if report is None:
            return None
        kept = {key: report[key] for key in ('round_number', 'passed', 'approved', 'tests_executed', 'tests_passed', 'tests_failed') if key in report}
        kept['summary'] = str(report.get('summary', ''))[:1800]
        if report.get('bugs'):
            kept['bugs'] = [{key: str(bug.get(key, ''))[:200] for key in ('id', 'title', 'severity', 'owning_agent')}
                            for bug in report['bugs'][:20]]
        return kept

    @staticmethod
    def brief_event(kind: str, data: dict) -> dict:
        if kind == 'tests.completed':
            return {key: data[key] for key in ('tests_executed', 'tests_passed', 'tests_failed', 'exit_code', 'passed') if key in data}
        if kind == 'plan.created':
            return {key: data[key] for key in ('target_agents', 'build_batches') if key in data}
        if kind == 'fix.assigned':
            return {key: data[key] for key in ('targets', 'round_number') if key in data}
        return {key: value[:1600] if isinstance(value, str) else value for key, value in data.items()}

    def event(self, project_id: str, kind: str, data: dict, revision_id: str | None = None, role: str | None = None):
        self.execute('INSERT INTO events(project_id,revision_id,role,type,data_json,created_at) VALUES(?,?,?,?,?,?)',
                     (project_id, revision_id, role, kind, json.dumps(self.brief_event(kind, data), ensure_ascii=False), now()))

    def events(self, project_id: str, after: int = 0, limit: int = 200) -> list[dict]:
        rows = self.rows('SELECT * FROM events WHERE project_id=? AND id>? ORDER BY id LIMIT ?', (project_id, after, limit))
        for row in rows:
            row['data'] = json.loads(row.pop('data_json'))
        return rows

    def snapshot(self, project_id: str) -> dict:
        project = self.project(project_id)
        project.pop('spec_json', None)
        project['website_path'] = str(self.project_dir(project_id))
        project['website_folder'] = f'websites/{project["folder_name"]}'
        revisions = self.rows('SELECT * FROM revisions WHERE project_id=? ORDER BY number DESC', (project_id,))
        for row in revisions:
            for column in ('spec_json', 'qa_json', 'signoff_json', 'changes_json'):
                value = json.loads(row.pop(column) or 'null')
                row[column.removesuffix('_json')] = None if column == 'spec_json' else value
        messages = self.rows('SELECT * FROM messages WHERE project_id=? ORDER BY id', (project_id,))
        tasks = self.rows('SELECT * FROM tasks WHERE project_id=? ORDER BY started_at', (project_id,))
        commands = self.rows('SELECT * FROM commands WHERE project_id=? ORDER BY created_at', (project_id,))
        events = self.rows('SELECT * FROM (SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT 120) ORDER BY id', (project_id,))
        for event in events:
            event['data'] = json.loads(event.pop('data_json'))
        return {'project': project, 'revisions': revisions, 'messages': messages, 'tasks': tasks,
                'storage_mode': 'single_folder', 'history_has_source': False,
                'commands': commands, 'events': events, 'provider_issue': self.setting('provider_issue'),
                'cursor': events[-1]['id'] if events else 0}

    def recover(self):
        interrupted = self.rows("SELECT * FROM commands WHERE status='running'")
        for command in interrupted:
            self.execute("UPDATE commands SET status='interrupted' WHERE id=?", (command['id'],))
            self.execute("UPDATE revisions SET status='interrupted',finished_at=?,error=? WHERE command_id=? AND status='running'",
                         (now(), 'Office stopped while this request was running. Send the request again to retry.', command['id']))
            self.execute("UPDATE tasks SET status='interrupted',finished_at=? WHERE revision_id=? AND status='running'", (now(), command['revision_id']))
            self.message(command['project_id'], 'assistant', 'Office หยุดระหว่างทำงาน คำสั่งและไฟล์ยังอยู่ในประวัติ กดส่งคำสั่งเดิมอีกครั้งเพื่อให้ทีมทำต่อครับ', command['id'])
            self.event(command['project_id'], 'command.interrupted', {'command_id': command['id']}, command['revision_id'])
