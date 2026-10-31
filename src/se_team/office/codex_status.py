"""Read CLI authentication and quota without starting a model turn."""
import json
import queue
import subprocess
import threading
import time

from se_team.crew.codex_runtime import codex_binary


def inspect_codex() -> dict:
    process = subprocess.Popen([codex_binary(), 'app-server', '--listen', 'stdio://', '-c', 'model_provider="openai"'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding='utf-8')
    responses = queue.Queue()
    def reader():
        for line in process.stdout:
            try:
                responses.put(json.loads(line))
            except ValueError:
                continue
    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + 20
    def request(identifier, method, params=None):
        payload = {'id': identifier, 'method': method}
        if params is not None:
            payload['params'] = params
        process.stdin.write(json.dumps(payload) + '\n')
        process.stdin.flush()
        while time.monotonic() < deadline:
            try:
                message = responses.get(timeout=.25)
            except queue.Empty:
                continue
            if message.get('id') == identifier:
                if 'error' in message:
                    raise RuntimeError('ยังตรวจสถานะ Codex ไม่ได้ ลองตรวจอีกครั้งครับ')
                return message.get('result', {})
        raise TimeoutError('ตรวจการเชื่อมต่อ Codex ไม่ทันเวลา ลองอีกครั้งครับ')
    try:
        request(0, 'initialize', {'clientInfo': {'name': 'burnt_office_status', 'title': 'Burnt Office status', 'version': '1.0.0'}})
        process.stdin.write(json.dumps({'method': 'initialized'}) + '\n')
        process.stdin.flush()
        auth = request(1, 'account/read', {'refreshToken': False})
        account = auth.get('account') or {}
        if not account and auth.get('requiresOpenaiAuth'):
            return {'ready': False, 'message': 'Codex ยังไม่ได้ล็อกอิน ให้เปิด Terminal แล้วใช้ codex login'}
        if account.get('type') == 'chatgpt':
            limits = request(2, 'account/rateLimits/read', {'excludeResetCreditDetails': True})
            allowed = limits.get('ordinaryUsageAllowed')
            if allowed is None:
                bucket = limits.get('rateLimits') or {}
                allowed = not any((bucket.get(window) or {}).get('usedPercent', 0) >= 100 for window in ('primary', 'secondary'))
            return {'ready': bool(allowed), 'message': 'Codex เชื่อมต่อแล้ว' if allowed else 'Codex ยังติดข้อจำกัดการใช้งาน คำสั่งในคิวจะพักไว้'}
        return {'ready': True, 'message': 'Codex เชื่อมต่อแล้ว'}
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
