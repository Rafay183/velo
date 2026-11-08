"""Run:  python -m pytest -q   (or: python tests/test_velo.py)"""
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import velo  # noqa: E402
from velo import server  # noqa: E402
from velo.markdown import render as md  # noqa: E402


def make_app():
    app = velo.App("Test")

    @app.page("/")
    def home(ui):
        ui.init(n=0)

        def inc(step=1):
            ui.state.n += step

        ui.button("Add", on_click=inc, args=(2,))
        ui.text(f"n={ui.state.n}")
        v = ui.slider("S", 0, 10, 5)
        c = ui.select("C", [1, 2, 3], value=2)
        m = ui.multiselect("M", ["a", "b", "c"], value=["a"])
        t = ui.toggle("T")
        ui.text(f"{v}|{c!r}|{m}|{t}")
        if ui.button("Boom"):
            raise RuntimeError("kaboom")
        msg = ui.chat_input("say")
        if msg:
            ui.text(f"got:{msg}")

    @app.page("/two", title="Two")
    def two(ui):
        ui.title("Page two")
    return app


def texts(out):
    return [n["p"]["text"] for n in out["tree"] if n["t"] == "text"]


def test_initial_render_and_nav():
    out = make_app().dispatch("s", "/", None)
    assert texts(out)[:2] == ["n=0", "5|2|['a']|False"]
    assert [p["path"] for p in out["nav"]] == ["/", "/two"]


def test_callbacks_and_values():
    app = make_app()
    app.dispatch("s", "/", None)
    app.dispatch("s", "/", {"type": "click", "k": "button:Add"})
    app.dispatch("s", "/", {"type": "set", "k": "slider:S", "v": 99})       # clamped to max
    app.dispatch("s", "/", {"type": "set", "k": "select:C", "v": 2})        # index -> option
    app.dispatch("s", "/", {"type": "set", "k": "multiselect:M", "v": [1, 2]})
    out = app.dispatch("s", "/", {"type": "set", "k": "toggle:T", "v": True})
    assert texts(out)[:2] == ["n=2", "10|3|['b', 'c']|True"]


def test_sessions_are_isolated():
    app = make_app()
    app.dispatch("a", "/", None)
    app.dispatch("a", "/", {"type": "click", "k": "button:Add"})
    assert texts(app.dispatch("b", "/", None))[0] == "n=0"


def test_invalid_values_ignored():
    app = make_app()
    app.dispatch("s", "/", None)
    out = app.dispatch("s", "/", {"type": "set", "k": "select:C", "v": 99})
    assert "5|2|" in texts(out)[1]


def test_errors_are_contained():
    app = make_app()
    app.dispatch("s", "/", None)
    out = app.dispatch("s", "/", {"type": "click", "k": "button:Boom"})
    err = [n for n in out["tree"] if n["t"] == "error"]
    assert err and "kaboom" in err[0]["p"]["text"]
    assert "velo/core.py" not in err[0]["p"]["tb"]  # framework frames hidden


def test_chat_input_returns_once():
    app = make_app()
    app.dispatch("s", "/", None)
    out = app.dispatch("s", "/", {"type": "submit", "k": "chat_input:say", "v": "hi"})
    assert "got:hi" in texts(out)
    assert "got:hi" not in texts(app.dispatch("s", "/", None))


def test_404():
    out = make_app().dispatch("s", "/nope", None)
    assert out["tree"][0]["t"] == "notfound"


def test_cache():
    calls = []

    @velo.cache(ttl=60)
    def f(x):
        calls.append(x)
        return x * 2

    assert f(2) == 4 and f(2) == 4 and f(3) == 6
    assert calls == [2, 3]


def test_tabular_shapes():
    from velo.core import _tabular, _chart_data
    assert _tabular([{"a": 1}, {"a": 2, "b": 3}]) == (["a", "b"], [[1, None], [2, 3]])
    assert _tabular({"x": [1, 2], "y": [3, 4]}) == (["x", "y"], [[1, 3], [2, 4]])
    xs, s = _chart_data({"day": ["a", "b"], "v": [1, 2]})
    assert xs == ["a", "b"] and s[0]["name"] == "v"
    try:
        import pandas as pd
        cols, rows = _tabular(pd.DataFrame({"a": [1, 2], "b": [0.5, float("nan")]}))
        assert cols == ["a", "b"] and rows[1] == [2, None]
    except ImportError:
        pass


def test_markdown_escapes_html():
    out = md("**hi** <script>x</script> [l](javascript:alert(1))")
    assert "<strong>hi</strong>" in out and "<script>" not in out and "javascript:" not in out


def test_http_roundtrip():
    app = make_app()
    httpd = server._Server(("127.0.0.1", 0), server._Handler)
    httpd.app = app
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert b"window.VELO" in urllib.request.urlopen(base + "/").read()
        assert urllib.request.urlopen(base + "/_velo/app.js").status == 200
        assert json.loads(urllib.request.urlopen(base + "/health").read())["ok"]
        req = urllib.request.Request(base + "/api/render", data=json.dumps(
            {"sid": "h", "path": "/", "event": {"type": "click", "k": "button:Add"}}).encode())
        app.dispatch("h", "/", None)
        out = json.loads(urllib.request.urlopen(req).read())
        assert texts(out)[0] == "n=2"
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    t0 = time.time()
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print("✓", fn.__name__)
    print(f"\n{len(fns)} passed in {time.time() - t0:.2f}s")
