# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com), versions: [SemVer](https://semver.org).

## [Unreleased]

## [0.2.1] - 2026-11-09
### Added
- Complete documentation site in one file: `docs/index.html` (guides, Studio, formulas, Python API,
  recipes, deploy, cheat sheets, FAQ). Publish it with GitHub Pages from `/docs`.
- Author credit built in: every Velo app's HTML (comment + `generator` meta tags + footer tooltip),
  the `X-Powered-By` header, Velo Studio, exported Python, `.velo.json` files and `velo version` name
  Muhammad Rafay Shaikh (Pakistan). Available as `velo.__author__`, `velo.__country__`, `velo.CREDIT`.

### Fixed
- Windows: no crash printing ✓ ⚡ 🎨 on non-UTF-8 consoles; no `relpath` error across drives.
- CI: Python 3.9 job runs on ubuntu-24.04 (ubuntu-latest no longer ships 3.9).

## [0.2.0] - 2026-11-09
### Added
- **Velo Studio** (`velo studio`): a drag & drop builder with a component palette, nested drop zones,
  an inspector, undo/redo, autosave, validation, variable rename-refactor, live preview (split view,
  desktop/mobile), a Python code view and 7 starter templates.
- No-code app format `.velo.json`, run directly with `velo run app.velo.json` (with hot reload) or
  `velo.load("app.velo.json")`.
- Spreadsheet-style formulas (`{name}`, `=price * qty`) in a sandboxed expression language, plus data
  helpers: `csv`, `col`, `where`, `group`, `columns`, `mean`, `to_csv`, `fmt` (also in `velo.helpers`).
- Button actions (set, toggle, append, clear, reset, toast, navigate, call Python), conditional
  actions and conditional visibility ("show if").
- Python hooks: `hooks.py` functions or `@app.action(...)` for buttons and chat replies (`velo.Context`).
- `velo export`: turn a Studio app into clean, idiomatic Velo Python.
- `ui.reset(*keys)` to reset widgets to their defaults.

### Fixed
- `ui.navigate()` now works inside `on_click` / `on_change` callbacks (it was silently ignored).

## [0.1.0] - 2026-11-09
### Added
- First public release: reactive page model, 40+ components, SVG charts, smart tables,
  chat UI, file upload, state-preserving hot reload, server push (SSE), light/dark themes,
  `velo run | new | docker` CLI.
