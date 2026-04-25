from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InvestigationNoteCreate(BaseModel):
    alert_id: UUID | None = None
    investigation_id: UUID | None = None
    note_type: str = "COMMENT"
    content: str
    author_id: UUID | None = None
    is_system: bool = False


class InvestigationNoteUpdate(BaseModel):
    note_type: str | None = None
    content: str | None = None
    author_id: UUID | None = None
    is_system: bool | None = None


class InvestigationNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: UUID | None
    investigation_id: UUID | None
    note_type: str
    content: str
    author_id: UUID | None
    is_system: bool
    created_at: datetime
