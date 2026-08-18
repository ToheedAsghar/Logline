from datetime import date, datetime
from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.entries.models import EntryFormat, EntryStatus


class StandupContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yesterday: str
    today: str
    blockers: str


class ContentAllocation(BaseModel):
    """Minutes charged against one measured activity block, as persisted on an entry.

    Mirrors `BlockAllocation` in the reconciliation schemas rather than importing it, so the stored
    shape of an entry stays independent of the draft schema the agent happens to emit today.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: int = Field(gt=0)
    minutes: int = Field(gt=0, le=24 * 60)


class ProjectLogContent(BaseModel):
    """Stored content of a project-log entry.

    `text` is the only required field and the only one plain (non-reconciled) entries carry. The rest
    are the reconciliation provenance -- which blocks the time was charged against, which remote events
    it cites, and why it was flagged -- kept so an approved entry remains auditable against the evidence
    it came from. They are optional, and omitted entirely (not stored as nulls) when absent, so entries
    written before reconciliation existed keep their exact `{"text": ...}` shape.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    project: str | None = None
    tag: str | None = None
    allocations: list[ContentAllocation] | None = None
    source_remote_event_ids: list[str] | None = None
    review_reason: str | None = None
    origin: Literal["evidence", "manual"] | None = None
    manual_minutes: int | None = Field(default=None, gt=0, le=24 * 60)

    @model_validator(mode="after")
    def _validate_provenance(self) -> "ProjectLogContent":
        if self.origin == "evidence":
            if not self.allocations or self.manual_minutes is not None:
                raise ValueError("evidence content requires allocations and cannot carry manual_minutes")
        elif self.origin == "manual":
            if bool(self.allocations) == (self.manual_minutes is not None):
                raise ValueError("manual content requires either allocations or manual_minutes, not both")
            if self.source_remote_event_ids:
                raise ValueError("manual content cannot cite remote events")
        return self


EntryContent = Union[StandupContent, ProjectLogContent]

_CONTENT_SCHEMA_BY_FORMAT: dict[EntryFormat, type[BaseModel]] = {
    EntryFormat.standup: StandupContent,
    EntryFormat.project_log: ProjectLogContent,
}


def parse_entry_content(format: EntryFormat, content: dict) -> EntryContent:
    """Validate a raw content dict against the shape required by `format`.

    Raises pydantic.ValidationError if `content` has missing, extra, or
    mistyped keys for that format.
    """
    schema = _CONTENT_SCHEMA_BY_FORMAT[format]
    return schema.model_validate(content)


def normalize_entry_content(format: EntryFormat, content: dict) -> dict:
    """Validate a raw content dict and return the exact dict to store on `entries.content`.

    Every write path goes through here rather than calling `.model_dump()` itself, so none of them can
    drift on how absent optional fields are stored. `exclude_none` is the point: a plain project-log
    entry stays `{"text": ...}` instead of being padded with a null for every reconciliation field it
    never had.
    """
    return parse_entry_content(format, content).model_dump(exclude_none=True)


class EntryCreate(BaseModel):
    user_id: int
    format: EntryFormat
    content: dict
    work_date: date
    status: EntryStatus = EntryStatus.draft

    @model_validator(mode="after")
    def _validate_content(self) -> "EntryCreate":
        self.content = normalize_entry_content(self.format, self.content)
        return self


class EntryUpdate(BaseModel):
    content: dict | None = None
    status: EntryStatus | None = None
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def _reject_internal_discarded_status(self) -> "EntryUpdate":
        if self.status == EntryStatus.discarded:
            raise ValueError("discarded is an internal reconciliation lifecycle status")
        return self

    def validate_content_for(self, format: EntryFormat) -> "EntryUpdate":
        if self.content is not None:
            self.content = normalize_entry_content(format, self.content)
        return self


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    format: EntryFormat
    content: dict
    work_date: date
    status: EntryStatus
    created_at: datetime
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_content(self) -> "EntryResponse":
        parse_entry_content(self.format, self.content)
        return self
