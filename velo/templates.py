"""Starter apps for Velo Studio (and ``velo studio --template <name>``)."""
from __future__ import annotations

from .spec import make_node as N, normalize


def M(**kw):
    """A metric without the catalog's example delta."""
    kw.setdefault("delta", "")
    return N("metric", **kw)


def _slots(node, *slots):
    node["slots"] = [list(s) for s in slots]
    return node


def blank():
    return {"app": {"title": "My Velo App", "icon": "⚡"},
            "pages": [{"path": "/", "title": "Home", "icon": "🏠", "body": [
                N("title", text="My Velo App", subtitle="Drag components from the left to build your app."),
            ]}]}


def hello():
    return {"app": {"title": "Hello Velo", "icon": "👋", "accent": "#6366f1"},
            "state": {"clicks": 0},
            "pages": [{"path": "/", "title": "Home", "icon": "🏠", "body": [
                N("title", text="Hello, {name or 'world'} 👋", subtitle="Type your name — the title updates live."),
                N("input", name="name", label="What's your name?", placeholder="Ada Lovelace"),
                N("slider", name="excitement", label="How excited are you?", min=1, max=10, value=7),
                N("text", text="Excitement: {'🎉' * excitement}"),
                _slots(N("row"), [
                    N("button", label="Click me", icon="✨", actions=[
                        {"do": "set", "var": "clicks", "value": "=clicks + 1"},
                        {"do": "toast", "text": "Thanks {name or 'friend'}! ({clicks} clicks)", "kind": "success"}]),
                    N("button", label="Reset", kind="secondary", actions=[
                        {"do": "set", "var": "clicks", "value": "0"}, {"do": "reset", "vars": ""}]),
                    N("badge", text="{clicks} clicks"),
                ]),
            ]}]}


SALES = """month,region,sales,costs
Jan,North,120,80
Jan,South,90,60
Feb,North,150,90
Feb,South,110,70
Mar,North,170,95
Mar,South,140,85
Apr,North,210,120
Apr,South,160,90
May,North,260,130
May,South,190,100
Jun,North,300,150
Jun,South,220,110"""


def dashboard():
    sales = "=where(csv(SALES_CSV), 'region', region)"
    return {
        "app": {"title": "Sales Dashboard", "icon": "📊", "accent": "#10b981", "wide": True},
        "state": {"SALES_CSV": SALES},
        "pages": [
            {"path": "/", "title": "Overview", "icon": "📊",
             "sidebar": [
                 N("header", text="Filters"),
                 N("multiselect", name="region", label="Region", options=["North", "South"], value=["North", "South"]),
                 N("caption", text="Charts update instantly as you change filters."),
             ],
             "body": [
                 N("title", text="Sales overview", subtitle="First half of the year · {len(region)} region(s) selected"),
                 _slots(N("columns", widths="1,1,1"), [
                     M(label="Total sales", value="=fmt(sum(col(" + sales[1:] + ", 'sales')))", delta="+18%"),
                 ], [
                     M(label="Total costs", value="=fmt(sum(col(" + sales[1:] + ", 'costs')))", delta="+9%", inverse=True),
                 ], [
                     M(label="Profit", value="=fmt(sum(col(" + sales[1:] + ", 'sales')) - sum(col(" + sales[1:] + ", 'costs')))", delta="+27%"),
                 ]),
                 _slots(N("tabs", labels=["Trend", "By region", "Raw data"]), [
                     N("chart", kind="area", data="=group(" + sales[1:] + ", 'month', 'sales')", x="month", y="sales",
                       title="Sales by month"),
                 ], [
                     N("chart", kind="pie", data="=group(" + sales[1:] + ", 'region', 'sales')", x="region", y="sales",
                       title="Share by region"),
                 ], [
                     N("table", data=sales),
                     N("download", label="Download CSV", content=sales, filename="sales.csv"),
                 ]),
             ]},
            {"path": "/about", "title": "About", "icon": "ℹ️", "body": [
                N("title", text="About this dashboard"),
                N("markdown", text="Built with **Velo Studio** — no code.\n\n"
                                   "Every number is a live formula, like a spreadsheet: `=sum(col(data, 'sales'))`."),
            ]},
        ]}


def form():
    return {
        "app": {"title": "Registration", "icon": "📝", "accent": "#8b5cf6"},
        "state": {"entries": []},
        "pages": [{"path": "/", "title": "Register", "icon": "📝", "body": [
            N("title", text="Workshop registration", subtitle="{len(entries)} people registered so far"),
            _slots(N("columns", widths="3,2"), [
                _slots(N("card", title="Your details"), [
                    N("input", name="full_name", label="Full name", placeholder="Ada Lovelace"),
                    N("input", name="email", label="Email", placeholder="ada@example.com", itype="email"),
                    N("select", name="track", label="Track", options=["Python basics", "Data analysis", "Web apps"]),
                    N("slider", name="experience", label="Years of experience", min=0, max=20, value=2),
                    N("checkbox", name="agree", label="I agree to the code of conduct"),
                    N("button", label="Register", icon="✅", full=True, actions=[
                        {"do": "toast", "if": "not full_name or '@' not in email",
                         "text": "Please enter your name and a valid email", "kind": "warning"},
                        {"do": "toast", "if": "full_name and '@' in email and not agree",
                         "text": "Please accept the code of conduct", "kind": "warning"},
                        {"do": "append", "var": "entries", "if": "full_name and '@' in email and agree",
                         "value": "={'name': full_name, 'email': email, 'track': track, 'experience': experience}"},
                        {"do": "toast", "if": "full_name and '@' in email and agree",
                         "text": "Welcome aboard, {full_name}! 🎉", "kind": "success"},
                        {"do": "reset", "if": "full_name and '@' in email and agree", "vars": "full_name email agree"},
                    ]),
                ]),
            ], [
                M(label="Registrations", value="=len(entries)"),
                N("chart", kind="pie", data="=group(entries, 'track')", x="track", y="count",
                  title="By track", height=220),
            ]),
            {**_slots(N("card", title="Registered people"), [
                N("table", data="=entries"),
                _slots(N("row"), [
                    N("download", label="Export CSV", content="=entries", filename="registrations.csv"),
                    N("button", label="Clear all", kind="danger", actions=[{"do": "clear", "var": "entries"}]),
                ]),
            ]), "show_if": "len(entries) > 0"},
        ]}]}


def explorer():
    rows = "csv(file) if file else csv(SAMPLE)"
    return {
        "app": {"title": "Data Explorer", "icon": "🔎", "accent": "#0ea5e9", "wide": True},
        "state": {"SAMPLE": SALES},
        "pages": [{"path": "/", "title": "Explore", "icon": "🔎",
                   "sidebar": [
                       N("upload", name="file", label="Upload your CSV", accept=".csv"),
                       N("caption", text="No file? A sample dataset is used."),
                       N("select", name="x_col", label="X axis", options=f"=columns({rows})"),
                       N("select", name="y_col", label="Y axis", options=f"=columns({rows})", value="sales"),
                       N("radio", name="kind", label="Chart", options=["bar", "line", "area", "pie"]),
                   ],
                   "body": [
                       N("title", text="Data explorer",
                         subtitle="{file.name if file else 'sample.csv'} · {len(" + rows + ")} rows"),
                       N("chart", kind="=kind", data=f"={rows}", x="{x_col}", y="{y_col}", title="{y_col} by {x_col}"),
                       N("table", data=f"={rows}"),
                   ]}]}


def chatbot():
    return {
        "app": {"title": "Chat Assistant", "icon": "💬", "accent": "#f43f5e"},
        "pages": [{"path": "/", "title": "Chat", "icon": "💬",
                   "sidebar": [
                       N("header", text="Settings"),
                       N("select", name="tone", label="Tone", options=["Friendly", "Formal", "Pirate"]),
                       N("caption", text="Connect a real AI model with a Python hook (see the docs)."),
                   ],
                   "body": [
                       N("title", text="Chat assistant", subtitle="A template-based bot — swap in an AI model with one Python function."),
                       N("chat", name="chat",
                         reply="{'Arr! ' if tone == 'Pirate' else ''}You said **{message}** — that's {len(message.split())} word(s). "
                               "({tone} mode)"),
                   ]}]}


def calculator():
    return {
        "app": {"title": "Loan Calculator", "icon": "🧮", "accent": "#f59e0b"},
        "pages": [{"path": "/", "title": "Calculator", "icon": "🧮", "body": [
            N("title", text="Loan calculator", subtitle="Move the sliders — results update instantly."),
            _slots(N("columns", widths="1,1"), [
                _slots(N("card", title="Inputs"), [
                    N("number", name="principal", label="Loan amount", value=500000, min=0, step=10000),
                    N("slider", name="rate", label="Yearly interest", min=1, max=30, value=12, suffix="%"),
                    N("slider", name="years", label="Years", min=1, max=30, value=5),
                ]),
            ], [
                M(label="Monthly payment",
                  value="=fmt(round(principal * (rate/1200) / (1 - (1 + rate/1200) ** (-years*12)), 2), ',.2f')"),
                M(label="Total paid",
                  value="=fmt(round(principal * (rate/1200) / (1 - (1 + rate/1200) ** (-years*12)) * years * 12), ',')"),
                M(label="Total interest", inverse=True,
                  value="=fmt(round(principal * (rate/1200) / (1 - (1 + rate/1200) ** (-years*12)) * years * 12 - principal), ',')"),
            ]),
            N("chart", kind="bar", title="Balance at the end of each year",
              data="=[{'year': y, 'balance': round(principal * (1 + rate/1200) ** (y*12) - "
                   "(principal * (rate/1200) / (1 - (1 + rate/1200) ** (-years*12))) * (((1 + rate/1200) ** (y*12) - 1) / (rate/1200)))} "
                   "for y in range(1, years + 1)]",
              x="year", y="balance"),
        ]}]}


TEMPLATES = {
    "blank": ("Blank", "Start from an empty page", "⬜", blank),
    "hello": ("Hello world", "Input, slider, button & live text", "👋", hello),
    "dashboard": ("Dashboard", "KPIs, filters, charts, multi-page", "📊", dashboard),
    "form": ("Form + table", "Collect entries, validate, export CSV", "📝", form),
    "explorer": ("Data explorer", "Upload a CSV, pick columns, chart it", "🔎", explorer),
    "chatbot": ("Chatbot", "Chat UI, ready for an AI hook", "💬", chatbot),
    "calculator": ("Calculator", "Formulas that update live", "🧮", calculator),
}


def get(name: str) -> dict:
    return normalize(TEMPLATES[name][3]())


def listing() -> list[dict]:
    return [{"id": k, "title": v[0], "desc": v[1], "icon": v[2]} for k, v in TEMPLATES.items()]
