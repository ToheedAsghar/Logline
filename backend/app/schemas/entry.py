from datetime import datetime
from typing import Union

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.entry import EntryFormat, EntryStatus


class StandupContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yesterday: str
    today: str
    blockers: str


class ProjectLogContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


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


class EntryCreate(BaseModel):
    user_id: int
    format: EntryFormat
    content: dict
    status: EntryStatus = EntryStatus.draft

    @model_validator(mode="after")
    def _validate_content(self) -> "EntryCreate":
        self.content = parse_entry_content(self.format, self.content).model_dump()
        return self


class EntryUpdate(BaseModel):
    # `format` is immutable and intentionally absent here, so content shape
    # can't be checked until the caller supplies the entry's existing format.
    content: dict | None = None
    status: EntryStatus | None = None
    approved_at: datetime | None = None

    def validate_content_for(self, format: EntryFormat) -> "EntryUpdate":
        if self.content is not None:
            self.content = parse_entry_content(format, self.content).model_dump()
        return self


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    format: EntryFormat
    content: dict
    status: EntryStatus
    created_at: datetime
    approved_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_content(self) -> "EntryResponse":
        parse_entry_content(self.format, self.content)
        return self
