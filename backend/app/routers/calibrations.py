"""Owner-scoped candidate training and controlled independent validation."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_write_access
from app.db.session import get_db
from app.models import CalibrationPairRecord, SensorCalibration, User
from app.repositories import calibration as repo
from app.schemas.calibration import CalibrationPairCreate, CalibrationTrainRequest, CalibrationValidateRequest
from app.services.sensor_calibration import (CalibrationError, CalibrationScope, profile_from_dict,
    profile_to_dict, train_candidate, validate_candidate)

router = APIRouter(prefix="/calibrations", tags=["sensor calibration"])


def _failure(error: ValueError):
    return HTTPException(422, {"code": getattr(error, "code", "invalid_calibration_evidence"), "message": str(error)})


def _read(record: SensorCalibration) -> dict:
    return {"id": str(record.id), "profile_id": record.profile_id, "version": record.version,
            "state": record.state, "profile": record.profile, "validation": record.validation,
            "pair_ids": record.pair_ids, "created_at": record.created_at.isoformat()}


async def _owned_profile(db, profile_id, user):
    record = await db.get(SensorCalibration, profile_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(404, "Calibration not found.")
    try:
        await repo.load_pairs(db, [uuid.UUID(x) for x in record.pair_ids], user.id, record.profile["predictor_names"])
    except ValueError as error:
        raise _failure(error) from error
    return record


@router.post("/pairs", status_code=201)
async def register_pair(payload: CalibrationPairCreate, current_user: User = Depends(require_write_access),
                        db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    reading = await repo.owned_reading(db, payload.reading_id, current_user.id)
    if reading is None:
        raise HTTPException(404, "Owned reading not found.")
    record = CalibrationPairRecord(user_id=current_user.id, reading_id=reading.id,
        sample_id=payload.sample_id, context_key=repo.physical_context_key(reading), variable=payload.variable,
        laboratory=payload.laboratory.model_dump(mode="json"))
    try:
        repo.pair_from_evidence(record, reading)
    except ValueError as error:
        raise _failure(error) from error
    if record.context_key is not None:
        alias = (await db.execute(select(CalibrationPairRecord.id).where(
            CalibrationPairRecord.user_id == current_user.id, CalibrationPairRecord.context_key == record.context_key,
            CalibrationPairRecord.sample_id != payload.sample_id).limit(1))).scalar_one_or_none()
        if alias is not None:
            raise HTTPException(409, "Repeated measurements of this physical context already belong to another sample ID.")
    existing = (await db.execute(select(CalibrationPairRecord).where(
        CalibrationPairRecord.user_id == current_user.id, CalibrationPairRecord.reading_id == reading.id,
        CalibrationPairRecord.variable == payload.variable))).scalar_one_or_none()
    if existing is not None:
        if existing.sample_id != payload.sample_id or existing.laboratory != record.laboratory:
            raise HTTPException(409, "The pair already has different immutable laboratory evidence.")
        return {"id": str(existing.id), **payload.model_dump(mode="json")}
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": str(record.id), **payload.model_dump(mode="json")}


@router.get("/pairs")
async def list_pairs(reading_id: uuid.UUID, current_user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    if await repo.owned_reading(db, reading_id, current_user.id) is None:
        raise HTTPException(404, "Owned reading not found.")
    rows = (await db.execute(select(CalibrationPairRecord).where(CalibrationPairRecord.reading_id == reading_id,
        CalibrationPairRecord.user_id == current_user.id))).scalars()
    return [{"id": str(row.id), "reading_id": str(row.reading_id), "sample_id": row.sample_id,
             "variable": row.variable, "laboratory": row.laboratory} for row in rows]


@router.post("/train", status_code=201)
async def train(payload: CalibrationTrainRequest, current_user: User = Depends(require_write_access),
                db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    try:
        pairs = await repo.load_pairs(db, payload.pair_ids, current_user.id, payload.predictors)
        scope = CalibrationScope(device_ids=tuple(sorted({p.device_id for p in pairs})),
            parcel_ids=tuple(sorted({p.parcel_id for p in pairs})),
            soil_types=tuple(sorted({p.soil_type for p in pairs if p.soil_type is not None})),
            measurement_contexts=tuple(sorted({(p.sensor_model, p.protocol_version, p.acquisition_profile_id) for p in pairs})),
            depth_range=(min(p.depth_cm for p in pairs), max(p.depth_cm for p in pairs)))
        candidate = train_candidate(pairs, profile_id=payload.profile_id, version=payload.version,
            analyte=pairs[0].analyte, unit=pairs[0].unit, predictor_names=tuple(payload.predictors),
            model_kind=payload.model_kind, scope=scope, holdout_group_ids=tuple(payload.holdout_sample_ids),
            training_evidence=payload.training_evidence, trained_at=datetime.now(UTC))
    except ValueError as error:
        raise _failure(error) from error
    existing = (await db.execute(select(SensorCalibration).where(SensorCalibration.user_id == current_user.id,
        SensorCalibration.profile_id == payload.profile_id, SensorCalibration.version == payload.version))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "Calibration versions are immutable; choose a new version.")
    record = SensorCalibration(user_id=current_user.id, profile_id=payload.profile_id, version=payload.version,
        state="candidate", profile=profile_to_dict(candidate), pair_ids=[str(x) for x in payload.pair_ids])
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _read(record)


@router.get("/{calibration_id}")
async def get_profile(calibration_id: uuid.UUID, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    return _read(await _owned_profile(db, calibration_id, current_user))


@router.post("/{calibration_id}/validate")
async def validate(calibration_id: uuid.UUID, payload: CalibrationValidateRequest,
                   current_user: User = Depends(require_write_access), db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    record = await _owned_profile(db, calibration_id, current_user)
    if record.state != "candidate":
        if record.state == "validated":
            return _read(record)
        raise HTTPException(422, "Retired calibrations cannot be promoted.")
    try:
        candidate = profile_from_dict(record.profile)
        pairs = await repo.load_pairs(db, [uuid.UUID(x) for x in record.pair_ids], current_user.id, candidate.predictor_names)
        validated = validate_candidate(candidate, pairs, validation_evidence=payload.validation_evidence)
    except ValueError as error:
        raise _failure(error) from error
    record.validation = profile_to_dict(validated)
    record.state = "validated"
    await db.commit()
    await db.refresh(record)
    return _read(record)


@router.post("/{calibration_id}/retire")
async def retire(calibration_id: uuid.UUID, current_user: User = Depends(require_write_access),
                 db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    record = await _owned_profile(db, calibration_id, current_user)
    record.state = "retired"
    await db.commit()
    return _read(record)
