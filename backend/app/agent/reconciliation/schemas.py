"""Define structured-output schemas and deterministic validation for reconciliation drafts."""

import enum
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.reconciliation.constants import (
    DESCRIPTION_MAX_LENGTH, DESCRIPTION_TRUNCATION_SUFFIX, MINUTES_PER_DAY, REMINDER_NOTE_MAX_LENGTH,
    REVIEW_REASON_MAX_LENGTH, TAG_SUGGESTION_REASON_MAX_LENGTH,
)

DateType = date


class EntryTag(str, enum.Enum):
    """Define canonical work-log tags in expected prompt-frequency order."""

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


ONES = r"one|two|three|four|five|six|seven|eight|nine"
TEENS = r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
TENS = r"twenty|thirty|forty|fourty|fifty|sixty|seventy|eighty|ninety"
NUMBER_WORD = rf"(?:{TENS})(?:[\s-](?:{ONES}))?|{TEENS}|{ONES}"

PERIOD = r"(?:day|morning|afternoon|evening)"

VERBAL_SUBJECT = r"(?:did|didn't|do|don't|does|doesn't|you|i|we|they|to|would|should|could|will|can|might)"

DURATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "digits followed by a time unit",
        re.compile(r"\b\d+(?:[.,]\d+)?[\s-]*(?:h|hrs?|hours?|m|mins?|minutes?|days?)\b", re.IGNORECASE),
    ),
    (
        "compound hour/minute duration",
        re.compile(r"\b\d{1,2}\s*h(?:rs?)?\s*\d{1,2}\s*(?:m|mins?)?\b", re.IGNORECASE),
    ),
    (
        "spelled-out quantity with a time unit",
        re.compile(
            rf"\b(?:an?|half|couple|few|several|{NUMBER_WORD})"
            r"\s+(?:of\s+)?(?:hours?|hrs?|minutes?|mins?|days?)\b",
            re.IGNORECASE,
        ),
    ),
    ("\"half an hour\"", re.compile(r"\bhalf\s+an?\s+(?:hour|hr)\b", re.IGNORECASE)),
    (
        "\"spent\"/\"spend\" used as a verb",
        re.compile(
            r"\bspent\b"
            rf"|\b{VERBAL_SUBJECT}\s+(?:you\s+|i\s+|we\s+|they\s+)?spend(?:ing)?\b"
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
    (
        "interrogative duration request",
        re.compile(r"\bhow\s+long\b|\bhow\s+much\s+time\b", re.IGNORECASE),
    ),
    (
        "whole-period duration claim",
        re.compile(
            rf"\ball\s+(?:of\s+the\s+)?{PERIOD}\b"
            rf"|\bthe\s+(?:entire|whole)\s+{PERIOD}\b"
            rf"|\b(?:most|the\s+rest)\s+of\s+the\s+{PERIOD}\b"
            rf"|\bhalf\s+(?:the|a)\s+{PERIOD}\b"
            rf"|\ba\s+full\s+{PERIOD}\b",
            re.IGNORECASE,
        ),
    ),
)


def find_duration_language(note: str) -> str | None:
    """Return the first explicit or hedged duration-language pattern in a note, or None.

    Colon-form clock times are allowed; ambiguous compact `14h30` forms are treated as durations.
    """
    for label, pattern in DURATION_PATTERNS:
        if pattern.search(note):
            return label
    return None


def truncate_description(description: str) -> str:
    """Limit description text while preserving complete words when a boundary is available."""
    if len(description) <= DESCRIPTION_MAX_LENGTH:
        return description
    keep = DESCRIPTION_MAX_LENGTH - len(DESCRIPTION_TRUNCATION_SUFFIX)
    truncated = description[:keep].rstrip()
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + DESCRIPTION_TRUNCATION_SUFFIX


def _reject_duplicate_block_ids(allocations: list["BlockAllocation"], field_name: str) -> None:
    """Reject duplicate block IDs within one allocation list."""
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


class ReviewBlockAllocation(BlockAllocation):
    """Expose the local day for a residual block so range review can assign it correctly."""

    date: DateType | None = None


class DraftEntry(BaseModel):
    """Proposed work-log entry with time allocations linked to measured blocks."""

    model_config = ConfigDict(extra="forbid")

    date: date
    project: str | None = Field(default=None, min_length=1)
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


class ReviewDraftEntry(DraftEntry):
    """Editable review entry, including persisted identity or explicitly asserted manual time."""

    entry_id: int | None = Field(default=None, gt=0)
    origin: Literal["evidence", "manual"] = "evidence"
    allocations: list[ReviewBlockAllocation] = Field(default_factory=list)
    manual_minutes: int | None = Field(default=None, gt=0, le=MINUTES_PER_DAY)

    @model_validator(mode="after")
    def _validate_origin(self) -> "ReviewDraftEntry":
        if self.origin == "evidence":
            if not self.allocations:
                raise ValueError("evidence entries require at least one measured block allocation")
            if self.manual_minutes is not None:
                raise ValueError("evidence entries cannot carry manual_minutes")
        else:
            if bool(self.allocations) == (self.manual_minutes is not None):
                raise ValueError("manual entries require either measured allocations or manual_minutes, not both")
            if self.source_remote_event_ids:
                raise ValueError("manual entries cannot cite remote events")
        return self


class TagSuggestion(BaseModel):
    """A model-proposed override of an entry's deterministically assigned tag, with its reason."""

    model_config = ConfigDict(extra="forbid")

    tag: EntryTag
    reason: str = Field(min_length=1, max_length=TAG_SUGGESTION_REASON_MAX_LENGTH)


class EntryDescriptionProposal(BaseModel):
    """Contain the model's per-entry prose and optional tag suggestion."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=DESCRIPTION_MAX_LENGTH)
    tag_suggestion: TagSuggestion | None = None


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
    """Complete reconciliation draft output containing entries, AI reminders, and residual block allocations.

    `tracked_wall_clock_minutes` is measured wall-clock time with concurrency counted once, so it can legitimately be
    less than the entries' allocated total when real overlapping work exists.
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[DraftEntry] = Field(default_factory=list)
    reminders: list[DraftReminder] = Field(default_factory=list)
    residual_unassigned_minutes: list[BlockAllocation] = Field(default_factory=list)
    tracked_wall_clock_minutes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _reject_repeated_residual_blocks(self) -> "WorkLogDraft":
        """Reject residual lists charging the same block more than once."""
        _reject_duplicate_block_ids(self.residual_unassigned_minutes, "residual_unassigned_minutes")
        return self


class ReviewWorkLogDraft(WorkLogDraft):
    """Review-time draft whose entries carry persisted IDs or manual-time assertions."""

    entries: list[ReviewDraftEntry] = Field(default_factory=list)
    residual_unassigned_minutes: list[ReviewBlockAllocation] = Field(default_factory=list)
