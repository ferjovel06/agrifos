"""Versioned provenance, independent of agronomic interpretation."""
import math
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VARIABLES = ("nitrogen", "phosphorus", "potassium", "ec", "ph", "temperature", "humidity")
LEGACY_LIMITS = dict(zip(VARIABLES, ((0, 1000), (0, 1000), (0, 1000), (0, 20), (2, 10), (-10, 60), (0, 100))))
UNITS = {"nitrogen": {"mg/kg", "mg/L", "ppm", "%"}, "phosphorus": {"mg/kg", "mg/L", "ppm", "%"},
         "potassium": {"mg/kg", "mg/L", "ppm", "%"}, "ec": {"dS/m", "mS/cm", "uS/cm"},
         "ph": {"pH"}, "temperature": {"degC"}, "humidity": {"%"}}
ANALYTES = {"nitrogen": {"N", "NO3-N", "NO3", "unidentified"},
            "phosphorus": {"P", "P2O5", "unidentified"}, "potassium": {"K", "K2O", "unidentified"},
            "ec": {"ec"}, "ph": {"ph"}, "temperature": {"temperature"}, "humidity": {"humidity"}}


class MeasuredVariable(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    raw_value: float = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=20)
    analyte: str = Field(min_length=1, max_length=32)
    declared_range: tuple[float, float] | None = None
    read_status: Literal["valid", "suspect", "invalid"] = "valid"

    @field_validator("declared_range")
    @classmethod
    def finite_ordered_range(cls, value):
        if value is not None and (not all(math.isfinite(x) for x in value) or value[0] >= value[1]):
            raise ValueError("declared_range must be finite and increasing")
        return value


class MeasurementLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: Literal[True]
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Location requires explicit boolean consent")
        return value


class MeasurementProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contract_version: Literal[1]
    session_id: uuid.UUID
    device_id: str = Field(min_length=1, max_length=120)
    sensor_model: str = Field(min_length=1, max_length=120)
    protocol_version: str = Field(min_length=1, max_length=80)
    profile_id: str = Field(min_length=1, max_length=120)
    acquired_at: datetime
    point_id: str | None = Field(default=None, min_length=1, max_length=120)
    depth_cm: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    soil_type: str | None = Field(default=None, min_length=1, max_length=120)
    location: MeasurementLocation | None = None
    frame_hex: str | None = Field(default=None, max_length=512, pattern=r"^(?:[0-9a-fA-F]{2})*$")
    variables: dict[str, MeasuredVariable] = Field(min_length=1, max_length=7)

    @field_validator("contract_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("contract_version must be an integer")
        return value

    @field_validator("acquired_at")
    @classmethod
    def plausible_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquired_at must include a timezone")
        if value.year < 2000 or value > datetime.now(timezone.utc):
            raise ValueError("acquired_at is not a plausible acquisition timestamp")
        return value.astimezone(timezone.utc)

    @field_validator("variables")
    @classmethod
    def known_variables(cls, values):
        for key, variable in values.items():
            if key not in VARIABLES or variable.unit not in UNITS[key] or variable.analyte not in ANALYTES[key]:
                raise ValueError("Unknown variable, unit or incompatible analyte")
        return values


def normalized_raw(key: str, variable: MeasuredVariable) -> float | None:
    """Only dimensional EC conversion is authorized; never chemical conversion."""
    if key in ("nitrogen", "phosphorus", "potassium"):
        if variable.unit != "mg/kg" or variable.analyte != {"nitrogen": "N", "phosphorus": "P", "potassium": "K"}[key]:
            return None
    return variable.raw_value / 1000 if key == "ec" and variable.unit == "uS/cm" else variable.raw_value


class ReadingProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reading_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    window_size: int = Field(default=5, ge=3, le=31)
    method: Literal["none", "mean", "median"] = "median"
    calibration_id: uuid.UUID | None = None

    @field_validator("reading_ids")
    @classmethod
    def distinct_ids(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Repeated measurement IDs in processing request")
        return values

    @field_validator("window_size")
    @classmethod
    def odd_window(cls, value):
        if value % 2 == 0:
            raise ValueError("A centered window must be odd")
        return value
