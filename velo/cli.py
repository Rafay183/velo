"""velo command line: studio · run · new · export · docker · version"""
from __future__ import annotations

import argparse
import os
import runpy
import shutil
import sys

from . import __version__

TEMPLATE = '''import velo

app = velo.App("{name}", icon="⚡", accent="#6366f1")


@app.page("/", title="Home", icon="🏠")
def home(ui):
    ui.init(clicks=0)

    ui.title("{name}", "Built with Velo — edit app.py and save to see changes instantly.")

    name = ui.input("What's your name?", placeholder="Ada Lovelace")
    if name:
        ui.success(f"Nice to meet you, **{{name}}**!")

    def add():
        ui.state.clicks += 1

    with ui.row():
        ui.button("Click me", on_click=add, icon="✨")
        ui.badge(f"{{ui.state.clicks}} clicks")


if __name__ == "__main__":
    app.run()
'''

DOCKERFILE = '''FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 VELO_PROD=1 PORT={port}
WORKDIR /app
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
EXPOSE {port}
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'])"
CMD ["python", "-m", "velo", "run", "{file}", "--prod"]
'''


def _load_app(path: str):
    from . import core, server
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SystemExit(f"velo: file not found: {path}")
    if path.endswith(".json"):  # no-code app saved by Velo Studio
        from . import spec
        return spec.load(path), path
    sys.path.insert(0, os.path.dirname(path))
    n = len(core._APPS)
    server.SUPPRESS_RUN = True
    try:
        runpy.run_path(path, run_name="__velo__")
    finally:
        server.SUPPRESS_RUN = False
    apps = core._APPS[n:]
    if not apps:
        raise SystemExit("velo: no velo.App(...) found in " + path)
    return apps[-1], path


def cmd_run(a):
    from .server import serve
    app, path = _load_app(a.file)
    serve(app, a.host, a.port, reload=False if (a.no_reload or a.prod) else None, prod=a.prod or None,
          open_browser=a.open, main_file=path)


def cmd_new(a):
    os.makedirs(a.name, exist_ok=True)
    target = os.path.join(a.name, "app.py")
    if os.path.exists(target):
        raise SystemExit(f"velo: {target} already exists")
    title = os.path.basename(os.path.abspath(a.name)).replace("-", " ").replace("_", " ").title()
    with open(target, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(name=title))
    print(f"\n  ✓ Created {target}\n\n  cd {a.name}\n  velo run app.py\n")


def cmd_studio(a):
    from .studio import run_studio
    from .templates import TEMPLATES
    if a.template and a.template not in TEMPLATES:
        raise SystemExit(f"velo: unknown template {a.template!r}. Choose from: {', '.join(TEMPLATES)}")
    if a.template and os.path.exists(a.file) and not a.force:
        raise SystemExit(f"velo: {a.file} exists — add --force to overwrite it with the {a.template!r} template")
    run_studio(a.file, a.host, a.port, open_browser=not a.no_open, template=a.template)


def cmd_export(a):
    from . import codegen, spec
    if not a.file.endswith(".json"):
        raise SystemExit("velo export: expects a .velo.json file made with Velo Studio")
    code = codegen.to_python(spec.read_spec(a.file))
    out = a.output or os.path.join(os.path.dirname(os.path.abspath(a.file)), "app.py")
    if os.path.exists(out) and not a.force:
        raise SystemExit(f"velo export: {out} exists — add --force to overwrite")
    with open(out, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"\n  ✓ Wrote {out}\n\n  python {os.path.relpath(out)}\n")


def cmd_docker(a):
    root = os.path.dirname(os.path.abspath(a.file)) or "."
    pkg_src = os.path.dirname(os.path.abspath(__file__))
    vendored = os.path.join(root, "velo")
    if not os.path.exists(vendored):
        shutil.copytree(pkg_src, vendored, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        print("  ✓ vendored velo/ (pure stdlib — nothing to pip install)")
    with open(os.path.join(root, "Dockerfile"), "w", encoding="utf-8") as f:
        f.write(DOCKERFILE.format(port=a.port, file=os.path.basename(a.file)))
    with open(os.path.join(root, ".dockerignore"), "w", encoding="utf-8") as f:
        f.write("__pycache__/\n*.pyc\n.venv/\nvenv/\n.git/\n")
    print(f"  ✓ wrote Dockerfile and .dockerignore\n\n"
          f"  docker build -t myapp {root}\n  docker run -p {a.port}:{a.port} myapp\n\n"
          f"  Works as-is on Render, Railway, Fly.io, Cloud Run, Koyeb… (they set $PORT)\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="velo", description="Velo — reactive Python web apps, zero dependencies. "
                                 "No code? Run: velo studio")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="run an app (hot reload in dev)")
    r.add_argument("file")
    r.add_argument("--host")
    r.add_argument("--port", type=int)
    r.add_argument("--prod", action="store_true", help="production mode: 0.0.0.0, no reload, no tracebacks")
    r.add_argument("--no-reload", action="store_true")
    r.add_argument("--open", action="store_true", help="open the browser")
    r.set_defaults(fn=cmd_run)

    n = sub.add_parser("new", help="scaffold a new app")
    n.add_argument("name")
    n.set_defaults(fn=cmd_new)

    st = sub.add_parser("studio", help="open the drag & drop builder (no code needed)")
    st.add_argument("file", nargs="?", default="app.velo.json", help="app spec to edit (created if missing)")
    st.add_argument("--template", "-t", help="start from: blank, hello, dashboard, form, explorer, chatbot, calculator")
    st.add_argument("--force", action="store_true", help="overwrite an existing file with --template")
    st.add_argument("--host")
    st.add_argument("--port", type=int)
    st.add_argument("--no-open", action="store_true", help="don't open the browser")
    st.set_defaults(fn=cmd_studio)

    ex = sub.add_parser("export", help="turn a Studio app (.velo.json) into plain Python code")
    ex.add_argument("file", nargs="?", default="app.velo.json")
    ex.add_argument("-o", "--output", help="output file (default: app.py next to the spec)")
    ex.add_argument("--force", action="store_true")
    ex.set_defaults(fn=cmd_export)

    d = sub.add_parser("docker", help="generate a Dockerfile for deployment")
    d.add_argument("file", nargs="?", default="app.py")
    d.add_argument("--port", type=int, default=8000)
    d.set_defaults(fn=cmd_docker)

    v = sub.add_parser("version")
    v.set_defaults(fn=lambda a: print(f"velo {__version__}"))

    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return
    a.fn(a)


if __name__ == "__main__":
    main()
