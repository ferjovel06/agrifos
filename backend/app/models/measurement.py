"""Append-only outputs and auditable calibration inputs."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPKMixin


class ReadingResult(Base, UUIDPKMixin):
    __tablename__ = "reading_results"
    __table_args__ = (UniqueConstraint("reading_id", "fingerprint", name="uq_reading_results_fingerprint"),)
    reading_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("readings.id"), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    calibration_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sensor_calibrations.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalibrationPairRecord(Base, UUIDPKMixin):
    __tablename__ = "sensor_calibration_pairs"
    __table_args__ = (UniqueConstraint("user_id", "reading_id", "variable", name="uq_sensor_calibration_pair"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    reading_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("readings.id"), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(120), nullable=False)
    context_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    variable: Mapped[str] = mapped_column(String(32), nullable=False)
    laboratory: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SensorCalibration(Base, UUIDPKMixin):
    __tablename__ = "sensor_calibrations"
    __table_args__ = (UniqueConstraint("user_id", "profile_id", "version", name="uq_sensor_calibration_version"),
                     CheckConstraint("state IN ('candidate', 'validated', 'retired')", name="ck_sensor_calibration_state"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, server_default="candidate")
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pair_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
