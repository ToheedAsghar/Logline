"""Structured-output Pydantic schemas for Stage 5 AI reconciliation.

Defines `WorkLogDraft`, `DraftEntry`, `DraftReminder`, and `BlockAllocation`. Measured time enters only via
`BlockAllocation.minutes` bound to measured block IDs to prevent AI duration guesses.
"""

import enum
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DESCRIPTION_MAX_LENGTH = 280
REVIEW_REASON_MAX_LENGTH = 280
REMINDER_NOTE_MAX_LENGTH = 280
MINUTES_PER_DAY = 24 * 60


class EntryTag(str, enum.Enum):
    """Canonical work-log entry tags ordered by expected prompt frequency.

    Enum string values are matched verbatim downstream.
    Member order reflects expected frequency to steer model tag selection.
    """

    coding = "Coding"
    debugging = "Debugging"
    code_review = "Code Review"
    meeting = "Meeting"
    testing = "Testing"
    documentation = "Documentation"
    coordination = "Coordination"
    deployment = "Deployment"
    project_planning = "Project Planning"
    architecture_design = "Architecture Design"
    designing = "Designing"
    technical_project_setup = "Technical Project Setup"
    backlog_grooming = "Backlog grooming"
    support_tickets = "Support Tickets"
    support = "Support"
    r_and_d = "R&D"
    tech_assessment = "Tech Assessment"
    reviews = "Reviews"
    reporting_analysis = "Reporting/Analysis"
    training_learning = "Training/Learning"
    team_engagement = "Team Engagement"
    team_management = "Team Management"
    project_estimations = "Project Estimations"
    presenting = "Presenting"
    interviewing = "Interviewing"
    recruiting = "Recruiting"
    course_authoring = "Course Authoring"
    account_management = "Account Management"
    customer_implementation = "Customer Implementation"
    operations = "Operations"
    audit_compliance = "Audit/Compliance"
    sales_client_demo = "Sales/Client Demo"
    marketing_campaigns = "Marketing Campaigns"
    capex = "Capex"
    opex = "Opex"
    other = "Other"


ReminderSource = Literal["github", "jira", "slack", "calendar"]


_ONES = r"one|two|three|four|five|six|seven|eight|nine"
_TEENS = r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
_TENS = r"twenty|thirty|forty|fourty|fifty|sixty|seventy|eighty|ninety"
# Order matters: the compound tens form is tried before the bare ones so "forty-five" is not read as "forty".
_NUMBER_WORD = rf"(?:{_TENS})(?:[\s-](?:{_ONES}))?|{_TEENS}|{_ONES}"

_PERIOD = r"(?:day|morning|afternoon|evening)"

_VERBAL_SUBJECT = r"(?:did|didn't|do|don't|does|doesn't|you|i|we|they|to|would|should|could|will|can|might)"

DURATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "2 hours", "45 min", "1.5hrs", "30m", "2-hour", "90-minute", "3 days"
    (
        "digits followed by a time unit",
        re.compile(r"\b\d+(?:[.,]\d+)?[\s-]*(?:h|hrs?|hours?|m|mins?|minutes?|days?)\b", re.IGNORECASE),
    ),
    # Compound hour/minute durations (e.g. "1h30"). This shape is indistinguishable from the European clock-time
    # format ("14h30"), which is therefore also matched — see `find_duration_language`.
    (
        "compound hour/minute duration",
        re.compile(r"\b\d{1,2}\s*h(?:rs?)?\s*\d{1,2}\s*(?:m|mins?)?\b", re.IGNORECASE),
    ),
    # Spelled-out quantities with time units (e.g. "two hours", "forty-five minutes", "a few minutes").
    (
        "spelled-out quantity with a time unit",
        re.compile(
            rf"\b(?:an?|half|couple|few|several|{_NUMBER_WORD})"
            r"\s+(?:of\s+)?(?:hours?|hrs?|minutes?|mins?|days?)\b",
            re.IGNORECASE,
        ),
    ),
    ("\"half an hour\"", re.compile(r"\bhalf\s+an?\s+(?:hour|hr)\b", re.IGNORECASE)),
    (
        "\"spent\"/\"spend\" used as a verb",
        re.compile(
            r"\bspent\b"
            rf"|\b{_VERBAL_SUBJECT}\s+(?:you\s+|i\s+|we\s+|they\s+)?spend(?:ing)?\b"
            r"|\bspend(?:ing)?\s+(?:time|about|approximately|approx|roughly|around|nearly|almost)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hedged duration phrase",
        re.compile(
            r"\b(?:for|took|takes|taking|lasted|lasting|logged)"
            r"\s+(?:about|approximately|approx|roughly|around|nearly|almost|~)\b",
            re.IGNORECASE,
        ),
    ),
    # Bare requests for a duration ("how long was that?") carry no unit of their own.
    (
        "interrogative duration request",
        re.compile(r"\bhow\s+long\b|\bhow\s+much\s+time\b", re.IGNORECASE),
    ),
    (
        "whole-period duration claim",
        re.compile(
            rf"\ball\s+(?:of\s+the\s+)?{_PERIOD}\b"
            rf"|\bthe\s+(?:entire|whole)\s+{_PERIOD}\b"
            rf"|\b(?:most|the\s+rest)\s+of\s+the\s+{_PERIOD}\b"
            rf"|\bhalf\s+(?:the|a)\s+{_PERIOD}\b"
            rf"|\ba\s+full\s+{_PERIOD}\b",
            re.IGNORECASE,
        ),
    ),
)


def find_duration_language(note: str) -> str | None:
    """Return the pattern label of the first duration phrase found in `note`, or None if clean.

    Scans for explicit or hedged time phrases ("2 hours", "45 min", "spent") to prevent AI duration assertions.

    Clock times written with a colon ("14:30", "9:00 to 9:30") are deliberately not treated as duration language —
    they name a point in time, not an amount of it. The European "14h30" form is not distinguishable from the
    compound duration "1h30" by shape alone and IS matched; reminder notes should use the colon form.
    """
    for label, pattern in DURATION_PATTERNS:
        if pattern.search(note):
            return label
    return None


def _reject_duplicate_block_ids(allocations: list["BlockAllocation"], field_name: str) -> None:
    """Raise if any block is charged twice within the same allocation list.

    Tier 2 (Python-side only): this cannot be pushed into the wire schema. OpenAI strict mode does not support
    `uniqueItems`, and even where it is supported it compares whole objects — so `{block 1, 30min}` plus
    `{block 1, 45min}` would pass as two distinct items while double-counting block 1's measured time.
    """
    seen: set[int] = set()
    for allocation in allocations:
        if allocation.block_id in seen:
            raise ValueError(
                f"{field_name} must charge each block at most once; block_id {allocation.block_id} appears "
                f"more than once. Sum the minutes for a block into a single allocation."
            )
        seen.add(allocation.block_id)


class BlockAllocation(BaseModel):
    """Minutes charged against a single measured block."""

    model_config = ConfigDict(extra="forbid")

    block_id: int = Field(gt=0)
    minutes: int = Field(gt=0, le=MINUTES_PER_DAY)


class DraftEntry(BaseModel):
    """Proposed work-log entry with time allocations linked to measured blocks."""

    model_config = ConfigDict(extra="forbid")

    date: date
    project: str = Field(min_length=1)
    allocations: list[BlockAllocation] = Field(min_length=1)
    tag: EntryTag
    description: str = Field(min_length=1, max_length=DESCRIPTION_MAX_LENGTH)
    source_remote_event_ids: list[str] = Field(default_factory=list)
    review_reason: str | None = Field(default=None, max_length=REVIEW_REASON_MAX_LENGTH)

    @model_validator(mode="after")
    def _reject_repeated_blocks(self) -> "DraftEntry":
        """Reject entries charging the same block more than once, which would double-count measured time."""
        _reject_duplicate_block_ids(self.allocations, "allocations")
        return self


class DraftReminder(BaseModel):
    """Question for the user about ambiguous evidence that could not be automatically reconciled."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=REMINDER_NOTE_MAX_LENGTH)
    source: ReminderSource
    day: date
    source_remote_event_ids: list[str] = Field(default_factory=list)

    @field_validator("note")
    @classmethod
    def _reject_duration_language(cls, value: str) -> str:
        """Reject notes containing explicit or hedged duration language."""
        label = find_duration_language(value)
        if label is not None:
            raise ValueError(
                f"reminder note must not assert or ask for a duration (matched: {label}); "
                f"time comes only from measured blocks. Got: {value!r}"
            )
        return value


class WorkLogDraft(BaseModel):
    """Complete reconciliation draft output containing entries, AI reminders, and residual block allocations."""

    model_config = ConfigDict(extra="forbid")

    entries: list[DraftEntry] = Field(default_factory=list)
    reminders: list[DraftReminder] = Field(default_factory=list)
    residual_unassigned_minutes: list[BlockAllocation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_repeated_residual_blocks(self) -> "WorkLogDraft":
        """Reject residual lists charging the same block more than once."""
        _reject_duplicate_block_ids(self.residual_unassigned_minutes, "residual_unassigned_minutes")
        return self
