# Logline

See `backend/CLAUDE.md` for backend architecture/agent docs. This file holds project-wide conventions that apply to
both backend and frontend.

## Git workflow

Solo project, no ticket system — every piece of work goes on its own branch, never committed directly to `main`.

**Branches:** `<username>/<category>/<description-in-kebab-case>` — username is always `toheed`. No ticket number,
and never a placeholder like `na` — omit that segment entirely.

**Correction (this supersedes an earlier, since-reverted convention):** a prior version of this doc briefly
documented a no-username-prefix style (`<category>/<description>`, "adopted 2026-07-10"). That was used for a
window of time and has been deliberately reverted back to the username-prefixed style. Some branches created during
that window still exist without the prefix — don't rename historical branches retroactively, but every new branch
uses the username-prefixed form.

Categories:
- `feature` — new/refactored/removed functionality
- `bugfix` — bug fixes
- `hotfix` — urgent temporary fixes
- `fix` — general fixes not urgent enough to be a hotfix
- `chore` — tooling, CI, config, dependency work
- `refactor` — restructuring with no behavior change
- `docs` — documentation-only changes
- `test` — experiments
- `wip` — long-running work in progress

**Commits:** an uppercase type, optional scope in parens, colon, short description — e.g. `FIX(auth): resolve
session race condition on page reload`. Body (optional) is free-form paragraphs after one blank line.

Types: `FEAT`, `FIX`, `HOTFIX`, `CHORE`, `REFACTOR`, `DOCS`.

Breaking changes: add `!` before the colon (e.g. `REFACTOR!: ...`), with a `BREAKING CHANGE:` footer explaining it
if needed.

Commits before this date (e.g. the `SessionContext` auth-hydration race fix) predate this convention and were
intentionally left as plain commits to `main` rather than rewritten.

## Stacked branches

When a branch genuinely depends on code that only exists on another unmerged branch, stack directly on that branch
— never branch off `main` or an unrelated branch just because it's the most recent one. Confirm the real dependency
before choosing a base (check actual imports/schema needs), don't assume. GitHub's native stacked-PR feature
(public preview) can be used once available/confirmed working on this repo; manual base-targeting (`--base
<branch>` on PR creation) works fine either way and is what most existing stacks on this repo use.

## Review requirements

Every security-sensitive or architecture-touching branch gets an independent model review before commit — never
skip this, even under time pressure. For genuinely security-sensitive work (new auth, new data paths, a
security/redaction boundary), budget for a **second, independent review round** after fixes are applied — a first
pass has repeatedly missed real issues that a second, independent pass caught. Require re-reproduction of the
original issue against the fixed code before considering it closed, not just a description of the fix.
