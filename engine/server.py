"""
The app's local engine process. The native shell starts it, reads the first
line it prints ("LISTENING <port> <token>") and opens a window on
http://127.0.0.1:<port>/#<token>.

  - Listens on 127.0.0.1 only, on a free port chosen at start.
  - Static files (the UI) are public; every /api/ call needs the per-launch
    token in an X-Token header, so other local programs can't drive it.
  - With --parent-pipe it exits as soon as its stdin closes, i.e. when the app
    that started it quits or crashes - no orphaned engine processes.

Run by hand for development:  python3 server.py --port 8520 --token dev
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api        # noqa: E402
from api import ApiError, ROUTES  # noqa: E402,F401
import backup     # noqa: E402
import engines    # noqa: E402
import patterns   # noqa: E402
import play       # noqa: E402
import repertoire  # noqa: E402
import store      # noqa: E402
import study      # noqa: E402
import system     # noqa: E402
# each module registers its /api/ routes on import
import routes.library, routes.review, routes.openings, routes.insights, routes.training, routes.coach  # noqa: E402,F401


def web_dir() -> str:
    for c in (os.environ.get("CHESS_REVIEW_WEB"),
              os.path.join(getattr(sys, "_MEIPASS", ""), "web"),
              os.path.join(HERE, "..", "web"),
              os.path.join(HERE, "web")):
        if c and os.path.isfile(os.path.join(c, "index.html")):
            return os.path.abspath(c)
    raise SystemExit("web/ folder not found")


class Handler(BaseHTTPRequestHandler):
    token = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; errors still go to stderr via traceback
        pass

    def _send(self, status: int, data: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _handle(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            if not secrets.compare_digest(self.headers.get("X-Token", ""), self.token):
                return self._json(403, {"error": "bad token"})
            body = None
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8"))
                except ValueError:
                    return self._json(400, {"error": "bad JSON"})
            q = urllib.parse.parse_qs(parsed.query)
            for m, rx, fn in ROUTES:
                if m != method:
                    continue
                mt = rx.match(path)
                if mt:
                    try:
                        kw = {k: urllib.parse.unquote(v) for k, v in mt.groupdict().items()}
                        return self._json(200, fn(body, q, **kw))
                    except ApiError as e:
                        return self._json(e.status, {"error": str(e)})
                    except (BrokenPipeError, ConnectionResetError):
                        return  # the page went away mid-request (navigation); nothing to answer
                    except Exception as e:
                        traceback.print_exc()
                        return self._json(500, {"error": f"{e.__class__.__name__}: {e}"})
            return self._json(404, {"error": "no such endpoint"})
        if method != "GET":
            return self._json(405, {"error": "method not allowed"})
        return self._static(path)

    def _static(self, path: str):
        root = web_dir()
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.abspath(os.path.join(root, rel))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")


def _watch_parent():
    try:
        while sys.stdin.read(1024):
            pass
    except Exception:
        pass
    _quiet(play.close_all)     # V10: lc0 of a game in progress
    os._exit(0)


def _quiet(fn):
    try:
        fn()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--token", default="")
    ap.add_argument("--parent-pipe", action="store_true", help="exit when stdin closes")
    a = ap.parse_args()
    for d in system.engine_dirs():  # apps started from Finder or a desktop menu get a minimal PATH
        if d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + d
    backup.apply_pending()           # a restore you chose in Settings happens now, before anything opens the database
    store.connect().close()
    store.refresh_grading()          # new grading rules: refresh the Library's cached counts
    store.compress_old_reviews()     # reviews are stored compressed since V5
    with store.db() as con:
        study.ensure_schema(con)
        need_lines = (con.execute("SELECT COUNT(*) FROM rep_lines").fetchone()[0] == 0
                      and con.execute("SELECT COUNT(*) FROM repertoire").fetchone()[0] > 0)
    if need_lines:                   # first start with line-by-line study: lines from the existing repertoire
        study.sync_all()
    repertoire.INDEXER.start()       # the opening tree of new games, in the background
    backup.auto_in_background()      # a weekly backup
    threading.Thread(target=lambda: _quiet(patterns.build), daemon=True, name="patterns").start()
    api.ANALYSER = engines.Analyser()
    Handler.token = a.token or secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    try:
        with open(os.path.join(store.data_dir(), "server.json"), "w") as f:
            json.dump({"port": port, "token": Handler.token, "pid": os.getpid(), "started": time.time()}, f)
    except OSError:
        pass
    print(f"LISTENING {port} {Handler.token}", flush=True)
    if a.parent_pipe:
        threading.Thread(target=_watch_parent, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
