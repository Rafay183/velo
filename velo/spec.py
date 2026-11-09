"""No-code apps: the ``.velo.json`` spec, its expression language, and the interpreter.

A spec is plain JSON (what Velo Studio saves)::

    {
      "velo": 1,
      "app":   {"title": "My app", "icon": "⚡", "accent": "#6366f1", "theme": "auto", "wide": false},
      "state": {"count": 0, "entries": []},
      "hooks": "hooks.py",                     # optional Python functions for buttons / chat
      "pages": [{"path": "/", "title": "Home", "icon": "🏠",
                 "body": [<node>, ...], "sidebar": [<node>, ...]}]
    }

    <node> = {"id": "n1", "type": "input", "props": {...}, "slots": [[<node>...]], "show_if": "age > 18"}

Expressions — the only "code" a no-code user ever writes, spreadsheet style:

* A prop value that starts with ``=`` is computed:   ``=count * 2``,  ``=csv(file)``
* Text props are templates:                          ``Hello {name}!``,  ``Total: {price * qty:,.2f}``
* Every widget is a variable (its *name*), every key in ``state`` too.

Expressions use Python syntax, evaluated with a whitelist (no imports, no dunder
access, only safe helpers). They are written by the app author, never by the
app's visitors, whose input only ever arrives as data.
"""
from __future__ import annotations

import ast
import copy
import csv as _csv
import datetime as _dt
import io
import json
import keyword
import math
import os
import re
import statistics
import uuid
from typing import Any, Callable

from .core import App, UI, UploadedFile

SPEC_VERSION = 1

# =========================================================================== catalog
# One source of truth: Studio's palette + inspector, the interpreter, the validator
# and the code exporter all read this table.

def _p(name, label, kind="text", default="", **extra):
    d = {"name": name, "label": label, "kind": kind, "default": default}
    d.update(extra)
    return d


_VAR = lambda default: _p("name", "Variable name", "var", default,  # noqa: E731
                          help="Use it anywhere as {%s} or =%s" % (default, default))
_HELP = _p("help", "Help text", "text", "")

COMPONENTS: dict[str, dict] = {
    # ---- text
    "title": dict(group="Text", label="Title", icon="H1", desc="Big page title with optional subtitle",
                  props=[_p("text", "Text", default="My awesome app"),
                         _p("subtitle", "Subtitle", default="Built with Velo Studio — no code needed")]),
    "header": dict(group="Text", label="Header", icon="H2", desc="Section heading",
                   props=[_p("text", "Text", default="Section")]),
    "subheader": dict(group="Text", label="Subheader", icon="H3", desc="Smaller heading",
                      props=[_p("text", "Text", default="Subsection")]),
    "text": dict(group="Text", label="Text", icon="¶", desc="A paragraph. Use {variables}",
                 props=[_p("text", "Text", "longtext", "Write something here. Use {variables} to show live values."),
                        _p("muted", "Muted", "bool", False)]),
    "markdown": dict(group="Text", label="Markdown", icon="M↓", desc="Rich text: **bold**, lists, links, tables",
                     props=[_p("text", "Markdown", "longtext", "**Bold**, _italic_, `code` and [links](https://github.com/rafay183/velo)\n\n- one\n- two")]),
    "caption": dict(group="Text", label="Caption", icon="ᶜ", desc="Small, muted text",
                    props=[_p("text", "Text", default="A small note")]),
    "badge": dict(group="Text", label="Badge", icon="◉", desc="Small coloured label",
                  props=[_p("text", "Text", default="New"),
                         _p("kind", "Colour", "choice", "accent", options=["accent", "success", "warning", "error", "neutral"])]),
    "link": dict(group="Text", label="Link", icon="↗", desc="External link",
                 props=[_p("text", "Text", default="Velo on GitHub"),
                        _p("url", "URL", default="https://github.com/rafay183/velo")]),
    "code": dict(group="Text", label="Code", icon="</>", desc="Code block with copy button",
                 props=[_p("code", "Code", "code", "print('hello velo')"),
                        _p("lang", "Language", default="python")]),
    "image": dict(group="Text", label="Image", icon="🖼", desc="Image from a URL",
                  props=[_p("src", "Image URL", default="https://picsum.photos/seed/velo/800/360"),
                         _p("caption", "Caption", default=""),
                         _p("width", "Max width (px)", "number", None)]),
    "divider": dict(group="Text", label="Divider", icon="—", desc="Horizontal line", props=[]),
    "space": dict(group="Text", label="Spacer", icon="↕", desc="Vertical space",
                  props=[_p("height", "Height (px)", "number", 24)]),

    # ---- feedback
    "alert": dict(group="Feedback", label="Alert", icon="ℹ", desc="Info / success / warning / error box",
                  props=[_p("kind", "Type", "choice", "info", options=["info", "success", "warning", "error"]),
                         _p("title", "Title", default=""),
                         _p("text", "Message", "longtext", "Something worth knowing.")]),
    "metric": dict(group="Feedback", label="Metric", icon="#", desc="KPI number with delta",
                   props=[_p("label", "Label", default="Revenue"),
                          _p("value", "Value", default="$12,400"),
                          _p("delta", "Delta", default="+8%"),
                          _p("inverse", "Lower is better", "bool", False),
                          _HELP]),
    "progress": dict(group="Feedback", label="Progress", icon="▰", desc="Progress bar (0–100)",
                     props=[_p("value", "Value (0–100)", default="65"),
                            _p("label", "Label", default="Progress")]),

    # ---- inputs (each one is a variable)
    "input": dict(group="Inputs", label="Text input", icon="⌨", desc="Single-line text", var=True,
                  props=[_VAR("name"), _p("label", "Label", default="Your name"),
                         _p("placeholder", "Placeholder", default="Ada Lovelace"),
                         _p("value", "Default value", default=""),
                         _p("itype", "Type", "choice", "text", options=["text", "password", "email", "url", "tel"]),
                         _HELP]),
    "textarea": dict(group="Inputs", label="Text area", icon="☰", desc="Multi-line text", var=True,
                     props=[_VAR("message"), _p("label", "Label", default="Message"),
                            _p("placeholder", "Placeholder", default="Type here…"),
                            _p("value", "Default value", "longtext", ""),
                            _p("rows", "Rows", "number", 4), _HELP]),
    "number": dict(group="Inputs", label="Number", icon="12", desc="Number box", var=True,
                   props=[_VAR("amount"), _p("label", "Label", default="Amount"),
                          _p("value", "Default", "number", 0), _p("min", "Min", "number", None),
                          _p("max", "Max", "number", None), _p("step", "Step", "number", None), _HELP]),
    "slider": dict(group="Inputs", label="Slider", icon="⊶", desc="Pick a number by dragging", var=True,
                   props=[_VAR("level"), _p("label", "Label", default="Level"),
                          _p("min", "Min", "number", 0), _p("max", "Max", "number", 100),
                          _p("value", "Default", "number", 50), _p("step", "Step", "number", None),
                          _p("suffix", "Suffix", default=""), _HELP]),
    "select": dict(group="Inputs", label="Dropdown", icon="▾", desc="Pick one from a list", var=True,
                   props=[_VAR("city"), _p("label", "Label", default="City"),
                          _p("options", "Options (one per line, or =expression)", "list", ["Karachi", "Lahore", "Islamabad"]),
                          _p("value", "Default", default=""), _HELP]),
    "radio": dict(group="Inputs", label="Segmented", icon="◐", desc="Pick one of a few (buttons)", var=True,
                  props=[_VAR("plan"), _p("label", "Label", default="Plan"),
                         _p("options", "Options (one per line)", "list", ["Free", "Pro", "Team"]),
                         _p("value", "Default", default="")]),
    "multiselect": dict(group="Inputs", label="Chips", icon="⊞", desc="Pick many (toggle chips)", var=True,
                        props=[_VAR("tags"), _p("label", "Label", default="Interests"),
                               _p("options", "Options (one per line)", "list", ["Python", "Data", "AI", "Web"]),
                               _p("value", "Default (one per line)", "list", [])]),
    "checkbox": dict(group="Inputs", label="Checkbox", icon="☑", desc="Yes / no", var=True,
                     props=[_VAR("agree"), _p("label", "Label", default="I agree to the terms"),
                            _p("value", "Checked", "bool", False)]),
    "toggle": dict(group="Inputs", label="Switch", icon="⏻", desc="On / off switch", var=True,
                   props=[_VAR("enabled"), _p("label", "Label", default="Enable notifications"),
                          _p("value", "On", "bool", False)]),
    "date": dict(group="Inputs", label="Date", icon="📅", desc="Date picker", var=True,
                 props=[_VAR("day"), _p("label", "Label", default="Date")]),
    "color": dict(group="Inputs", label="Colour", icon="🎨", desc="Colour picker", var=True,
                  props=[_VAR("colour"), _p("label", "Label", default="Brand colour"),
                         _p("value", "Default", "color", "#6366f1")]),
    "upload": dict(group="Inputs", label="File upload", icon="⇪", desc="Drag & drop a file (CSV → =csv(file))", var=True,
                   props=[_VAR("file"), _p("label", "Label", default="Upload a CSV file"),
                          _p("accept", "Accept", default=".csv")]),

    # ---- actions
    "button": dict(group="Actions", label="Button", icon="▶", desc="Runs actions when clicked",
                   props=[_p("label", "Label", default="Click me"),
                          _p("kind", "Style", "choice", "primary", options=["primary", "secondary", "ghost", "danger"]),
                          _p("icon", "Icon (emoji)", default=""),
                          _p("full", "Full width", "bool", False),
                          _p("actions", "When clicked", "actions", [{"do": "toast", "text": "Clicked! 🎉", "kind": "success"}])]),
    "download": dict(group="Actions", label="Download", icon="⬇", desc="Download text / CSV built from your data",
                     props=[_p("label", "Label", default="Download"),
                            _p("content", "Content (text or =expression)", "longtext", "Hello {name}"),
                            _p("filename", "File name", default="export.txt")]),

    # ---- data
    "table": dict(group="Data", label="Table", icon="▦", desc="Searchable, sortable table",
                  props=[_p("data", "Data (CSV text or =expression)", "data",
                            "name,role,score\nAda,Engineer,98\nAlan,Scientist,95\nGrace,Admiral,99"),
                         _p("page_size", "Rows per page", "number", 10),
                         _p("search", "Search box", "bool", True)]),
    "chart": dict(group="Data", label="Chart", icon="📈", desc="Line, area, bar or donut chart",
                  props=[_p("kind", "Chart type", "choice", "bar", options=["line", "area", "bar", "pie"]),
                         _p("data", "Data (CSV text or =expression)", "data",
                            "month,sales,costs\nJan,120,80\nFeb,150,90\nMar,170,95\nApr,210,120\nMay,260,130"),
                         _p("x", "X column", default=""), _p("y", "Y columns (comma separated)", default=""),
                         _p("title", "Title", default=""), _p("height", "Height (px)", "number", 280),
                         _p("stacked", "Stacked", "bool", False)]),
    "chat": dict(group="Data", label="Chat", icon="💬", desc="Chat box: replies from a template or a Python hook", var=True,
                 props=[_VAR("chat"), _p("placeholder", "Placeholder", default="Ask me anything…"),
                        _p("greeting", "Greeting", default="Hi! I'm your assistant. Say something 👋"),
                        _p("reply", "Reply ({message} = what the user typed)", "longtext", "You said: **{message}**"),
                        _p("hook", "…or Python hook function (optional)", default="")]),

    # ---- layout (containers have drop zones = "slots")
    "columns": dict(group="Layout", label="Columns", icon="▥", desc="Side-by-side columns", slots="columns",
                    props=[_p("widths", "Widths (e.g. 1,1 or 2,1)", default="1,1"),
                           _p("gap", "Gap", "choice", "md", options=["sm", "md", "lg"])]),
    "card": dict(group="Layout", label="Card", icon="▢", desc="A panel that groups things", slots="one",
                 props=[_p("title", "Title", default="Card"), _p("subtitle", "Subtitle", default="")]),
    "row": dict(group="Layout", label="Row", icon="⋯", desc="Items in a horizontal line", slots="one", props=[]),
    "tabs": dict(group="Layout", label="Tabs", icon="⊟", desc="Tabbed sections", slots="tabs",
                 props=[_p("labels", "Tabs (one per line)", "list", ["Overview", "Details"])]),
    "expander": dict(group="Layout", label="Expander", icon="⌄", desc="Collapsible section", slots="one",
                     props=[_p("label", "Label", default="More details"), _p("open", "Open by default", "bool", False)]),
    "container": dict(group="Layout", label="Group", icon="◫", desc="Invisible group (great with 'show if')", slots="one",
                      props=[]),
}

GROUPS = ["Text", "Inputs", "Actions", "Data", "Feedback", "Layout"]

ACTIONS = {
    "set": {"label": "Set variable", "fields": ["var", "value"]},
    "toggle": {"label": "Flip yes/no", "fields": ["var"]},
    "append": {"label": "Add to list", "fields": ["var", "value"]},
    "clear": {"label": "Clear variable", "fields": ["var"]},
    "reset": {"label": "Reset inputs", "fields": ["vars"]},
    "toast": {"label": "Show message", "fields": ["text", "kind"]},
    "navigate": {"label": "Go to page", "fields": ["to"]},
    "call": {"label": "Run Python hook", "fields": ["fn"]},
}


def catalog() -> dict:
    return {"components": COMPONENTS, "groups": GROUPS, "actions": ACTIONS, "helpers": sorted(HELPERS),
            "version": SPEC_VERSION}


def slot_count(node: dict) -> int:
    kind = COMPONENTS.get(node.get("type"), {}).get("slots")
    props = node.get("props") or {}
    if kind == "columns":
        return max(1, len(_widths(props.get("widths"))))
    if kind == "tabs":
        return max(1, len(_as_list(props.get("labels")) or ["Tab"]))
    return 1 if kind else 0


def _widths(w) -> list[float]:
    if isinstance(w, (int, float)):
        return [1.0] * max(1, int(w))
    out = []
    for part in str(w or "1,1").replace(";", ",").replace(" ", ",").split(","):
        try:
            v = float(part)
            if v > 0:
                out.append(v)
        except ValueError:
            pass
    return out or [1.0, 1.0]


def _as_list(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x is not None and x != ""]
    return [line.strip() for line in str(v).splitlines() if line.strip()]


# =========================================================================== helpers
def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v).strip().replace(",", "")
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return v


def h_csv(src, delimiter: str = ",") -> list[dict]:
    """Parse CSV text or an uploaded file into a list of row dicts (numbers converted)."""
    if src is None:
        return []
    if isinstance(src, UploadedFile):
        src = src.text("utf-8-sig")
    elif isinstance(src, (bytes, bytearray)):
        src = bytes(src).decode("utf-8-sig", errors="replace")
    elif isinstance(src, list):
        return src
    text = str(src).strip("\n")
    if not text.strip():
        return []
    reader = _csv.DictReader(io.StringIO(text), delimiter=delimiter, skipinitialspace=True)
    return [{(k or "").strip(): _num(v) if isinstance(v, str) else v for k, v in row.items()} for row in reader]


def h_col(rows, name) -> list:
    """All values of one column: ``col(data, "price")``."""
    return [r.get(name) for r in (rows or []) if isinstance(r, dict)]


def h_mean(xs):
    xs = [x for x in (xs or []) if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return statistics.fmean(xs) if xs else 0


def h_where(rows, col, value):
    """Rows whose ``col`` equals ``value`` (or any of them, if value is a list)."""
    if value is None or value == "" or value == []:
        return list(rows or [])
    vals = value if isinstance(value, (list, tuple, set)) else [value]
    return [r for r in (rows or []) if isinstance(r, dict) and r.get(col) in vals]


def h_columns(rows) -> list[str]:
    """Column names of a table: ``=columns(csv(file))`` (handy for dropdown options)."""
    seen: list[str] = []
    for r in rows or []:
        if isinstance(r, dict):
            for k in r:
                if k not in seen:
                    seen.append(k)
    return seen


def h_group(rows, by, value=None, agg: str = "sum") -> list[dict]:
    """Group & aggregate: ``group(data, "region", "sales")`` → [{region, sales}]. agg: sum|count|mean|min|max."""
    out: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        out.setdefault(r.get(by), []).append(r.get(value) if value else 1)
    fn = {"sum": sum, "count": len, "mean": h_mean, "min": min, "max": max}.get(agg, sum)
    res = []
    for k, vs in out.items():
        nums = [v for v in vs if isinstance(v, (int, float)) and not isinstance(v, bool)]
        res.append({by: k, (value or "count"): fn(vs) if agg == "count" or not value else (fn(nums) if nums else 0)})
    return res


def h_to_csv(rows) -> str:
    """Turn a list of row dicts back into CSV text (for the Download component)."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return ""
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=h_columns(rows))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def h_as_rows(v) -> list:
    """Anything table-like -> rows: CSV text / uploaded file are parsed, None -> []."""
    if isinstance(v, (str, bytes, bytearray, UploadedFile)):
        return h_csv(v)
    return [] if v is None else v


def h_as_text(v) -> str:
    """Download content: a list of rows becomes CSV, anything else text."""
    if isinstance(v, list) and (not v or isinstance(v[0], dict)):
        return h_to_csv(v)
    return "" if v is None else str(v)


def h_fmt(v, spec: str = ",") -> str:
    try:
        return format(v, spec)
    except (TypeError, ValueError):
        return str(v)


def _pow(a, b):
    if isinstance(b, (int, float)) and abs(b) > 1000:
        raise ValueError("exponent too large")
    return a ** b


HELPERS: dict[str, Any] = {
    # python builtins that are safe
    "len": len, "str": str, "int": int, "float": float, "bool": bool, "round": round, "abs": abs,
    "min": min, "max": max, "sum": sum, "sorted": sorted, "range": range, "list": list, "dict": dict,
    "any": any, "all": all, "enumerate": enumerate, "zip": zip, "reversed": reversed, "set": set,
    "True": True, "False": False, "None": None,
    # velo helpers
    "csv": h_csv, "col": h_col, "mean": h_mean, "where": h_where, "columns": h_columns, "group": h_group,
    "to_csv": h_to_csv, "as_rows": h_as_rows, "as_text": h_as_text, "fmt": h_fmt, "today": _dt.date.today, "now": _dt.datetime.now,
    "pi": math.pi, "sqrt": math.sqrt,
    "__pow__": _pow,
}

_SAFE_ATTRS = {
    # str
    "upper", "lower", "title", "capitalize", "strip", "lstrip", "rstrip", "split", "join", "replace",
    "startswith", "endswith", "count", "find", "zfill", "isdigit", "isnumeric", "isalpha", "splitlines", "format",
    # list / dict
    "index", "get", "keys", "values", "items",
    # dates
    "year", "month", "day", "hour", "minute", "isoformat", "strftime", "weekday",
    # uploaded files
    "name", "size", "type", "text",
    # numbers
    "real", "imag", "is_integer",
}

_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Store, ast.BinOp, ast.UnaryOp, ast.BoolOp,
    ast.Compare, ast.IfExp, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice, ast.Call,
    ast.keyword, ast.Attribute, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.JoinedStr, ast.FormattedValue, ast.Starred,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)
if hasattr(ast, "Index"):  # Python 3.8 compatibility node
    _ALLOWED_NODES += (ast.Index,)  # type: ignore[attr-defined]


class ExprError(ValueError):
    pass


class _PowRewrite(ast.NodeTransformer):
    def visit_BinOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Pow):
            return ast.copy_location(ast.Call(func=ast.Name("__pow__", ast.Load()), args=[node.left, node.right],
                                              keywords=[]), node)
        return node


_COMPILED: dict[str, tuple] = {}


def compile_expr(src: str):
    """Validate and compile an expression. Returns (code, names_used). Raises ExprError."""
    hit = _COMPILED.get(src)
    if hit:
        return hit
    try:
        tree = ast.parse(src.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error in `{src}`: {e.msg}") from None
    bound: set[str] = set()
    used: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"`{type(node).__name__}` is not allowed in expressions")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ExprError(f"names starting with _ are not allowed: {node.id}")
            (bound if isinstance(node.ctx, ast.Store) else used).add(node.id)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr not in _SAFE_ATTRS:
                raise ExprError(f"`.{node.attr}` is not allowed in expressions")
    tree = ast.fix_missing_locations(_PowRewrite().visit(tree))
    code = compile(tree, "<velo expr>", "eval")
    out = (code, used - bound)
    if len(_COMPILED) > 4096:
        _COMPILED.clear()
    _COMPILED[src] = out
    return out


def evaluate(src: str, env: dict):
    code, _ = compile_expr(src)
    scope = dict(HELPERS)
    scope.update(env)
    scope["__builtins__"] = {}
    try:
        return eval(code, scope)  # noqa: S307 — validated, whitelisted AST, no builtins
    except NameError as e:
        name = str(e).split("'")[1] if "'" in str(e) else str(e)
        raise ExprError(f"unknown variable `{name}`") from None
    except ExprError:
        raise
    except Exception as e:
        raise ExprError(f"{type(e).__name__}: {e}") from None


def is_expr(v) -> bool:
    return isinstance(v, str) and v.startswith("=") and len(v) > 1


def template_parts(text: str) -> list[tuple[str, str | None, str | None]]:
    """Split a template into [(literal, expr, format_spec)]. ``{{`` / ``}}`` escape braces."""
    out: list[tuple[str, str | None, str | None]] = []
    buf, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "{" and text.startswith("{{", i):
            buf.append("{"); i += 2; continue  # noqa: E702
        if ch == "}" and text.startswith("}}", i):
            buf.append("}"); i += 2; continue  # noqa: E702
        if ch == "{":
            depth, j, quote = 1, i + 1, None
            while j < n and depth:
                c = text[j]
                if quote:
                    if c == quote:
                        quote = None
                elif c in "'\"":
                    quote = c
                elif c in "{[(":
                    depth += 1
                elif c in "}])":
                    depth -= 1
                j += 1
            if depth:  # unbalanced -> literal
                buf.append(text[i:]); break  # noqa: E702
            inner = text[i + 1:j - 1].strip()
            expr, spec = inner, None
            if inner:
                try:
                    compile_expr(inner)
                except ExprError:
                    if ":" in inner:  # maybe a format spec: {price:,.2f}
                        e2, s2 = inner.rsplit(":", 1)
                        try:
                            compile_expr(e2)
                            expr, spec = e2.strip(), s2
                        except ExprError:
                            pass
            out.append(("".join(buf), expr or None, spec))
            buf = []
            i = j
            continue
        buf.append(ch)
        i += 1
    if buf:
        out.append(("".join(buf), None, None))
    return out


def _show(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if isinstance(v, UploadedFile):
        return v.name
    if isinstance(v, (list, tuple)):
        return ", ".join(_show(x) for x in v)
    if isinstance(v, _dt.date):
        return v.isoformat()
    return str(v)


def render_template(text, env: dict, errors: list | None = None) -> str:
    if not isinstance(text, str):
        return _show(text)
    if is_expr(text):
        try:
            return _show(evaluate(text[1:], env))
        except ExprError as e:
            if errors is not None:
                errors.append(str(e))
            return f"⚠ {e}"
    if "{" not in text and "}" not in text:
        return text
    out = []
    for lit, expr, spec in template_parts(text):
        out.append(lit)
        if expr:
            try:
                v = evaluate(expr, env)
                out.append(format(v, spec) if spec else _show(v))
            except (ExprError, ValueError, TypeError) as e:
                if errors is not None:
                    errors.append(str(e))
                out.append(f"⚠{{{expr}}}")
    return "".join(out)


def value_of(v, env: dict, errors: list | None = None):
    """Resolve a prop: ``=expr`` is computed, strings are templates, the rest is passed through."""
    if is_expr(v):
        try:
            return evaluate(v[1:], env)
        except ExprError as e:
            if errors is not None:
                errors.append(str(e))
            return None
    if isinstance(v, str):
        return render_template(v, env, errors)
    return v


def literal(v, env: dict, errors: list | None = None):
    """Action values: ``=expr`` computed; '5' -> 5; 'true' -> True; otherwise a template string."""
    if is_expr(v):
        return value_of(v, env, errors)
    if isinstance(v, str):
        s = v.strip()
        low = s.lower()
        if low in ("true", "yes"):
            return True
        if low in ("false", "no"):
            return False
        n = _num(s)
        if isinstance(n, (int, float)) and s:
            return n
        return render_template(v, env, errors)
    return v


def data_of(v, env: dict, errors: list | None = None):
    if is_expr(v):
        d = value_of(v, env, errors)
    else:
        d = v
    if isinstance(d, (str, bytes, UploadedFile)):
        return h_csv(d)
    return d if d is not None else []


def num_of(v, env, default=None, errors=None):
    if v is None or v == "":
        return default
    r = value_of(v, env, errors) if isinstance(v, str) else v
    r = _num(r) if isinstance(r, str) else r
    return r if isinstance(r, (int, float)) and not isinstance(r, bool) else default


# =========================================================================== spec utils
def new_id() -> str:
    return "n" + uuid.uuid4().hex[:8]


def walk(nodes, parent=None):
    """Yield every node (depth first) in a list of nodes."""
    for n in nodes or []:
        yield n
        for slot in n.get("slots") or []:
            yield from walk(slot, n)


def page_nodes(page):
    yield from walk(page.get("body"))
    yield from walk(page.get("sidebar"))


def all_nodes(spec):
    for p in spec.get("pages") or []:
        yield from page_nodes(p)


def make_node(type: str, **props) -> dict:
    meta = COMPONENTS[type]
    p = {d["name"]: copy.deepcopy(d["default"]) for d in meta["props"]}
    p.update(props)
    node = {"id": new_id(), "type": type, "props": p}
    if meta.get("slots"):
        node["slots"] = [[] for _ in range(slot_count(node))]
    return node


def normalize(spec: dict) -> dict:
    """Fill in defaults so every consumer can rely on the shape. Never mutates the input."""
    spec = copy.deepcopy(spec or {})
    spec.setdefault("velo", SPEC_VERSION)
    a = spec.setdefault("app", {})
    a.setdefault("title", "My Velo App")
    a.setdefault("icon", "⚡")
    a.setdefault("accent", "#6366f1")
    a.setdefault("theme", "auto")
    a.setdefault("wide", False)
    if not isinstance(spec.get("state"), dict):
        spec["state"] = {}
    pages = spec.get("pages") or []
    if not pages:
        pages = [{"path": "/", "title": "Home", "icon": "🏠", "body": []}]
    seen_paths = set()
    for i, p in enumerate(pages):
        p.setdefault("id", f"p{i + 1}")
        path = "/" + str(p.get("path") or ("/" if i == 0 else f"page{i + 1}")).strip().strip("/")
        while path in seen_paths:
            path += f"-{i + 1}"
        seen_paths.add(path)
        p["path"] = path
        p.setdefault("title", "Home" if path == "/" else path.strip("/").replace("-", " ").title())
        p.setdefault("icon", "•")
        p["body"] = p.get("body") or []
        p["sidebar"] = p.get("sidebar") or []
    spec["pages"] = pages
    ids = set()
    for n in all_nodes(spec):
        if not n.get("id") or n["id"] in ids:
            n["id"] = new_id()
        ids.add(n["id"])
        meta = COMPONENTS.get(n.get("type"))
        props = n.setdefault("props", {})
        if meta:
            for d in meta["props"]:
                props.setdefault(d["name"], copy.deepcopy(d["default"]))
            if meta.get("slots"):
                want = slot_count(n)
                slots = n.get("slots") or []
                if len(slots) < want:
                    slots += [[] for _ in range(want - len(slots))]
                elif len(slots) > want:  # never lose content: merge extras into the last slot
                    keep = slots[:want]
                    for extra in slots[want:]:
                        keep[-1].extend(extra)
                    slots = keep
                n["slots"] = slots
    return spec


def variables(spec) -> dict[str, dict]:
    """name -> {"type", "default", "page", "kind": "widget"|"state"}"""
    out: dict[str, dict] = {}
    for k, v in (spec.get("state") or {}).items():
        out[k] = {"kind": "state", "type": "state", "default": v}
    for p in spec.get("pages") or []:
        for n in page_nodes(p):
            meta = COMPONENTS.get(n.get("type"), {})
            if meta.get("var"):
                name = (n.get("props") or {}).get("name")
                if name:
                    out.setdefault(name, {"kind": "widget", "type": n["type"], "default": _widget_default(n),
                                          "page": p["path"], "id": n["id"]})
    return out


def _widget_default(n):
    t, p = n["type"], n.get("props") or {}
    if t in ("input", "textarea", "color"):
        return p.get("value") or ("" if t != "color" else "#6366f1")
    if t in ("number", "slider"):
        v = p.get("value")
        return v if isinstance(v, (int, float)) else (p.get("min") if isinstance(p.get("min"), (int, float)) else 0)
    if t in ("select", "radio"):
        opts = p.get("options")
        if isinstance(opts, list) and opts:
            return p.get("value") if p.get("value") in opts else opts[0]
        return None
    if t == "multiselect":
        return list(p.get("value") or [])
    if t in ("checkbox", "toggle"):
        return bool(p.get("value"))
    if t == "date":
        return None
    if t == "upload":
        return None
    if t == "chat":
        return []
    return None


# =========================================================================== validation
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RESERVED = {"ui", "app", "velo", "hooks", "message", "state", "data", "content"}
_STRUCTURAL = {"type", "id", "slots"}


def _expr_sources(n) -> list[tuple[str, str]]:
    """(prop, expression) pairs found in a node."""
    out = []
    meta = COMPONENTS.get(n.get("type"), {})
    kinds = {d["name"]: d["kind"] for d in meta.get("props", [])}
    for k, v in (n.get("props") or {}).items():
        if k == "actions":
            for i, a in enumerate(v or []):
                for f in ("value", "text", "if", "to"):
                    s = a.get(f)
                    if isinstance(s, str):
                        out += _exprs_in(s, f"action {i + 1} {f}")
            continue
        if kinds.get(k) in ("code", "var") or k in ("hook",):
            continue
        if isinstance(v, str):
            out += _exprs_in(v, k)
    if isinstance(n.get("show_if"), str) and n["show_if"].strip():
        s = n["show_if"].strip()
        out.append(("show if", s[1:] if s.startswith("=") else s))
    return out


def _exprs_in(s: str, where: str):
    if is_expr(s):
        return [(where, s[1:])]
    if "{" in s:
        return [(where, e) for _, e, _ in template_parts(s) if e]
    return []


def validate(spec: dict) -> list[dict]:
    """Return a list of problems: {"id": node id or None, "level": "error"|"warning", "msg": str}."""
    spec = normalize(spec)
    probs: list[dict] = []
    vars_ = variables(spec)
    known = set(vars_) | set(HELPERS) | {"message", "state"}
    names_seen: dict[str, str] = {}
    for k in spec["state"]:
        if not _IDENT.match(k) or keyword.iskeyword(k) or k in HELPERS or k in RESERVED:
            probs.append({"id": None, "level": "error", "msg": f"state variable `{k}` is not a valid name"})
    for page in spec["pages"]:
        for n in page_nodes(page):
            if n.get("type") not in COMPONENTS:
                probs.append({"id": n.get("id"), "level": "error", "msg": f"unknown component `{n.get('type')}`"})
                continue
            meta = COMPONENTS[n["type"]]
            if meta.get("var"):
                name = (n.get("props") or {}).get("name") or ""
                if not _IDENT.match(name) or keyword.iskeyword(name):
                    probs.append({"id": n["id"], "level": "error",
                                  "msg": f"variable name `{name}` must start with a letter and use only letters, digits, _"})
                elif name in HELPERS or name in RESERVED:
                    probs.append({"id": n["id"], "level": "error", "msg": f"`{name}` is a built-in helper name — pick another"})
                elif name in names_seen and names_seen[name] != n["id"]:
                    probs.append({"id": n["id"], "level": "error", "msg": f"variable `{name}` is used twice"})
                elif name in spec["state"]:
                    probs.append({"id": n["id"], "level": "error", "msg": f"`{name}` is also a state variable"})
                names_seen.setdefault(name, n["id"])
            for where, e in _expr_sources(n):
                try:
                    _, used = compile_expr(e)
                    for u in sorted(used - known):
                        probs.append({"id": n["id"], "level": "warning",
                                      "msg": f"{where}: unknown variable `{u}`"})
                except ExprError as ex:
                    probs.append({"id": n["id"], "level": "error", "msg": f"{where}: {ex}"})
            for i, a in enumerate((n.get("props") or {}).get("actions") or []):
                if a.get("do") not in ACTIONS:
                    probs.append({"id": n["id"], "level": "error", "msg": f"action {i + 1}: unknown action `{a.get('do')}`"})
                elif a["do"] in ("set", "toggle", "append", "clear") and not a.get("var"):
                    probs.append({"id": n["id"], "level": "error", "msg": f"action {i + 1}: choose a variable"})
                elif a["do"] in ("append",) and a.get("var") in vars_ and vars_[a["var"]]["kind"] == "state" \
                        and not isinstance(vars_[a["var"]]["default"], list):
                    probs.append({"id": n["id"], "level": "warning",
                                  "msg": f"action {i + 1}: `{a['var']}` should start as a list [] to add to it"})
    return probs


# =========================================================================== interpreter
class Context:
    """What a Python hook receives: ``def my_action(ctx): ctx.toast(f"Hi {ctx['name']}")``."""

    def __init__(self, ui: UI, names: list[str] | None = None):
        self.ui = ui
        self.state = ui.state
        self._names = names or []

    @property
    def values(self) -> dict:
        return {n: self.ui.get(n) for n in self._names}

    def __getitem__(self, name):
        if name in self.state:
            return self.state[name]
        return self.ui.get(name)

    def get(self, name, default=None):
        v = self[name]
        return default if v is None else v

    def set(self, name, value):
        if name in self.state or name not in self._names:
            self.state[name] = value
        else:
            self.ui.set(name, value)

    def toast(self, text, kind: str = "info"):
        self.ui.toast(text, kind)

    def navigate(self, path: str):
        self.ui.navigate(path)


def _load_hooks(path: str | None, base_dir: str | None):
    if not path:
        return None
    import importlib.util
    full = path if os.path.isabs(path) else os.path.join(base_dir or os.getcwd(), path)
    if not os.path.isfile(full):
        return None
    mod_name = "velo_hooks_" + uuid.uuid4().hex[:6]
    sp = importlib.util.spec_from_file_location(mod_name, full)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class SpecApp(App):
    """An :class:`App` built from a spec. Add Python on top whenever you like::

        app = velo.load("app.velo.json")

        @app.action("send_email")
        def send_email(ctx): ...

        @app.page("/custom")          # mix hand-written pages in, too
        def custom(ui): ...
    """

    def __init__(self, spec: dict, base_dir: str | None = None, actions: dict | None = None):
        spec = normalize(spec)
        a = spec["app"]
        super().__init__(a["title"], icon=a["icon"], theme=a["theme"], accent=a["accent"], wide=bool(a["wide"]))
        self.spec = spec
        self.base_dir = base_dir
        self.actions: dict[str, Callable] = dict(actions or {})
        self.hooks = None
        try:
            self.hooks = _load_hooks(spec.get("hooks"), base_dir)
        except Exception as e:  # keep the app usable, show the error on every page
            self._hook_error = f"Could not load hooks: {type(e).__name__}: {e}"
        else:
            self._hook_error = None
        self._vars = variables(spec)
        self._widget_names = [k for k, v in self._vars.items() if v["kind"] == "widget"]
        for page in spec["pages"]:
            self.page(page["path"], title=page["title"], icon=page.get("icon") or "•")(self._page_fn(page))

    def action(self, name: str | None = None):
        """Register a Python function for buttons ("Run Python hook") and chat replies."""
        def deco(fn):
            self.actions[name or fn.__name__] = fn
            return fn
        return deco

    def _adopt(self, other: "App"):
        super()._adopt(other)
        if isinstance(other, SpecApp):
            for a in ("spec", "base_dir", "hooks", "_hook_error", "_vars", "_widget_names"):
                setattr(self, a, getattr(other, a))
            merged = dict(other.actions)
            merged.update({k: v for k, v in self.actions.items() if k not in merged})
            self.actions = merged

    # ---- environment -------------------------------------------------------
    def _env(self, ui: UI) -> dict:
        env: dict = {}
        for name in self._widget_names:
            v = ui.get(name)
            env[name] = copy.copy(self._vars[name]["default"]) if v is None else v
        for k in self.spec["state"]:
            env[k] = ui.state.get(k)
        env["state"] = dict(ui.state)
        return env

    def _fn(self, name: str):
        fn = self.actions.get(name)
        if fn is None and self.hooks is not None:
            fn = getattr(self.hooks, name, None)
        if not callable(fn):
            raise ExprError(f"no Python hook named `{name}` (add it to {self.spec.get('hooks') or 'hooks.py'})")
        return fn

    # ---- pages -------------------------------------------------------------
    def _page_fn(self, page: dict):
        def fn(ui: UI):
            ui.init(**copy.deepcopy(self.spec["state"]))
            if self._hook_error:
                ui.error(self._hook_error)
            env = self._env(ui)
            r = _Renderer(self, ui, env)
            if page.get("sidebar"):
                with ui.sidebar:
                    r.nodes(page["sidebar"])
            r.nodes(page["body"])
            if not page.get("body") and not page.get("sidebar"):
                ui.info("This page is empty. Drag components onto it in **Velo Studio**.")
        fn.__name__ = re.sub(r"\W", "_", page["title"].lower()) or "page"
        return fn

    def run_actions(self, ui: UI, actions: list, page_vars: list[str]):
        errors: list[str] = []
        for a in actions or []:
            env = self._env(ui)
            cond = a.get("if")
            if isinstance(cond, str) and cond.strip():
                try:
                    if not evaluate(cond.strip().lstrip("="), env):
                        continue
                except ExprError as e:
                    errors.append(f"condition: {e}")
                    continue
            do = a.get("do")
            var = (a.get("var") or "").strip()
            try:
                if do == "set":
                    self._assign(ui, var, literal(a.get("value", ""), env, errors))
                elif do == "toggle":
                    self._assign(ui, var, not env.get(var))
                elif do == "append":
                    cur = env.get(var)
                    cur = list(cur) if isinstance(cur, (list, tuple)) else ([] if cur in (None, "") else [cur])
                    cur.append(literal(a.get("value", ""), env, errors))
                    self._assign(ui, var, cur)
                elif do == "clear":
                    cur = env.get(var)
                    empty = [] if isinstance(cur, list) else 0 if isinstance(cur, (int, float)) and not isinstance(cur, bool) \
                        else False if isinstance(cur, bool) else {} if isinstance(cur, dict) else ""
                    self._assign(ui, var, empty)
                elif do == "reset":
                    names = [s.strip() for s in str(a.get("vars") or "").replace(",", " ").split() if s.strip()]
                    ui.reset(*(names or page_vars))
                elif do == "toast":
                    ui.toast(render_template(a.get("text", ""), env, errors), a.get("kind") or "info")
                elif do == "navigate":
                    ui.navigate(render_template(a.get("to") or "/", env, errors))
                elif do == "call":
                    self._fn((a.get("fn") or "").strip())(Context(ui, self._widget_names))
            except ExprError as e:
                errors.append(str(e))
        for e in errors:
            ui.toast(f"⚠ {e}", "error")

    def _assign(self, ui: UI, var: str, value):
        if not var:
            raise ExprError("choose a variable to change")
        if var in self._widget_names:
            ui.set(var, value)
        else:
            ui.state[var] = value


class _Renderer:
    def __init__(self, app: SpecApp, ui: UI, env: dict):
        self.app, self.ui, self.env = app, ui, env
        self.errs: list[str] = []

    # helpers
    def t(self, v):  # template
        return render_template(v, self.env, self.errs) if v is not None else None

    def v(self, v):
        return value_of(v, self.env, self.errs)

    def n(self, v, default=None):
        return num_of(v, self.env, default, self.errs)

    def nodes(self, nodes):
        for node in nodes or []:
            self.node(node)

    def node(self, node: dict):
        cond = node.get("show_if")
        if isinstance(cond, str) and cond.strip():
            try:
                if not evaluate(cond.strip().lstrip("="), self.env):
                    return
            except ExprError as e:
                self.ui.caption(f"⚠ show if: {e}")
                return
        typ = node.get("type")
        fn = getattr(self, "r_" + str(typ), None)
        if fn is None:
            self.ui.warning(f"Unknown component `{typ}`")
            return
        self.errs = []
        p = node.get("props") or {}
        try:
            fn(node, p)
        except ExprError as e:
            self.ui.error(f"`{typ}`: {e}")
        except Exception as e:  # a bad prop must not take the whole page down
            self.ui.error(f"`{typ}`: {type(e).__name__}: {e}")

    def _slots(self, node):
        return node.get("slots") or [[]]

    # ---- text
    def r_title(self, n, p):
        self.ui.title(self.t(p.get("text")), self.t(p.get("subtitle")) or None)

    def r_header(self, n, p):
        self.ui.header(self.t(p.get("text")))

    def r_subheader(self, n, p):
        self.ui.subheader(self.t(p.get("text")))

    def r_text(self, n, p):
        self.ui.text(self.t(p.get("text")), muted=bool(p.get("muted")))

    def r_markdown(self, n, p):
        self.ui.markdown(self.t(p.get("text")))

    def r_caption(self, n, p):
        self.ui.caption(self.t(p.get("text")))

    def r_badge(self, n, p):
        self.ui.badge(self.t(p.get("text")), p.get("kind") or "accent")

    def r_link(self, n, p):
        self.ui.link(self.t(p.get("text")), self.t(p.get("url")) or "#")

    def r_code(self, n, p):
        self.ui.code(str(p.get("code") or ""), p.get("lang") or "python")

    def r_image(self, n, p):
        src = self.v(p.get("src"))
        if src:
            self.ui.image(src, caption=self.t(p.get("caption")) or None, width=self.n(p.get("width")))

    def r_divider(self, n, p):
        self.ui.divider()

    def r_space(self, n, p):
        self.ui.space(int(self.n(p.get("height"), 24)))

    # ---- feedback
    def r_alert(self, n, p):
        self.ui.alert(self.t(p.get("text")) or "", p.get("kind") or "info", self.t(p.get("title")) or None)

    def r_metric(self, n, p):
        val = self.v(p.get("value"))
        delta = self.v(p.get("delta"))
        self.ui.metric(self.t(p.get("label")), val if val is not None else "—", delta if delta not in ("", None) else None,
                       help=self.t(p.get("help")) or None, inverse=bool(p.get("inverse")))

    def r_progress(self, n, p):
        v = self.n(p.get("value"), 0) or 0
        self.ui.progress(max(0.0, min(100.0, float(v))) / 100, self.t(p.get("label")) or None)

    # ---- inputs
    def _set_env(self, p, v):
        if p.get("name"):
            self.env[p["name"]] = v

    def r_input(self, n, p):
        v = self.ui.input(self.t(p.get("label")), str(p.get("value") or ""), key=p.get("name") or n["id"],
                          placeholder=self.t(p.get("placeholder")) or None, type=p.get("itype") or "text",
                          help=self.t(p.get("help")) or None)
        self._set_env(p, v)

    def r_textarea(self, n, p):
        v = self.ui.textarea(self.t(p.get("label")), str(p.get("value") or ""), key=p.get("name") or n["id"],
                             placeholder=self.t(p.get("placeholder")) or None, rows=int(self.n(p.get("rows"), 4)),
                             help=self.t(p.get("help")) or None)
        self._set_env(p, v)

    def r_number(self, n, p):
        mn, mx, st = self.n(p.get("min")), self.n(p.get("max")), self.n(p.get("step"))
        v = self.ui.number(self.t(p.get("label")), self.n(p.get("value"), mn if mn is not None else 0),
                           key=p.get("name") or n["id"], min=mn, max=mx, step=st, help=self.t(p.get("help")) or None)
        self._set_env(p, v)

    def r_slider(self, n, p):
        mn, mx = self.n(p.get("min"), 0), self.n(p.get("max"), 100)
        if mx <= mn:
            mx = mn + 1
        val = self.n(p.get("value"), mn)
        val = min(max(val, mn), mx)
        v = self.ui.slider(self.t(p.get("label")), mn, mx, val, key=p.get("name") or n["id"],
                           step=self.n(p.get("step")), suffix=self.t(p.get("suffix")) or "",
                           help=self.t(p.get("help")) or None)
        self._set_env(p, v)

    def _options(self, p):
        o = p.get("options")
        if is_expr(o):
            r = self.v(o)
            return list(r) if isinstance(r, (list, tuple, set, dict)) else ([] if r is None else [r])
        return _as_list(o)

    def r_select(self, n, p):
        opts = self._options(p)
        default = p.get("value") if p.get("value") in opts else None
        if not opts:
            self.ui.select(self.t(p.get("label")), ["—"], key=p.get("name") or n["id"])
            self._set_env(p, None)
            return
        v = self.ui.select(self.t(p.get("label")), opts, default, key=p.get("name") or n["id"],
                           help=self.t(p.get("help")) or None)
        self._set_env(p, v)

    def r_radio(self, n, p):
        opts = self._options(p) or ["—"]
        default = p.get("value") if p.get("value") in opts else None
        v = self.ui.radio(self.t(p.get("label")), opts, default, key=p.get("name") or n["id"])
        self._set_env(p, v)

    def r_multiselect(self, n, p):
        opts = self._options(p)
        v = self.ui.multiselect(self.t(p.get("label")), opts, _as_list(p.get("value")), key=p.get("name") or n["id"])
        self._set_env(p, v)

    def r_checkbox(self, n, p):
        self._set_env(p, self.ui.checkbox(self.t(p.get("label")), bool(p.get("value")), key=p.get("name") or n["id"]))

    def r_toggle(self, n, p):
        self._set_env(p, self.ui.toggle(self.t(p.get("label")), bool(p.get("value")), key=p.get("name") or n["id"]))

    def r_date(self, n, p):
        self._set_env(p, self.ui.date(self.t(p.get("label")), key=p.get("name") or n["id"]))

    def r_color(self, n, p):
        self._set_env(p, self.ui.color(self.t(p.get("label")), p.get("value") or "#6366f1", key=p.get("name") or n["id"]))

    def r_upload(self, n, p):
        self._set_env(p, self.ui.upload(self.t(p.get("label")) or "Upload a file", key=p.get("name") or n["id"],
                                        accept=p.get("accept") or None))

    # ---- actions
    def r_button(self, n, p):
        page_vars = [name for name in self.app._widget_names]
        self.ui.button(self.t(p.get("label")) or "Button", key=n["id"], kind=p.get("kind") or "primary",
                       icon=p.get("icon") or None, full=bool(p.get("full")),
                       on_click=self.app.run_actions, args=(self.ui, p.get("actions") or [], page_vars))

    def r_download(self, n, p):
        content = h_as_text(self.v(p.get("content")))
        self.ui.download(self.t(p.get("label")) or "Download", content,
                         self.t(p.get("filename")) or "export.txt")

    # ---- data
    def r_table(self, n, p):
        data = data_of(p.get("data"), self.env, self.errs)
        if self.errs:
            raise ExprError(self.errs[0])
        if not data:
            self.ui.caption("No rows yet.")
            return
        self.ui.table(data, page_size=int(self.n(p.get("page_size"), 10)), search=bool(p.get("search", True)), key=n["id"])

    def r_chart(self, n, p):
        data = data_of(p.get("data"), self.env, self.errs)
        if self.errs:
            raise ExprError(self.errs[0])
        if not data:
            self.ui.caption("No data to chart yet.")
            return
        x = (self.t(p.get("x")) or "").strip() or None
        ys = [s.strip() for s in (self.t(p.get("y")) or "").split(",") if s.strip()] or None
        kind = str(self.v(p.get("kind")) or "line")
        self.ui.chart(data, x, ys, kind=kind if kind in ("line", "area", "bar", "pie") else "line", title=self.t(p.get("title")) or None,
                      height=int(self.n(p.get("height"), 280)), stacked=bool(p.get("stacked")), key=n["id"])

    def r_chat(self, n, p):
        ui, name = self.ui, p.get("name") or n["id"]
        skey = f"k:{name}"
        history = ui._s.values.get(skey)
        if not isinstance(history, list):
            history = []
        sub = ui._submitted
        if sub and sub[0] == f"k:{name}::in":
            msg = sub[1]
            history = history + [{"role": "user", "content": msg}]
            env = dict(self.env, message=msg, **{name: history})
            hook = (p.get("hook") or "").strip()
            try:
                if hook:
                    reply = self.app._fn(hook)(Context(ui, self.app._widget_names), msg)
                else:
                    reply = render_template(p.get("reply") or "{message}", env, self.errs)
            except Exception as e:
                reply = f"⚠ {type(e).__name__}: {e}"
            history = history + [{"role": "assistant", "content": "" if reply is None else str(reply)}]
            ui._s.values[skey] = history
        self.env[name] = history
        if p.get("greeting"):
            ui.chat_message("assistant", self.t(p.get("greeting")))
        for m in history:
            ui.chat_message(m.get("role", "assistant"), m.get("content", ""))
        ui.chat_input(self.t(p.get("placeholder")) or "Send a message…", key=f"{name}::in")

    # ---- layout
    def r_columns(self, n, p):
        cols = self.ui.columns(_widths(p.get("widths")), gap=p.get("gap") or "md")
        for c, slot in zip(cols, self._slots(n)):
            with c:
                self.nodes(slot)

    def r_card(self, n, p):
        with self.ui.card(self.t(p.get("title")) or None, self.t(p.get("subtitle")) or None):
            self.nodes(self._slots(n)[0])

    def r_row(self, n, p):
        with self.ui.row():
            self.nodes(self._slots(n)[0])

    def r_container(self, n, p):
        with self.ui.container():
            self.nodes(self._slots(n)[0])

    def r_tabs(self, n, p):
        labels = [self.t(x) for x in _as_list(p.get("labels"))] or ["Tab"]
        panes = self.ui.tabs(labels, key=n["id"])
        for pane, slot in zip(panes, self._slots(n)):
            with pane:
                self.nodes(slot)

    def r_expander(self, n, p):
        with self.ui.expander(self.t(p.get("label")) or "More", open=bool(p.get("open")), key=n["id"]):
            self.nodes(self._slots(n)[0])


# =========================================================================== public API
def read_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_spec(path: str, spec: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def load(spec: "str | dict", *, actions: dict | None = None) -> SpecApp:
    """Build a runnable app from a ``.velo.json`` file (or a dict)::

        app = velo.load("app.velo.json")
        app.run()
    """
    base = None
    if isinstance(spec, (str, os.PathLike)):
        base = os.path.dirname(os.path.abspath(spec))
        spec = read_spec(str(spec))
    return SpecApp(spec, base_dir=base, actions=actions)
