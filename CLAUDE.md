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

## Bearer tokens in manual testing

Never type a real token literally into a Bash command (e.g. `curl -H
'Authorization: Bearer eyJ...'`) during manual testing. Claude Code's
permission system captures the exact command text into `.claude/settings.json`'s
allowlist when a command gets approved, and since that file is tracked, the
token rides into the next commit that touches it -- this already happened
once. Use an env var instead:

```
export TOKEN=eyJ...
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/...
```

A pre-commit hook (`.githooks/pre-commit`) blocks commits containing a
JWT-shaped string as a backstop. It isn't installed automatically -- run
`git config core.hooksPath .githooks` once per clone to enable it.
