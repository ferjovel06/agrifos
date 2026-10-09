import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, Float, String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base
from app.models.mixins import RevisionMixin, UUIDPKMixin


class Reading(Base, RevisionMixin, UUIDPKMixin):
    """NPK readings from sensors."""
    __tablename__ = "readings"
    __table_args__ = (
        CheckConstraint("measurement IS NOT NULL OR (nitrogen IS NOT NULL AND phosphorus IS NOT NULL AND potassium IS NOT NULL AND ec IS NOT NULL AND ph IS NOT NULL AND temperature IS NOT NULL AND humidity IS NOT NULL)", name="ck_readings_provenance_or_legacy_values"),
        CheckConstraint("measurement IS NULL OR (jsonb_typeof(measurement)='object' AND COALESCE(measurement->'contract_version'='1'::jsonb,false))", name="ck_readings_measurement_version"),
    )

    parcel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parcels.id"), nullable=False)

    nitrogen: Mapped[float | None] = mapped_column(Float, nullable=True)
    phosphorus: Mapped[float | None] = mapped_column(Float, nullable=True)
    potassium: Mapped[float | None] = mapped_column(Float, nullable=True)
    ec: Mapped[float | None] = mapped_column(Float, nullable=True)
    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Cache projection published through the existing reading change journal.
    derived_results: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    parcel: Mapped["Parcel"] = relationship(back_populates="readings")
    fertilization_plans: Mapped[list["FertilizationPlan"]] = relationship(
        back_populates="reading"
    )


class LabAnalysis(Base, RevisionMixin, UUIDPKMixin):
    """Lab analysis of soil samples."""
    __tablename__ = "lab_analyses"
    __table_args__ = (
        UniqueConstraint(
            "parcel_id",
            "sample_code",
            name="uq_lab_analyses_parcel_sample_code",
        ),
    )

    parcel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parcels.id"), nullable=False)

    sample_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    depth_start_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_end_cm: Mapped[float | None] = mapped_column(Float, nullable=True)

    ph: Mapped[float] = mapped_column(Float)
    ph_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ec: Mapped[float | None] = mapped_column(Float, nullable=True)
    ec_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    organic_matter_pct: Mapped[float] = mapped_column(Float)
    cic: Mapped[float] = mapped_column(Float)
    clay_pct: Mapped[float] = mapped_column(Float)
    silt_pct: Mapped[float] = mapped_column(Float)
    sand_pct: Mapped[float] = mapped_column(Float)
    nitrogen: Mapped[float] = mapped_column(Float)
    phosphorus: Mapped[float] = mapped_column(Float)
    phosphorus_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    potassium: Mapped[float] = mapped_column(Float)
    potassium_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    calcium: Mapped[float] = mapped_column(Float)
    magnesium: Mapped[float] = mapped_column(Float)
    sulfur: Mapped[float] = mapped_column(Float)
    lab: Mapped[str] = mapped_column(String(150))

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    parcel: Mapped["Parcel"] = relationship(back_populates="lab_analyses")
    fertilization_plans: Mapped[list["FertilizationPlan"]] = relationship(
        back_populates="lab_analysis"
    )
