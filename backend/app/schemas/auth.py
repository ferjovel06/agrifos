from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


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


class RegisterRequest(LoginRequest):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=150, pattern=r"\S")


class EmailRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


class EmailTokenRequest(BaseModel):
    token: SecretStr = Field(min_length=32, max_length=128)


class PasswordResetRequest(EmailTokenRequest):
    new_password: SecretStr = Field(min_length=1, max_length=1024)


class PasswordChangeRequest(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=1, max_length=1024)


class MfaEnrollmentResponse(BaseModel):
    factor_id: UUID
    qr_code: str
    secret: str


class MfaEnrollmentVerifyRequest(BaseModel):
    factor_id: UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
