from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MfaChallengeResponse(BaseModel):
    mfa_required: Literal[True] = True
    challenge_id: UUID
    expires_in: int


class MfaVerifyRequest(BaseModel):
    challenge_id: UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
