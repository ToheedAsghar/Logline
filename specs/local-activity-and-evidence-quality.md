# Spec: Local Activity & Evidence Quality (Phase 4 pipeline)

Status: DRAFT — awaiting human review before Plan phase.
Branch: continues uncommitted work on `toheed/feature/pipeline-classify-evidence`.

## Objective

Logline's automatic reconciliation output (Stage 5 draft entries, reviewed on the Review page) is
visibly lower quality than manually pasting raw tracker logs into Claude/ChatGPT and asking for the
same workstream format. Two root causes were confirmed against real production data (user 2328,
2026-08-06) rather than assumed:

1. **Screen-lock time is misclassified as work.** `com.apple.loginwindow` (macOS's lock screen)
   logged 520 minutes that day across 17 sessions — including single stretches of 364, 280, and 220
   minutes — none flagged `is_idle=true`. `IdleWatcher` (`tracker/watchers/idle_watcher.py`) detects
   idleness via keyboard/mouse input (`CGEventSource`) and evidently does not fire while the screen is
   locked, so this time survives the `LocalSession.is_idle.is_(False)` filter in
   `_gather_evidence` (`app/agent/reconciliation/routers.py:122`), falls through
   `classify_session` into the `admin` catch-all (`com.apple.loginwindow` is in no known bundle-id
   list), and chains with other `(admin, project=None)` rows into multi-hour garbage blocks — the
   direct source of the "Login window and system idle session" entries in the screenshots.
2. **There is no remote evidence to reconcile against.** `remote_events` has zero rows for this user,
   ever. `integrations` shows GitHub/Jira/Slack all `connected` as of 2026-08-06, but
   `remote_fetch_state` is empty and `app/remote_fetch/orchestrator.py::fetch_all_sources` — the only
   entry point into Stage 2 — is never called from anywhere outside its own test suite. This is why
   all 136 blocks that day show `UNSURE`: there is nothing to match against, not a matching-logic
   defect. It is also the real gap versus the manual Claude example — that evidence was pasted in by
   hand; Logline's automatic equivalent (connected integrations) has never actually run.
   **Decided:** wire this into `POST /reconciliation/generate` — awaiting `fetch_all_sources(user_id)`
   before `_gather_evidence` runs (see Decisions below).
3. **`SlackFetcher` is dead code today regardless of trigger point.** It exists
   (`app/remote_fetch/mcp/slack.py`, with a configured 90s timeout in
   `remote_fetch/constants.py::SOURCE_TIMEOUT_SECONDS`), but `orchestrator.py::ALL_FETCHERS` only
   registers `GitHubFetcher`, `JiraFetcher`, `CalendarFetcher`. Even after wiring, a user with Slack
   connected (user 2328 included) would never get Slack evidence. Independent bug, fix regardless of
   how fetch gets triggered.

**Success looks like:** a real day's Review page shows blocks that a human would recognize as
distinct work sessions (no lock-screen time folded into "Coding"), and shows real corroborating
GitHub/Jira/Slack evidence for a connected user, materially reducing the UNSURE rate and the need for
kitchen-sink multi-hour entries.

**Users:** Toheed (single user today), reviewing their own auto-generated work log before approving it.

**Explicitly out of scope for this spec:** rewriting the Stage 5 prompt/rules
(`app/agent/reconciliation/prompt.py`) — it already enforces conservation, citation discipline, and a
documented grouping rule (rule 8); it is correctly describing the bad evidence it's given. Do not
touch it unless a task below proves the prompt itself is the defect after the evidence is fixed.

## Tech Stack

No new dependencies. Existing stack: FastAPI + SQLAlchemy + Postgres (backend), Pydantic schemas,
`app/agent/llm` provider abstraction (OpenAI today). Local dev Postgres via `docker-compose` (container
`logline_postgres`) — see backend/CLAUDE.md.

## Commands

```
Test (backend):     cd backend && pytest
Test (one file):    cd backend && pytest tests/test_local_activity_classification.py -v
Lint:                cd backend && isort <touched files> && flake8 <touched files or package>
Migrate:              cd backend && alembic upgrade head   # run `alembic heads` first, see known 2-head issue
Dev DB query:        docker exec -i logline_postgres psql -U logline -d logline -c "<query>"
```

## Project Structure (files this spec touches)

```
backend/app/local_activity/constants.py       → new lock-screen/idle bundle-id list, category naming
backend/app/local_activity/classification.py  → new SessionCategory.idle + detection rule
backend/app/local_activity/aggregation.py     → confirm idle blocks close/never chain (likely no change
                                                  needed once the category exists — same-key merge logic
                                                  already isolates distinct categories)
backend/app/agent/reconciliation/prompt.py    → no rule changes needed for Idle -- it never reaches
                                                  the model (see Decisions)
backend/app/agent/reconciliation/evidence.py  → build_evidence excludes Idle blocks from the LLM-facing
                                                  bundle; their minutes are accounted for deterministically
                                                  instead (exact shape is a Plan-phase task)
backend/app/agent/reconciliation/routers.py   → POST /generate awaits fetch_all_sources(user_id) before
                                                  _gather_evidence; update its now-stale "read-only,
                                                  doesn't depend on a live fetch" docstring
backend/app/remote_fetch/orchestrator.py      → register SlackFetcher in ALL_FETCHERS (currently
                                                  missing -- Slack never fetches even once wired up)
backend/tests/                                → one new permanent pytest file per fix (see Testing
                                                  Strategy) — no throwaway/ephemeral validation scripts
```

## Code Style

Match the existing module style exactly — this codebase's docstrings are load-bearing (see
backend/CLAUDE.md "Comments and docstrings"). Example, from `classification.py`:

```python
def _is_coding(bundle_id: str, project_path: Optional[str]) -> bool:
    if project_path is None:
        return False
    return bundle_id in KNOWN_IDE_BUNDLE_IDS or bundle_id in KNOWN_TERMINAL_BUNDLE_IDS
```

Deterministic, one-purpose predicate functions checked in a fixed priority order inside
`classify_session`; each rule documented with WHY it exists and WHY its priority position matters, not
just WHAT it matches. New idle/lock-screen detection should follow the exact same shape as the
existing `_is_meeting`/`_is_code_review`/etc. predicates, with its bundle-id list added to
`constants.py` next to `KNOWN_IDE_BUNDLE_IDS`.

## Testing Strategy

- pytest, existing suite structure (`tests/test_local_activity_classification.py`,
  `tests/test_local_activity_aggregation_categories.py`, `tests/test_pipeline_classify_and_evidence_fixture.py`
  are the direct siblings of anything new here).
- Every fix in this spec gets a **permanent** pytest test, not an ephemeral validation script — this
  project's established convention after prior live-validation work.
- Reuse the `test_pipeline_classify_and_evidence_fixture.py` pattern (drive real
  `classify_session` → `aggregate_local_activity` → `build_evidence` → `verify_draft`, no LLM call) to
  add a fixture reproducing the loginwindow/lock-screen scenario directly — it is a perfect template
  since it already exists to catch exactly this class of real-data-vs-fixture gap.
- Before closing this spec's work, re-run a live comparison against real 2026-08-06 data (same method
  the current branch already used) and confirm the block count / UNSURE rate materially improves —
  don't rely on unit tests alone given the whole premise here is "unit tests passed, real data didn't."
- Any live-validation DB rows created during testing get cleaned up afterward (per established project
  practice) — do not leave test artifacts in the shared dev Postgres "for precedent."

## Boundaries

- **Always:** run pytest + isort + flake8 on touched files before considering a task done; keep
  `SessionCategory`'s existing five values' behavior unchanged (this is additive, not a rename); keep
  the confidence-grounding principle (proven/estimated/gap) intact — an idle block is `proven`
  non-work, never a fabricated `estimated` entry.
- **Ask first:** any change to `prompt.py`'s numbered rules (renumbering is a documented breaking
  change per its own docstring); any change to the UTC-day-boundary behavior noted below, since it's a
  documented, deliberately deferred limitation elsewhere in the codebase.
- **Never:** silently drop idle/lock-screen rows the way the old `project_path IS NOT NULL` filter
  silently dropped browser rows (this codebase has explicitly called that pattern out as a past bug —
  see `aggregation.py` module docstring and the fixture test's
  `TestOldPipelineWouldHaveDroppedMostOfTheDay`); commit real user data (query output, screenshots) into
  the repo or into test fixtures — use synthetic/scaled fixtures as the existing tests already do.

## Success Criteria

1. A raw `local_sessions` row with `bundle_id="com.apple.loginwindow"` (or other lock-screen
   signal) never becomes part of a Coding/Admin block's `apps` list, and never contributes to a
   Coding-tagged entry's minutes.
2. Re-running the pipeline against the real 2026-08-06 data for user 2328 shows the ~520 lock-screen
   minutes correctly separated out, and the previous multi-hour "Login window and system idle" blocks
   no longer appear as Coding entries.
3. `POST /reconciliation/generate` awaits `fetch_all_sources(user_id)` before building evidence, and
   running it against user 2328's real GitHub/Jira/Slack connections populates `remote_events` with
   real rows (including Slack, once `SlackFetcher` is registered).
4. Re-running reconciliation for a day with populated remote evidence shows a materially lower UNSURE
   rate than 136/136, with entries citing real `source_remote_event_ids` (e.g. real PR numbers) the way
   the manual Claude example did.
5. Every fix has a permanent, passing pytest test under `backend/tests/`, and the full suite
   (`cd backend && pytest`) passes clean.
6. `isort`/`flake8` clean on every touched file.

## Decisions (resolved during spec review)

1. **Idle blocks skip the Stage 5 model entirely.** `build_evidence` excludes Idle-category blocks
   from the LLM-facing bundle; their minutes are accounted for deterministically in code instead (exact
   mechanism — a dedicated field vs. folding into `residual_unassigned_minutes` — is a Plan-phase task).
   Consistent with how pre-built reminders are already handled: merged in code, never left to the
   model's judgment, per backend/CLAUDE.md's confidence-grounding principle (non-work time is `proven`,
   not something to ask an LLM about).
2. **Remote-fetch triggers from `POST /reconciliation/generate`.** The endpoint awaits
   `fetch_all_sources(user_id)` before `_gather_evidence` runs. This intentionally supersedes the
   endpoint's current docstring claim that reconciliation is read-only and doesn't depend on a live
   fetch succeeding — update that docstring as part of this change, and surface partial-source failure
   (a source hitting its timeout) to the response rather than swallowing it, since `fetch_all_sources`
   already returns per-source `ok`/`error` and that information shouldn't be dropped on the floor.
   Accepted tradeoff: a cold first fetch (no prior `remote_fetch_state`) can take up to the per-source
   timeout (120s for GitHub/Jira) since it pulls a 90-day lookback; every fetch after that is
   incremental via the high-water mark and should be fast. The frontend should show a
   fetching/generating state rather than a silent hang.

## Open Questions

1. **New category name.** `SessionCategory.idle`? `.locked`? `.away`? Needs to read clearly in both
   internal code and, since it's excluded from the LLM bundle entirely (see Decisions), possibly in the
   Review UI directly (a chip showing "Idle — Xh Ym, not counted as work" or similar). Recommend `idle`
   for consistency with the existing `is_idle` DB flag and `tracker`'s `END_REASON_IDLE`/`idle_start`
   vocabulary — a naming call worth a quick confirm, low stakes either way.
2. **UTC day-boundary bug (secondary, not blocking).** `_gather_evidence`'s `as_utc_bounds()` and
   `aggregation.py::_merge_unlimited_within_day`'s `row.start_time.date()` both use UTC, not the user's
   local day. For a non-UTC user this can split or duplicate a local day's activity across two queried
   UTC days. Already a documented, deliberately deferred limitation elsewhere in the codebase
   (`aggregation.py`'s "user-local-date-boundary follow-up" comment) — recommend leaving deferred here
   too unless it's found to materially affect the loginwindow/UNSURE numbers once measured again.
3. **Should `com.apple.SecurityAgent` (macOS's auth-prompt process, 2 rows / <1 min in the real data)
   get the same idle treatment as loginwindow?** Low-volume in this sample but same underlying
   phenomenon (screen lock/auth) — recommend including it in the same bundle-id list rather than
   special-casing loginwindow alone.
