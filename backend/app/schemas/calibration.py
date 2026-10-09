"""Clients supply laboratory evidence; model coefficients/metrics are server-derived."""
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LaboratoryReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    laboratory: str = Field(min_length=1, max_length=150)
    report_id: str = Field(min_length=1, max_length=120)
    sampled_at: datetime
    sampling_procedure: str = Field(min_length=1, max_length=1500)
    depth_start_cm: float = Field(ge=0, allow_inf_nan=False)
    depth_end_cm: float = Field(ge=0, allow_inf_nan=False)
    moisture_conditions: str = Field(min_length=1, max_length=500)
    method: str = Field(min_length=1, max_length=150)
    report_basis: str = Field(min_length=1, max_length=150)
    unit: str = Field(min_length=1, max_length=20)
    analyte: str = Field(min_length=1, max_length=32)
    reference_value: float = Field(allow_inf_nan=False)
    uncertainty: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    comparability_evidence: str = Field(min_length=1, max_length=2000)
    soil_type: str | None = Field(default=None, min_length=1, max_length=120)
    synthetic: bool = False

    @field_validator("sampled_at")
    @classmethod
    def acquisition_time(cls, value):
        if value.tzinfo is None or value.year < 2000 or value > datetime.now(timezone.utc):
            raise ValueError("A plausible timezone-aware sample timestamp is required")
        return value

    @model_validator(mode="after")
    def ordered_depth(self):
        if self.depth_end_cm < self.depth_start_cm:
            raise ValueError("Sample depth must be increasing")
        return self


class CalibrationPairCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reading_id: uuid.UUID
    sample_id: str = Field(min_length=1, max_length=120)
    variable: Literal["nitrogen", "phosphorus", "potassium"]
    laboratory: LaboratoryReference


class CalibrationTrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    profile_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    pair_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    holdout_sample_ids: list[str] = Field(min_length=1, max_length=200)
    predictors: list[Literal["humidity", "temperature", "ph", "ec"]] = Field(default_factory=list, max_length=4)
    model_kind: Literal["linear", "bias"] = "linear"
    training_evidence: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def unique_inputs(self):
        if len(set(self.pair_ids)) != len(self.pair_ids) or len(set(self.predictors)) != len(self.predictors) or len(set(self.holdout_sample_ids)) != len(self.holdout_sample_ids):
            raise ValueError("Calibration inputs must not be repeated")
        return self


class CalibrationValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    validation_evidence: str = Field(min_length=1, max_length=2000)
