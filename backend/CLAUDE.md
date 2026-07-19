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

Validated via Pydantic schemas in `app/entries/schemas.py`. Don't assume `content`
is a plain string anywhere.

## Stack

FastAPI, SQLAlchemy, PostgreSQL, Pydantic, Alembic for migrations.

## LLM API: OpenAI, behind a provider abstraction (decided 2026-07-06)

The agent runner uses OpenAI (`LLM_PROVIDER=openai`, model configurable via
`LLM_MODEL`, default `gpt-5-mini`) but nothing outside `app/agent/llm/` may import
`openai` or `anthropic` directly:

- `app/agent/llm/base.py` — the neutral `LLMProvider` interface plus
  `Message`/`ToolDefinition`/`ToolCall`/`AgentResponse` dataclasses.
- `app/agent/llm/openai_provider.py` — the only file that imports `openai` and
  converts to/from its wire format.
- `app/agent/llm/__init__.py::get_llm_provider()` — factory reading
  `LLM_PROVIDER` from `.env`; anything other than `"openai"` raises
  `NotImplementedError` rather than failing silently.

Switching providers (e.g. adding Anthropic back) means adding one new file
under `app/agent/llm/` and one branch in the factory — `runner.py` and
`toolbelt.py` never change.

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
  `#logline_mcp_test` channel. Reads go through one composite custom tool,
  `get_slack_channel_activity(name)` (in `toolbelt.py`), which resolves the
  channel and reads its history in one call, falling back to listing the
  bot's real accessible channels if the name doesn't resolve. This replaced
  a two-tool `slack_find_channel` + `slack_list_my_channels` flow that burned
  an extra round trip and — because neither tool marked "slack" as attempted
  — could let `write_draft_entry`'s source-check (below) pass without Slack
  ever really being checked.
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

`write_event`, `get_existing_events`, `flag_gap`, and `write_draft_entry`
(all in `app/agent/tools/`) are built and tested. `flag_gap` computes gaps
dynamically from the `events` table — it never writes a row.

### `write_draft_entry` requires every connected source to have been checked

`flag_gap` only answers "is there uncovered time in the events table" —
a different question from "did the agent actually check every connected
source." Live testing showed the model could conflate the two and
synthesize a draft having silently skipped GitHub/Slack entirely. A
prompt-only fix wasn't enough, so this is now enforced in code:
`Toolbelt` (in `toolbelt.py`) tracks which sources (github/slack/jira/
calendar) have had at least one tool call attempted this run in
`self._attempted_sources`, and `write_draft_entry` is refused with an
error naming the missing sources until each connected source has at least
one attempt (success or failure both count). Scoped to whichever sources
actually connected this run, not unconditionally all four, so a source
that failed to connect can't deadlock the agent.

## Agent runner (`app/agent/runner.py`, `app/agent/toolbelt.py`)

`run_agent(user_id, task)` is the live loop: build the toolbelt, get the
configured `LLMProvider`, then call/execute/append in a loop (capped at
`MAX_TOOL_ROUNDS = 15`) until the model stops requesting tools. Tested
end-to-end via `backend/scripts/manual_test_agent_runner.py`.

`Toolbelt` (in `toolbelt.py`) connects to all four MCP servers using the same
stdio server params proven in `scripts/manual_test_*_mcp.py`, and registers
`write_event`/`get_existing_events`/`flag_gap` as `ToolDefinition`s so the
runner treats every tool uniformly. MCP tool names are namespaced
`{source}__{native_name}` (e.g. `github__get_me`) to route dispatch and avoid
cross-server name collisions. The Slack write-tool channel restriction from
`manual_test_slack_mcp.py` is carried over unchanged in `Toolbelt.dispatch`.

Current limitation: MCP connections use the shared test credentials in
`.env`, not per-user OAuth — every `user_id` gets the same MCP sessions until
the real `/integrations/{source}/connect` flow exists.

## REST API (`app/api/`)

Ordinary FastAPI CRUD routes for the frontend — no LLM/agent/MCP involved.
Wired into `app/main.py` with prefixes `/auth`, `/integrations`, `/entries`,
`/timeline`, `/self_captures`.

- Auth is JWT bearer tokens (`pyjwt` + `bcrypt`, see `app/core/security.py`),
  not session cookies. `app/api/deps.py::get_current_user` decodes the
  `Authorization: Bearer <token>` header and is the DI dependency every other
  router uses to scope queries to the current user.
- `GET /auth/me` (`app/api/auth.py`) returns the current user via
  `get_current_user`. Used by the frontend's Account & Settings modal to
  populate profile fields on open.
- `POST /integrations/{source}/connect` is a placeholder returning 501 — real
  per-source OAuth flows aren't built yet.
- There's intentionally no `POST /entries` — entries are created by the agent
  (via `write_event`-style tools), not directly by the user through the API.
- Error convention: 404 for a resource that doesn't exist *or* belongs to
  another user, 401 for missing/invalid auth. Do not use 403 to distinguish
  "not yours" from "doesn't exist" — with no sharing/collaboration model,
  every resource is single-owner, so confirming existence to a non-owner via
  a different status code is a pure information leak with no legitimate use.
  Scope ownership checks in the query itself (`.filter(Entry.id == id,
  Entry.user_id == current_user.id)`), not as a separate check after
  fetching — see `_get_owned_entry` in `app/api/entries.py`.

## Frontend known gaps

The Entry Detail slide-over panel (view/edit a single event's summary, time,
and raw evidence; delete an entry) was never built — `TimelineBlock`'s click
handler (`frontend/src/molecules/TimelineBlock.tsx`) is currently a no-op
stub. This is a real missing page/component from the original Phase 4 scope,
not a minor bug.

## Local dev

Postgres runs via Docker Compose (container name `logline_postgres`), not
installed natively. Use `docker-compose up` in this directory, not a local
`pg_ctl`/`brew services` Postgres.
