"""Small, single-process interview demo behind Render's HTTPS proxy.

The local owner configuration endpoint is never exposed. No .env is packaged.
Limits are per process; provider balance is the monetary boundary.
"""
import os
import secrets
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer
import local_server as app

app.KEY = os.environ.get('DEEPSEEK_API_KEY', '').strip()
ACCESS = os.environ.get('DEMO_ACCESS_CODE', '').strip()
HOST = os.environ.get('RENDER_EXTERNAL_HOSTNAME', os.environ.get('PUBLIC_HOST', '')).lower()
LIMIT = max(1, min(30, int(os.environ.get('MODEL_CALL_LIMIT', '30'))))
PAID = 0
GUARD = threading.Lock()
RATE = {}
original_fetch = app.fetch_json

def guarded_fetch(url, data=None, headers=None):
    global PAID
    if urllib.parse.urlparse(url).hostname == 'api.deepseek.com':
        with GUARD:
            if PAID >= LIMIT:
                raise ValueError('本轮体验额度已用完，请联系作者。')
            PAID += 1
    return original_fetch(url, data, headers)

app.fetch_json = guarded_fetch

class CloudHandler(app.Handler):
    def valid_host(self):
        return bool(HOST) and self.headers.get('Host', '').lower() == HOST

    def valid_origin(self):
        return self.headers.get('Origin') == 'https://' + HOST

    def authorized(self):
        return (super().authorized() and bool(ACCESS)
                and secrets.compare_digest(self.headers.get('X-Demo-Code', '').encode(), ACCESS.encode()))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/healthz':
            return self.reply({'ok': True})
        if not self.valid_host():
            return self.reply({'error': '请使用网站的正式地址。'}, 403)
        if path == '/api/status':
            return self.reply({'configured': bool(app.KEY and ACCESS), 'token': app.TOKEN,
                               'calls': PAID, 'limit': LIMIT, 'mode': 'cloud', 'accessRequired': True})
        if path == '/api/visual-reference':
            return self.reply({'error': '不存在'}, 404)
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path not in ('/api/generate', '/api/upload-reference'):
            return self.reply({'error': '不存在'}, 404)
        if not self.authorized():
            return self.reply({'error': '请填写正确的体验码。'}, 403)
        if not app.KEY:
            return self.reply({'error': '网站暂未开放生成，请稍后再来。'}, 503)
        # A short in-memory window also bounds repeated failed uploads/requests.
        ip = self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[0]
        now = time.monotonic()
        with GUARD:
            for key in list(RATE):
                if now - RATE[key][0] >= 3600:
                    del RATE[key]
            start, count = RATE.get(ip, (now, 0))
            if count >= 20:
                return self.reply({'error': '体验次数较多，请稍后再试。'}, 429)
            RATE[ip] = (start, count + 1)
        return super().do_POST()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    server = ThreadingHTTPServer(('0.0.0.0', port), CloudHandler)
    print('Paper Muse demo started; credentials are not logged.', flush=True)
    server.serve_forever()
