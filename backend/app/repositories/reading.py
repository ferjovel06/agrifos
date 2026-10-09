import uuid
import hashlib
import json
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reading, ReadingResult
from app.schemas.measurement import MeasurementProvenance, VARIABLES
from app.services.measurement_processing import ALGORITHM_VERSION, MeasurementSample, ProcessingConfig, process_measurements


async def create_reading(db: AsyncSession, reading: Reading) -> Reading:
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    return reading


async def get_reading(db: AsyncSession, reading_id: uuid.UUID) -> Reading | None:
    result = await db.execute(select(Reading).where(Reading.id == reading_id))
    return result.scalar_one_or_none()


async def list_readings_by_parcel(
    db: AsyncSession,
    parcel_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> list[Reading]:
    result = await db.execute(
        select(Reading)
        .where(Reading.parcel_id == parcel_id)
        .order_by(Reading.recorded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


def _jsonable(value):
    return json.loads(json.dumps(value, default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item), allow_nan=False))


def process_originals(readings: list[Reading], *, window_size: int = 5, method: str = "median") -> dict[str, dict]:
    """Adapt immutable envelopes to the pure processing API without filling gaps."""
    output = {str(reading.id): {} for reading in readings}
    ordered = sorted(readings, key=lambda r: (r.recorded_at, str(r.id)))
    for variable_key in VARIABLES:
        samples = []
        present_ids = set()
        for reading in ordered:
            provenance = MeasurementProvenance.model_validate(reading.measurement)
            variable = provenance.variables.get(variable_key)
            if variable is not None:
                present_ids.add(str(reading.id))
            samples.append(MeasurementSample(
                measurement_id=str(reading.id), session_id=str(provenance.session_id),
                device_id=provenance.device_id, parcel_id=str(reading.parcel_id), point_id=provenance.point_id,
                analyte=variable.analyte if variable is not None else variable_key,
                value=variable.raw_value if variable is not None else None,
                unit=variable.unit if variable is not None else "",
                acquired_at=provenance.acquired_at, received_at=reading.received_at,
                protocol_version=provenance.protocol_version, reading_status=variable.read_status if variable is not None else "invalid",
                declared_range=variable.declared_range if variable is not None else None,
                device_model=provenance.sensor_model, depth_cm=provenance.depth_cm,
                acquisition_profile_id=provenance.profile_id, soil_type=provenance.soil_type))
        for processed in process_measurements(samples, ProcessingConfig(window=window_size, method=method)):
            if processed.raw.measurement_id in present_ids:
                output[processed.raw.measurement_id][variable_key] = _jsonable(asdict(processed))
    return output


def calibrate_original(provenance: MeasurementProvenance, variables: dict, variable_key: str,
                       profile, *, parcel_id: str, version: int) -> dict:
    """Apply a raw-trained model only to technically eligible original inputs."""
    from app.services.sensor_calibration import CalibrationError, apply_profile
    value = variables[variable_key]
    if value["quality_state"] != "valid" or value["transmission_state"] != "valid" or value["repeatability_state"] == "suspect":
        raise CalibrationError("CALIBRATION_INPUT_SUSPECT")
    predictors, predictor_units = {}, {}
    for name in profile.predictor_names:
        predictor = provenance.variables.get(name)
        processed_predictor = variables.get(name)
        if predictor is None or processed_predictor is None or predictor.read_status != "valid":
            raise CalibrationError("MISSING_OR_INVALID_PREDICTOR")
        if processed_predictor["quality_state"] != "valid" or processed_predictor["transmission_state"] != "valid":
            raise CalibrationError("CALIBRATION_PREDICTOR_SUSPECT")
        if predictor.declared_range is not None and not predictor.declared_range[0] <= predictor.raw_value <= predictor.declared_range[1]:
            raise CalibrationError("PREDICTOR_OUTSIDE_DECLARED_RANGE")
        predictors[name], predictor_units[name] = predictor.raw_value, predictor.unit
    estimate = apply_profile(profile, analyte=value["raw"]["analyte"], unit=value["raw"]["unit"],
        device_id=provenance.device_id, parcel_id=parcel_id, sensor_value=value["raw"]["value"],
        predictors=predictors, predictor_units=predictor_units, soil_type=provenance.soil_type,
        sensor_model=provenance.sensor_model, protocol_version=provenance.protocol_version,
        acquisition_profile_id=provenance.profile_id, depth_cm=provenance.depth_cm, expected_version=version)
    return {**_jsonable(asdict(estimate)), "input_basis": "raw"}


async def store_results(db: AsyncSession, readings: list[Reading], *, window_size: int = 5,
                        method: str = "median", calibration=None) -> list[dict]:
    variables = process_originals(readings, window_size=window_size, method=method)
    context = {"algorithm_version": ALGORITHM_VERSION, "window_size": window_size, "method": method,
               "reading_ids": sorted(str(r.id) for r in readings),
               "calibration_id": str(calibration.id) if calibration is not None else None,
               "calibration_version": calibration.version if calibration is not None else None}
    # Serialize retries at the same boundary already used by offline mutations.
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    result = []
    for reading in readings:
        payload = {**context, "reading_id": str(reading.id), "variables": variables[str(reading.id)],
                   "agronomic_use": "laboratory_confirmation_required"}
        if calibration is not None:
            from app.services.sensor_calibration import profile_from_dict
            profile = profile_from_dict(calibration.validation)
            provenance = MeasurementProvenance.model_validate(reading.measurement)
            for key, value in payload["variables"].items():
                if value["raw"]["analyte"] != profile.analyte:
                    continue
                try:
                    value["calibration"] = calibrate_original(provenance, payload["variables"], key, profile,
                        parcel_id=str(reading.parcel_id), version=calibration.version)
                    value["accuracy_state"] = "calibrated"
                except ValueError as error:
                    value["calibration"] = None
                    value["reason_codes"].append(getattr(error, "code", str(error)))
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        existing = (await db.execute(select(ReadingResult).where(ReadingResult.reading_id == reading.id,
                                      ReadingResult.fingerprint == fingerprint))).scalar_one_or_none()
        if existing is None:
            existing = ReadingResult(reading_id=reading.id, fingerprint=fingerprint,
                algorithm_version=ALGORITHM_VERSION, calibration_id=calibration.id if calibration is not None else None,
                payload=payload)
            db.add(existing)
            await db.flush()
            await db.refresh(existing)
        result.append({**existing.payload, "id": str(existing.id), "created_at": existing.created_at.isoformat()})
    await db.commit()
    return result


async def list_results(db: AsyncSession, reading_id: uuid.UUID) -> list[dict]:
    rows = (await db.execute(select(ReadingResult).where(ReadingResult.reading_id == reading_id)
                            .order_by(ReadingResult.created_at))).scalars()
    return [{**row.payload, "id": str(row.id), "created_at": row.created_at.isoformat()} for row in rows]
