"""Helper module used by test_uvicorn_access_log_redaction.py to boot a real Uvicorn process. Not a test file.

Calls configure_logging() before importing the app, just like app/main.py does. This has to live in its own
module, not inline code before uvicorn.run(), because Uvicorn sets up its own default logging as soon as it
builds its Config, before it imports the app -- configure_logging() needs to run during that later import
step so it runs after Uvicorn's setup and wins.
"""

from app.core.logging import configure_logging

configure_logging()

from app.main import app  # noqa: E402,F401
