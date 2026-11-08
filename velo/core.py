"""Velo core: the App, per-browser Sessions and the UI builder.

Execution model (why Velo feels faster than "rerun the whole script" tools):

* Only the *page function* re-runs on an interaction, never your module
  (imports, model loading, DB connections run once).
* Callbacks (``on_click`` / ``on_change``) run *before* the re-render, so state
  is always consistent in a single pass.
* Expensive work is memoised with ``@velo.cache`` (TTL + LRU).
* The browser receives a compact component tree and *morphs* the DOM in place:
  no flicker, focus and cursor position are preserved, tables keep their
  sort/search/page state, tabs switch instantly on the client.
* Text inputs are debounced and sliders throttled in the browser, so typing
  never floods the server.
"""
from __future__ import annotations

import base64
import collections
import datetime as _dt
import functools
import json
import math
import mimetypes
import os
import pickle
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Iterable

from .markdown import render as _md, inline as _md_inline

_APPS: list["App"] = []
_INVALID = object()


class Rerun(Exception):
    """Raise (or call ``ui.rerun()``) to immediately re-run the page."""


class State(dict):
    """Per-session state with attribute access: ``ui.state.count += 1``."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"state has no '{name}'. Initialise it first, e.g. ui.init({name}=...)"
            ) from None

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        self.pop(name, None)


class UploadedFile:
    """A file sent from the browser via ``ui.upload``."""

    def __init__(self, name: str, type: str, data: bytes):
        self.name, self.type, self.data = name, type or "application/octet-stream", data

    @property
    def size(self) -> int:
        return len(self.data)

    def text(self, encoding: str = "utf-8") -> str:
        return self.data.decode(encoding, errors="replace")

    def __repr__(self):
        return f"UploadedFile(name={self.name!r}, type={self.type!r}, size={self.size})"


class Node:
    __slots__ = ("t", "p", "k", "c")

    def __init__(self, t: str, p: dict | None = None, k: str | None = None):
        self.t, self.p, self.k, self.c = t, p or {}, k, []

    def to_json(self) -> dict:
        d: dict = {"t": self.t}
        if self.k:
            d["k"] = self.k
        if self.p:
            d["p"] = self.p
        if self.c:
            d["c"] = [c.to_json() for c in self.c]
        return d


# --------------------------------------------------------------------------- data helpers

def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if hasattr(v, "item") and callable(v.item) and not isinstance(v, (list, tuple, dict)):
        try:
            return _jsonable(v.item())
        except Exception:
            pass
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if hasattr(v, "tolist"):
        return _jsonable(v.tolist())
    return str(v)


def _tabular(data: Any, columns: Iterable | None = None) -> tuple[list[str], list[list]]:
    """Normalise DataFrames, dicts, lists of dicts/lists into (columns, rows)."""
    if data is None:
        return [], []
    if hasattr(data, "columns") and hasattr(data, "values") and hasattr(data, "to_dict"):  # DataFrame
        cols = [str(c) for c in data.columns]
        return cols, [[_jsonable(x) for x in row] for row in data.values.tolist()]
    if hasattr(data, "to_frame") and hasattr(data, "index"):  # Series
        return _tabular(data.reset_index())
    if isinstance(data, dict):
        vals = list(data.values())
        if vals and all(isinstance(v, (list, tuple)) or hasattr(v, "tolist") for v in vals):
            vals = [list(v.tolist() if hasattr(v, "tolist") else v) for v in vals]
            n = max(len(v) for v in vals)
            rows = [[_jsonable(v[i]) if i < len(v) else None for v in vals] for i in range(n)]
            return [str(k) for k in data], rows
        return ["key", "value"], [[str(k), _jsonable(v)] for k, v in data.items()]
    data = list(data)
    if not data:
        return [str(c) for c in (columns or [])], []
    if isinstance(data[0], dict):
        cols: list = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
        return [str(c) for c in cols], [[_jsonable(r.get(c)) for c in cols] for r in data]
    if isinstance(data[0], (list, tuple)):
        n = max(len(r) for r in data)
        cols = list(columns) if columns else [f"col{i + 1}" for i in range(n)]
        return [str(c) for c in cols], [[_jsonable(x) for x in r] for r in data]
    cols = list(columns) if columns else ["value"]
    return [str(cols[0])], [[_jsonable(x)] for x in data]


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _chart_data(data, x=None, y=None):
    if isinstance(data, (list, tuple)) and data and all(_is_num(v) or v is None for v in data):
        data = {"value": list(data)}
    cols, rows = _tabular(data)
    if not cols:
        return [], []
    num = {c: any(_is_num(r[i]) for r in rows) and all(_is_num(r[i]) or r[i] is None for r in rows)
           for i, c in enumerate(cols)}
    if x is None and not num[cols[0]] and len(cols) > 1:
        x = cols[0]
    if x is not None and x not in cols:
        raise ValueError(f"x column '{x}' not found. Columns: {cols}")
    ys = [y] if isinstance(y, str) else list(y) if y else [c for c in cols if num[c] and c != x]
    for c in ys:
        if c not in cols:
            raise ValueError(f"y column '{c}' not found. Columns: {cols}")
    xs = [r[cols.index(x)] for r in rows] if x is not None else list(range(len(rows)))
    series = [{"name": c, "data": [r[cols.index(c)] if _is_num(r[cols.index(c)]) else None for r in rows]}
              for c in ys]
    return xs, series


def _data_url(data: bytes, mime: str | None = None) -> str:
    if not mime:
        head = data[:12]
        if head.startswith(b"\x89PNG"):
            mime = "image/png"
        elif head[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif head[:4] == b"GIF8":
            mime = "image/gif"
        elif head[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        elif b"<svg" in data[:200]:
            mime = "image/svg+xml"
        else:
            mime = "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _fmt_value(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1e15 else f"{v:.3g}"
    return str(v)


# --------------------------------------------------------------------------- caching

def cache(fn: Callable | None = None, *, ttl: float | None = None, maxsize: int = 256):
    """Memoise an expensive function across all sessions and re-runs.

    >>> @velo.cache(ttl=60)
    ... def load(path): ...
    """
    def deco(f):
        store: "collections.OrderedDict[bytes, tuple[float, Any]]" = collections.OrderedDict()
        lock = threading.Lock()

        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                key = pickle.dumps((args, sorted(kwargs.items())), protocol=4)
            except Exception:
                key = repr((args, sorted(kwargs.items()))).encode()
            now = time.time()
            with lock:
                hit = store.get(key)
                if hit and (ttl is None or now - hit[0] < ttl):
                    store.move_to_end(key)
                    return hit[1]
            value = f(*args, **kwargs)
            with lock:
                store[key] = (now, value)
                store.move_to_end(key)
                while len(store) > maxsize:
                    store.popitem(last=False)
            return value

        wrapper.clear = store.clear  # type: ignore[attr-defined]
        return wrapper

    return deco(fn) if callable(fn) else deco


# --------------------------------------------------------------------------- session

class Session:
    def __init__(self, sid: str):
        self.id = sid
        self.state = State()
        self.values: dict[str, Any] = {}
        self.widgets: dict[str, dict] = {}
        self.callbacks: dict[str, tuple] = {}
        self.toasts: list[dict] = []
        self.lock = threading.RLock()
        self.last_seen = time.time()
        self.path = "/"
        self.pending_nav: str | None = None


class _Ctx:
    """A layout container usable as ``with`` block or as a proxy: ``col.metric(...)``."""

    def __init__(self, ui: "UI", node: Node):
        self._ui, self._node = ui, node

    def __enter__(self):
        self._ui._stack.append(self._node)
        return self

    def __exit__(self, *exc):
        self._ui._stack.pop()
        return False

    def __getattr__(self, name):
        attr = getattr(self._ui, name)
        if not callable(attr):
            return attr

        def call(*a, **kw):
            with self:
                return attr(*a, **kw)

        return call


# --------------------------------------------------------------------------- UI builder

class UI:
    """The object passed to every page function. All components live here."""

    def __init__(self, app: "App", session: Session, clicked: str | None, submitted: tuple | None):
        self.app = app
        self._s = session
        self.state: State = session.state
        self._root = Node("root")
        self._side = Node("side")
        self._stack: list[Node] = [self._root]
        self._counts: dict[str, int] = {}
        self._seen: set[str] = set()
        self._clicked = clicked
        self._submitted = submitted
        self._callbacks: dict[str, tuple] = {}
        self._widgets: dict[str, dict] = {}
        self._refresh: float | None = None
        self._navigate: str | None = None

    # ---- internals -------------------------------------------------------
    def _add(self, t: str, p: dict | None = None, k: str | None = None) -> Node:
        node = Node(t, {a: b for a, b in (p or {}).items() if b is not None}, k)
        self._stack[-1].c.append(node)
        return node

    def _key(self, kind: str, label: Any, key: str | None) -> str:
        if key is not None:
            k = f"k:{key}"
            if k in self._seen:
                raise ValueError(f"Duplicate widget key {key!r}. Keys must be unique on a page.")
        else:
            base = f"{kind}:{label}"
            n = self._counts.get(base, 0)
            self._counts[base] = n + 1
            k = base if n == 0 else f"{base}#{n}"
        self._seen.add(k)
        return k

    def _val(self, k: str, default: Any) -> Any:
        if k not in self._s.values:
            self._s.values[k] = default
        return self._s.values[k]

    def _cb(self, k: str, fn, args=None, kwargs=None):
        if fn is not None:
            self._callbacks[k] = (fn, tuple(args or ()), dict(kwargs or {}))

    # ---- state helpers ---------------------------------------------------
    def init(self, **defaults) -> State:
        """Set state defaults once per session: ``ui.init(count=0, todos=[])``."""
        for k, v in defaults.items():
            if k not in self.state:
                self.state[k] = v
        return self.state

    def get(self, key: str, default=None):
        """Read the current value of a widget by its ``key=``."""
        return self._s.values.get(f"k:{key}", default)

    def set(self, key: str, value):
        """Programmatically set a widget's value by its ``key=``."""
        self._s.values[f"k:{key}"] = value

    @property
    def session_id(self) -> str:
        return self._s.id

    def rerun(self):
        raise Rerun()

    def navigate(self, path: str):
        """Go to another page. Works in the page body *and* inside on_click callbacks."""
        self._navigate = path
        self._s.pending_nav = path

    def reset(self, *keys: str):
        """Reset widgets (by ``key=``) to their defaults. No keys: reset every widget on the session."""
        if not keys:
            self._s.values.clear()
        for k in keys:
            self._s.values.pop(f"k:{k}", None)

    def autorefresh(self, seconds: float):
        """Re-run this page every ``seconds`` while it is open (live dashboards)."""
        self._refresh = max(0.25, float(seconds))

    # ---- text ------------------------------------------------------------
    def title(self, text, subtitle: str | None = None):
        self._add("title", {"text": str(text), "sub": subtitle})

    def header(self, text):
        self._add("heading", {"text": str(text), "level": 2})

    def subheader(self, text):
        self._add("heading", {"text": str(text), "level": 3})

    def text(self, text, *, muted: bool = False):
        self._add("text", {"text": str(text), "muted": muted or None})

    def caption(self, text):
        self._add("text", {"text": str(text), "muted": True, "small": True})

    def markdown(self, text):
        self._add("md", {"html": _md(text)})

    md = markdown

    def html(self, raw: str):
        """Insert raw, trusted HTML."""
        self._add("html", {"html": str(raw)})

    def divider(self):
        self._add("divider")

    def space(self, height: int = 16):
        self._add("space", {"h": int(height)})

    def code(self, code: str, lang: str = "python"):
        self._add("code", {"code": str(code).strip("\n"), "lang": lang})

    def json(self, obj):
        self.code(json.dumps(_jsonable(obj), indent=2, ensure_ascii=False), "json")

    def link(self, text, url: str):
        self._add("link", {"text": str(text), "url": url})

    def badge(self, text, kind: str = "accent"):
        self._add("badge", {"text": str(text), "kind": kind})

    # ---- feedback --------------------------------------------------------
    def alert(self, text, kind: str = "info", title: str | None = None):
        self._add("alert", {"html": _md(text), "kind": kind, "title": title})

    def info(self, text, title=None):
        self.alert(text, "info", title)

    def success(self, text, title=None):
        self.alert(text, "success", title)

    def warning(self, text, title=None):
        self.alert(text, "warning", title)

    def error(self, text, title=None):
        self.alert(text, "error", title)

    def toast(self, text, kind: str = "info"):
        """Show a short notification in the corner."""
        self._s.toasts.append({"text": str(text), "kind": kind})

    def metric(self, label, value, delta=None, *, help: str | None = None, inverse: bool = False):
        up, d = None, None
        if delta is not None:
            if _is_num(delta):
                up, d = delta >= 0, ("+" if delta >= 0 else "") + _fmt_value(delta)
            else:
                d = str(delta)
                up = not d.strip().startswith("-")
        good = None if up is None else (up != inverse)
        self._add("metric", {"label": str(label), "value": _fmt_value(value), "delta": d, "up": up,
                             "good": good, "help": help})

    def progress(self, value: float, label: str | None = None):
        v = float(value)
        v = v / 100 if v > 1 else v
        self._add("progress", {"value": max(0.0, min(1.0, v)), "label": label})

    def image(self, src, caption: str | None = None, width: int | None = None):
        if isinstance(src, (bytes, bytearray)):
            src = _data_url(bytes(src))
        elif isinstance(src, str) and not src.startswith(("http:", "https:", "data:", "/")) and os.path.isfile(src):
            with open(src, "rb") as f:
                src = _data_url(f.read(), mimetypes.guess_type(src)[0])
        elif hasattr(src, "save"):  # PIL image
            import io
            buf = io.BytesIO()
            src.save(buf, format="PNG")
            src = _data_url(buf.getvalue(), "image/png")
        self._add("image", {"src": str(src), "caption": caption, "width": width})

    # ---- widgets ---------------------------------------------------------
    def button(self, label, key: str | None = None, *, kind: str = "primary", icon: str | None = None,
               on_click: Callable | None = None, args=None, kwargs=None, full: bool = False,
               disabled: bool = False) -> bool:
        """A button. Returns True on the run triggered by its click.
        ``kind``: primary | secondary | ghost | danger."""
        k = self._key("button", label, key)
        self._cb(k, on_click, args, kwargs)
        self._add("button", {"label": str(label), "kind": kind, "icon": icon,
                             "full": full or None, "disabled": disabled or None}, k)
        return self._clicked == k

    def input(self, label, value: str = "", key: str | None = None, *, placeholder: str | None = None,
              type: str = "text", help: str | None = None, on_change=None, args=None, disabled=False) -> str:
        """Single-line text input (``type`` may be text, password, email, url…)."""
        k = self._key("input", label, key)
        v = self._val(k, value)
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "text"}
        self._add("input", {"label": label, "value": v, "ph": placeholder, "itype": type, "help": help,
                            "disabled": disabled or None}, k)
        return v

    text_input = input

    def textarea(self, label, value: str = "", key: str | None = None, *, placeholder=None, rows: int = 4,
                 help=None, on_change=None, args=None) -> str:
        k = self._key("textarea", label, key)
        v = self._val(k, value)
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "text"}
        self._add("textarea", {"label": label, "value": v, "ph": placeholder, "rows": rows, "help": help}, k)
        return v

    def number(self, label, value: float = 0, key: str | None = None, *, min=None, max=None, step=None,
               help=None, on_change=None, args=None):
        k = self._key("number", label, key)
        is_int = all(isinstance(x, int) for x in (value, min, max, step) if x is not None)
        v = self._val(k, value)
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "number", "int": is_int, "min": min, "max": max}
        self._add("number", {"label": label, "value": v, "min": min, "max": max,
                             "step": step if step is not None else (1 if is_int else "any"), "help": help}, k)
        return v

    def slider(self, label, min=0, max=100, value=None, key: str | None = None, *, step=None,
               help=None, on_change=None, args=None, suffix: str = ""):
        k = self._key("slider", label, key)
        is_int = all(isinstance(x, int) for x in (min, max, value, step) if x is not None)
        step = step if step is not None else (1 if is_int else (max - min) / 100)
        v = self._val(k, min if value is None else value)
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "number", "int": is_int, "min": min, "max": max}
        self._add("slider", {"label": label, "value": v, "min": min, "max": max, "step": step,
                             "help": help, "suffix": suffix or None}, k)
        return v

    def select(self, label, options, value=None, key: str | None = None, *, format: Callable | None = None,
               help=None, on_change=None, args=None):
        """Dropdown. Returns the selected option object itself (any type)."""
        options = list(options)
        k = self._key("select", label, key)
        default = value if value is not None else (options[0] if options else None)
        v = self._val(k, default)
        if options and v not in options:
            v = self._s.values[k] = default if default in options else options[0]
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "option", "options": options}
        labels = [str(format(o) if format else o) for o in options]
        self._add("select", {"label": label, "options": labels, "index": options.index(v) if options else -1,
                             "help": help}, k)
        return v

    def radio(self, label, options, value=None, key: str | None = None, *, format=None,
              on_change=None, args=None):
        """Segmented control — great for 2-6 choices."""
        options = list(options)
        k = self._key("radio", label, key)
        default = value if value is not None else options[0]
        v = self._val(k, default)
        if v not in options:
            v = self._s.values[k] = options[0]
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "option", "options": options}
        self._add("radio", {"label": label, "options": [str(format(o) if format else o) for o in options],
                            "index": options.index(v)}, k)
        return v

    segmented = radio

    def multiselect(self, label, options, value=None, key: str | None = None, *, format=None,
                    on_change=None, args=None) -> list:
        """Toggleable chips. Returns a list of selected options."""
        options = list(options)
        k = self._key("multiselect", label, key)
        default = [o for o in (value or []) if o in options]
        stored = self._val(k, default)
        v = [o for o in stored if o in options]
        if stored and not v:  # options changed underneath us -> fall back to the default
            v = default
        self._s.values[k] = v
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "options", "options": options}
        self._add("multiselect", {"label": label, "options": [str(format(o) if format else o) for o in options],
                                  "selected": [options.index(o) for o in v]}, k)
        return v

    def checkbox(self, label, value: bool = False, key: str | None = None, *, on_change=None, args=None) -> bool:
        k = self._key("checkbox", label, key)
        v = bool(self._val(k, value))
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "bool"}
        self._add("checkbox", {"label": str(label), "value": v}, k)
        return v

    def toggle(self, label, value: bool = False, key: str | None = None, *, on_change=None, args=None) -> bool:
        k = self._key("toggle", label, key)
        v = bool(self._val(k, value))
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "bool"}
        self._add("checkbox", {"label": str(label), "value": v, "toggle": True}, k)
        return v

    def date(self, label, value: _dt.date | None = None, key: str | None = None, *, on_change=None, args=None):
        k = self._key("date", label, key)
        v = self._val(k, value or _dt.date.today())
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "date"}
        self._add("input", {"label": label, "value": v.isoformat() if v else "", "itype": "date"}, k)
        return v

    def color(self, label, value: str = "#6366f1", key: str | None = None, *, on_change=None, args=None) -> str:
        k = self._key("color", label, key)
        v = self._val(k, value)
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "text"}
        self._add("input", {"label": label, "value": v, "itype": "color"}, k)
        return v

    def upload(self, label="Upload a file", key: str | None = None, *, accept: str | None = None,
               multiple: bool = False, on_change=None, args=None):
        """File picker with drag & drop. Returns UploadedFile, a list (multiple=True) or None."""
        k = self._key("upload", label, key)
        v = self._val(k, [] if multiple else None)
        self._cb(k, on_change, args)
        self._widgets[k] = {"kind": "files", "multiple": multiple}
        files = v if isinstance(v, list) else ([v] if v else [])
        self._add("upload", {"label": label, "accept": accept, "multiple": multiple or None,
                             "files": [f"{f.name} ({f.size:,} bytes)" for f in files]}, k)
        return v

    def download(self, label, data, filename: str, mime: str | None = None):
        if isinstance(data, str):
            data = data.encode()
        mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        self._add("download", {"label": str(label), "href": _data_url(bytes(data), mime), "filename": filename})

    # ---- chat ------------------------------------------------------------
    def chat_message(self, role: str, content, avatar: str | None = None):
        avatar = avatar or {"user": "🧑", "assistant": "✨", "system": "⚙️"}.get(role, "💬")
        self._add("chat", {"role": role, "html": _md(content), "avatar": avatar})

    def chat_input(self, placeholder: str = "Send a message…", key: str | None = None) -> str | None:
        """Returns the submitted message on the run it was sent, otherwise None."""
        k = self._key("chat_input", placeholder, key)
        self._add("chat_input", {"ph": placeholder}, k)
        return self._submitted[1] if self._submitted and self._submitted[0] == k else None

    # ---- data ------------------------------------------------------------
    def table(self, data, columns=None, *, page_size: int = 10, search: bool = True, height: int | None = None,
              key: str | None = None):
        """Sortable, searchable, paginated table (DataFrame, dicts, lists…)."""
        cols, rows = _tabular(data, columns)
        k = self._key("table", ",".join(cols), key)
        self._add("table", {"cols": cols, "rows": rows, "page": int(page_size), "search": search or None,
                            "height": height}, k)

    dataframe = table

    def chart(self, data, x=None, y=None, *, kind: str = "line", title: str | None = None,
              height: int = 300, stacked: bool = False, key: str | None = None):
        xs, series = _chart_data(data, x, y)
        k = self._key("chart", f"{kind}:{title}", key)
        self._add("chart", {"kind": kind, "x": _jsonable(xs), "series": series, "title": title,
                            "height": height, "stacked": stacked or None}, k)

    def line_chart(self, data, x=None, y=None, **kw):
        self.chart(data, x, y, kind="line", **kw)

    def area_chart(self, data, x=None, y=None, **kw):
        self.chart(data, x, y, kind="area", **kw)

    def bar_chart(self, data, x=None, y=None, **kw):
        self.chart(data, x, y, kind="bar", **kw)

    def pie_chart(self, data, labels=None, values=None, **kw):
        self.chart(data, labels, values, kind="pie", **kw)

    # ---- layout ----------------------------------------------------------
    def columns(self, spec: int | list = 2, gap: str = "md") -> list[_Ctx]:
        widths = [1] * spec if isinstance(spec, int) else list(spec)
        node = self._add("columns", {"gap": gap})
        out = []
        for w in widths:
            c = Node("col", {"w": w})
            node.c.append(c)
            out.append(_Ctx(self, c))
        return out

    def card(self, title: str | None = None, subtitle: str | None = None) -> _Ctx:
        return _Ctx(self, self._add("card", {"title": title, "sub": subtitle}))

    def row(self) -> _Ctx:
        """Horizontal, wrapping flex row (e.g. a group of buttons)."""
        return _Ctx(self, self._add("row"))

    def container(self) -> _Ctx:
        return _Ctx(self, self._add("container"))

    def tabs(self, labels: list[str], key: str | None = None) -> list[_Ctx]:
        labels = [str(l) for l in labels]
        k = self._key("tabs", "|".join(labels), key)
        idx = self._val(k, 0)
        idx = idx if 0 <= idx < len(labels) else 0
        self._widgets[k] = {"kind": "index", "n": len(labels)}
        node = self._add("tabs", {"labels": labels, "index": idx}, k)
        panes = []
        for _ in labels:
            p = Node("panel")
            node.c.append(p)
            panes.append(_Ctx(self, p))
        return panes

    def expander(self, label: str, open: bool = False, key: str | None = None) -> _Ctx:
        k = self._key("expander", label, key)
        v = bool(self._val(k, open))
        self._widgets[k] = {"kind": "bool"}
        return _Ctx(self, self._add("expander", {"label": str(label), "open": v}, k))

    @property
    def sidebar(self) -> _Ctx:
        return _Ctx(self, self._side)


# --------------------------------------------------------------------------- app

class App:
    """A Velo application.

    >>> app = velo.App("My app", theme="auto", accent="#6366f1")
    >>> @app.page("/")
    ... def home(ui): ui.title("Hello")
    >>> app.run()
    """

    def __init__(self, title: str = "Velo App", *, icon: str = "⚡", theme: str = "auto",
                 accent: str = "#6366f1", wide: bool = False, session_ttl: int = 3600 * 6):
        self.title, self.icon, self.theme, self.accent, self.wide = title, icon, theme, accent, wide
        self.session_ttl = session_ttl
        self.pages: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        self.sessions: dict[str, Session] = {}
        self.prod = False
        self._lock = threading.Lock()
        self._streams: dict[str, set] = {}
        self._streams_lock = threading.Lock()
        _APPS.append(self)

    # ---- registration ----------------------------------------------------
    def page(self, path: str = "/", title: str | None = None, icon: str | None = None):
        if not path.startswith("/"):
            path = "/" + path

        def deco(fn):
            self.pages[path] = {"fn": fn, "title": title or fn.__name__.replace("_", " ").title(),
                                "icon": icon or "•"}
            return fn

        return deco

    cache = staticmethod(cache)

    def _adopt(self, other: "App"):
        """Hot reload: take the new code, keep the live sessions."""
        self.pages = other.pages
        for a in ("title", "icon", "theme", "accent", "wide", "session_ttl"):
            setattr(self, a, getattr(other, a))

    # ---- sessions / push -------------------------------------------------
    def session(self, sid: str) -> Session:
        with self._lock:
            s = self.sessions.get(sid)
            if s is None:
                s = self.sessions[sid] = Session(sid)
            s.last_seen = time.time()
            return s

    def gc(self):
        cutoff = time.time() - self.session_ttl
        with self._lock:
            for sid in [k for k, s in self.sessions.items() if s.last_seen < cutoff and not self._streams.get(k)]:
                del self.sessions[sid]

    def _subscribe(self, sid: str, q):
        with self._streams_lock:
            self._streams.setdefault(sid, set()).add(q)

    def _unsubscribe(self, sid: str, q):
        with self._streams_lock:
            qs = self._streams.get(sid)
            if qs:
                qs.discard(q)
                if not qs:
                    del self._streams[sid]

    def broadcast(self, event: str, data: Any = None, sid: str | None = None):
        with self._streams_lock:
            targets = [q for k, qs in self._streams.items() if sid is None or k == sid for q in qs]
        for q in targets:
            q.put((event, data))

    def push(self, session_id: str | None = None):
        """Ask open browsers (one session or all) to re-render now.
        Call from background threads, schedulers, webhooks…"""
        self.broadcast("rerun", None, session_id)

    # ---- the render loop -------------------------------------------------
    @staticmethod
    def _coerce(meta: dict, v):
        kind = meta.get("kind")
        try:
            if kind == "number":
                if v is None or v == "":
                    return _INVALID
                f = float(v)
                if math.isnan(f):
                    return _INVALID
                if meta.get("min") is not None:
                    f = max(f, meta["min"])
                if meta.get("max") is not None:
                    f = min(f, meta["max"])
                return int(round(f)) if meta.get("int") else f
            if kind == "option":
                return meta["options"][int(v)]
            if kind == "options":
                return [meta["options"][int(i)] for i in v]
            if kind == "bool":
                return bool(v)
            if kind == "index":
                i = int(v)
                return i if 0 <= i < meta.get("n", 1 << 30) else _INVALID
            if kind == "date":
                return _dt.date.fromisoformat(v) if v else None
            if kind == "files":
                files = [UploadedFile(f.get("name", "file"), f.get("type", ""), base64.b64decode(f.get("data", "")))
                         for f in (v or [])]
                return files if meta.get("multiple") else (files[0] if files else None)
        except (ValueError, TypeError, IndexError, KeyError):
            return _INVALID
        return "" if v is None else str(v)

    def dispatch(self, sid: str, path: str, event: dict | None) -> dict:
        s = self.session(sid or uuid.uuid4().hex)
        with s.lock:
            s.path = path
            clicked = submitted = None
            errors: list[str] = []
            if event:
                typ, k = event.get("type"), event.get("k")
                if typ == "set" and k in s.widgets:
                    v = self._coerce(s.widgets[k], event.get("v"))
                    if v is not _INVALID:
                        s.values[k] = v
                elif typ == "click":
                    clicked = k
                elif typ == "submit":
                    submitted = (k, str(event.get("v", "")))
                if typ in ("set", "click", "submit") and k in s.callbacks:
                    fn, a, kw = s.callbacks[k]
                    try:
                        fn(*a, **kw)
                    except Exception:
                        errors.append(traceback.format_exc())

            page = self.pages.get(path) or self.pages.get(path.rstrip("/") or "/")
            ui = None
            for _ in range(5):
                ui = UI(self, s, clicked, submitted)
                for tb in errors:
                    ui._add("error", {"text": "Error in callback", "tb": None if self.prod else tb})
                if page is None:
                    ui._add("notfound", {"path": path})
                    break
                try:
                    page["fn"](ui)
                    break
                except Rerun:
                    clicked = submitted = None
                    errors = []
                    continue
                except Exception as e:
                    ui._add("error", {"text": f"{type(e).__name__}: {e}",
                                      "tb": None if self.prod else _user_tb()})
                    break

            s.callbacks, s.widgets = ui._callbacks, ui._widgets
            toasts, s.toasts = s.toasts, []
            nav, s.pending_nav = s.pending_nav, None
            return {
                "tree": [c.to_json() for c in ui._root.c],
                "side": [c.to_json() for c in ui._side.c],
                "nav": [{"path": p, "title": v["title"], "icon": v["icon"]} for p, v in self.pages.items()]
                if len(self.pages) > 1 else [],
                "app": {"title": self.title, "icon": self.icon},
                "page": page["title"] if page and len(self.pages) > 1 else None,
                "toasts": toasts,
                "refresh": ui._refresh,
                "navigate": nav if nav and nav != path else None,
            }

    # ---- running ---------------------------------------------------------
    def run(self, host: str | None = None, port: int | None = None, *, reload: bool | None = None,
            prod: bool | None = None, open: bool = False):
        """Start the server. Dev mode (default) has hot reload; ``prod=True`` for deployment.
        Honours $PORT and $VELO_HOST, so it runs as-is on Render, Railway, Fly, Heroku, Docker…"""
        from . import server
        if server.SUPPRESS_RUN or server.RUNNING:
            return
        import sys
        main = getattr(sys.modules.get("__main__"), "__file__", None)
        server.serve(self, host, port, reload=reload, prod=prod, open_browser=open, main_file=main)


def _user_tb() -> str:
    """Traceback with Velo's own frames removed, so users see *their* code."""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    etype, value, tb = sys.exc_info()
    frames = [f for f in traceback.extract_tb(tb) if not os.path.abspath(f.filename).startswith(here)]
    return "".join(traceback.format_list(frames) + traceback.format_exception_only(etype, value))
