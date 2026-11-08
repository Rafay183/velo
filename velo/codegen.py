"""Export a ``.velo.json`` spec as a clean, idiomatic Velo Python app ("eject").

    velo export app.velo.json -o app.py

The output is meant to be read and edited by humans: widgets become local
variables, button actions become small callback functions, templates become
f-strings.
"""
from __future__ import annotations

import ast
import keyword
import re

from . import spec as S

_HELPER_NAMES = ["csv", "col", "mean", "where", "columns", "group", "to_csv", "as_rows", "as_text", "fmt"]


def _slug(s: str, fallback: str = "page") -> str:
    s = re.sub(r"\W+", "_", str(s).lower()).strip("_")
    if not s or s[0].isdigit():
        s = f"{fallback}_{s}" if s else fallback
    return s + "_" if keyword.iskeyword(s) else s


_DICT_ATTRS = set(dir(dict))


def _st(name: str) -> str:
    """ui.state.x — or ui.state['x'] when x collides with a dict method (items, keys, …)."""
    return f"ui.state[{name!r}]" if name in _DICT_ATTRS else f"ui.state.{name}"


def _qs(lit: str) -> str:
    """Escape literal text for inside a double-quoted (f-)string."""
    return lit.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


class _Names(ast.NodeTransformer):
    def __init__(self, gen: "_Gen"):
        self.gen = gen
        self.bound: set[str] = set()

    def visit_comprehension(self, node):
        for n in ast.walk(node.target):
            if isinstance(n, ast.Name):
                self.bound.add(n.id)
        return self.generic_visit(node)

    def visit_Name(self, node):
        if not isinstance(node.ctx, ast.Load) or node.id in self.bound:
            return node
        new = self.gen.ref(node.id)
        return ast.copy_location(ast.parse(new, mode="eval").body, node) if new != node.id else node


class _Gen:
    def __init__(self, spec: dict):
        self.spec = S.normalize(spec)
        self.vars = S.variables(self.spec)
        self.state = set(self.spec["state"])
        self.chats = {k for k, v in self.vars.items() if v.get("type") == "chat"}
        self.widgets = {k for k, v in self.vars.items() if v["kind"] == "widget" and k not in self.chats}
        self.lines: list[str] = []
        self.ind = 1
        self.locals: set[str] = set()
        self.cond = 0          # >0 while inside an `if show_if:` block
        self.in_cb = False     # inside a callback -> always read fresh values
        self.counter: dict[str, int] = {}
        self.uses_helpers: set[str] = set()
        self.uses_hooks = False
        self.consts: list[str] = []
        self.extra_locals: set[str] = set()

    # ---- expressions -----------------------------------------------------
    def uid(self, base: str) -> str:
        while True:
            n = self.counter.get(base, 0) + 1
            self.counter[base] = n
            name = f"{base}_{n}" if n > 1 else base
            if name not in self.vars and name not in ("ui", "app", "velo", "message", "reply", "m"):
                return name

    def ref(self, name: str) -> str:
        if name in self.extra_locals:
            return name
        if name == "state":
            return "dict(ui.state)"
        if name in self.state or name in self.chats:
            return _st(name)
        if name in self.widgets:
            if name in self.locals and not self.in_cb:
                return name
            d = self.vars[name]["default"]
            return f"ui.get({name!r})" if d is None else f"ui.get({name!r}, {d!r})"
        if name in _HELPER_NAMES:
            self.uses_helpers.add(name)
        return name

    def expr(self, src: str) -> str:
        try:
            tree = ast.parse(src.strip(), mode="eval")
        except SyntaxError:
            return repr(src) + "  # ⚠ invalid expression"
        tree = _Names(self).visit(tree)
        return ast.unparse(tree)

    def template(self, text) -> str:
        if not isinstance(text, str):
            return repr(text)
        if S.is_expr(text):
            return f"str({self.expr(text[1:])})"
        parts = S.template_parts(text)
        if not any(e for _, e, _ in parts):
            return repr("".join(lit for lit, _, _ in parts))
        exprs = [(self.expr(e) if e else None) for _, e, _ in parts]
        if any(e and ('"' in e or "\\" in e) for e in exprs):  # pre-3.12 f-strings can't hold these
            pieces = []
            for (lit, _, spec), e in zip(parts, exprs):
                if lit:
                    pieces.append(repr(lit))
                if e:
                    pieces.append(f"format({e}, {spec!r})" if spec else f"str({e})")
            return " + ".join(pieces)
        out = []
        for (lit, _, spec), e in zip(parts, exprs):
            out.append(_qs(lit).replace("{", "{{").replace("}", "}}"))
            if e:
                out.append("{" + e + (":" + spec if spec else "") + "}")
        return 'f"' + "".join(out) + '"'

    def value(self, v) -> str:
        """A prop: =expr -> code, text -> template, other -> literal."""
        if S.is_expr(v):
            return self.expr(v[1:])
        if isinstance(v, str):
            return self.template(v)
        return repr(v)

    def literal(self, v) -> str:
        if S.is_expr(v):
            return self.expr(v[1:])
        if isinstance(v, str):
            s = v.strip()
            if s.lower() in ("true", "yes"):
                return "True"
            if s.lower() in ("false", "no"):
                return "False"
            n = S._num(s)
            if isinstance(n, (int, float)) and s:
                return repr(n)
            return self.template(v)
        return repr(v)

    def number(self, v, default=None):
        if v is None or v == "":
            return repr(default) if default is not None else None
        if S.is_expr(v):
            return self.expr(v[1:])
        n = S._num(v) if isinstance(v, str) else v
        return repr(n) if isinstance(n, (int, float)) else (repr(default) if default is not None else None)

    # ---- emit ------------------------------------------------------------
    def emit(self, line: str = ""):
        self.lines.append(("    " * self.ind + line) if line else "")

    def call(self, fn: str, *args, **kw) -> str:
        a = [x for x in args if x is not None]
        a += [f"{k}={v}" for k, v in kw.items() if v is not None]
        return f"{fn}({', '.join(a)})"

    def block(self, header: str, nodes):
        self.emit(header)
        self.ind += 1
        before = len(self.lines)
        self.nodes(nodes)
        if len(self.lines) == before:
            self.emit("pass")
        self.ind -= 1

    def nodes(self, nodes):
        for n in nodes or []:
            self.node(n)

    def node(self, n):
        cond = n.get("show_if")
        if isinstance(cond, str) and cond.strip():
            self.emit(f"if {self.expr(cond.strip().lstrip('='))}:")
            self.ind += 1
            self.cond += 1
            self._node(n)
            self.cond -= 1
            self.ind -= 1
        else:
            self._node(n)

    def _txt(self, p, k):
        v = p.get(k)
        return None if v in (None, "") else self.template(v)

    def _bind(self, p, expr: str):
        name = p.get("name")
        if name and name.isidentifier():
            self.emit(f"{name} = {expr}")
            if not self.cond:
                self.locals.add(name)
        else:
            self.emit(expr)

    def _node(self, n):
        t, p = n.get("type"), n.get("props") or {}
        tx = lambda k: self._txt(p, k)  # noqa: E731
        key = repr(p.get("name")) if p.get("name") else None
        if t == "title":
            self.emit(self.call("ui.title", tx("text") or "''", tx("subtitle")))
        elif t in ("header", "subheader", "markdown", "caption"):
            self.emit(self.call(f"ui.{t}", tx("text") or "''"))
        elif t == "text":
            self.emit(self.call("ui.text", tx("text") or "''", muted="True" if p.get("muted") else None))
        elif t == "badge":
            self.emit(self.call("ui.badge", tx("text") or "''", repr(p.get("kind") or "accent")))
        elif t == "link":
            self.emit(self.call("ui.link", tx("text") or "''", tx("url") or "'#'"))
        elif t == "code":
            self.emit(self.call("ui.code", repr(str(p.get("code") or "")), repr(p.get("lang") or "python")))
        elif t == "image":
            self.emit(self.call("ui.image", self.value(p.get("src") or ""), caption=tx("caption"),
                                width=self.number(p.get("width"))))
        elif t == "divider":
            self.emit("ui.divider()")
        elif t == "space":
            self.emit(f"ui.space({self.number(p.get('height'), 24)})")
        elif t == "alert":
            fn = {"info": "info", "success": "success", "warning": "warning", "error": "error"}.get(p.get("kind"), "info")
            self.emit(self.call(f"ui.{fn}", tx("text") or "''", title=tx("title")))
        elif t == "metric":
            d = p.get("delta")
            self.emit(self.call("ui.metric", tx("label") or "''", self.value(p.get("value") if p.get("value") not in (None, "") else "—"),
                                self.value(d) if d not in (None, "") else None, help=tx("help"),
                                inverse="True" if p.get("inverse") else None))
        elif t == "progress":
            v = self.number(p.get("value"), 0) or "0"
            self.emit(self.call("ui.progress", f"{v} / 100", tx("label")))
        elif t == "input":
            self._bind(p, self.call("ui.input", tx("label") or "''", repr(p.get("value")) if p.get("value") else None, key=key,
                                    placeholder=tx("placeholder"),
                                    type=repr(p["itype"]) if p.get("itype") not in (None, "text") else None,
                                    help=tx("help")))
        elif t == "textarea":
            rows = self.number(p.get("rows"), 4)
            self._bind(p, self.call("ui.textarea", tx("label") or "''", repr(p.get("value")) if p.get("value") else None,
                                    key=key, placeholder=tx("placeholder"), rows=rows if rows != "4" else None, help=tx("help")))
        elif t == "number":
            self._bind(p, self.call("ui.number", tx("label") or "''", self.number(p.get("value"), 0), key=key,
                                    min=self.number(p.get("min")), max=self.number(p.get("max")),
                                    step=self.number(p.get("step")), help=tx("help")))
        elif t == "slider":
            self._bind(p, self.call("ui.slider", tx("label") or "''", self.number(p.get("min"), 0),
                                    self.number(p.get("max"), 100), self.number(p.get("value"), 0), key=key,
                                    step=self.number(p.get("step")),
                                    suffix=tx("suffix"), help=tx("help")))
        elif t in ("select", "radio"):
            o = p.get("options")
            opts = f"list({self.expr(o[1:])})" if S.is_expr(o) else repr(S._as_list(o) or ["—"])
            default = repr(p["value"]) if p.get("value") and not S.is_expr(o) and p["value"] in S._as_list(o) else None
            self._bind(p, self.call(f"ui.{t}", tx("label") or "''", opts, default, key=key,
                                    help=tx("help") if t == "select" else None))
        elif t == "multiselect":
            o = p.get("options")
            opts = f"list({self.expr(o[1:])})" if S.is_expr(o) else repr(S._as_list(o))
            v = S._as_list(p.get("value"))
            self._bind(p, self.call("ui.multiselect", tx("label") or "''", opts, repr(v) if v else None, key=key))
        elif t in ("checkbox", "toggle"):
            self._bind(p, self.call(f"ui.{t}", tx("label") or "''", "True" if p.get("value") else None, key=key))
        elif t == "date":
            self._bind(p, self.call("ui.date", tx("label") or "''", key=key))
        elif t == "color":
            self._bind(p, self.call("ui.color", tx("label") or "''", repr(p.get("value") or "#6366f1"), key=key))
        elif t == "upload":
            self._bind(p, self.call("ui.upload", tx("label") or "''", key=key,
                                    accept=repr(p["accept"]) if p.get("accept") else None))
        elif t == "button":
            acts = p.get("actions") or []
            cb = None
            if acts:
                cb = self.uid("on_" + _slug(p.get("label") or "click", "click"))
                self.callback(cb, acts)
            self.emit(self.call("ui.button", tx("label") or "'Button'",
                                kind=repr(p["kind"]) if p.get("kind") not in (None, "primary") else None,
                                icon=repr(p["icon"]) if p.get("icon") else None,
                                full="True" if p.get("full") else None, on_click=cb))
        elif t == "download":
            c = p.get("content")
            content = f"as_text({self.expr(c[1:])})" if S.is_expr(c) else (self.template(c) if c else "''")
            if S.is_expr(c):
                self.uses_helpers.add("as_text")
            self.emit(self.call("ui.download", tx("label") or "'Download'", content, tx("filename") or "'export.txt'"))
        elif t in ("table", "chart"):
            data = self.data(p.get("data"))
            if t == "table":
                ps = self.number(p.get("page_size"), 10)
                self.emit(self.call("ui.table", data, page_size=ps if ps != "10" else None,
                                    search="False" if p.get("search") is False else None))
            else:
                ys = [self.template(s.strip()) for s in str(p.get("y") or "").split(",") if s.strip()]
                h = self.number(p.get("height"), 280)
                self.emit(self.call("ui.chart", data, x=self.template(p["x"].strip()) if (p.get("x") or "").strip() else None,
                                    y=(ys[0] if len(ys) == 1 else "[" + ", ".join(ys) + "]") if ys else None,
                                    kind=self.value(p.get("kind") or "line"), title=tx("title"),
                                    height=h if h != "300" else None, stacked="True" if p.get("stacked") else None))
        elif t == "chat":
            self.chat(n, p)
        elif t == "columns":
            var = self.uid("cols")
            widths = S._widths(p.get("widths"))
            widths = [int(w) if float(w).is_integer() else w for w in widths]
            spec = str(len(widths)) if all(w == 1 for w in widths) else repr(widths)
            self.emit(self.call(f"{var} = ui.columns", spec, gap=repr(p["gap"]) if p.get("gap") not in (None, "md") else None))
            for i, slot in enumerate(n.get("slots") or []):
                self.block(f"with {var}[{i}]:", slot)
        elif t == "card":
            self.block(f"with {self.call('ui.card', tx('title'), tx('subtitle'))}:", (n.get("slots") or [[]])[0])
        elif t in ("row", "container"):
            self.block(f"with ui.{t}():", (n.get("slots") or [[]])[0])
        elif t == "tabs":
            var = self.uid("tabs")
            labels = S._as_list(p.get("labels")) or ["Tab"]
            self.emit(f"{var} = ui.tabs({labels!r})")
            for i, slot in enumerate(n.get("slots") or []):
                self.block(f"with {var}[{i}]:", slot)
        elif t == "expander":
            self.block(f"with {self.call('ui.expander', tx('label') or repr('More'), open='True' if p.get('open') else None)}:",
                       (n.get("slots") or [[]])[0])
        else:
            self.emit(f"# unknown component {t!r}")

    def data(self, v) -> str:
        if S.is_expr(v):
            self.uses_helpers.add("as_rows")
            return f"as_rows({self.expr(v[1:])})"
        if isinstance(v, str) and v.strip():
            self.uses_helpers.add("csv")
            name = self.uid("DATA").upper()
            body = v.strip("\n").replace('"""', '\\"\\"\\"')
            self.consts.append(f'{name} = csv("""\\\n{body}\n""")')
            return name
        return repr(v if isinstance(v, list) else [])

    def chat(self, n, p):
        name = p.get("name") or "chat"
        hook = (p.get("hook") or "").strip()
        if p.get("greeting"):
            self.emit(self.call("ui.chat_message", "'assistant'", self.template(p["greeting"])))
        self.emit(f"for m in {_st(name)}:")
        self.emit("    ui.chat_message(m['role'], m['content'])")
        self.emit(f"message = {self.call('ui.chat_input', self._txt(p, 'placeholder'), key=repr(name))}")
        self.emit("if message:")
        self.ind += 1
        self.emit(f"{_st(name)}.append({{'role': 'user', 'content': message}})")
        if hook:
            self.uses_hooks = True
            self.emit(f"reply = {self._hooks_mod()}.{hook}(velo.Context(ui, {sorted(self.widgets)!r}), message)")
        else:
            self.extra_locals.add("message")
            self.emit(f"reply = {self.template(p.get('reply') or '{message}')}")
            self.extra_locals.discard("message")
        self.emit(f"{_st(name)}.append({{'role': 'assistant', 'content': str(reply)}})")
        self.emit("ui.rerun()")
        self.ind -= 1

    def _hooks_mod(self) -> str:
        return _slug((self.spec.get("hooks") or "hooks.py").rsplit("/", 1)[-1].rsplit(".", 1)[0], "hooks")

    def callback(self, name: str, actions: list):
        self.emit(f"def {name}():")
        self.ind += 1
        was, self.in_cb = self.in_cb, True
        before = len(self.lines)
        for a in actions:
            cond = a.get("if")
            if isinstance(cond, str) and cond.strip():
                self.emit(f"if {self.expr(cond.strip().lstrip('='))}:")
                self.ind += 1
                self.action(a)
                self.ind -= 1
            else:
                self.action(a)
        if len(self.lines) == before:
            self.emit("pass")
        self.in_cb = was
        self.ind -= 1
        self.emit()

    def assign(self, var: str, code: str):
        if var in self.widgets:
            self.emit(f"ui.set({var!r}, {code})")
        else:
            self.emit(f"{_st(var)} = {code}")

    def action(self, a):
        do, var = a.get("do"), (a.get("var") or "").strip()
        if do in ("set", "toggle", "append", "clear") and not var.isidentifier():
            self.emit(f"pass  # ⚠ {do}: no variable chosen")
            return
        if do == "set":
            self.assign(var, self.literal(a.get("value", "")))
        elif do == "toggle":
            self.assign(var, f"not {self.ref(var)}")
        elif do == "append":
            self.assign(var, f"{self.ref(var)} + [{self.literal(a.get('value', ''))}]")
        elif do == "clear":
            d = self.vars.get(var, {}).get("default")
            empty = "[]" if isinstance(d, list) else "{}" if isinstance(d, dict) else "False" if isinstance(d, bool) \
                else "0" if isinstance(d, (int, float)) else "''"
            self.assign(var, empty)
        elif do == "reset":
            names = [s for s in str(a.get("vars") or "").replace(",", " ").split() if s]
            names = names or sorted(self.widgets)
            self.emit(f"ui.reset({', '.join(repr(x) for x in names)})")
        elif do == "toast":
            kind = a.get("kind") or "info"
            self.emit(self.call("ui.toast", self.template(a.get("text") or ""), repr(kind) if kind != "info" else None))
        elif do == "navigate":
            self.emit(f"ui.navigate({self.template(a.get('to') or '/')})")
        elif do == "call":
            self.uses_hooks = True
            fn = (a.get("fn") or "").strip() or "my_action"
            self.emit(f"{self._hooks_mod()}.{fn}(velo.Context(ui, {sorted(self.widgets)!r}))")
        else:
            self.emit(f"pass  # unknown action {do!r}")

    # ---- whole file ------------------------------------------------------
    def page(self, page):
        self.locals = set()
        fn = self.uid(_slug(page.get("title") or page["path"], "page"))
        self.emit(f"@app.page({page['path']!r}, title={page['title']!r}, icon={page.get('icon') or '•'!r})")
        self.emit(f"def {fn}(ui):")
        self.ind += 1
        init = dict(self.spec["state"])
        for c in sorted(self.chats):
            init[c] = []
        if init:
            self.emit("ui.init(" + ", ".join(f"{k}={v!r}" for k, v in init.items()) + ")")
        before = len(self.lines)
        if page.get("sidebar"):
            self.block("with ui.sidebar:", page["sidebar"])
        self.nodes(page.get("body"))
        if len(self.lines) == before and not init:
            self.emit("pass")
        self.ind -= 1
        self.emit()
        self.emit()

    def file(self) -> str:
        self.ind = 0
        body_start = len(self.lines)
        for page in self.spec["pages"]:
            self.page(page)
        body = self.lines[body_start:]
        a = self.spec["app"]
        head = ['"""Generated by Velo Studio — this is plain Velo code: edit it freely.', "",
                "Run:  python app.py      (or: velo run app.py)", '"""', "import velo"]
        if self.uses_helpers:
            head.append("from velo.helpers import " + ", ".join(sorted(self.uses_helpers)))
        if self.uses_hooks:
            head.append(f"import {self._hooks_mod()}  # your Python functions")
        head += ["", ""]
        app_kw = [repr(a["title"]), f"icon={a['icon']!r}", f"accent={a['accent']!r}"]
        if a.get("theme") not in (None, "auto"):
            app_kw.append(f"theme={a['theme']!r}")
        if a.get("wide"):
            app_kw.append("wide=True")
        head.append(f"app = velo.App({', '.join(app_kw)})")
        head.append("")
        if self.consts:
            head += self.consts + [""]
        head.append("")
        tail = ['if __name__ == "__main__":', "    app.run()", ""]
        while body and body[-1] == "":
            body.pop()
        return "\n".join(head + body + ["", ""] + tail)


def to_python(spec: dict) -> str:
    """Return the Python source code equivalent of a spec."""
    return _Gen(spec).file()
