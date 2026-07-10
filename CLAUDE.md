# Logline

See `backend/CLAUDE.md` for backend architecture/agent docs. This file holds
project-wide conventions that apply to both backend and frontend.

## Git workflow (adopted 2026-07-10)

Solo project, no ticket system — every piece of work goes on its own branch,
never committed directly to `main`.

**Branches:** `<category>/<description-in-kebab-case>` — no username or
ticket-number prefix.

Categories:
- `feature` — new/refactored/removed functionality
- `bugfix` — bug fixes
- `hotfix` — urgent temporary fixes
- `test` — experiments
- `wip` — long-running work in progress

**Commits:** an uppercase type, optional scope in parens, colon, short
description — e.g. `FIX(auth): resolve session race condition on page reload`.
Body (optional) is free-form paragraphs after one blank line.

Types: `FEAT`, `FIX`, `HOTFIX`, `CHORE`, `REFACTOR`, `DOCS`.

Breaking changes: add `!` before the colon (e.g. `REFACTOR!: ...`), with a
`BREAKING CHANGE:` footer explaining it if needed.

Commits before this date (e.g. the `SessionContext` auth-hydration race fix)
predate this convention and were intentionally left as plain commits to
`main` rather than rewritten.
