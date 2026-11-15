
"""
FirePulse application server.

Serves:
    - Static dashboard from web/
    - JSON API for exact-area analysis
    - Dashboard navigation routes

Local usage:
    python serve.py
    python serve.py --demo
    python serve.py --port 8001

Cloud deployment:
    Uses PORT environment variable automatically.
    Binds to 0.0.0.0 for cloud accessibility.

Open locally:
    http://localhost:8000

Uses Python standard library for HTTP serving.
"""

import argparse
import json
import math
import os
import sys

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


# ============================================================
# CONFIGURATION
# ============================================================

MAX_BODY = 2_000_000

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"

DASHBOARD_ROUTES = {
    "/",
    "/index.html",
    "/overview",
    "/map",
    "/calendar",
    "/trends",
    "/advanced",
    "/about",
}

API_ROUTES = {
    "/api/area",
    "/api/points",
    "/api/quality",
}


# ============================================================
# JSON SERIALIZATION
# ============================================================

def _jsonable(obj):
    """Convert non-finite floating-point values into JSON null."""

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None

    if isinstance(obj, dict):
        return {
            key: _jsonable(value)
            for key, value in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [
            _jsonable(value)
            for value in obj
        ]

    return obj


# ============================================================
# DASHBOARD ENHANCEMENTS
# ============================================================

def _enhance_dashboard(html: str) -> str:
    """
    Inject shared dashboard navigation and styling
    without modifying the original index.html.
    """

    style = (
        '<link rel="stylesheet" '
        'href="/dashboard-enhancements.css">'
    )

    script = (
        '<script src="/dashboard-enhancements.js" '
        'defer></script>'
    )

    if "dashboard-enhancements.css" not in html:
        html = html.replace(
            "</head>",
            style + "</head>",
            1
        )

    if "dashboard-enhancements.js" not in html:
        html = html.replace(
            "</body>",
            script + "</body>",
            1
        )

    if (
        'id="baseNote"' not in html
        and '<div id="peaks"' in html
    ):
        html = html.replace(
            '<div id="peaks"',
            '<div id="baseNote" class="note" '
            'role="status"></div><div id="peaks"',
            1
        )

    return html


# ============================================================
# HTTP HANDLER
# ============================================================

def make_handler(ds, web_dir):

    from firepulse import api, spatial, area

    class Handler(SimpleHTTPRequestHandler):

        # ----------------------------------------------------
        # JSON RESPONSE
        # ----------------------------------------------------

        def _send(self, code, obj):

            body = json.dumps(
                _jsonable(obj),
                allow_nan=False
            ).encode("utf-8")

            self.send_response(code)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.send_header(
                "X-Content-Type-Options",
                "nosniff"
            )

            self.end_headers()

            self.wfile.write(body)

        # ----------------------------------------------------
        # GET REQUESTS
        # ----------------------------------------------------

        def do_GET(self):

            path = urlsplit(self.path).path

            # Health endpoint
            if path == "/api/health":

                return self._send(
                    200,
                    api.health(ds)
                )

            # Dashboard routes
            if path in DASHBOARD_ROUTES:

                index = Path(web_dir) / "index.html"

                if not index.is_file():

                    return self._send(
                        404,
                        {
                            "error": "Dashboard page not found."
                        }
                    )

                html = index.read_text(
                    encoding="utf-8"
                )

                html = _enhance_dashboard(html)

                body = html.encode("utf-8")

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )

                self.send_header(
                    "Content-Length",
                    str(len(body))
                )

                self.send_header(
                    "Cache-Control",
                    "no-cache"
                )

                self.send_header(
                    "X-Content-Type-Options",
                    "nosniff"
                )

                self.end_headers()

                self.wfile.write(body)

                return

            # Static files: CSS, JS, JSON, images, etc.
            return super().do_GET()

        # ----------------------------------------------------
        # POST REQUESTS
        # ----------------------------------------------------

        def do_POST(self):

            routes = {
                "/api/area": api.handle_area,
                "/api/points": api.handle_points,
                "/api/quality": api.handle_quality,
            }

            path = urlsplit(self.path).path

            if path not in routes:

                return self._send(
                    404,
                    {
                        "error": "Unknown endpoint."
                    }
                )

            # Validate request size
            try:

                n = int(
                    self.headers.get(
                        "Content-Length",
                        "0"
                    )
                )

                if n <= 0:

                    return self._send(
                        400,
                        {
                            "error": "Request body is missing."
                        }
                    )

                if n > MAX_BODY:

                    return self._send(
                        413,
                        {
                            "error": "Request body is too large."
                        }
                    )

                raw = self.rfile.read(n)

                payload = json.loads(raw)

                if not isinstance(payload, dict):

                    return self._send(
                        400,
                        {
                            "error": "JSON request must be an object."
                        }
                    )

            except (
                ValueError,
                UnicodeDecodeError
            ):

                return self._send(
                    400,
                    {
                        "error": "Request body is not valid JSON."
                    }
                )

            # Process API request
            try:

                result = routes[path](
                    ds,
                    payload
                )

                return self._send(
                    200,
                    result
                )

            except (
                spatial.GeometryError,
                area.AreaError
            ) as error:

                return self._send(
                    422,
                    {
                        "error": str(error)
                    }
                )

            except Exception as error:

                print(
                    "Internal FirePulse error:",
                    repr(error),
                    file=sys.stderr
                )

                return self._send(
                    500,
                    {
                        "error": (
                            "Internal error while "
                            "analysing the area."
                        )
                    }
                )

        # ----------------------------------------------------
        # LOGGING
        # ----------------------------------------------------

        def log_message(self, format, *args):

            # Keep normal HTTP requests quiet.
            pass

    return partial(
        Handler,
        directory=str(web_dir)
    )


# ============================================================
# APPLICATION STARTUP
# ============================================================

def main(argv=None):

    parser = argparse.ArgumentParser(
        description="FirePulse application server"
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use synthetic demonstration data."
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port. Defaults to PORT environment variable or 8000."
    )

    args = parser.parse_args(argv)

    # --------------------------------------------------------
    # DEMO MODE
    # --------------------------------------------------------

    if args.demo:

        os.environ["FIREPULSE_DEMO"] = "1"

    else:

        os.environ.pop(
            "FIREPULSE_DEMO",
            None
        )

    # --------------------------------------------------------
    # PORT CONFIGURATION
    # --------------------------------------------------------

    raw_port = (
        args.port
        if args.port is not None
        else os.environ.get("PORT", "8000")
    )

    try:

        port = int(raw_port)

        if not 1 <= port <= 65535:
            raise ValueError

    except ValueError:

        sys.exit(
            "Invalid server port. "
            "Use a port between 1 and 65535."
        )

    # --------------------------------------------------------
    # HOST CONFIGURATION
    # --------------------------------------------------------

    # Local development and cloud hosting both use this binding.
    host = "0.0.0.0"

    # --------------------------------------------------------
    # LOAD DATASET
    # --------------------------------------------------------

    from firepulse.area import Dataset, AreaError
    from firepulse.config import WEB_DATA, DEMO

    if not WEB_DIR.is_dir():

        sys.exit(
            f"Dashboard directory not found: {WEB_DIR}"
        )

    if not (WEB_DIR / "index.html").is_file():

        sys.exit(
            "web/index.html does not exist."
        )

    # --------------------------------------------------------
    # SYNTHETIC DATA SAFETY CHECK
    # --------------------------------------------------------

    meta_path = WEB_DATA / "meta.json"

    if not DEMO and meta_path.exists():

        try:

            meta = json.loads(
                meta_path.read_text(
                    encoding="utf-8"
                )
            )

        except (OSError, json.JSONDecodeError) as error:

            sys.exit(
                f"Cannot read dashboard metadata: {error}"
            )

        if meta.get("data_origin") == "SYNTHETIC_DEMO":

            sys.exit(
                "The generated dashboard data is synthetic. "
                "Run python run_pipeline.py with NASA FIRMS "
                "inputs before launching the real-data application."
            )

    # --------------------------------------------------------
    # INITIALIZE DATASET
    # --------------------------------------------------------

    try:

        print("Loading FirePulse dataset...")

        ds = Dataset()

    except AreaError as error:

        sys.exit(
            f"Cannot start FirePulse: {error}"
        )

    # --------------------------------------------------------
    # START SERVER
    # --------------------------------------------------------

    try:

        server = ThreadingHTTPServer(
            (host, port),
            make_handler(ds, WEB_DIR)
        )

    except OSError as error:

        sys.exit(
            f"Cannot start HTTP server: {error}"
        )

    print()
    print("=" * 55)
    print("              FIREPULSE SERVER")
    print("=" * 55)

    print(f"Host:       {host}")
    print(f"Port:       {port}")
    print(f"Local URL:  http://localhost:{port}")
    print(f"Data:       {ds.origin}")
    print(f"Detections: {len(ds.points):,}")
    print(f"Mode:       {'DEMO' if DEMO else 'REAL DATA'}")

    print("=" * 55)

    print("Server running. Press CTRL+C to stop.")
    print()

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print("\nShutting down FirePulse...")

    finally:

        server.server_close()

        print("FirePulse server stopped.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
