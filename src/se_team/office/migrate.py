"""Move the latest website into one shallow folder; retain compact work logs."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .store import Store, now


def manifest(root: Path) -> dict[str, str]:
    result = {}
    if root.is_symlink():
        raise ValueError(f'Migration will not follow a symbolic link: {root}')
    if not root.exists():
        return result
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in {'__pycache__', '.pytest_cache'} for part in relative.parts) or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError(f'Migration will not follow a symbolic link: {path}')
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def move_tree(source: Path, destination: Path):
    if source.is_symlink() or destination.is_symlink():
        raise ValueError('Migration will not move through symbolic links')
    if not source.exists():
        return
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return
    if source.is_file():
        if source.read_bytes() != destination.read_bytes():
            raise ValueError(f'Refusing to overwrite an existing file: {destination}')
        source.unlink()
        return
    for child in list(source.iterdir()):
        move_tree(child, destination / child.name)
    source.rmdir()


def compact_history(store: Store):
    with store.connection() as db:
        for row in db.execute('SELECT id,changes_json,qa_json,signoff_json FROM revisions').fetchall():
            changes = json.loads(row['changes_json'] or 'null')
            if changes:
                changes = [{key: value for key, value in change.items() if key != 'diff'} for change in changes]
            qa = store.brief_report(json.loads(row['qa_json'] or 'null'))
            signoff = store.brief_report(json.loads(row['signoff_json'] or 'null'))
            db.execute('UPDATE revisions SET spec_json=NULL,changes_json=?,qa_json=?,signoff_json=? WHERE id=?',
                       (json.dumps(changes, ensure_ascii=False) if changes is not None else None,
                        json.dumps(qa, ensure_ascii=False) if qa is not None else None,
                        json.dumps(signoff, ensure_ascii=False) if signoff is not None else None, row['id']))
        for row in db.execute('SELECT id,type,data_json FROM events').fetchall():
            db.execute('UPDATE events SET data_json=? WHERE id=?',
                       (json.dumps(store.brief_event(row['type'], json.loads(row['data_json'])), ensure_ascii=False), row['id']))
        db.execute('UPDATE tasks SET summary=substr(summary,1,1600) WHERE summary IS NOT NULL')


def migrate_storage(store: Store, *, remove_legacy=True) -> dict:
    if store.one("SELECT COUNT(*) AS count FROM commands WHERE status='running'")['count']:
        raise RuntimeError('Stop the Office worker before migrating project files')
    report = {'migrated_at': now(), 'projects': [], 'storage_mode': 'single_folder'}
    for project in store.rows('SELECT * FROM projects ORDER BY created_at'):
        legacy = store.root / 'projects' / project['id']
        destination = store.project_dir(project['id'])
        marker = destination / '.office-layout.json'
        if marker.is_file():
            metadata = json.loads(marker.read_text(encoding='utf-8'))
            if metadata.get('project_id') != project['id']:
                raise ValueError(f'Project folder belongs to a different project: {destination}')
        else:
            revisions = store.rows('SELECT * FROM revisions WHERE project_id=? ORDER BY number DESC', (project['id'],))
            candidates = sorted(revisions, key=lambda row: row['id'] == project['latest_revision_id'], reverse=True)
            selected = next((row for row in candidates if (store.legacy_revision_dir(row) / 'frontend').is_dir() or (store.legacy_revision_dir(row) / 'backend').is_dir()), None)
            destination.mkdir(parents=True, exist_ok=True)
            manifest(destination)
            expected = {}
            if selected:
                source = store.legacy_revision_dir(selected)
                for component in ('frontend', 'backend', 'tests'):
                    expected.update({f'{component}/{name}': digest for name, digest in manifest(source / component).items()})
                    move_tree(source / component, destination / component)
                if not project['spec_json'] and selected['spec_json']:
                    store.set_spec(project['id'], selected['spec_json'])
            data = legacy / 'data'
            expected.update({f'data/{name}': digest for name, digest in manifest(data).items()})
            move_tree(data, destination / 'data')
            actual = manifest(destination)
            if any(actual.get(name) != digest for name, digest in expected.items()):
                raise RuntimeError(f'File verification failed; old copies have not been removed: {destination}')
            marker.write_text(json.dumps({'project_id': project['id'], 'storage_mode': 'single_folder', 'migrated_at': now()}, indent=2), encoding='utf-8')
            report['projects'].append({'name': project['name'], 'path': str(destination), 'verified_files': len(expected)})
            if expected:
                store.message(project['id'], 'system', f'ย้ายเว็บหลักมาไว้ที่ {destination} แล้ว จากนี้ทีมจะแก้ไฟล์ในโฟลเดอร์เดิม เก็บเฉพาะสรุปงานและผลทดสอบ ไม่มีสำเนาเว็บย้อนหลัง ข้อมูลการใช้งานกับแชตเดิมยังอยู่ครบ')
        # Removing old copies is authorized only after the current source/data hashes match.
        if remove_legacy and (legacy / 'revisions').exists():
            shutil.rmtree(legacy / 'revisions')
        if legacy.exists() and not any(legacy.iterdir()):
            legacy.rmdir()
        for cache in list(destination.rglob('__pycache__')) + list(destination.rglob('.pytest_cache')):
            if cache.is_dir() and not cache.is_symlink():
                shutil.rmtree(cache)
    compact_history(store)
    projects = store.root / 'projects'
    if projects.exists() and not any(projects.iterdir()):
        projects.rmdir()
    with store.connection() as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.execute('VACUUM')
    return report
