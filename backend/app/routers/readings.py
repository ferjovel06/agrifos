import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.auth import (
    get_current_user,
    has_global_read_access,
    require_write_access,
)
from app.db.session import get_db
from app.models import Parcel, Reading, User
from app.models import SensorCalibration
from app.repositories import parcel as parcel_repo
from app.repositories import reading as reading_repo
from app.repositories.agronomic_reference import (
    AgronomicReferenceNotFoundError,
    get_active_engine_config,
)
from app.schemas.reading import ReadingCreate, ReadingCreateResponse, ReadingRead
from app.schemas.measurement import ReadingProcessRequest
from app.services.diagnostic_service import (
    diagnose_sensor_reading,
)
from app.services.agronomic_config import IncompleteAgronomicConfigError

router = APIRouter(prefix="/readings", tags=["readings"])


async def _get_authorized_parcel(
    db: AsyncSession, parcel_id: uuid.UUID, user: User
) -> Parcel:
    """Verify that the parcel exists and that the user has access to it."""
    parcel = await parcel_repo.get_parcel(db, parcel_id)
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parcel not found."
        )
    if not has_global_read_access(user) and parcel.farm.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions."
        )
    return parcel


@router.post(
    "",
    response_model=ReadingCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reading(
    payload: ReadingCreate,
    current_user: User = Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
):
    """Receives and stores a sensor reading (NPK, EC, pH, temperature, humidity)."""
    if payload.measurement is not None:
        await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    parcel = await _get_authorized_parcel(db, payload.parcel_id, current_user)
    config = None
    if payload.measurement is None:
        try:
            config = await get_active_engine_config(db, parcel.crop_id)
        except (AgronomicReferenceNotFoundError, IncompleteAgronomicConfigError) as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    if payload.measurement_id is not None:
        existing = await reading_repo.get_reading(db, payload.measurement_id)
        if existing is not None:
            await _get_authorized_parcel(db, existing.parcel_id, current_user)
            if existing.parcel_id != payload.parcel_id or existing.measurement != payload.measurement.model_dump(mode="json"):
                raise HTTPException(409, "Measurement ID already has different immutable evidence.")
            return ReadingCreateResponse(**ReadingRead.model_validate(existing).model_dump(),
                                         warnings=["UNCALIBRATED_LABORATORY_CONFIRMATION_REQUIRED"])
    reading = Reading(**payload.orm_values())
    reading = await reading_repo.create_reading(db, reading)
    return ReadingCreateResponse(
        **ReadingRead.model_validate(reading).model_dump(),
        diagnosis=diagnose_sensor_reading(reading, parcel.crop.name, config) if config is not None else None,
        warnings=["UNCALIBRATED_LABORATORY_CONFIRMATION_REQUIRED"] if payload.measurement is not None else [],
    )


@router.post("/process", response_model=list[dict])
async def process_readings(payload: ReadingProcessRequest,
                           current_user: User = Depends(require_write_access), db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    readings = []
    for reading_id in payload.reading_ids:
        reading = await reading_repo.get_reading(db, reading_id)
        if reading is None:
            raise HTTPException(404, "Reading not found.")
        parcel = await _get_authorized_parcel(db, reading.parcel_id, current_user)
        if parcel.farm.user_id != current_user.id:
            raise HTTPException(403, "Processing is restricted to the measurement owner.")
        if reading.measurement is None:
            raise HTTPException(422, "Processing requires versioned physical provenance.")
        readings.append(reading)
    calibration = None
    if payload.calibration_id is not None:
        calibration = await db.get(SensorCalibration, payload.calibration_id)
        if calibration is None or calibration.user_id != current_user.id:
            raise HTTPException(404, "Calibration not found.")
        if calibration.state != "validated" or calibration.validation is None:
            raise HTTPException(422, "A validated calibration version is required.")
        from app.repositories.calibration import load_pairs
        try:
            await load_pairs(db, [uuid.UUID(x) for x in calibration.pair_ids], current_user.id, calibration.profile["predictor_names"])
        except ValueError as error:
            raise HTTPException(422, {"code": "calibration_source_not_owned"}) from error
    return await reading_repo.store_results(db, readings, window_size=payload.window_size, method=payload.method,
                                           calibration=calibration)


@router.get("/{reading_id}/results", response_model=list[dict])
async def get_results(reading_id: uuid.UUID, current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    reading = await reading_repo.get_reading(db, reading_id)
    if reading is None:
        raise HTTPException(404, "Reading not found.")
    await _get_authorized_parcel(db, reading.parcel_id, current_user)
    return await reading_repo.list_results(db, reading_id)


@router.get("", response_model=list[ReadingRead])
async def list_readings(
    parcel_id: uuid.UUID = Query(..., description="Parcel to query"),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_authorized_parcel(db, parcel_id, current_user)
    return await reading_repo.list_readings_by_parcel(db, parcel_id, skip, limit)


@router.get("/{reading_id}", response_model=ReadingRead)
async def get_reading(
    reading_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reading = await reading_repo.get_reading(db, reading_id)
    if not reading:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reading not found."
        )
    await _get_authorized_parcel(db, reading.parcel_id, current_user)
    return reading
