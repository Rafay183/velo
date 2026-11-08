"""Velo — beautiful, reactive Python web apps. Zero dependencies.

No code:  velo studio        (drag & drop builder, saves app.velo.json)
Python:

    import velo

    app = velo.App("Hello")

    @app.page("/")
    def home(ui):
        name = ui.input("Your name")
        ui.title(f"Hello, {name or 'world'} 👋")

    app.run()
"""
__version__ = "0.2.0"

from .core import App, UI, State, UploadedFile, Rerun, cache  # noqa: E402
from .spec import load, Context  # noqa: E402

__all__ = ["App", "UI", "State", "UploadedFile", "Rerun", "cache", "load", "Context", "__version__"]
