"""Derive calibration inputs from stored sensor originals and laboratory evidence."""
import uuid
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CalibrationPairRecord, Farm, Parcel, Reading
from app.schemas.measurement import MeasurementProvenance
from app.services.sensor_calibration import CalibrationError, CalibrationPair


def physical_context_key(reading: Reading) -> str | None:
    if reading.measurement is None:
        return None
    provenance = MeasurementProvenance.model_validate(reading.measurement)
    if provenance.point_id is None:
        return None
    context = (str(reading.parcel_id), str(provenance.session_id), provenance.point_id,
               provenance.device_id, provenance.depth_cm)
    return hashlib.sha256(json.dumps(context, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


async def owned_reading(db: AsyncSession, reading_id: uuid.UUID, user_id: uuid.UUID) -> Reading | None:
    return (await db.execute(select(Reading).join(Parcel, Reading.parcel_id == Parcel.id)
        .join(Farm, Parcel.farm_id == Farm.id).where(Reading.id == reading_id, Farm.user_id == user_id))).scalar_one_or_none()


def pair_from_evidence(record: CalibrationPairRecord, reading: Reading, predictor_names=()) -> CalibrationPair:
    if reading.measurement is None:
        raise CalibrationError("VERSIONED_PROVENANCE_REQUIRED")
    provenance = MeasurementProvenance.model_validate(reading.measurement)
    variable = provenance.variables.get(record.variable)
    lab = record.laboratory
    if variable is None or variable.read_status != "valid" or variable.analyte == "unidentified":
        raise CalibrationError("INVALID_CALIBRATION_MEASUREMENT")
    if variable.declared_range is not None and not variable.declared_range[0] <= variable.raw_value <= variable.declared_range[1]:
        raise CalibrationError("MEASUREMENT_OUTSIDE_DECLARED_RANGE")
    if lab["analyte"] != variable.analyte or lab["unit"] != variable.unit:
        raise CalibrationError("INCOMPATIBLE_ANALYTE_OR_UNIT")
    if provenance.depth_cm is None or not lab["depth_start_cm"] <= provenance.depth_cm <= lab["depth_end_cm"]:
        raise CalibrationError("SAMPLE_DEPTH_NOT_COMPARABLE")
    if lab.get("soil_type") is not None and lab["soil_type"] != provenance.soil_type:
        raise CalibrationError("SAMPLE_SOIL_TYPE_NOT_COMPARABLE")
    predictors, units = [], []
    for key in predictor_names:
        predictor = provenance.variables.get(key)
        if predictor is None or predictor.read_status != "valid":
            raise CalibrationError("MISSING_OR_INVALID_PREDICTOR")
        if predictor.declared_range is not None and not predictor.declared_range[0] <= predictor.raw_value <= predictor.declared_range[1]:
            raise CalibrationError("PREDICTOR_OUTSIDE_DECLARED_RANGE")
        predictors.append((key, predictor.raw_value))
        units.append((key, predictor.unit))
    return CalibrationPair(sample_group_id=record.sample_id, analyte=variable.analyte,
        sensor_value=variable.raw_value, reference_value=lab["reference_value"], unit=variable.unit,
        reference_method=lab["method"], reference_basis=lab["report_basis"],
        comparability_evidence=lab["comparability_evidence"], predictors=tuple(predictors), predictor_units=tuple(units),
        device_id=provenance.device_id, parcel_id=str(reading.parcel_id), soil_type=provenance.soil_type,
        sensor_model=provenance.sensor_model, protocol_version=provenance.protocol_version,
        acquisition_profile_id=provenance.profile_id, depth_cm=provenance.depth_cm,
        synthetic=lab.get("synthetic", False))


async def load_pairs(db: AsyncSession, pair_ids: list[uuid.UUID], user_id: uuid.UUID,
                     predictor_names=()) -> list[CalibrationPair]:
    rows = list((await db.execute(select(CalibrationPairRecord, Reading)
        .join(Reading, CalibrationPairRecord.reading_id == Reading.id)
        .join(Parcel, Reading.parcel_id == Parcel.id).join(Farm, Parcel.farm_id == Farm.id)
        .where(CalibrationPairRecord.id.in_(pair_ids), CalibrationPairRecord.user_id == user_id,
               Farm.user_id == user_id))).all())
    if len(rows) != len(pair_ids):
        raise CalibrationError("CALIBRATION_SOURCE_NOT_OWNED")
    return [pair_from_evidence(record, reading, predictor_names) for record, reading in rows]
