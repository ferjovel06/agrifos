from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthCredential(Base):
    __tablename__ = "auth_credentials"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(String)
    email_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    mfa_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthMfaFactor(Base):
    __tablename__ = "auth_mfa_factors"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("auth_credentials.user_id", ondelete="CASCADE"), index=True)
    secret_ciphertext: Mapped[str] = mapped_column(String)
    last_verified_counter: Mapped[int | None] = mapped_column(BigInteger)


class AuthMfaChallenge(Base):
    __tablename__ = "auth_mfa_challenges"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("auth_credentials.user_id", ondelete="CASCADE"), index=True)
    factor_id: Mapped[UUID] = mapped_column(ForeignKey("auth_mfa_factors.id", ondelete="CASCADE"))
    password_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
