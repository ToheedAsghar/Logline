# Logline Backend

Logline is an agentic work-log and standup assistant. It pulls signal from tools
people already use (GitHub, Slack, Jira, Calendar) and helps them reconstruct what
they did — surfacing it with an honest sense of how much to trust each piece.

## Core principle: evidence/confidence grounding

Every piece of surfaced information carries a `confidence` value, and there are
only three:

- **proven** — directly evidenced (e.g. a merged PR, a calendar event that happened)
- **estimated** — inferred, editable by the user
- **gap** — no data; ask the user

Do not add a fourth confidence value. In particular, non-work time is not a
special "personal" confidence — it's `source="personal"` or `source="dismissed"`
with `confidence="proven"`. The source describes *what it is*; confidence
describes *how sure we are*. Keep that separation.

## Architecture: fully agentic, no hardcoded pipeline

There is no deterministic orchestration layer — no `correlation_engine.py`, no
`draft_generator.py`, no fixed sequence of "fetch → correlate → draft" steps as
separate services. Instead, an LLM agent is given a toolbelt (MCP servers for
GitHub/Slack/Jira/Calendar, plus custom tools we define) and decides entirely on
its own which tools to call, in what order, and when to stop.

- Tool **contracts** (inputs/outputs) are strictly Pydantic-validated.
- The agent's **reasoning** about which tools to call and why is unconstrained —
  don't try to hardcode that decision logic in Python.

If you find yourself writing a Python module that decides "first call X, then
call Y, then merge results" — stop. That decision belongs to the agent, not to
scaffolding code.

## Data model: generic event shape

Every event, regardless of source, has the same shape:

```
{source, type, timestamp, metadata, confidence}
```

Never add per-source tables or per-source branching logic. New integrations
should slot into this shape, not extend it.

### `metadata` is a reserved name on SQLAlchemy's declarative base

Workaround in use: the DB column is named `metadata`, but the Python attribute
is renamed:
- `events` table → Python attribute `event_metadata`
- `integrations` table → Python attribute `integration_metadata`

Follow this same pattern (`<table>_metadata`) for any future metadata-style
JSONB columns.

### `entries.content` is JSONB, not TEXT

Shape depends on `entries.format`:
- `standup` → `{yesterday, today, blockers}`
- `project_log` → `{text}`

Validated via Pydantic schemas in `app/schemas/entry.py`. Don't assume `content`
is a plain string anywhere.

## Stack

FastAPI, SQLAlchemy, PostgreSQL, Pydantic, Alembic for migrations.

## LLM API: not yet decided

Do not assume Anthropic or OpenAI anywhere in the codebase until explicitly told
which one we're using. Keep tool definitions and schema work API-agnostic until
that decision is made. This is still undecided as of 2026-07-06 — continue to
keep all tool/schema code API-agnostic until told otherwise.

## MCP integrations: all four independently verified (as of 2026-07-06)

Each source's MCP server has been connectivity-tested standalone — raw MCP
protocol only, no LLM/agent involved. None of these test scripts call any
LLM API:

- **GitHub** — official server (Docker, `ghcr.io/github/github-mcp-server`),
  tested via `backend/scripts/manual_test_github_mcp.py`.
- **Slack** — `@modelcontextprotocol/server-slack` (npx), tested via
  `backend/scripts/manual_test_slack_mcp.py`. Write tools
  (`slack_post_message`, `slack_reply_to_thread`, `slack_add_reaction`) are
  hard-restricted in code via `call_tool_restricted` to only ever target the
  `#logline_mcp_test` channel.
- **Google Calendar** — `@cocal/google-calendar-mcp` (npx), tested via
  `backend/scripts/manual_test_calendar_mcp.py`. Requires a one-time browser
  auth step, already completed; credentials live at
  `backend/gcp-oauth.keys.json`.
- **Jira** — community `sooperset/mcp-atlassian` (Docker), tested via
  `backend/scripts/manual_test_jira_mcp.py`.

### Two separate credential sets per source in `.env` — don't conflate them

- **OAuth App credentials** (`*_CLIENT_ID` / `*_CLIENT_SECRET` /
  `*_REDIRECT_URI`) — for the real user-facing "Connect X" flow we'll build
  later, where any Logline user connects their own account.
- **Personal/API token credentials** (PAT, bot token, API token) — used only
  for our own standalone MCP connectivity testing above, tied to our own
  accounts. Not meant for multi-user production use.

## Agent tools progress

`write_event`, `get_existing_events`, and `flag_gap` (all in
`app/agent/tools/`) are built and tested. `flag_gap` computes gaps
dynamically from the `events` table — it never writes a row.

## Local dev

Postgres runs via Docker Compose (container name `logline_postgres`), not
installed natively. Use `docker-compose up` in this directory, not a local
`pg_ctl`/`brew services` Postgres.
