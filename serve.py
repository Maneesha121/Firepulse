"""Local server for the static dashboard and area-analysis API."""
import argparse
import json
import math
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_BODY = 2_000_000


def _jsonable(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def _enhance_dashboard(html: str) -> str:
    """Progressively enhance the existing dashboard while preserving the scientific analysis."""
    style = '<link rel="stylesheet" href="/dashboard-enhancements.css">'
    if 'dashboard-enhancements.css' not in html:
        html = html.replace('</head>', style + '</head>', 1)

    nav = (
        '<nav class="fp-nav" aria-label="Dashboard sections">'
        '<a href="#map">Hotspot map</a>'
        '<a href="#cal">Fire calendar</a>'
        '<a href="#anom">Anomalies</a>'
        '<a href="#sensorSec">Sensor comparison</a>'
        '<a href="#summary">Area statistics</a>'
        '</nav>'
    )
    if 'class="fp-nav"' not in html:
        html = html.replace('</header>', nav + '</header>', 1)

    if 'id="baseNote"' not in html and '<div id="peaks"' in html:
        html = html.replace('<div id="peaks"', '<div id="baseNote" class="note" role="status"></div><div id="peaks"', 1)
    return html


def make_handler(ds, web_dir):
    from firepulse import api, spatial, area

    class Handler(SimpleHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(_jsonable(obj), allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/health':
                return self._send(200, api.health(ds))
            if path in ('/', '/index.html'):
                index = Path(web_dir) / 'index.html'
                if not index.is_file():
                    return self._send(404, {'error': 'Dashboard page not found.'})
                body = _enhance_dashboard(index.read_text(encoding='utf-8')).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

        def do_POST(self):
            routes = {'/api/area': api.handle_area, '/api/points': api.handle_points, '/api/quality': api.handle_quality}
            path = urlsplit(self.path).path
            if path not in routes:
                return self._send(404, {'error': 'Unknown endpoint.'})
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n <= 0 or n > MAX_BODY:
                    return self._send(413 if n > MAX_BODY else 400, {'error': 'Request body missing or too large.'})
                payload = json.loads(self.rfile.read(n))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {'error': 'Request body is not valid JSON.'})
            try:
                return self._send(200, routes[path](ds, payload))
            except (spatial.GeometryError, area.AreaError) as e:
                return self._send(422, {'error': str(e)})
            except Exception as e:
                print('internal error:', repr(e), file=sys.stderr)
                return self._send(500, {'error': 'Internal error while analysing the area.'})

        def log_message(self, *args):
            pass

    return partial(Handler, directory=str(web_dir))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo', action='store_true', help='use synthetic data in data_demo/')
    ap.add_argument('--port', type=int, default=8000)
    a = ap.parse_args(argv)
    if a.demo:
        os.environ['FIREPULSE_DEMO'] = '1'
    else:
        os.environ.pop('FIREPULSE_DEMO', None)

    from firepulse.area import Dataset, AreaError
    from firepulse.config import WEB_DATA, DEMO
    if not DEMO and WEB_DATA.joinpath('meta.json').exists():
        meta = json.loads(WEB_DATA.joinpath('meta.json').read_text())
        if meta.get('data_origin') == 'SYNTHETIC_DEMO':
            sys.exit('The generated web data is still synthetic. Run python run_pipeline.py with NASA FIRMS inputs first; use python serve.py --demo only for the synthetic demo.')
    try:
        ds = Dataset()
    except AreaError as e:
        sys.exit(f'Cannot start: {e}')

    srv = ThreadingHTTPServer(('127.0.0.1', a.port), make_handler(ds, WEB_DATA.parent))
    print(f'FirePulse on http://localhost:{a.port}  (data origin: {ds.origin}, {len(ds.points)} detections)  Ctrl+C to stop')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
