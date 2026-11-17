"""Personal, loopback-only web UI. Each installation owns its Garmin session."""
import json
import secrets
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import garmin_daily as core

ROOT = Path(__file__).resolve().parent
KEY = secrets.token_urlsafe(32)
LOCK = threading.Lock()
MFA = __import__('queue').Queue()
STATE = {'state': 'idle', 'message': '连接佳明，开始了解你的日常。'}

def progress(message):
    STATE.update(state='working', message=message)

def request_mfa():
    STATE.update(state='mfa', message='请输入 Garmin 发来的验证码。')
    return MFA.get(timeout=300)

def sync(data):
    try:
        target = date.fromisoformat(data['date'])
        if target >= datetime.now(core.CHINA).date():
            raise ValueError('请选择昨天或更早的日期')
        _, output = core.fetch_report(target, data.get('email', ''), data.get('password', ''), request_mfa, progress)
        payload = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
        STATE.update(state='done', message='数据已更新', data=payload, date=target.isoformat())
    except Exception as error:
        STATE.update(state='error', message=core.error_message(error))
    finally:
        data.clear()
        LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, body, content_type='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))

    def do_GET(self):
        if self.headers.get('Host') != '127.0.0.1:8765':
            return self.respond(403, '{}')
        if self.path == '/':
            body = (ROOT / 'index.html').read_text(encoding='utf-8').replace('__SESSION_KEY__', KEY)
            return self.respond(200, body, 'text/html; charset=utf-8')
        if self.path == '/api/state' and self.headers.get('X-Session-Key') == KEY:
            return self.respond(200, json.dumps(STATE, ensure_ascii=False))
        self.respond(404, '{}')

    def do_POST(self):
        if self.headers.get('Host') != '127.0.0.1:8765' or self.headers.get('X-Session-Key') != KEY:
            return self.respond(403, '{}')
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length > 16384:
                return self.respond(413, '{}')
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/mfa':
                MFA.put(data['code'])
                STATE.update(state='working', message='正在验证…')
            elif self.path == '/api/sync':
                date.fromisoformat(data['date'])
                if not LOCK.acquire(blocking=False):
                    return self.respond(409, '{}')
                STATE.clear()
                progress('正在连接 Garmin…')
                threading.Thread(target=sync, args=(data,), daemon=True).start()
            else:
                return self.respond(404, '{}')
            self.respond(200, '{}')
        except (ValueError, KeyError, TypeError):
            self.respond(400, '{}')

if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    print('打开 http://127.0.0.1:8765，按 Ctrl+C 停止。')
    webbrowser.open('http://127.0.0.1:8765')
    server.serve_forever()
