# Logline Backend

Logline is an agentic work-log and standup assistant. It pulls signal from tools people already use (GitHub, Slack,
Jira, Calendar) and helps them reconstruct what they did — surfacing it with an honest sense of how much to trust
each piece.

## Core principle: evidence/confidence grounding

Every piece of surfaced information carries a `confidence` value, and there are only three:

- **proven** — directly evidenced (e.g. a merged PR, a calendar event that happened)
- **estimated** — inferred, editable by the user
- **gap** — no data; ask the user

Do not add a fourth confidence value. In particular, non-work time is not a special "personal" confidence — it's
`source="personal"` or `source="dismissed"` with `confidence="proven"`. The source describes *what it is*;
confidence describes *how sure we are*. Keep that separation.

## Architecture: Phase 4 deterministic pipeline

**This corrects an earlier version of this file.** Two systems used to coexist: a fully-agentic runner
(`app/agent/runner.py` + `app/agent/toolbelt.py`, an LLM deciding on its own which tools to call) and the
deterministic pipeline below. The agentic runner was removed (`toheed/chore/remove-runner-toolbelt`) after a live
diagnostic run showed it functionally broken — its MCP sources failed to connect, so the agent could never ground
"today" and either hallucinated a date or exhausted its tool-call budget — and its only frontend entry point
(`/compose`, "Re-generate Standup") was confirmed unused. Only the pipeline below remains; treat any reference to
"the old runner" elsewhere as historical.

Deterministic code decides what to fetch and how to match evidence; an LLM is used only for the narrow final task
of writing descriptions and resolving genuine ambiguity — never for deciding what to fetch, never for stating a
duration directly.

**Verify build status before assuming a stage exists — it's uneven right now:**

| Stage | Module | Status on `main` |
| --- | --- | --- |
| 1. Local aggregation (raw tracker activity → blocks, pure function) | `app/local_activity/` | Built, tested (`tests/test_local_activity_aggregation.py`) |
| 2. Remote fetch (code decides what to fetch, never the LLM) | `app/remote_fetch/` | Built, tested (`tests/test_remote_fetch_sources.py`, `tests/test_remote_fetch_orchestrator.py`). Per-source fetchers live under `app/remote_fetch/mcp/`; `orchestrator.py` drives them and advances the `remote_fetch_state` high-water marks |
| 3. Deterministic matching (exact project + time-window rules, no automatic tiebreaking) | `app/matching/` | Built, tested (`tests/test_matching_resolution.py`) |
| 4. Reminder generation (unmatched remote events, never auto-assigned durations) | `app/reminders/` | Built, tested |
| 5. AI reconciliation (structured draft; AI allocates minutes against real measured blocks, never states bare durations) | `app/agent/reconciliation/` | **Schemas only** (`WorkLogDraft`, `DraftEntry`, `DraftReminder`, `BlockAllocation` in `schemas.py`, tested in `tests/test_reconciliation_schema*.py`). No service calls `run_structured` with them yet — nothing produces a `WorkLogDraft` in a real run. |
| 6. Code-side verification (conservation, ID cross-check, completeness — never auto-fixes) | — | **Not on `main`.** Part of the `feature/remote-fetch` branch's later commits, not yet ported |
| 7. Human review (client-side edits, single write on approval) | — | **Not on `main`.** The `ReviewDraft` frontend UI referenced in commit `43c6f49` lives only on `feature/remote-fetch` |
| 8. Save | — | Not wired up on `main` — no router exposes any of stages 1–7 to the API yet |

Local aggregation, remote fetch, matching, and reminders are real, tested, importable modules on `main` today — but
they still aren't connected to each other by any single end-to-end orchestrator, and nothing outside their own test
suites calls them. `app/remote_fetch/orchestrator.py` sequences the fetch stage only; it does not hand off to
matching or reconciliation. Treat "the Phase 4 pipeline" as a set of validated building blocks being assembled, not
a live end-to-end flow, until stages 6–8 land and a router exposes them.

Writing deterministic orchestration code under `app/remote_fetch/`, `app/matching/`, etc. is correct, intended
design, not something to "fix" into agentic form.

## Data model

**This corrects an earlier version of this file**, which said "never add per-source tables, everything is a generic
`{source, type, timestamp, metadata, confidence}` event." That was an early, since-superseded modeling decision.
Purpose-built tables exist per pipeline stage instead of one generic shape — e.g. `events` (self-capture evidence),
`remote_events`/`project_mappings` (matching), `entries`/`entry_versions` (drafts and approval history),
`tracker_devices`/`tracker_sync_states`/`local_sessions` (local-tracker device auth and sync state),
`integrations`/`oauth_tokens`/`connect_link_tokens` (per-user OAuth). When adding a new table, match the shape to
what the pipeline stage actually needs — check existing sibling tables in the same stage for the established
pattern rather than assuming a single universal event shape applies everywhere.

The `confidence` principle above still applies universally regardless of table shape — every stage that surfaces
information to a human should carry a proven/estimated/gap signal, whatever the underlying table looks like.

All of the above constrains *storage*, not file layout. One fetcher module per source is fine — each source's real
API genuinely differs — even when those fetchers all write into one shared table. `app/remote_fetch/mcp/` is the
worked example: four per-source fetchers (`github.py`, `jira.py`, `slack.py`, `calendar.py`) all persisting into
the single `remote_events` table.

### `metadata` is a reserved name on SQLAlchemy's declarative base

Workaround in use: the DB column is named `metadata`, but the Python attribute is renamed, following the pattern
`<table>_metadata`. Currently in use for `events` → `event_metadata` and `integrations` → `integration_metadata`.
Apply the same pattern to any future metadata-style JSONB columns.

### `entries.content` is JSONB, not TEXT

Shape depends on `entries.format`:
- `standup` → `{yesterday, today, blockers}`
- `project_log` → `{text}`

Validated via Pydantic schemas in `app/entries/schemas.py`. Don't assume `content` is a plain string anywhere.

### `entry_versions` — append-only draft/approval history

Never mutate a saved `Entry` row's content in a way that discards history. `entry_versions` captures a snapshot on
three events: `ai_draft` (at generation), `human_approved` (at approval), `human_revision` (a content edit made
*after* approval only — pre-approval edits are refinements of the draft, not tracked separately). This is the
foundational dataset for measuring reconciliation quality over time; don't bypass it when adding new write paths to
`Entry`.

## Comments and docstrings

Important notes, deliberate design decisions, and non-obvious behavior belong in the docstring, not scattered as
inline comments.

Docstrings state WHAT plainly: inputs, outputs, and non-obvious behavior. Include a one-line WHY only when omitting
it risks a future developer accidentally "fixing" a deliberate design choice.

Do not put multi-paragraph rationale, worked-example narratives, or "what was tested" commentary in docstrings or
comments; that belongs in commit messages or PR descriptions.

Verbose inline comments explaining deferred or known limitations do not belong scattered in code. Put a one-line
pointer in code if needed, and put the full reasoning in the PR description.

Wrap docstrings and comments near 120 characters; do not stop short out of habit.

## Postgres enum types are shared DB objects, not per-table

A `sa.Enum(...)`/`postgresql.ENUM(...)` column creates a named type at the Postgres level, not a per-column
constraint — if a second table's migration declares the same enum inline, Alembic tries to `CREATE TYPE` it again
and fails on a duplicate. Only the original owning migration (`5eea9c691db5`, which first added it for
`integrations.source`) should create the `integration_source` type. Any later table that needs the same set of
values must reference it with `create_type=False` instead of falling back to a plain `String` column.

Use the shared helper in `app/db/pg_enums.py::integration_source_enum()` rather than hand-rolling
`postgresql.ENUM(...)` again:

```python
from app.db.pg_enums import integration_source_enum

sa.Column("source", integration_source_enum(create_type=False), nullable=False)
```

The helper's value list is a frozen literal snapshot, not an import of the live `IntegrationSource` app enum —
migration files must stay self-contained so they don't silently drift if the app enum changes later. Adding a new
source value means writing a separate `ALTER TYPE integration_source ADD VALUE ...` migration, not just editing the
app-code enum.

## Alembic: keep a single migration head

**Correction: this repo has no CI.** There is no `.github/workflows/` directory, no pre-commit hook, and no other
automated check anywhere in the repo that runs `alembic upgrade head` or `configure_mappers()` — an earlier version
of this file claimed CI enforced this on every PR; that was aspirational, not real. Keeping a single head is
currently a manual discipline only, and it has lapsed before: as of this writing, `main` itself has two divergent
heads (`283e0bebe749` and `d77b8f9a3c20`, from `entries.entry_versions` and `tracker_sync`'s tables landing
independently) with no `alembic merge` between them yet. Run `alembic heads` yourself before trusting `alembic
upgrade head` to mean what you think it means, and resolve any divergence you introduce or discover with a proper
`alembic merge` rather than leaving it — `configure_mappers()` failures can hide behind an ambiguous multi-head
state, and nothing will catch that for you automatically.

## Pre-commit checks

Before committing, always run isort and flake8 across any files touched:

    isort <touched files or .>
    flake8 <touched files or the relevant package>

Both are configured at the repo root (`.isort.cfg`, `.flake8`) with `line_length`/`max-line-length` 120. Fix
anything either tool flags before committing — do not commit code with import-ordering or lint issues, even if
tests pass.

## LLM API: provider abstraction

Nothing outside `app/agent/llm/` may import a specific LLM SDK directly — route everything through the neutral
`LLMProvider` interface in `app/agent/llm/base.py`, with per-provider implementations (`openai_provider.py`, etc.)
doing the wire-format conversion. Currently only `OpenAIProvider` exists (`LLM_PROVIDER=openai`, model configurable
via `LLM_MODEL`, default `gpt-5-mini`, both read in `app/config.py`); any other value raises `NotImplementedError`
from the `get_llm_provider()` factory rather than failing silently. Switching or adding providers means adding one
new file under `app/agent/llm/` and one branch in the factory function — callers should never need to change for a
provider swap.

**Correction: structured output is already built, not a gap.** An earlier version of this file said the ABC only
supported plain-text turns; that's no longer true. `LLMProvider.run_structured(messages, response_model)` exists in
`base.py` (default raises `NotImplementedError` for providers that don't support it) and `OpenAIProvider` overrides
it with a full implementation — content-filter/truncation/zero-choices/validation-failure error handling via
`LLMStructuredOutputError`, usage logging, tested in `tests/test_reconciliation_schema_openai_strict.py`. **The
real current gap is that nothing calls it yet** — no service in `app/agent/reconciliation/` actually invokes
`run_structured` to produce a `WorkLogDraft`; only the target schemas exist. Building that caller is what's
actually blocking Phase 4 stage 5. When you do: keep any retry-on-validation-failure loop in the caller (not
reimplemented per provider — `run_structured` already handles the provider-side error taxonomy), and pin the model
version in the stored draft so a provider-side model update doesn't silently change output quality with no way to
detect it.

## Integrations: per-user OAuth, not shared test credentials

Real per-user OAuth connect flows exist for GitHub, Slack, and Jira — `app/integrations/providers/{github,jira,
slack}.py` implement the shared `OAuthProvider` interface (`providers/base.py`), wired through
`POST /integrations/{source}/connect-link`, `GET /integrations/{source}/connect`, `GET
/integrations/{source}/callback`, and `DELETE /integrations/{source}` in `app/integrations/routers.py`. Calendar
has no provider module yet (`is_source_registered` 404s cleanly for it) — still pending, per-user OAuth work. Do
not build new integration work against shared/global test credentials in `.env` — that pattern was an early
bootstrapping shortcut for standalone MCP connectivity testing (see below), not the production design. Route new
work through the existing per-source OAuth pattern rather than reintroducing a global credential.

## MCP integrations: connectivity-tested standalone

Each source's MCP server has a standalone connectivity test script under `backend/scripts/` — raw MCP protocol
only, no LLM/agent involved:

- **GitHub** — official server (Docker, `ghcr.io/github/github-mcp-server`), `manual_test_github_mcp.py`.
- **Slack** — `@modelcontextprotocol/server-slack` (npx), `manual_test_slack_mcp.py`. Write tools are restricted in
  the script itself (`ALLOWED_CHANNEL_NAME`) to only ever target the `#logline_mcp_test` channel.
- **Google Calendar** — `@cocal/google-calendar-mcp` (npx), `manual_test_calendar_mcp.py`.
- **Jira** — community `sooperset/mcp-atlassian` (Docker, `ghcr.io/sooperset/mcp-atlassian`),
  `manual_test_jira_mcp.py`.

These four scripts are the only surviving use of the shared/global test credentials in `.env` — nothing else in the
codebase connects to these MCP servers. `manual_test_write_event.py` covers the one custom tool that survived the
agentic-runner removal directly against Postgres, no MCP server involved.

## REST API (`app/api/` equivalents — one router per domain, see below)

Ordinary FastAPI CRUD routes for the frontend, wired into `app/main.py` under these prefixes:

- `/auth` (`app/auth/routers.py`) — `GET /me`, `POST /signup`, `GET /verify-email`, `POST /resend-verification`,
  `POST /forgot-password`, `POST /reset-password`, `POST /login`, `GET /google/login`, `GET /google/callback`. JWT
  bearer tokens (`pyjwt` + `bcrypt`, see `app/core/security.py`), not session cookies —
  `app/auth/deps.py::get_current_user` decodes the `Authorization: Bearer <token>` header and is the DI dependency
  every other router uses to scope queries to the current user.
- `/integrations` (`app/integrations/routers.py`) — `GET ""`, `POST /{source}/connect-link`, `GET
  /{source}/connect`, `GET /{source}/callback`, `DELETE /{source}`. See the OAuth section above.
- `/entries` (`app/entries/routers.py`) — `GET ""`, `GET /{entry_id}`, `PATCH /{entry_id}`, `POST
  /{entry_id}/approve`. There's intentionally no `POST /entries` — entries are created by
  `POST /reconciliation/approve`, not directly by the user through this router.
- `/timeline` (`app/timeline/routers.py`) — `GET ""`, `PATCH /{event_id}`, `DELETE /{event_id}`.
- `/self_captures` (`app/self_captures/routers.py`) — `POST ""`.
- `/tracker` (`app/tracker_sync/routers.py`) — `GET /sync/checkpoint`, `POST /sync`. Receives batches of local
  activity sessions from the separate `tracker/` desktop app (a sibling top-level project, not part of this
  backend), authenticated per-device via `TrackerDevice`'s encrypted long-lived token rather than user JWT. This is
  the ingestion path that feeds Phase 4 stage 1 (`app/local_activity/`'s pure aggregation function reads the
  `local_sessions` rows this endpoint writes).

Error convention across all of the above: 404 for a resource that doesn't exist *or* belongs to another user, 401
for missing/invalid auth. Do not use 403 to distinguish "not yours" from "doesn't exist" — with no
sharing/collaboration model, every resource is single-owner, so confirming existence to a non-owner via a different
status code is a pure information leak with no legitimate use. Scope ownership checks in the query itself
(`.filter(Entry.id == id, Entry.user_id == current_user.id)`), not as a separate check after fetching — see
`_get_owned_entry` in `app/entries/routers.py` and `_get_owned_event` in `app/timeline/routers.py`.

## Local dev

Postgres runs via Docker Compose (container name `logline_postgres`), not installed natively. Use `docker-compose
up` in this directory, not a local `pg_ctl`/`brew services` Postgres.
