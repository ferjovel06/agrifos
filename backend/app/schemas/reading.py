import uuid
import math
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.diagnostic import SensorDiagnosticRead
from app.schemas.measurement import LEGACY_LIMITS, VARIABLES, MeasurementProvenance, normalized_raw


class ReadingCreate(BaseModel):
    """Payload sent by the IoT sensor or the application when registering a reading."""

    model_config = ConfigDict(extra="forbid")

    parcel_id: uuid.UUID

    measurement_id: uuid.UUID | None = None
    nitrogen: float | None = Field(default=None, allow_inf_nan=False)
    phosphorus: float | None = Field(default=None, allow_inf_nan=False)
    potassium: float | None = Field(default=None, allow_inf_nan=False)
    ec: float | None = Field(default=None, allow_inf_nan=False)
    ph: float | None = Field(default=None, allow_inf_nan=False)
    temperature: float | None = Field(default=None, allow_inf_nan=False)
    humidity: float | None = Field(default=None, allow_inf_nan=False)
    measurement: MeasurementProvenance | None = None

    # If the sensor does not send a timestamp, the server's time is used (server_default).
    recorded_at: datetime | None = Field(
        default=None, description="Timestamp of the reading (optional, defined by the sensor)."
    )

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_not_in_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value > datetime.now(timezone.utc):
            raise ValueError("recorded_at cannot be a future date.")
        return value

    @model_validator(mode="after")
    def preserve_and_match_raw(self):
        if self.measurement is None:
            if self.measurement_id is not None:
                raise ValueError("measurement_id requires versioned provenance")
            for key, (low, high) in LEGACY_LIMITS.items():
                value = getattr(self, key)
                if value is None or not low <= value <= high:
                    raise ValueError(f"{key} must be between {low} and {high}.")
            return self
        if self.recorded_at is not None and self.recorded_at != self.measurement.acquired_at:
            raise ValueError("recorded_at must match acquired_at")
        self.recorded_at = self.measurement.acquired_at
        for key in VARIABLES:
            variable = self.measurement.variables.get(key)
            expected = normalized_raw(key, variable) if variable is not None else None
            supplied = getattr(self, key)
            if supplied is not None and (expected is None or not math.isclose(supplied, expected, rel_tol=1e-12, abs_tol=1e-12)):
                raise ValueError(f"{key} must match the decoded raw value and unit")
            setattr(self, key, expected)
        return self

    def orm_values(self, *, entity_id: uuid.UUID | None = None) -> dict:
        if self.measurement_id is not None and entity_id is not None and self.measurement_id != entity_id:
            raise ValueError("measurement_id must match the synchronization entity ID")
        result = self.model_dump(exclude={"measurement_id", "measurement"}, exclude_none=True)
        if self.measurement is not None:
            result["measurement"] = self.measurement.model_dump(mode="json")
        if entity_id is not None or self.measurement_id is not None:
            result["id"] = entity_id or self.measurement_id
        return result


class ReadingRead(BaseModel):
    revision: int = 1
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parcel_id: uuid.UUID
    nitrogen: float | None
    phosphorus: float | None
    potassium: float | None
    ec: float | None
    ph: float | None
    temperature: float | None
    humidity: float | None
    recorded_at: datetime
    received_at: datetime | None = None
    measurement: MeasurementProvenance | None = None
    derived_results: list[dict] = Field(default_factory=list)


class ReadingCreateResponse(ReadingRead):
    diagnosis: SensorDiagnosticRead | None = None
    warnings: list[str] = Field(default_factory=list)
