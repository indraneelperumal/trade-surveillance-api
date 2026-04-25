from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    email: str
    display_name: str | None = None
    role: str = "ANALYST"
    is_active: bool = True
    supabase_uid: str | None = None


class UserUpdate(BaseModel):
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    supabase_uid: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    role: str
    is_active: bool
    supabase_uid: str | None
    created_at: datetime
    updated_at: datetime
