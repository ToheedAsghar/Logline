# Proposal: Truncate event text before it reaches the LLM prompt

Status: **Proposed.** Not implemented yet — awaiting review before any code changes.

## Context

During live-fetch testing, some calendar/Jira event summaries and descriptions turned out to be
very long (Zoom links, passcodes, full agendas, Jira description bodies). When these reach the
LLM prompt via the reconciliation pipeline, they consume tokens that could be bounded. This
proposal covers truncating event text *before* it enters the evidence pipeline, separate from
the already-enforced 280-character cap on the LLM's *output* descriptions.

## What reaches the LLM today

The LLM receives evidence text built by `_format_event_line` (`evidence.py:272`), which
includes `event.summary` but **not** `event.description`. The `description` field lives on
the `RemoteEvent` ORM model but is never passed to `RemoteEventData` (`matcher.py:38`) and
therefore never enters the reconciliation pipeline. So the immediate token-cost concern is
`summary` only.

| Field | Source | Currently reaches LLM? | Example length |
| --- | --- | --- | --- |
| `summary` | GitHub PR title, Jira summary, Calendar event title, Slack message text | **Yes** — via `_format_event_line` | 20-300+ chars |
| `description` | Calendar HTML body, Jira description, PR body | **No** — not in `RemoteEventData` | 100-5000+ chars |
| LLM output | Generated entry description | Yes — capped at 280 chars via `DESCRIPTION_MAX_LENGTH` | ≤280 chars |

## Where truncation should apply

### Option A: Truncate `summary` on `RemoteEventData` (recommended)

At the point where `RemoteEvent` ORM rows are converted to `RemoteEventData` dataclasses
(`routers.py:134-141`), apply `truncate_summary(event.summary)` before passing it into the
matching pipeline. This bounds tokens entering the evidence text without touching storage.

```python
# app/agent/reconciliation/routers.py, inside _gather_evidence
RemoteEventData(
    ...
    summary=truncate_summary(row.summary),
)
```

### Option B: Truncate at storage time

Apply truncation in `upsert_remote_events` (`orchestrator.py:72`) before writing to the DB.
This saves storage but permanently loses data — a stricter trade-off that isn't necessary
for token bounding alone.

**Recommendation:** Option A. Storage is cheap; the LLM token budget is the constraint.
Truncating at the consumption boundary leaves the full data available for future non-LLM
uses (search, display, export).

## Suggested per-field limit

`SUMMARY_MAX_LENGTH = 300` characters.

Rationale:
- `DESCRIPTION_MAX_LENGTH` is already 280 for LLM output. Input summaries at 300 are
  consistent.
- GitHub PR titles rarely exceed 100 chars. Calendar event titles rarely exceed 80.
  Jira summaries occasionally reach 200+ when they include ticket descriptions in the
  summary field.
- 300 chars preserves the useful part (title/subject) while cutting noise (Zoom passcodes,
  full agendas, trailing Jira markup).
- A separate constant from `DESCRIPTION_MAX_LENGTH` (280) to avoid coupling input and
  output limits.

## Truncation strategy: end-truncation with word boundary

```python
def truncate_summary(summary: str | None) -> str | None:
    if summary is None or len(summary) <= SUMMARY_MAX_LENGTH:
        return summary
    keep = SUMMARY_MAX_LENGTH - len(TRUNCATION_SUFFIX)
    truncated = summary[:keep].rstrip()
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + TRUNCATION_SUFFIX
```

Why end-truncation (not beginning):
- Event titles put the useful signal first: "Add Jira OAuth flow" is more useful than the
  trailing "— review comments addressed".
- Calendar titles are "Meeting Name (N attendees)" — the name is the useful part.
- GitHub PR titles are "FEAT(scope): description" — the type/scope are most useful.

Risk: occasionally the most informative part is at the end (e.g. a Jira summary where the
title is generic but the description has specifics). This is an acceptable trade-off at 300
chars — the first 300 characters of most summaries contain the subject. If this proves
wrong in practice, a smarter middle-truncation strategy can be added later.

## Interaction with the evidence.py PII/redaction issue

The `description` field (which may contain raw HTML, Zoom passcodes, PII) currently does NOT
reach the LLM — it's excluded from `RemoteEventData`. The standing project decision is to
address PII/redaction in `evidence.py` as a dedicated pass. This proposal is independent:
- It only truncates `summary`, which is already sent to the LLM.
- It doesn't touch `description` or `raw_data`.
- It doesn't modify `evidence.py` itself.

**Recommendation:** Ship this as a separate change. The PII pass should address what happens
when `description` is eventually added to `RemoteEventData` (sanitization, redaction, HTML
stripping at storage time). Bundling them would conflate two different concerns.

## Files to change

| File | Change |
| --- | --- |
| `app/agent/reconciliation/constants.py` | Add `SUMMARY_MAX_LENGTH = 300` |
| `app/agent/reconciliation/schemas.py` | Add `truncate_summary()` (parallel to existing `truncate_description()`) |
| `app/agent/reconciliation/routers.py` | Apply `truncate_summary()` in `_gather_evidence` when building `RemoteEventData` |

## Testing

- Unit test: `truncate_summary` preserves short strings, truncates long ones at word boundary,
  returns None for None input.
- Integration: verify reconciliation still generates valid descriptions with truncated summaries.
- Live: confirm token usage doesn't increase when running reconciliation against real data.
