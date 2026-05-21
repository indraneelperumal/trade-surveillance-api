from __future__ import annotations

from pydantic import BaseModel, Field


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class AuthRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class AuthUserInfo(BaseModel):
    id: str
    email: str


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
    user: AuthUserInfo
