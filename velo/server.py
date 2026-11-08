"""Velo server: stdlib HTTP + Server-Sent Events + state-preserving hot reload."""
from __future__ import annotations

import gzip
import html
import importlib
import json
import os
import queue
import runpy
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from . import core

SUPPRESS_RUN = False   # set while the CLI / reloader executes a user file
RUNNING = False
BOOT_ID = uuid.uuid4().hex[:12]
MAX_BODY = 50 * 1024 * 1024
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_static_cache: dict[str, tuple[bytes, bytes, str]] = {}


def _static(name: str):
    if name not in _static_cache:
        path = os.path.join(_STATIC_DIR, name)
        if not os.path.isfile(path) or os.path.dirname(os.path.abspath(path)) != _STATIC_DIR:
            return None
        with open(path, "rb") as f:
            raw = f.read()
        ctype = "text/css" if name.endswith(".css") else "application/javascript"
        _static_cache[name] = (raw, gzip.compress(raw, 6), ctype + "; charset=utf-8")
    return _static_cache[name]


def _favicon(icon: str) -> str:
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>{icon}</text></svg>"
    return "data:image/svg+xml," + svg.replace("#", "%23").replace("'", "%27").replace("<", "%3C").replace(">", "%3E")


def _index(app: "core.App") -> bytes:
    cfg = json.dumps({"theme": app.theme, "accent": app.accent, "wide": app.wide, "dev": not app.prod,
                      "title": app.title})
    t, ic = html.escape(app.title), html.escape(app.icon)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t}</title>
<link rel="icon" href="{_favicon(app.icon)}">
<link rel="stylesheet" href="/_velo/app.css?v={__version__}">
<script>window.VELO={cfg};(function(){{var t;try{{t=localStorage.getItem('velo:theme')}}catch(e){{}}
t=t||VELO.theme;if(t==='auto')t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
document.documentElement.dataset.theme=t;document.documentElement.style.setProperty('--accent',VELO.accent);}})()</script>
</head><body class="{'wide' if app.wide else ''}">
<div id="v-load"></div>
<div id="v-shell">
  <aside id="v-side">
    <div class="v-brand"><span class="v-logo">{ic}</span><span class="v-brand-t" id="v-brand-t">{t}</span></div>
    <nav id="v-nav"></nav>
    <div id="v-side-content" class="v-stack"></div>
    <div class="v-side-foot">Built with <b>Velo</b></div>
  </aside>
  <div id="v-scrim"></div>
  <div id="v-body">
    <header id="v-top">
      <button id="v-burger" aria-label="Menu">☰</button>
      <div id="v-top-t"></div>
      <div class="v-top-r"><span id="v-conn" class="ok" title="Connected"></span>
      <button id="v-theme" aria-label="Toggle theme" title="Toggle theme"></button></div>
    </header>
    <main id="v-main"><div id="v-root" class="v-stack">
      <div class="v-skel" style="height:44px;width:40%"></div><div class="v-skel" style="height:18px;width:70%"></div>
      <div class="v-skel" style="height:160px"></div></div></main>
  </div>
</div>
<div id="v-toasts"></div>
<div id="v-overlay" hidden><div class="v-ov-box"><div class="v-ov-h">⚠ Your app failed to reload</div>
<pre id="v-ov-pre"></pre><div class="v-ov-f">Fix the error and save — Velo reloads automatically.</div></div></div>
<script src="/_velo/app.js?v={__version__}" defer></script>
</body></html>""".encode()


class _Handler(BaseHTTPRequestHandler):
    server_version = f"Velo/{__version__}"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> "core.App":
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):
        if os.environ.get("VELO_ACCESS_LOG"):
            sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str, gz: bytes | None = None, cache: str = "no-store"):
        use_gz = "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 1024
        if use_gz and gz is None:
            gz = gzip.compress(body, 5)
        payload = gz if use_gz else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        if p.startswith("/_velo/"):
            st = _static(p[len("/_velo/"):])
            if st is None:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, st[0], st[2], st[1], cache="public, max-age=86400")
        if p == "/api/stream":
            return self._stream(parse_qs(url.query).get("sid", [""])[0])
        if p == "/health":
            return self._send(200, b'{"ok":true}', "application/json")
        if p == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return self._send(200, _index(self.app), "text/html; charset=utf-8")

    def do_POST(self):
        if urlparse(self.path).path != "/api/render":
            return self._send(404, b"not found", "text/plain")
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_BODY:
                return self._send(413, b"payload too large", "text/plain")
            req = json.loads(self.rfile.read(n) or b"{}")
            out = self.app.dispatch(str(req.get("sid", ""))[:64], str(req.get("path") or "/"), req.get("event"))
            body = json.dumps(out, separators=(",", ":"), ensure_ascii=False, default=str).encode()
            self._send(200, body, "application/json")
        except Exception:
            traceback.print_exc()
            self._send(500, b'{"error":"internal"}', "application/json")

    def _stream(self, sid: str):
        q: queue.Queue = queue.Queue()
        self.app._subscribe(sid, q)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self._event("hello", {"boot": BOOT_ID, "dev": not self.app.prod})
            while True:
                try:
                    ev, data = q.get(timeout=15)
                    self._event(ev, data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.app._unsubscribe(sid, q)

    def _event(self, name: str, data):
        self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# --------------------------------------------------------------------------- hot reload

_SKIP_DIRS = {"__pycache__", "venv", ".venv", "env", "node_modules", "site-packages", "build", "dist"}


class Reloader(threading.Thread):
    """Watches your project and swaps in new code *without* dropping sessions,
    so widget values and ui.state survive every save."""

    def __init__(self, app: "core.App", main_file: str):
        super().__init__(daemon=True, name="velo-reloader")
        self.app, self.main = app, os.path.abspath(main_file)
        self.root = os.path.dirname(self.main)
        self.mtimes = self._scan()

    def _scan(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS]
            if base.count(os.sep) - self.root.count(os.sep) > 3:
                dirs[:] = []
            for f in files:
                if f.endswith((".py", ".md", ".css", ".json", ".csv")):
                    path = os.path.join(base, f)
                    try:
                        out[path] = os.stat(path).st_mtime
                    except OSError:
                        pass
            if len(out) > 3000:
                break
        return out

    def run(self):
        while True:
            time.sleep(0.5)
            now = self._scan()
            if now != self.mtimes:
                changed = {p for p in set(now) | set(self.mtimes) if now.get(p) != self.mtimes.get(p)}
                self.mtimes = now
                time.sleep(0.05)
                self.reload(changed)

    def reload(self, changed: set[str]):
        global SUPPRESS_RUN
        t0 = time.perf_counter()
        for mod in list(sys.modules.values()):
            f = getattr(mod, "__file__", None)
            if f and os.path.abspath(f) in changed and os.path.abspath(f) != self.main:
                try:
                    importlib.reload(mod)
                except Exception:
                    pass
        n = len(core._APPS)
        SUPPRESS_RUN = True
        try:
            runpy.run_path(self.main, run_name="__velo__")
        except Exception:
            tb = traceback.format_exc()
            print(f"\n  \033[31m✗ reload failed\033[0m\n{tb}")
            self.app.broadcast("deverror", tb)
            return
        finally:
            SUPPRESS_RUN = False
        new = core._APPS[n:]
        del core._APPS[n:]
        if new:
            self.app._adopt(new[-1])
        names = ", ".join(sorted(os.path.relpath(c, self.root) for c in changed))
        print(f"  \033[32m↻ reloaded\033[0m {names} in {(time.perf_counter() - t0) * 1000:.0f} ms")
        self.app.broadcast("reload")


def serve(app: "core.App", host=None, port=None, *, reload=None, prod=None, open_browser=False, main_file=None):
    global RUNNING
    prod = bool(prod) if prod is not None else os.environ.get("VELO_PROD", "") not in ("", "0", "false")
    app.prod = prod
    reload = (not prod) if reload is None else reload
    host = host or os.environ.get("VELO_HOST") or ("0.0.0.0" if prod else "127.0.0.1")
    explicit = port is not None or "PORT" in os.environ
    port = int(port or os.environ.get("PORT") or 8000)

    httpd = None
    for p in ([port] if explicit else range(port, port + 20)):
        try:
            httpd = _Server((host, p), _Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"Velo: port {port} is busy. Try --port <n>.")
    httpd.app = app  # type: ignore[attr-defined]
    RUNNING = True

    if reload and main_file and os.path.isfile(main_file):
        Reloader(app, main_file).start()

    def _gc():
        while True:
            time.sleep(300)
            app.gc()

    threading.Thread(target=_gc, daemon=True, name="velo-gc").start()

    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"http://{shown}:{port}"
    mode = "production" if prod else ("dev · hot reload" if reload else "dev")
    print(f"\n  \033[1m⚡ Velo {__version__}\033[0m  ·  {app.title}  ·  {mode}\n"
          f"  → \033[36m{url}\033[0m   (Ctrl+C to stop)\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n  bye 👋")
    finally:
        httpd.server_close()
        RUNNING = False
