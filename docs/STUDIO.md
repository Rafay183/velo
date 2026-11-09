# Velo Studio reference

Velo Studio is the drag & drop builder that ships inside the `velo-ui` package. Nothing extra to install.

```bash
pip install velo-ui
velo studio                # opens http://localhost:7860, edits ./app.velo.json
```

| Command | |
|---|---|
| `velo studio [file] [-t template] [--force] [--port N] [--host H] [--no-open]` | Open the builder. The live preview runs on `port + 1`. |
| `velo run app.velo.json [--prod]` | Run a Studio app like any Velo app (hot reload when the JSON or `hooks.py` changes) |
| `velo export app.velo.json [-o app.py] [--force]` | Generate equivalent Python |
| `velo docker app.velo.json` | Dockerfile for deployment |

Templates: `blank`, `hello`, `dashboard`, `form`, `explorer`, `chatbot`, `calculator`.

## The screen

* **Left:** *Components* (search with `/`), *Pages* (add, rename, reorder, set URL and icon), *App & Data* (title, icon, accent colour, theme, wide layout, **state variables**, hooks file, formula cheat sheet).
* **Centre:** *Design* (canvas), *Split* (canvas + live app), *Preview* (live app), *Code* (generated Python). Desktop/mobile toggle.
* **Right:** the inspector for the selected component: properties, actions (buttons), *Show only if*, and any problems.

Keyboard: `Del` delete · `Ctrl/⌘ D` duplicate · `Ctrl/⌘ Z` undo · `Ctrl/⌘ Shift Z` or `Ctrl Y` redo · `Alt ↑/↓` move · `Ctrl/⌘ S` save now · `Esc` deselect · `1`–`4` switch view · double-click a component to edit it.

## Variables

There are two kinds, and both are used the same way:

* **Inputs:** every input component has a *Variable name* (`name`, `email`, `file`…). Its value is whatever the visitor entered.
* **State variables:** values the app remembers per visitor (a counter, a list of entries). Add them in *App & Data* with a starting value: `0`, `""`, `[]`, `false`. Choosing a new variable name in an action creates one automatically.

Renaming a variable in the inspector updates every reference to it.

## Formulas

| You write | Meaning |
|---|---|
| `Hello {name}` | A **template**: `{…}` is replaced by the value. Works in every text property. |
| `{price * qty:,.2f}` | Compute, with an optional Python format spec after `:` |
| `{{` `}}` | Literal braces |
| `=count + 1` | A whole value is computed (the property starts with `=`) |
| *Show only if* / *Only if* | A formula that is true or false: `agree and '@' in email` |

Formulas are Python expressions: arithmetic, comparisons, `and/or/not`, `x if cond else y`, lists, dicts, comprehensions, f-strings, indexing and slicing. They run in a sandbox: no imports, no attribute access starting with `_`, only a fixed set of safe methods (`upper`, `lower`, `split`, `join`, `replace`, `get`, `keys`, `items`, `strftime`, …) and functions:

| Function | Example |
|---|---|
| `len sum min max round abs sorted range list dict set any all enumerate zip reversed str int float bool sqrt pi` | `=round(sum(xs) / len(xs), 1)` |
| `csv(text_or_file)` | `=csv(file)`: list of row dicts, numbers converted |
| `col(rows, name)` | `=sum(col(rows, 'sales'))` |
| `where(rows, column, value)` | `=where(rows, 'region', region)`. `value` may be a list; empty means "all" |
| `group(rows, by, value=None, agg='sum')` | `=group(rows, 'month', 'sales')`, agg: `sum` `mean` `count` `min` `max` |
| `columns(rows)` | `=columns(csv(file))`, e.g. as dropdown options |
| `mean(xs)` · `fmt(v, ',.2f')` · `to_csv(rows)` | |
| `as_rows(v)` · `as_text(v)` | Normalise table data / download content |
| `today()` · `now()` | dates |

Inside a chat reply, `message` is what the visitor typed. The chat history is a list in the chat's variable (`chat`).

> The sandbox is there for robustness: a typo can't break your computer or the server. Formulas are written by the app author, and visitors only ever provide data, never code.

## Actions (buttons)

Steps run top to bottom. Each can have an **Only if** condition.

| Action | Fields | Example |
|---|---|---|
| Set variable | variable, value | `count` ← `=count + 1` |
| Flip yes/no | variable | `dark_mode` |
| Add to list | variable, value | `entries` ← `={'name': name, 'email': email}` |
| Clear variable | variable | `entries` → `[]` |
| Reset inputs | names (blank = all) | `name email` |
| Show message | text, style | `Saved, {name}!` (`success`) |
| Go to page | page | `/thanks` |
| Run Python hook | function | `send_email` |

Values: `=…` is computed, `5` becomes a number, `true`/`false` become booleans, anything else is text (with `{templates}`).

## Python hooks

Set *Hooks file* (App & Data) to `hooks.py`, next to your `.velo.json`:

```python
# hooks.py
def send_email(ctx):            # button action
    ctx["email"]                # read any variable (input or state)
    ctx.values                  # dict of all input values
    ctx.state                   # the visitor's state (dict-like)
    ctx.set("sent", True)       # set a state variable or input
    ctx.toast("Sent!", "success")
    ctx.navigate("/thanks")
    ctx.ui                      # the full Velo `ui` object, if you need it

def reply(ctx, message):        # chat component hook → return the reply text
    return f"You said {message}"
```

Studio reloads the preview when `hooks.py` changes. You can register functions from Python instead:

```python
app = velo.load("app.velo.json")

@app.action("send_email")
def send_email(ctx): ...
```

## Components

| Type | Palette name | What it is | Properties |
|---|---|---|---|
| `title` | Title | Big page title with optional subtitle | `text`, `subtitle` |
| `header` | Header | Section heading | `text` |
| `subheader` | Subheader | Smaller heading | `text` |
| `text` | Text | A paragraph. Use {variables} | `text`, `muted` |
| `markdown` | Markdown | Rich text: **bold**, lists, links, tables | `text` |
| `caption` | Caption | Small, muted text | `text` |
| `badge` | Badge | Small coloured label | `text`, `kind` |
| `link` | Link | External link | `text`, `url` |
| `code` | Code | Code block with copy button | `code`, `lang` |
| `image` | Image | Image from a URL | `src`, `caption`, `width` |
| `divider` | Divider | Horizontal line | — |
| `space` | Spacer | Vertical space | `height` |
| `alert` | Alert | Info / success / warning / error box | `kind`, `title`, `text` |
| `metric` | Metric | KPI number with delta | `label`, `value`, `delta`, `inverse`, `help` |
| `progress` | Progress | Progress bar (0–100) | `value`, `label` |
| `input` | Text input | Single-line text | `name`, `label`, `placeholder`, `value`, `itype`, `help` |
| `textarea` | Text area | Multi-line text | `name`, `label`, `placeholder`, `value`, `rows`, `help` |
| `number` | Number | Number box | `name`, `label`, `value`, `min`, `max`, `step`, `help` |
| `slider` | Slider | Pick a number by dragging | `name`, `label`, `min`, `max`, `value`, `step`, `suffix`, `help` |
| `select` | Dropdown | Pick one from a list | `name`, `label`, `options`, `value`, `help` |
| `radio` | Segmented | Pick one of a few (buttons) | `name`, `label`, `options`, `value` |
| `multiselect` | Chips | Pick many (toggle chips) | `name`, `label`, `options`, `value` |
| `checkbox` | Checkbox | Yes / no | `name`, `label`, `value` |
| `toggle` | Switch | On / off switch | `name`, `label`, `value` |
| `date` | Date | Date picker | `name`, `label` |
| `color` | Colour | Colour picker | `name`, `label`, `value` |
| `upload` | File upload | Drag & drop a file (CSV → =csv(file)) | `name`, `label`, `accept` |
| `button` | Button | Runs actions when clicked | `label`, `kind`, `icon`, `full`, `actions` |
| `download` | Download | Download text / CSV built from your data | `label`, `content`, `filename` |
| `table` | Table | Searchable, sortable table | `data`, `page_size`, `search` |
| `chart` | Chart | Line, area, bar or donut chart | `kind`, `data`, `x`, `y`, `title`, `height`, `stacked` |
| `chat` | Chat | Chat box: replies from a template or a Python hook | `name`, `placeholder`, `greeting`, `reply`, `hook` |
| `columns` | Columns | Side-by-side columns | `widths`, `gap` |
| `card` | Card | A panel that groups things | `title`, `subtitle` |
| `row` | Row | Items in a horizontal line | — |
| `tabs` | Tabs | Tabbed sections | `labels` |
| `expander` | Expander | Collapsible section | `label`, `open` |
| `container` | Group | Invisible group (great with 'show if') | — |

Layout components (`columns`, `card`, `row`, `tabs`, `expander`, `container`) hold other components in **slots**: one per column or tab, one for the rest. Every page also has a **sidebar** zone.

## The `.velo.json` format

```json
{
  "velo": 1,
  "app":   {"title": "Registration", "icon": "📝", "accent": "#8b5cf6", "theme": "auto", "wide": false},
  "state": {"entries": []},
  "hooks": "hooks.py",
  "pages": [{
    "path": "/", "title": "Register", "icon": "📝",
    "sidebar": [],
    "body": [
      {"id": "n1", "type": "input", "props": {"name": "email", "label": "Email"}},
      {"id": "n2", "type": "button", "props": {"label": "Join", "actions": [
        {"do": "append", "var": "entries", "value": "={'email': email}", "if": "'@' in email"}]}},
      {"id": "n3", "type": "card", "props": {"title": "People"}, "show_if": "len(entries) > 0",
       "slots": [[{"id": "n4", "type": "table", "props": {"data": "=entries"}}]]}
    ]
  }]
}
```

Missing properties take their defaults, so hand-written specs can stay short. Python API: `velo.load(path_or_dict)` → app, `velo.spec.validate(spec)` → problems, `velo.codegen.to_python(spec)` → source.
