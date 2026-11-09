"""No-code layer: spec runtime, expressions, exporter, templates, Studio server.

Run:  python -m pytest -q   (or: python tests/test_studio.py)
"""
import json
import os
import runpy
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import velo  # noqa: E402
from velo import codegen, core, server  # noqa: E402
from velo import spec as S  # noqa: E402
from velo import templates as T  # noqa: E402


def kinds(tree):
    out = []
    for n in tree:
        out.append(n["t"])
        out += kinds(n.get("c", []))
    return out


def find(tree, t):
    for n in tree:
        if n["t"] == t:
            return n
        r = find(n.get("c", []), t)
        if r:
            return r
    return None


def counter_spec():
    return {"state": {"count": 0, "items": []}, "pages": [{"path": "/", "body": [
        S.make_node("title", text="Hi {name or 'there'}", subtitle="count={count}"),
        S.make_node("input", name="name"),
        S.make_node("button", label="Add", actions=[
            {"do": "set", "var": "count", "value": "=count + 1"},
            {"do": "append", "var": "items", "value": "={'who': name}", "if": "name"},
            {"do": "toast", "text": "Hello {name}", "kind": "success"}]),
        {**S.make_node("table", data="=items"), "show_if": "len(items) > 0"},
    ]}]}


# ---------------------------------------------------------------- expressions
def test_expressions_and_templates():
    env = {"price": 1234.5, "qty": 2, "name": "Ada"}
    assert S.evaluate("price * qty", env) == 2469.0
    assert S.render_template("Total {price * qty:,.2f} for {name}", env) == "Total 2,469.00 for Ada"
    assert S.render_template("{{literal}} braces", env) == "{literal} braces"
    assert S.render_template("=qty + 1", env) == "3"
    assert S.literal("5", env) == 5 and S.literal("true", env) is True and S.literal("Hi {name}", env) == "Hi Ada"
    assert S.evaluate("[r['a'] for r in rows if r['a'] > 1]", {"rows": [{"a": 1}, {"a": 2}]}) == [2]


def test_sandbox_blocks_escapes():
    for bad in ["().__class__", "__import__('os')", "open('x')", "x.__dict__", "2 ** 99999", "lambda: 1"]:
        try:
            S.evaluate(bad, {"x": 1})
        except S.ExprError:
            continue
        raise AssertionError(f"not blocked: {bad}")


def test_data_helpers():
    rows = S.h_csv("a,b\n1,x\n2,y\n3,x")
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "x"}]
    assert S.h_group(rows, "b", "a") == [{"b": "x", "a": 4}, {"b": "y", "a": 2}]
    assert S.h_where(rows, "b", "x") == [rows[0], rows[2]]
    assert S.h_columns(rows) == ["a", "b"]
    assert S.h_to_csv(rows).splitlines()[0] == "a,b"


# ---------------------------------------------------------------- runtime
def test_spec_app_actions_state_and_visibility():
    app = velo.load(counter_spec())
    out = app.dispatch("s", "/", None)
    assert find(out["tree"], "title")["p"]["text"] == "Hi there"
    assert find(out["tree"], "table") is None  # hidden by show_if
    btn = find(out["tree"], "button")["k"]
    app.dispatch("s", "/", {"type": "set", "k": "k:name", "v": "Ada"})
    out = app.dispatch("s", "/", {"type": "click", "k": btn})
    assert find(out["tree"], "title")["p"] == {"text": "Hi Ada", "sub": "count=1"}
    assert out["toasts"] == [{"text": "Hello Ada", "kind": "success"}]
    assert find(out["tree"], "table")["p"]["rows"] == [["Ada"]]


def test_navigate_and_reset_from_actions():
    sp = {"pages": [
        {"path": "/", "body": [S.make_node("input", name="q"), S.make_node("button", actions=[
            {"do": "reset", "vars": "q"}, {"do": "navigate", "to": "/two"}])]},
        {"path": "/two", "title": "Two", "body": [S.make_node("text", text="page two")]}]}
    app = velo.load(sp)
    out = app.dispatch("s", "/", None)
    app.dispatch("s", "/", {"type": "set", "k": "k:q", "v": "hello"})
    out = app.dispatch("s", "/", {"type": "click", "k": find(out["tree"], "button")["k"]})
    assert out["navigate"] == "/two"
    assert app.sessions["s"].values.get("k:q") in (None, "")


def test_chat_component_and_hooks():
    sp = {"pages": [{"path": "/", "body": [S.make_node("chat", name="c", greeting="", hook="bot")]}]}
    app = velo.load(sp)

    @app.action("bot")
    def bot(ctx, message):
        return message.upper()

    app.dispatch("s", "/", None)
    out = app.dispatch("s", "/", {"type": "submit", "k": "k:c::in", "v": "hi"})
    assert [n["p"]["html"] for n in out["tree"] if n["t"] == "chat"] == ["<p>hi</p>", "<p>HI</p>"]


def test_bad_expression_shows_error_not_crash():
    sp = {"pages": [{"path": "/", "body": [S.make_node("table", data="=nope + 1"), S.make_node("text", text="still here")]}]}
    out = velo.load(sp).dispatch("s", "/", None)
    assert find(out["tree"], "alert")["p"]["kind"] == "error" and find(out["tree"], "text")["p"]["text"] == "still here"


def test_validation():
    sp = counter_spec()
    assert S.validate(sp) == []
    sp["pages"][0]["body"].append(S.make_node("input", name="name"))       # duplicate variable
    sp["pages"][0]["body"].append(S.make_node("text", text="{missing}"))  # unknown variable
    sp["pages"][0]["body"].append(S.make_node("text", text="=1 +"))       # syntax error
    msgs = [p["msg"] for p in S.validate(sp)]
    assert any("used twice" in m for m in msgs)
    assert any("unknown variable `missing`" in m for m in msgs)
    assert any("syntax error" in m for m in msgs)


def test_normalize_keeps_content_when_slots_shrink():
    col = S.make_node("columns", widths="1,1,1")
    col["slots"] = [[S.make_node("text")], [S.make_node("text")], [S.make_node("badge")]]
    col["props"]["widths"] = "1,1"
    out = S.normalize({"pages": [{"path": "/", "body": [col]}]})
    slots = out["pages"][0]["body"][0]["slots"]
    assert len(slots) == 2 and [n["type"] for n in slots[1]] == ["text", "badge"]


# ---------------------------------------------------------------- templates + exporter
def _exec_python(code):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "app.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    n = len(core._APPS)
    server.SUPPRESS_RUN = True
    try:
        runpy.run_path(path, run_name="__velo__")
    finally:
        server.SUPPRESS_RUN = False
    app = core._APPS[-1]
    del core._APPS[n:]
    return app


def test_every_template_runs_and_exports_equivalent_python():
    for name in T.TEMPLATES:
        sp = T.get(name)
        assert S.validate(sp) == [], name
        a = velo.load(sp)
        b = _exec_python(codegen.to_python(sp))
        for page in sp["pages"]:
            ra, rb = a.dispatch("x", page["path"], None), b.dispatch("x", page["path"], None)
            assert "error" not in kinds(ra["tree"] + ra["side"]), (name, page["path"])
            assert "error" not in kinds(rb["tree"] + rb["side"]), (name, page["path"], rb["tree"])
            ka, kb = kinds(ra["tree"] + ra["side"]), kinds(rb["tree"] + rb["side"])
            if name != "form":  # the form shows "no data yet" text where Python shows an empty chart
                assert ka == kb, (name, ka, kb)


def test_exported_actions_behave_like_the_spec():
    app = _exec_python(codegen.to_python(counter_spec()))
    out = app.dispatch("s", "/", None)
    app.dispatch("s", "/", {"type": "set", "k": "k:name", "v": "Ada"})
    out = app.dispatch("s", "/", {"type": "click", "k": find(out["tree"], "button")["k"]})
    assert find(out["tree"], "title")["p"] == {"text": "Hi Ada", "sub": "count=1"}
    assert find(out["tree"], "table")["p"]["rows"] == [["Ada"]]


def test_cli_run_accepts_json():
    from velo import cli
    d = tempfile.mkdtemp()
    path = os.path.join(d, "app.velo.json")
    S.write_spec(path, T.get("hello"))
    app, _ = cli._load_app(path)
    assert isinstance(app, S.SpecApp) and app.title == "Hello Velo"
    cli.main(["export", path, "-o", os.path.join(d, "app.py")])
    assert "import velo" in open(os.path.join(d, "app.py"), encoding="utf-8").read()


# ---------------------------------------------------------------- author credit
def test_author_credit_everywhere():
    assert velo.__author__ == "Muhammad Rafay Shaikh" and velo.__country__ == "Pakistan"
    page = server._index(velo.App("X")).decode()
    assert "Muhammad Rafay Shaikh" in page and "Pakistan" in page and 'name="generator"' in page
    assert "Muhammad Rafay Shaikh" in codegen.to_python(T.get("blank"))
    assert "Muhammad Rafay Shaikh" in S.normalize({})["generator"]
    from velo import studio
    html = studio._read_static("studio.html").decode()
    assert "Muhammad Rafay Shaikh" in html and "Pakistan" in html


# ---------------------------------------------------------------- studio server
def test_studio_http_api():
    from velo import studio
    d = tempfile.mkdtemp()
    proj = studio.Project(os.path.join(d, "app.velo.json"))
    assert proj.fresh and os.path.exists(proj.path)
    httpd = server._Server(("127.0.0.1", 0), studio._StudioHandler)
    httpd.project, httpd.preview_port = proj, 1
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())

    try:
        assert b"Velo Studio" in urllib.request.urlopen(base + "/").read()
        for asset in ("/_studio/studio.js", "/_studio/studio.css", "/_velo/app.css"):
            assert urllib.request.urlopen(base + asset).status == 200
        st = json.loads(urllib.request.urlopen(base + "/api/state").read())
        assert "button" in st["catalog"]["components"] and len(st["templates"]) == len(T.TEMPLATES)
        sp = json.loads(urllib.request.urlopen(base + "/api/template?name=form").read())["spec"]
        res = post("/api/save", {"spec": sp})
        assert res["ok"] and res["problems"] == []
        assert S.read_spec(proj.path)["app"]["title"] == "Registration"
        assert not proj.fresh
        assert proj.preview.dispatch("p", "/", None)["app"]["title"] == "Registration"  # hot-swapped
        assert "def register(ui):" in post("/api/code", {"spec": sp})["code"]
        assert b"import velo" in urllib.request.urlopen(base + "/api/export.py").read()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    velo._safe_console()
    t0 = time.time()
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("✓", fn.__name__)
    print(f"\n{len(fns)} passed in {time.time() - t0:.2f}s")
