"""Register a checked-in website without copying files or importing private history."""
from __future__ import annotations

import json
from pathlib import Path

from se_team.models import SpecPackage
from .store import Store, now, uid


def import_website(store: Store, source: Path) -> dict:
    source = Path(source).resolve()
    if source.parent != store.websites_root:
        raise ValueError(f'Website must be directly inside {store.websites_root}')
    for name in ('frontend/index.html', 'backend/main.py', 'project-spec.json'):
        path = source / name
        if not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(f'Website source is missing or unsafe: {name}')
    spec = SpecPackage.model_validate_json((source / 'project-spec.json').read_text(encoding='utf-8'))
    # Repeated launches keep the existing spec, conversation, queue and preview data.
    existing = store.one('SELECT * FROM projects WHERE folder_name=? COLLATE NOCASE', (source.name,))
    if existing:
        if not existing['spec_json']:
            store.set_spec(existing['id'], spec.model_dump_json())
        return store.project(existing['id'])
    marker = source / '.office-layout.json'
    if marker.exists():
        raise ValueError('This folder already belongs to a local Office database; use that workspace or a fresh Git clone')
    project_id, stamp = uid(), now()
    with store.connection() as db:
        db.execute('''INSERT INTO projects(id,name,brief,created_at,updated_at,folder_name,spec_json)
                      VALUES(?,?,?,?,?,?,?)''',
                   (project_id,spec.project_name,spec.brief_summary,stamp,stamp,source.name,spec.model_dump_json()))
    # The import is a completed local action, not a model run or a passing QA claim.
    command = store.enqueue(project_id, 'นำเข้าซอร์สเว็บเดิมจาก Git')
    revision = store.new_revision(command)
    store.execute("UPDATE revisions SET status='needs_attention',finished_at=?,changes_json='[]' WHERE id=?", (stamp,revision['id']))
    store.execute("UPDATE commands SET status='completed' WHERE id=?", (command['id'],))
    store.execute('UPDATE projects SET latest_revision_id=? WHERE id=?', (revision['id'],project_id))
    store.message(project_id, 'system', 'นำเข้าเว็บเดิมแล้ว ใช้ไฟล์ในโฟลเดอร์เดิมต่อได้ทันที บัญชีผู้ใช้ ข้อมูล และประวัติ Office เริ่มใหม่บนเครื่องนี้ ยังไม่ได้รัน QA หรือตรวจรับเว็บจากการนำเข้านี้')
    store.event(project_id, 'project.imported', {'name':spec.project_name,'folder':source.name})
    marker.write_text(json.dumps({'project_id':project_id,'storage_mode':'single_folder','imported_at':stamp},indent=2),encoding='utf-8')
    return store.project(project_id)
