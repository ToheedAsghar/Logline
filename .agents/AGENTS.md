# Project context

## Stack

- Frontend: Vite + TypeScript (React or similar). Tests: vitest or similar.
- Backend: FastAPI/Python (`backend/`). Postgres via SQLAlchemy (Alembic).
- Tracker: Python background service (`tracker/`).

## Conventions reviews should enforce

- Follow existing conventions in the respective folders.
- Database access goes through SQLAlchemy in the backend.
- Tracker is a standalone Python background service.

## Python style, signatures & constants

- Wrap docstring prose at **120 characters**, same as code. Fill each line before
  wrapping — a docstring wrapped at 79 turns two lines into six. flake8 enforces the
  120 ceiling via `max-doc-length` (W505); using the width is on you.
- **Imports**: Format and sort imports using `isort` configured by `.isort.cfg` (120-column line length). Group imports by standard library, third party, and local project modules. Fill import lines up to the 120-character limit before wrapping.
- **String constants**: Avoid inline magic string literals, fallback strings, or log messages;
  define them as centralized constants (e.g. in `constants.py` or module level) and import them.
- **Function signatures & calls**: Collapse signatures and function call arguments onto a single line
  whenever they fit within the 120-character limit. Split onto multiple lines only when exceeding 120 characters.
- Plain words. "use" not "utilize", "create" not "instantiate". One idea per sentence.
- Third person, present tense: "Returns the tenant's unpaid invoices."
- Don't restate the name or the type annotations. Document what the signature can't
  say: units, edge-case returns, what it raises and when, side effects, whether it
  hits the network, whether it's safe to call twice.
- If the code does something surprising, the docstring is where the reason lives.
- Match the docstring style already in the file. Don't mix conventions.

## Commands

- `make check` — isort, flake8, mypy, tsc, eslint, semgrep. `make test` — full suite.
- Python style config: `.flake8` (120 cols, max-doc-length 120) and `.isort.cfg`.
- `make migrate` / `make makemigrations`.
- Dev server: `npm run dev` on port 3000.
