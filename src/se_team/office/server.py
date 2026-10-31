"""Loopback-only Office UI, durable chat API, event stream and version previews."""
from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from se_team.crew.codex_runtime import check_codex_login
from .manager import OfficeRunner, source_files
from .preview import PreviewManager
from .store import Store
from .codex_status import inspect_codex
from .migrate import migrate_storage

STATIC = Path(__file__).parent / 'static'


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    brief: str = Field(default='', max_length=20000)


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class PreviewInput(BaseModel):
    revision_id: str | None = None


def create_app(root: Path | str = 'workspace/office', *, start_worker=True, max_rounds=3) -> FastAPI:
    store = Store(Path(root))
    preview = PreviewManager()
    runner = OfficeRunner(store, preview, max_rounds)
    csrf_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            store.recover()
            if (store.root / 'projects').exists():
                migrate_storage(store)
            runner.start()
        try:
            yield
        finally:
            runner.close()
            preview.stop()

    app = FastAPI(title='Burnt Studio · Agent Office', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.runner, app.state.preview = store, runner, preview
    app.state.csrf_token = csrf_token

    @app.middleware('http')
    async def local_access(request: Request, call_next):
        if request.url.hostname not in {'127.0.0.1', 'localhost', 'testserver', '::1'}:
            return JSONResponse({'detail': 'Office accepts local hostnames only'}, status_code=403)
        if request.url.path.startswith('/office-api/'):
            origin = request.headers.get('origin')
            if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
                return JSONResponse({'detail': 'This request must come from Office'}, status_code=403)
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not secrets.compare_digest(request.headers.get('x-office-token', ''), csrf_token):
                return JSONResponse({'detail': 'Reload Office before sending this request'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src http://127.0.0.1:* http://localhost:*; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({'detail': str(exc.args[0])}, status_code=404)

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/office-api/bootstrap')
    def bootstrap():
        return {'token': csrf_token, 'projects': store.rows('SELECT id,name,brief,created_at,updated_at,latest_revision_id,folder_name FROM projects ORDER BY updated_at DESC'),
                'roles': ['orchestrator', 'frontend_specialist', 'backend_specialist', 'qa_verifier']}

    @app.get('/office-api/health')
    def health():
        return {'ok': True, 'queue': store.one("SELECT COUNT(*) AS count FROM commands WHERE status='queued'")['count']}

    @app.get('/office-api/codex')
    def codex_status():
        issue = store.setting('provider_issue')
        if issue:
            return {'ready': False, 'message': issue['message']}
        try:
            check_codex_login()
            return {'ready': True, 'message': 'Codex พร้อมรับงาน'}
        except Exception as exc:
            return {'ready': False, 'message': str(exc)}

    @app.post('/office-api/codex/recheck')
    def codex_recheck():
        try:
            status = inspect_codex()
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc
        if status['ready']:
            runner.resume_provider()
        return status

    @app.post('/office-api/projects', status_code=201)
    def create_project(body: ProjectInput):
        if not body.name.strip():
            raise HTTPException(422, 'ตั้งชื่อโปรเจกต์ก่อนครับ')
        return store.create_project(body.name.strip(), body.brief.strip())

    @app.get('/office-api/projects/{project_id}')
    def project_state(project_id: str):
        snapshot = store.snapshot(project_id)
        snapshot['preview'] = preview.status(project_id)
        return snapshot

    @app.post('/office-api/projects/{project_id}/messages', status_code=202)
    def send_message(project_id: str, body: MessageInput):
        text = body.content.strip()
        if not text:
            raise HTTPException(422, 'พิมพ์สิ่งที่อยากให้ทีมทำก่อนครับ')
        queued = store.one("SELECT COUNT(*) AS count FROM commands WHERE project_id=? AND status='queued'", (project_id,))['count']
        if queued >= 20:
            raise HTTPException(409, 'มีงานรออยู่ 20 งานแล้ว รอให้ทีมทำงานก่อนครับ')
        return runner.submit(project_id, text)

    @app.post('/office-api/projects/{project_id}/stop')
    def stop_project(project_id: str):
        runner.cancel_project(project_id)
        return {'ok': True}

    @app.get('/office-api/projects/{project_id}/events')
    async def stream(project_id: str, request: Request, after: int = 0):
        store.project(project_id)
        try:
            cursor = max(after, int(request.headers.get('last-event-id', '0')))
        except ValueError:
            cursor = after
        async def generate():
            nonlocal cursor
            yield ': connected\n\n'
            while not await request.is_disconnected():
                events = store.events(project_id, cursor)
                for event in events:
                    cursor = event['id']
                    yield f'id: {cursor}\nevent: update\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
                if not events:
                    yield ': keep-alive\n\n'
                    await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.get('/office-api/projects/{project_id}/files')
    def files(project_id: str):
        return {'files': [{'path': path, 'size': len(content.encode('utf-8'))} for path, content in source_files(store.project_dir(project_id)).items()]}

    @app.get('/office-api/projects/{project_id}/file')
    def file(project_id: str, path: str):
        current = source_files(store.project_dir(project_id))
        if path not in current:
            raise HTTPException(404, 'File not found in the current website')
        return {'path': path, 'content': current[path]}

    @app.get('/office-api/projects/{project_id}/revisions/{revision_id}/files')
    @app.get('/office-api/projects/{project_id}/revisions/{revision_id}/file')
    def historical_source(project_id: str, revision_id: str):
        store.revision(project_id, revision_id)
        raise HTTPException(410, 'เก็บเฉพาะบันทึกงาน ดูไฟล์ปัจจุบันได้จากไฟล์เว็บหลัก')

    @app.post('/office-api/projects/{project_id}/open-folder')
    def open_folder(project_id: str):
        folder = store.project_dir(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(folder))
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'path': str(folder)}

    @app.post('/office-api/projects/{project_id}/preview')
    def open_preview(project_id: str, body: PreviewInput):
        project = store.project(project_id)
        if body.revision_id and body.revision_id != project['latest_revision_id']:
            raise HTTPException(410, 'เปิดได้เฉพาะเว็บหลักปัจจุบัน ไม่มีสำเนาเว็บย้อนหลัง')
        if store.one("SELECT COUNT(*) AS count FROM commands WHERE project_id=? AND status='running'", (project_id,))['count']:
            raise HTTPException(409, 'ทีมกำลังทำงาน รอให้เสร็จก่อนเปิดเว็บหลักครับ')
        revision_id = body.revision_id or project['latest_revision_id']
        if not revision_id:
            raise HTTPException(409, 'ยังไม่มีเว็บ ส่งงานให้หัวหน้าก่อนครับ')
        revision = store.revision(project_id, revision_id)
        source = store.revision_dir(revision)
        inspectable_failure = revision['status'] in {'failed', 'cancelled', 'interrupted'} and (source / 'frontend/index.html').is_file() and (source / 'backend/main.py').is_file()
        if revision['status'] not in {'approved', 'needs_attention'} and not inspectable_failure:
            raise HTTPException(409, 'ยังไม่มีเว็บที่พร้อมเปิด')
        try:
            state = preview.start(project_id, revision_id, store.revision_dir(revision))
            store.event(project_id, 'preview.ready', {'revision_id': revision_id}, revision_id)
            return state
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/office-api/projects/{project_id}/export')
    def export_history(project_id: str):
        snapshot = store.snapshot(project_id)
        snapshot['events'] = store.events(project_id, limit=100000)
        return JSONResponse(snapshot, headers={'Content-Disposition': f'attachment; filename="office-{project_id}.json"'})

    app.mount('/assets', StaticFiles(directory=STATIC), name='office-assets')
    return app
