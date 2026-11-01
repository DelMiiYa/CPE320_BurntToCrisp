"""Generated applications run on a separate loopback origin from Office."""
from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen


class PreviewManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.current = None
        self.process = None
        self.log = None

    def status(self, project_id=None):
        with self.lock:
            if not self.current or (project_id and self.current['project_id'] != project_id):
                return None
            return {**self.current, 'running': bool(self.process and self.process.poll() is None)}

    def stop(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                if os.name != 'nt':
                    os.killpg(self.process.pid, signal.SIGTERM)
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.log:
                self.log.close()
            self.current, self.process, self.log = None, None, None

    def start(self, project_id: str, revision_id: str, source: Path):
        with self.lock:
            if self.current and self.current['revision_id'] == revision_id and self.process.poll() is None:
                return self.status()
            self.stop()
            # A new origin per completed job avoids cached assets after in-place edits.
            # Project data remains in the current website folder.
            with socket.socket() as candidate:
                candidate.bind(('127.0.0.1', 0))
                port = candidate.getsockname()[1]
            log_path = source / 'preview.log'
            self.log = log_path.open('w', encoding='utf-8')
            env = os.environ.copy()
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
            data_dir = source / 'data'
            data_dir.mkdir(parents=True, exist_ok=True)
            env['APP_DATA_DIR'] = str(data_dir)
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            self.process = subprocess.Popen([sys.executable, '-m', 'se_team.office.preview', '--source', str(source), '--port', str(port)],
                                            cwd=source, env=env, stdout=self.log, stderr=self.log,
                                            start_new_session=os.name != 'nt')
            self.current = {'project_id': project_id, 'revision_id': revision_id, 'url': f'http://127.0.0.1:{port}/'}
            for _ in range(100):
                if self.process.poll() is not None:
                    error = log_path.read_text(encoding='utf-8')[-2000:]
                    self.stop()
                    raise RuntimeError(f'เปิดเว็บไม่สำเร็จ: {error}')
                try:
                    with urlopen(self.current['url'], timeout=.25) as response:
                        if response.status == 200:
                            return self.status()
                except OSError:
                    pass
                time.sleep(.1)
            self.stop()
            raise RuntimeError('เว็บยังไม่พร้อมหลังจากรอ 10 วินาที ดู startup instructions ในประวัติงาน')


def create_preview(source: Path):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    source = source.resolve()
    backend = source / 'backend' / 'main.py'
    if backend.is_file():
        sys.path[:0] = [str(source), str(source / 'backend')]
        spec = importlib.util.spec_from_file_location('backend.main', backend)
        module = importlib.util.module_from_spec(spec)
        sys.modules['backend.main'] = module
        spec.loader.exec_module(module)
        app = module.app
        if not isinstance(app, FastAPI):
            raise ValueError('backend/main.py must export a FastAPI app')
    else:
        app = FastAPI()
    @app.middleware('http')
    async def frontend_index(request, call_next):
        if request.method in {'GET', 'HEAD'} and request.url.path == '/':
            response = FileResponse(source / 'frontend' / 'index.html')
        else:
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    # API routes are registered before this catch-all frontend mount.
    app.mount('/', StaticFiles(directory=source / 'frontend', html=True), name='frontend')
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    os.environ.setdefault('APP_DATA_DIR', str(args.source.resolve() / 'data'))
    uvicorn.run(create_preview(args.source), host='127.0.0.1', port=args.port, log_level='warning')
