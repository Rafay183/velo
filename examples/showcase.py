"""Velo showcase — run with:  velo run examples/showcase.py   (or: python examples/showcase.py)"""
import csv
import io
import math
import random
import time

import velo

app = velo.App("Velo Showcase", icon="⚡", accent="#6366f1")


@velo.cache(ttl=30)
def sales_data(days: int):
    """Pretend this is a slow database query — it runs once per 30 s, not on every click."""
    random.seed(days)
    rows, base = [], 1200
    for d in range(days):
        base *= 1 + random.uniform(-0.04, 0.06)
        rows.append({"day": f"D{d + 1}", "revenue": round(base), "orders": int(base / random.uniform(28, 34)),
                     "refunds": int(base * random.uniform(0.01, 0.04))})
    return rows


# ------------------------------------------------------------------ dashboard
@app.page("/", title="Dashboard", icon="📊")
def dashboard(ui):
    ui.title("Sales dashboard", "Cached data, live controls, zero page reloads.")

    with ui.sidebar:
        ui.subheader("Filters")
        days = ui.slider("Days of history", 7, 60, 30, suffix=" d")
        region = ui.select("Region", ["Global", "EMEA", "APAC", "Americas"])
        live = ui.toggle("Live mode (refresh every 2 s)")

    if live:
        ui.autorefresh(2)

    rows = sales_data(days)
    factor = {"Global": 1, "EMEA": 0.38, "APAC": 0.27, "Americas": 0.35}[region]
    if live:
        jitter = 1 + 0.03 * math.sin(time.time())
        rows = [{**r, "revenue": round(r["revenue"] * jitter)} for r in rows]
    rows = [{**r, "revenue": round(r["revenue"] * factor), "orders": round(r["orders"] * factor)} for r in rows]

    total = sum(r["revenue"] for r in rows)
    prev = rows[-2]["revenue"] if len(rows) > 1 else rows[-1]["revenue"]
    c1, c2, c3, c4 = ui.columns(4)
    c1.metric("Revenue", f"${total:,}", f"{(rows[-1]['revenue'] - prev) / prev * 100:+.1f}%")
    c2.metric("Orders", sum(r["orders"] for r in rows), 128)
    c3.metric("Avg. order", f"${total / max(1, sum(r['orders'] for r in rows)):.2f}", "+2.4%")
    c4.metric("Refunds", sum(r["refunds"] for r in rows), "-0.6%", inverse=True)

    left, right = ui.columns([2, 1])
    with left:
        ui.area_chart(rows, x="day", y="revenue", title=f"Revenue · {region}")
    with right:
        ui.pie_chart({"channel": ["Web", "Mobile", "Retail", "Partners"], "share": [46, 31, 15, 8]},
                     title="Channel mix", height=240)

    ui.bar_chart(rows[-12:], x="day", y=["orders", "refunds"], title="Orders vs refunds (last 12 days)")
    ui.subheader("Raw data")
    ui.table(rows, page_size=8)


# ------------------------------------------------------------------ widgets
@app.page("/widgets", title="Widgets", icon="🎛️")
def widgets(ui):
    ui.title("Widget gallery", "Every input returns its value. Callbacks are optional.")
    ui.init(todos=["Try the theme toggle ↗", "Resize the window"], done=[])

    tab_inputs, tab_state, tab_misc = ui.tabs(["Inputs", "State & callbacks", "Feedback"])

    with tab_inputs:
        a, b = ui.columns(2)
        with a.card("Text & numbers"):
            name = ui.input("Name", placeholder="Grace Hopper")
            age = ui.number("Age", 30, min=0, max=120)
            bio = ui.textarea("Bio", placeholder="A few words…", rows=3)
            when = ui.date("Start date")
        with b.card("Choices"):
            plan = ui.radio("Plan", ["Free", "Pro", "Team"], value="Pro")
            langs = ui.multiselect("Languages", ["Python", "Rust", "Go", "TypeScript", "Kotlin"], value=["Python"])
            ok = ui.checkbox("I agree to the terms")
            color = ui.color("Brand colour", "#6366f1")
        ui.json({"name": name, "age": age, "bio": bio, "start": when, "plan": plan, "languages": langs,
                 "agreed": ok, "color": color})

    with tab_state:
        with ui.card("Todo list", "State lives in ui.state and survives hot reloads."):
            def add():
                item = ui.get("new_todo", "").strip()
                if item:
                    ui.state.todos.append(item)
                    ui.set("new_todo", "")
                    ui.toast(f"Added “{item}”", "success")

            with ui.row():
                ui.input("New todo", key="new_todo", placeholder="Something to do…")
            ui.button("Add todo", on_click=add, icon="＋")
            for i, t in enumerate(ui.state.todos):
                ui.checkbox(t, key=f"todo-{i}-{t}")
            done = sum(1 for i, t in enumerate(ui.state.todos) if ui.get(f"todo-{i}-{t}"))
            ui.progress(done / max(1, len(ui.state.todos)), f"{done} of {len(ui.state.todos)} done")

    with tab_misc:
        ui.info("Velo renders **markdown** everywhere, including `inline code`.")
        ui.success("Saved successfully.", title="Done")
        ui.warning("Your trial ends in 3 days.")
        ui.error("Something went wrong (this is just a demo).")
        with ui.row():
            if ui.button("Show a toast", kind="secondary"):
                ui.toast("Hello from Python 👋", "success")
            ui.button("Ghost button", kind="ghost")
            ui.button("Danger", kind="danger")
            ui.download("Download CSV", "a,b\n1,2\n", "sample.csv")
        with ui.expander("Show me the code for this page"):
            ui.code('ui.button("Show a toast", kind="secondary")\nui.toast("Hello from Python 👋", "success")')


# ------------------------------------------------------------------ data explorer
@app.page("/data", title="Data explorer", icon="🗂️")
def data(ui):
    ui.title("Data explorer", "Drop a CSV — get a sortable table and an instant chart.")
    f = ui.upload("Upload a CSV file", accept=".csv")
    if f is None:
        rows = [{"city": c, "population": p, "area": a} for c, p, a in
                [("Karachi", 20.4, 3780), ("Lahore", 13.5, 1772), ("Faisalabad", 3.7, 1330),
                 ("Rawalpindi", 2.3, 259), ("Islamabad", 1.2, 906), ("Peshawar", 2.4, 1257)]]
        ui.caption("No file yet — showing sample data.")
    else:
        rows = list(csv.DictReader(io.StringIO(f.text())))
        for r in rows:
            for k, v in r.items():
                try:
                    r[k] = float(v) if "." in v else int(v)
                except (ValueError, TypeError):
                    pass
        ui.success(f"Loaded **{f.name}** — {len(rows):,} rows, {len(rows[0]) if rows else 0} columns.")
    if not rows:
        return
    cols = list(rows[0].keys())
    numeric = [c for c in cols if isinstance(rows[0][c], (int, float))]
    a, b, c = ui.columns(3)
    with a:
        x = ui.select("X axis", cols)
    with b:
        y = ui.multiselect("Y axis", numeric, value=numeric[:1])
    with c:
        kind = ui.radio("Chart", ["bar", "line", "area"])
    if y:
        ui.chart(rows, x=x, y=y, kind=kind, title=f"{', '.join(y)} by {x}")
    ui.table(rows)


# ------------------------------------------------------------------ chat
@app.page("/chat", title="Chat", icon="💬")
def chat(ui):
    ui.title("Chat", "A chat UI in 15 lines — plug in any LLM.")
    ui.init(messages=[{"role": "assistant", "content": "Hi! I'm a tiny echo bot. Ask me anything."}])
    msg = ui.chat_input("Ask something…")
    if msg:
        ui.state.messages.append({"role": "user", "content": msg})
        words = len(msg.split())
        ui.state.messages.append({"role": "assistant",
                                  "content": f"You said **{words} word{'s' * (words != 1)}**. Reversed: `{msg[::-1]}`"})
    for m in ui.state.messages:
        ui.chat_message(m["role"], m["content"])
    if len(ui.state.messages) > 1 and ui.button("Clear conversation", kind="ghost"):
        ui.state.messages = ui.state.messages[:1]
        ui.rerun()


if __name__ == "__main__":
    app.run()
