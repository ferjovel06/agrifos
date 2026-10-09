"""Durable synchronization metadata; no client credentials are stored here."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncChange(Base):
    __tablename__ = "sync_changes"
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False, index=True)
    farm_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)
    operation: Mapped[str] = mapped_column(String(10), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SyncReceipt(Base):
    __tablename__ = "sync_receipts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    after_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    until_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WeatherHttpCache(Base):
    __tablename__ = "weather_http_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
