"""FirePulse local server: static site (web/) + JSON API for exact-area analysis.

    python serve.py                 # real data in data/
    python serve.py --demo          # synthetic data in data_demo/
    python serve.py --port 8001

Open http://localhost:8000 .  Binds to 127.0.0.1 only. Uses the Python standard library (Windows friendly).
"""
import argparse, json, os, sys, math
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

MAX_BODY = 2_000_000


def _jsonable(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def make_handler(ds, web_dir):
    from firepulse import api, spatial, area

    class Handler(SimpleHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(_jsonable(obj), allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/health":
                return self._send(200, api.health(ds))
            return super().do_GET()

        def do_POST(self):
            routes = {"/api/area": api.handle_area, "/api/points": api.handle_points, "/api/quality": api.handle_quality}
            if self.path not in routes:
                return self._send(404, {"error": "Unknown endpoint."})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n <= 0 or n > MAX_BODY:
                    return self._send(413 if n > MAX_BODY else 400, {"error": "Request body missing or too large."})
                payload = json.loads(self.rfile.read(n))
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": "Request body is not valid JSON."})
            try:
                return self._send(200, routes[self.path](ds, payload))
            except (spatial.GeometryError, area.AreaError) as e:
                return self._send(422, {"error": str(e)})
            except Exception as e:                                   # never leak a stack trace to the browser
                print("internal error:", repr(e), file=sys.stderr)
                return self._send(500, {"error": "Internal error while analysing the area."})

        def log_message(self, *a):
            pass

    return partial(Handler, directory=str(web_dir))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="use synthetic data in data_demo/")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    if a.demo:
        os.environ["FIREPULSE_DEMO"] = "1"
    else:
        os.environ.pop("FIREPULSE_DEMO", None)
    from firepulse.area import Dataset, AreaError
    from firepulse.config import WEB_DATA, DEMO
    if not DEMO and WEB_DATA.joinpath("meta.json").exists():
        meta = json.loads(WEB_DATA.joinpath("meta.json").read_text())
        if meta.get("data_origin") == "SYNTHETIC_DEMO":
            sys.exit("The generated web data is still synthetic. Run python run_pipeline.py to process the FIRMS files in data/raw/ first; use python serve.py --demo only for the synthetic demo.")
    try:
        ds = Dataset()
    except AreaError as e:
        sys.exit(f"Cannot start: {e}")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(ds, WEB_DATA.parent))
    print(f"FirePulse on http://localhost:{a.port}  (data origin: {ds.origin}, {len(ds.points)} detections)  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
