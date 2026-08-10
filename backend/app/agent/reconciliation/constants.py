"""Constants and configuration defaults for Stage 5-6 reconciliation.

Centralized here so schema bounds, prompt rules, verifier keys, and message templates are maintainable in one place.
"""

from app.local_activity.constants import TOPIC_SESSION_GAP_MINUTES

DESCRIPTION_MAX_LENGTH = 280
DESCRIPTION_TRUNCATION_SUFFIX = "..."
REVIEW_REASON_MAX_LENGTH = 280
REMINDER_NOTE_MAX_LENGTH = 280
TAG_SUGGESTION_REASON_MAX_LENGTH = 120
MINUTES_PER_DAY = 24 * 60

MAX_CONCURRENT_DESCRIPTION_REQUESTS = 8
MAX_RANGE_DAYS = 31

TOPIC_ENTRY_MINUTES_FLOOR = 10
FLOORED_TOPIC_KINDS = frozenset({"pr", "branch"})

ENTRY_MIN_MINUTES = 5

CATEGORY_MERGE_MAX_MINORITY_SHARE = 0.40

ENTRY_MERGE_GAP_MINUTES = TOPIC_SESSION_GAP_MINUTES
ENTRY_MERGE_MAX_SPAN_MINUTES = 240

FRAGMENT_CLUSTER_MIN_BLOCKS = 3
FRAGMENT_CLUSTER_MAX_SPAN_MINUTES = 30

NO_MATCHED_EVIDENCE_LINE = "(no matched remote evidence)"
EVENT_INDENT = "    "

CHECK_CONSERVATION = "conservation"
CHECK_UNKNOWN_ID = "unknown_id"
CHECK_COMPLETENESS = "completeness"
CHECK_CROSS_ENTRY_DUPLICATE = "cross_entry_duplicate"
CHECK_DUPLICATE_REMINDER = "duplicate_reminder"
CHECK_UNEXPLAINED_OVERLAP = "unexplained_overlap"
CHECK_DESCRIPTION_DURATION_LANGUAGE = "description_duration_language"

RESIDUAL_FIELD = "residual_unassigned_minutes"

MEETING_NO_EVENT_DESCRIPTION = "Meeting (unidentified)"
MEETING_UNSAFE_DESCRIPTION = "Meeting"
MEETING_MULTIPLE_EVENTS_REVIEW_REASON = (
    "Multiple calendar events matched this meeting block; used the earliest by time for the description."
)

UNIDENTIFIED_PROJECT = "an unidentified project"
NOTE_WITH_SUMMARIES = "Unlogged {source} activity on {project}: {summaries}"
NOTE_WITHOUT_SUMMARIES = "Unlogged {source} activity on {project}, with no measured local activity."
NOTE_LAST_RESORT = "Unlogged remote activity with no measured local activity."

ERROR_UNKNOWN_REMINDER_SOURCE = (
    "cannot convert a reminder from source {source!r} into a DraftReminder; DraftReminder.source accepts only "
    "{allowed}. A reminder reached Stage 5 from a source the draft schema does not model."
)

OVERLAP_REVIEW_REASON_TEMPLATE = (
    "Overlaps Meeting block(s) {ids}; the two may double-count concurrent work during that meeting."
)

VIOLATION_INVENTED_PR = "invented PR #{number} not in this entry's evidence"
VIOLATION_DURATION_LANGUAGE = "contains duration/time language: {label}"
VIOLATION_NO_OP_TAG = "tag_suggestion repeats the entry's current tag"
VIOLATION_PROVIDER_FAILURE = "the provider failed to produce valid structured output: {error}"
