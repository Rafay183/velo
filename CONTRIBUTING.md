# Contributing to Velo

Thanks for helping! 🎉 Every contribution counts: bug reports, docs, examples, new components.

## Ground rules

1. **Zero dependencies.** Velo uses only the Python standard library. No `pip install` required, ever.
2. **Small and readable.** Prefer clear code over clever code.
3. **Every change is tested.** Add a test in `tests/test_velo.py` (runtime) or `tests/test_studio.py` (no-code / Studio).

## Set up (5 minutes)

```bash
git clone https://github.com/<you>/velo.git
cd velo
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -e .            # editable install: your edits apply instantly
python tests/test_velo.py && python tests/test_studio.py   # both should pass
velo run examples/showcase.py --open
velo studio /tmp/try.velo.json                            # the drag & drop builder
```

## Workflow

1. Pick an issue (look for **good first issue**) and comment "I'll take this".
2. Create a branch: `git checkout -b feat/date-range-picker`
3. Make your change, then run the tests.
4. Commit with a clear message: `feat: add ui.date_range`, `fix: slider jumps on mobile`
5. Push and open a Pull Request. Fill in the checklist.

## Where things live

| File | What it does |
|---|---|
| `velo/core.py` | `App`, sessions, and every `ui.*` component (Python side) |
| `velo/server.py` | HTTP server, SSE stream, hot reload |
| `velo/static/app.js` | Browser: renders components, DOM morphing, charts, tables |
| `velo/static/app.css` | Theme (light/dark), all component styles |
| `velo/markdown.py` | Safe markdown renderer |
| `velo/cli.py` | `velo studio / run / new / export / docker` |
| `velo/spec.py` | No-code layer: component **catalog**, formula sandbox, `.velo.json` interpreter, validator |
| `velo/codegen.py` | `velo export`: spec → readable Python |
| `velo/templates.py` | Studio starter apps |
| `velo/studio.py` | Studio server (UI, autosave, live preview on port+1) |
| `velo/static/studio.{html,js,css}` | Studio UI: palette, canvas, drag & drop, inspector (vanilla JS, no build step) |

## Adding a new component (recipe)

1. **Python** (`core.py`): add a method on `UI` that calls `self._add("mytype", {...props}, key)`.
   For inputs, also store the value with `self._val(k, default)` and register `self._widgets[k] = {"kind": ...}`.
2. **Browser** (`app.js`): add `R.mytype = (p, n, k) => h("div", {...})`.
   Use `data-bind` / `data-click` attributes. Never attach listeners directly (events are delegated).
3. **Style** (`app.css`): use the CSS variables (`--accent`, `--panel`, `--border`…) so dark mode works for free.
4. **Test** it, and add it to `examples/showcase.py` and the README.

## Making a component available in Studio

The catalog in `velo/spec.py` (`COMPONENTS`) is the single source of truth: Studio's palette and inspector are generated from it.

1. Add an entry: `group`, `label`, `icon`, `desc`, `props` (each with a `kind`: text, longtext, number, bool, choice, color, list, var, data, code, actions), plus `var=True` for inputs or `slots=...` for containers.
2. Render it: add `r_<type>` to `_Renderer` in `spec.py`.
3. Export it: add a branch in `_Gen._node` in `codegen.py`.
4. Preview it on the canvas: add a `case` in `preview()` in `static/studio.js`.
5. `test_every_template_runs_and_exports_equivalent_python` checks the runtime and exporter agree. Add it to a template to get that coverage.

## Releasing (maintainers)

1. Bump the version in `pyproject.toml` **and** `velo/__init__.py`, then update `CHANGELOG.md`.
2. Commit, then create a GitHub Release with tag `v0.x.y`. GitHub Actions publishes to PyPI automatically.
