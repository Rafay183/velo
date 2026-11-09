"""Velo Studio — the drag & drop builder.

    velo studio                 # edits ./app.velo.json (created if missing)
    velo studio myapp.velo.json --port 7000

Two servers start, both pure stdlib:

* the **Studio** UI (default http://localhost:7860) — palette, canvas, inspector,
* a **live preview** of your app (Studio port + 1), running on the real Velo
  runtime. Every edit is autosaved to the JSON file and hot-swapped into the
  preview without losing what you typed into it.
"""
from __future__ import annotations

import gzip
import html
import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import __version__, codegen, core, server
from . import spec as S
from . import templates as T


def _rel(path: str) -> str:
    """os.path.relpath that never fails (Windows raises across drives, e.g. C: vs D:)."""
    try:
        return os.path.relpath(path)
    except ValueError:
        return path

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 20 * 1024 * 1024


class Project:
    """The spec file being edited, plus the live preview app."""

    def __init__(self, path: str, template: str | None = None):
        self.path = os.path.abspath(path)
        self.base = os.path.dirname(self.path)
        self.lock = threading.RLock()
        exists = os.path.exists(self.path)
        self.fresh = not exists and not template  # show the template gallery on first open
        if template or not exists:
            S.write_spec(self.path, T.get(template or "blank"))
        self.spec = S.normalize(S.read_spec(self.path))
        self.saved_at = time.time()
        self.preview = self._build(self.spec)
        self._hooks_mtime = self._hooks_stat()

    def _build(self, spec) -> S.SpecApp:
        n = len(core._APPS)
        app = S.SpecApp(spec, base_dir=self.base)
        del core._APPS[n:]
        return app

    def _hooks_stat(self):
        h = self.spec.get("hooks")
        if not h:
            return None
        p = h if os.path.isabs(h) else os.path.join(self.base, h)
        try:
            return os.stat(p).st_mtime
        except OSError:
            return None

    def save(self, spec: dict) -> dict:
        with self.lock:
            spec = S.normalize(spec)
            S.write_spec(self.path, spec)
            self.spec = spec
            self.saved_at = time.time()
            self.fresh = False
            self.refresh()
            return {"ok": True, "saved_at": self.saved_at, "problems": S.validate(spec), "spec": spec}

    def refresh(self):
        try:
            new = self._build(self.spec)
        except Exception:
            self.preview.broadcast("deverror", traceback.format_exc())
            return
        self.preview._adopt(new)
        self._hooks_mtime = self._hooks_stat()
        self.preview.broadcast("reload")

    def watch(self):
        """Reload when hooks.py or the JSON file is changed by another editor."""
        last_json = os.stat(self.path).st_mtime
        while True:
            time.sleep(1)
            try:
                m = self._hooks_stat()
                if m != self._hooks_mtime:
                    self.refresh()
                jm = os.stat(self.path).st_mtime
                if jm != last_json:
                    last_json = jm
                    if jm - self.saved_at > 1.5:  # not our own write
                        with self.lock:
                            self.spec = S.normalize(S.read_spec(self.path))
                            self.saved_at = jm
                            self.refresh()
            except Exception:
                pass


def _read_static(name: str):
    path = os.path.join(_STATIC, name)
    if os.path.dirname(os.path.abspath(path)) != _STATIC or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


class _StudioHandler(BaseHTTPRequestHandler):
    server_version = f"VeloStudio/{__version__}"
    protocol_version = "HTTP/1.1"

    @property
    def project(self) -> Project:
        return self.server.project  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):
        if os.environ.get("VELO_ACCESS_LOG"):
            sys.stderr.write("  studio %s\n" % (fmt % args))

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        gz = "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 1024
        payload = gzip.compress(body, 5) if gz else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        if p in ("/", "/index.html"):
            raw = _read_static("studio.html") or b""
            cfg = json.dumps({"version": __version__, "previewPort": self.server.preview_port})  # type: ignore[attr-defined]
            raw = raw.replace(b"__VELO_STUDIO_CFG__", cfg.encode()).replace(b"__V__", __version__.encode())
            return self._send(200, raw, "text/html; charset=utf-8")
        if p.startswith("/_studio/") or p.startswith("/_velo/"):
            name = p.split("/", 2)[2]
            raw = _read_static(name)
            if raw is None:
                return self._send(404, b"not found", "text/plain")
            ctype = "text/css; charset=utf-8" if name.endswith(".css") else "application/javascript; charset=utf-8"
            return self._send(200, raw, ctype)
        if p == "/api/state":
            pr = self.project
            with pr.lock:
                return self._json({"spec": pr.spec, "catalog": S.catalog(), "templates": T.listing(),
                                   "file": pr.path, "fresh": pr.fresh, "problems": S.validate(pr.spec),
                                   "version": __version__, "saved_at": pr.saved_at})
        if p == "/api/template":
            name = parse_qs(url.query).get("name", ["blank"])[0]
            if name not in T.TEMPLATES:
                return self._json({"error": "unknown template"}, 404)
            return self._json({"spec": T.get(name)})
        if p == "/api/export.py":
            code = codegen.to_python(self.project.spec).encode()
            return self._send(200, code, "text/x-python; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="app.py"'})
        if p == "/api/export.json":
            body = json.dumps(self.project.spec, indent=2, ensure_ascii=False).encode()
            name = os.path.basename(self.project.path)
            return self._send(200, body, "application/json; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{html.escape(name)}"'})
        if p == "/health":
            return self._json({"ok": True})
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > MAX_BODY:
                return self._json({"error": "too large"}, 413)
            body = json.loads(self.rfile.read(n) or b"{}")
            spec = body.get("spec")
            if not isinstance(spec, dict):
                return self._json({"error": "missing spec"}, 400)
            if p == "/api/save":
                out = self.project.save(spec)
                out.pop("spec", None)
                return self._json(out)
            if p == "/api/code":
                return self._json({"code": codegen.to_python(spec)})
            if p == "/api/validate":
                return self._json({"problems": S.validate(spec)})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def _bind(handler, host, port, explicit):
    for p in ([port] if explicit else range(port, port + 30, 2)):
        try:
            return server._Server((host, p), handler), p
        except OSError:
            continue
    raise SystemExit(f"velo studio: port {port} is busy. Try --port <n>.")


def run_studio(path: str = "app.velo.json", host: str | None = None, port: int | None = None, *,
               open_browser: bool = False, template: str | None = None):
    from . import _safe_console
    _safe_console()
    host = host or os.environ.get("VELO_HOST") or "127.0.0.1"
    explicit = port is not None
    port = int(port or 7860)
    if not path.endswith(".json"):
        path += ".velo.json" if not path.endswith(".velo") else ".json"
    project = Project(path, template)

    studio, port = _bind(_StudioHandler, host, port, explicit)
    preview, pport = _bind(server._Handler, host, port + 1, False)
    preview.app = project.preview  # type: ignore[attr-defined]
    studio.project = project  # type: ignore[attr-defined]
    studio.preview_port = pport  # type: ignore[attr-defined]
    server.RUNNING = True

    threading.Thread(target=preview.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True,
                     name="velo-preview").start()
    threading.Thread(target=project.watch, daemon=True, name="velo-studio-watch").start()

    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"http://{shown}:{port}"
    print(f"\n  \033[1m🎨 Velo Studio {__version__}\033[0m  ·  editing {_rel(project.path)}\n"
          f"  → Studio   \033[36m{url}\033[0m\n"
          f"  → Preview  \033[36mhttp://{shown}:{pport}\033[0m\n"
          f"  Run it later with:  velo run {_rel(project.path)}     (Ctrl+C to stop)\n"
          f"  \033[2mVelo by Muhammad Rafay Shaikh · Pakistan\033[0m\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        studio.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n  saved ✓  bye 👋")
    finally:
        studio.server_close()
        preview.server_close()
        server.RUNNING = False
