# Proposal: Remove MCP from `remote_fetch`, fix the Slack identity gap

Status: **Implemented.** Part B landed on `toheed/feature/remote-fetch-direct-api` (commits `063e6df`/`9496d13`,
plus follow-up review-driven fixes), stacked on #72. Kept here as the design record — "Part A" below describes the
pre-implementation MCP state, not current `main`.

## Pre-flight note

This branch (`toheed/feature/production-logging`) currently has an in-progress merge with 4
unresolved conflicts (`app/agent/llm/constants.py`, `gemini_provider.py`, `openai_provider.py`,
`app/auth/routers.py`). None of these overlap `app/remote_fetch/` — those files are already
staged/resolved in the merge — so this investigation was safe to do read-only. Flagging it here
because it means the working tree is mid-operation; resolve or abort that merge before starting
any implementation from this proposal.

## Part A: Current state — MCP vs. direct API, per source

All four fetchers are the same shape: they call `self.fetch(user_id, since)`
(`app/remote_fetch/base.py:53`), which opens an MCP `ClientSession` via
`connect_mcp_source()` (`app/remote_fetch/mcp/connection.py:144`) and hands it to
`fetch_with_session()`. Every fetcher below calls `session.call_tool(...)` — **none of the
four make a direct HTTP call to the provider's REST API.** Living under `mcp/` is accurate,
not just a stale directory name.

| Source | File | MCP server | Tool calls used |
| --- | --- | --- | --- |
| GitHub | `app/remote_fetch/mcp/github.py` | Docker: `ghcr.io/github/github-mcp-server` (`connection.py:41-58`) | `get_me` (github.py:173), `list_commits` (github.py:221), `list_pull_requests` (github.py:253), `search_commits` / `search_pull_requests` (github.py:306) |
| Jira | `app/remote_fetch/mcp/jira.py` | Docker: `ghcr.io/sooperset/mcp-atlassian` (`connection.py:97-125`) | `jira_search` (jira.py:115) |
| Calendar | `app/remote_fetch/mcp/calendar.py` | npx: `@cocal/google-calendar-mcp` (`connection.py:76-94`) | `list-events` (calendar.py:112) |
| Slack | `app/remote_fetch/mcp/slack.py` | npx: `@modelcontextprotocol/server-slack` (`connection.py:61-73`) | `slack_list_channels` (slack.py:46), `slack_get_channel_history` (slack.py:200) |

Slack is **already removed from `ALL_FETCHERS`** (`app/remote_fetch/orchestrator.py:29-33` lists
only `GitHubFetcher, JiraFetcher, CalendarFetcher`) — confirming the earlier investigation's
finding. GitHub, Jira, and Calendar are still live in the orchestrator today, all three via MCP.

Every MCP server is spun up from a single global credential in `.env`
(`ENV_GITHUB_TEST_PAT`, `ENV_SLACK_BOT_TOKEN`+`ENV_SLACK_TEAM_ID`, `ENV_GOOGLE_OAUTH_CREDENTIALS`,
`ENV_JIRA_API_TOKEN`+`ENV_JIRA_EMAIL`+`ENV_JIRA_SITE_URL` — `connection.py:13-19`), not the
per-user OAuth tokens already stored in `oauth_tokens` for GitHub/Slack/Jira. This is the same
"shared test credentials" pattern `backend/CLAUDE.md` already flags as a bootstrapping
shortcut, not the production design — it just wasn't fully unwound yet.

### What's shared across fetchers that a removal needs to preserve

- **`app/remote_fetch/base.py`** — `SourceFetcher` ABC, `FetchedEvent`/`SourceFetchData`
  dataclasses, `SourceUnavailable` exception. None of this is MCP-specific; it's the
  fetch-then-normalize contract the orchestrator depends on. Survives untouched except that
  `fetch()`'s body (`base.py:53-60`, currently `connect_mcp_source` + `AsyncExitStack`) needs
  a per-source replacement for "acquire a client/session" — see Part B.
- **`app/remote_fetch/mcp/connection.py`** — `mcp_result_to_json()` (flattens MCP text blocks
  to JSON) is MCP-only and goes away entirely once no caller uses `session.call_tool`. The
  `MCP_SERVER_BUILDERS` registry and `connect_mcp_source()` go away with it. Nothing here is
  reused by direct API calls.
- **`app/remote_fetch/parsing.py`** — `first_non_empty_string`, `parse_iso_datetime`,
  `split_commit_message`, `parse_slack_ts`, `to_naive_utc_isoformat`. Pure functions, provider-
  format-agnostic where the payload shape doesn't change; these survive as-is.
- **`app/remote_fetch/orchestrator.py`** — `fetch_all_sources`, `upsert_remote_events`,
  `record_fetch_state`, per-source timeout/error isolation. All of this operates on
  `FetchedEvent`/`SourceFetchData` from `base.py`, not on MCP directly. Survives untouched.
- **`app/remote_fetch/constants.py`** — `SOURCE_TIMEOUT_SECONDS` per source will need
  retuning (MCP subprocess startup latency vs. a plain HTTP call are very different budgets),
  but the mechanism (`asyncio.wait_for` around `fetcher.fetch(...)` in
  `orchestrator.py:180`) is unaffected.
- **Response-shape parsing inside each fetcher** (`_commit_event`, `_pull_request_event`,
  `_issue_event`, `_calendar_event`, `_message_event`) reads dict payloads keyed exactly like
  each provider's native REST response (e.g. GitHub commit shape, Jira `fields.*`, Google
  Calendar event resource) — the MCP servers pass these through close to verbatim. Expect
  **most of this logic to survive**, with adjustments where an MCP server normalized something
  the raw REST API doesn't (flagged per-source below).

## Part B: Proposed direct-API replacement, per source

### GitHub

- **Auth**: `oauth_tokens.access_token` for the user's `github` `Integration`
  (`app/integrations/models.py:44-54`) — a real per-user OAuth token already exists and is
  currently unused by the fetch path. Header: `Authorization: Bearer <access_token>`,
  `Accept: application/vnd.github+json`. GitHub OAuth App tokens don't expire
  (`providers/github.py:5-9`), so no refresh-before-fetch logic is needed here beyond what
  `token_refresh.py` already provides generically.
- **Endpoints**:
  - `GET https://api.github.com/user` replaces `get_me` (github.py:173) — same `login` field.
  - `GET https://api.github.com/repos/{owner}/{repo}/commits?since=...&per_page=100&page=N`
    replaces `list_commits` (github.py:211-234). Response is a flat array, not
    `{commits:[...]}` or `{items:[...]}` — `_as_list` (github.py:30-40) needs a case for bare
    arrays, which it already has (`isinstance(payload, list)` branch), so this should work
    with no change to `_commit_event`.
  - `GET https://api.github.com/repos/{owner}/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100&page=N`
    replaces `list_pull_requests` (github.py:252-264). Same flat-array shape.
  - `GET https://api.github.com/search/commits?q=...&sort=committer-date&order=desc&per_page=100&page=N`
    (needs `Accept: application/vnd.github.cloak-preview+json` historically, verify current
    requirement) and `GET https://api.github.com/search/issues?q=...+type:pr&sort=updated&order=desc`
    replace `search_commits`/`search_pull_requests` (github.py:305-330). These *do* return
    `{items:[...]}` and `{total_count, items:[...]}` respectively — `_as_list`'s `items` key
    already covers this.
- **Rate limits**: direct REST calls are subject to GitHub's per-user rate limits
  (5000/hr authenticated) with no MCP server absorbing that; add a 403/`X-RateLimit-Remaining`
  check somewhere in the HTTP layer — the MCP server may have been silently retrying or the
  limit was never hit in testing. Flagged as a gap to design during implementation, not decided
  here.

### Jira

- **Auth**: this is the one source where the existing OAuth flow *doesn't* directly hand you a
  usable base URL. `providers/jira.py`'s docstring (lines 15-18) already documents that a
  separate `GET https://api.atlassian.com/oauth/token/accessible-resources` call is needed
  after obtaining the token, to discover the user's Jira **cloud ID** — "outside this module's
  scope." The direct-API replacement needs to add this discovery step (cache the cloud ID,
  it's stable per connection) before it can call Jira's REST API at
  `https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/...`.
- **Auth header**: `Authorization: Bearer <access_token>` against the `api.atlassian.com`
  proxy (not Basic Auth with API token + email — that's the *other* auth style Jira supports,
  and not what this app's OAuth 2.0 (3LO) flow produces).
- **Endpoint**: `POST /rest/api/3/search` with the same JQL body already built by
  `_build_jql()` (jira.py:142-177) — `{jql, fields, maxResults, startAt}` (note: REST API field
  name is `maxResults`, MCP's `limit` may have been a translation layer; verify against
  Atlassian's current REST v3 docs, not assumed). Response shape is `{issues: [...], ...}` —
  `_issues_from_payload` (jira.py:180-188) already handles the `issues` key.
  - **Description field risk**: `_issue_description` (jira.py:89-102) already anticipates that
    "the MCP server usually renders [ADF] to markdown for us, but not always." Direct REST API
    v3 returns `description` as a raw Atlassian Document Format (ADF) object *always*, not
    "usually" — this function's dict branch (`description.get("text")`) is a shallow ADF read
    that will likely lose nested formatting/paragraphs the MCP server was flattening. This
    needs either a real ADF-to-text renderer or an explicit decision to accept lossier
    descriptions. Flagged as a design question, not decided here.

### Calendar

- **Auth**: no per-user OAuth provider exists yet for Calendar
  (`backend/CLAUDE.md`: "Calendar has no provider module yet ... still pending, per-user OAuth
  work"). This is a **blocking prerequisite**, not a small task — direct API replacement for
  Calendar needs a full `CalendarOAuthProvider` (mirroring `providers/github.py`/`jira.py`)
  built and wired through `app/integrations/routers.py` before any direct-API fetcher can
  authenticate per-user. Today's MCP path sidesteps this entirely by using a shared
  `GOOGLE_OAUTH_CREDENTIALS` service-account/installed-app credential file
  (`connection.py:76-94`), which is exactly the kind of shared-credential shortcut
  `backend/CLAUDE.md` says new work shouldn't be built against.
- **Endpoint** (once per-user OAuth exists): `GET https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin=...&timeMax=...&maxResults=250`
  replaces `list-events` (calendar.py:112). Response shape `{items: [...]}` already matches
  `_events_from_payload` (calendar.py:139-148).
- **Scope**: `https://www.googleapis.com/auth/calendar.readonly` (read-only is sufficient;
  this app never writes calendar events).

### Slack — see Part C below; it's the dependency-heavy one.

## Part C: Fixing the Slack identity gap (dependency of re-adding Slack, not a separate task)

This is more built than the task brief assumed. Key finding: **a real per-user Slack OAuth
flow already exists** (`app/integrations/providers/slack.py`) and is already user-token-based,
not bot-token-based — `SlackOAuthProvider.build_authorize_url()` requests `user_scope`
(slack.py:191-198), and `_parse_authed_user_response`/`_parse_refresh_response`
(slack.py:104-154) both already parse `authed_user.access_token`, the user token. This flow is
simply unused by the fetch path today, which instead uses the separate global
`SLACK_BOT_TOKEN` through MCP (`connection.py:61-73`). Re-adding Slack via direct API means
switching the fetch path onto the OAuth flow that already exists, not building a new one from
scratch.

Three concrete gaps, in dependency order:

1. **`authed_user_id` is parsed but discarded before it ever reaches the database.**
   `OAuthTokens.authed_user_id` (`providers/base.py:33`) is populated correctly by both Slack
   parse functions, but `_upsert_oauth_token()` (`app/integrations/routers.py:175-184`) only
   copies `access_token`, `refresh_token`, `expires_at` onto the `OAuthToken` row — the fourth
   field is silently dropped. **Fix**: add an `authed_user_id` column to `oauth_tokens`
   (new Alembic migration; nullable, since GitHub/Jira/Calendar tokens don't have one), persist
   it in `_upsert_oauth_token`, along the same generic (non-source-branching) code path the
   rest of that function already uses. — **Done**, shipped in PR #72 (migration `808e7a2e4ee9`).

2. **`resolve_connected_slack_user_id()` is a stub returning `None`** (`mcp/slack.py:74-80`),
   which is why `SlackFetcher.fetch_with_session` currently always returns `SourceFetchData(events=[])`
   (slack.py:145-148) — every Slack fetch is a no-op today, independent of the MCP-vs-direct
   question. **Fix**: once (1) lands, this becomes `db.query(OAuthToken.authed_user_id).join(Integration)...`
   scoped to the calling `user_id`'s Slack integration — a real DB read, no longer a stub. This
   function's signature will need `user_id`/`db` parameters it doesn't currently take.

3. **Missing scope for DMs.** `SLACK_OAUTH_USER_SCOPES` (slack.py:22-27) is
   `channels:read, channels:history, groups:history, im:read` — **`im:read` lists DM
   conversations but does not grant reading their message content; `im:history` does, and it's
   missing.** This matches the memory note that DM huddle-metadata work was blocked without
   `im:history`. **Fix**: add `im:history` to `SLACK_OAUTH_USER_SCOPES`. Existing connected
   users will need to reconnect (Slack scope changes aren't retroactive to already-issued
   tokens) — this needs a note in the connect flow or a forced reconnect prompt, not silent
   failure. — **Done**, shipped in PR #72.

### Proposed direct-API Slack fetcher (once 1–3 land)

- **Auth**: user token from `oauth_tokens.access_token` (now correctly scoped, with
  `authed_user_id` available for identity filtering), header `Authorization: Bearer <token>`.
- **Endpoints**:
  - `GET https://slack.com/api/conversations.list?types=public_channel,private_channel,im&limit=200`
    replaces `slack_list_channels` (slack.py:46) — note `types` needs to include `im` explicitly
    to also enumerate DMs, which the current channel-only fetcher doesn't do at all; this is a
    scope expansion beyond a 1:1 MCP swap and should be called out to the user as a behavior
    change, not assumed. — **Approved**: DMs are in scope, deliberately, per explicit sign-off.
  - `GET https://slack.com/api/conversations.history?channel={id}&limit=200` replaces
    `slack_get_channel_history` (slack.py:200) — response shape `{ok, messages:[...],
    response_metadata:{next_cursor}}` matches what `_messages_from_payload` (slack.py:249-256)
    and `iter_all_slack_channels`'s cursor handling (slack.py:40-54) already expect; this is
    close to a drop-in.
- **Identity filtering**: `_message_event`'s `user != connected_user_id` check
  (slack.py:102-104) becomes real once `resolve_connected_slack_user_id` returns the real ID
  instead of always skipping via the `None` short-circuit. **Required verification once built**:
  confirm empirically against a real busy multi-person channel that only the connected user's
  messages ever reach `remote_events` — not yet exercised against real data.

### Re-adding Slack to `ALL_FETCHERS`

Once the direct-API `SlackFetcher` exists and 1–3 above are in place: add `SlackFetcher` back
to the list at `app/remote_fetch/orchestrator.py:29-33`, restoring it to
`FETCHERS`/`ALL_FETCHERS` alongside GitHub/Jira/Calendar. No other orchestrator change needed —
`fetch_all_sources` already iterates `FETCHERS` generically.

## Adjacent issues found, not fixed here

- **`backend/CLAUDE.md` documented `main` as having two divergent Alembic heads**
  (`283e0bebe749`, `d77b8f9a3c20`) — **confirmed stale**: already resolved by merge migration
  `6866f50785b9`. Worth a doc fix, low priority, not blocking.
- **GitHub search API rate-limit handling** is unaddressed by the current MCP fetcher and would
  become directly visible to this app's own HTTP client once MCP no longer absorbs it (flagged
  in Part B, GitHub section) — worth a design pass, not a blocker for the proposal itself.
- **The four standalone MCP connectivity scripts** (`backend/scripts/manual_test_*_mcp.py`,
  documented in `backend/CLAUDE.md` under "MCP integrations: connectivity-tested standalone")
  are the last surviving users of the shared/global `.env` test credentials. If MCP is removed
  from the live fetch path, these scripts either need to be kept as pure standalone
  connectivity smoke tests (harmless, but now testing a code path nothing else in the app
  uses) or removed along with the credentials they depend on. Not decided here.
- **Per-source fetch timeout budgets** (`SOURCE_TIMEOUT_SECONDS`, `constants.py:14-19`) were
  tuned for MCP subprocess spin-up latency (Docker pulls, npx installs). Direct HTTP calls will
  likely need much shorter timeouts, but the actual right numbers aren't something this
  investigation can determine without live measurement — flagged, not proposed.
- **Slack `conversations.list` pagination + rate limiting**: Slack's Web API has stricter
  per-method rate limits (Tier 3/4) than what the MCP server may have been buffering. Not
  addressed here.
- **Real migration-lineage note**: `808e7a2e4ee9` (this proposal's Slack migration, shipped in
  PR #72) is confirmed correctly based on `main`'s real head (`a3a236e45cad`), but will become
  a sibling head to PR #71's `a66fa2c77e22` once #71 merges — a merge migration
  (`alembic merge a66fa2c77e22 808e7a2e4ee9`) will be needed at that point. Expected, not urgent,
  tracked in PR #72's description.

## Status of open questions (now resolved, kept here for record)

1. Slack DM scope expansion — **approved**, in scope.
2. Calendar OAuth provider — **approved to build now**; shipped in PR #72
   (`CalendarOAuthProvider`, connect-flow only, no fetcher wired yet).
3. Forced reconnect on Slack scope change — **not built**; documented as a known limitation in
   the module docstring, no forced-reconnect UI, deferred.