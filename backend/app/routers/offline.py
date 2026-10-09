"""Owner-scoped incremental downloads and atomic, idempotent soil operations."""
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_write_access
from app.db.session import get_db
from app.models import Farm, LabAnalysis, Parcel, Reading, User
from app.models.offline import SyncChange, SyncCursor, SyncReceipt
from app.schemas.lab_analysis import LabAnalysisCreate, LabAnalysisRead
from app.schemas.offline import SyncOperation
from app.schemas.reading import ReadingCreate, ReadingRead

router = APIRouter(prefix="/sync", tags=["offline synchronization"])


def advisory_key(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)


@router.post("/operations")
async def apply_operation(
    payload: SyncOperation,
    current_user: User = Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
):
    # Lock and receipt are in the SAME transaction as the mutation. Concurrent
    # retries wait until the committed response can be replayed.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                     {"key": advisory_key(f"operation:{current_user.id}:{payload.operation_id}")})
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    try:
        request_hash = hashlib.sha256(json.dumps(payload.model_dump(mode="json"),
                                                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except ValueError as error:
        raise HTTPException(422, "Soil values must be finite.") from error
    receipt = await db.get(SyncReceipt, (current_user.id, payload.operation_id))
    farm = await db.get(Farm, payload.farm_id)
    if farm is None or farm.user_id != current_user.id:
        raise HTTPException(403, "This farm is not available to this account.")
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise HTTPException(409, {"code": "operation_reused", "message": "Operation payload changed."})
        return receipt.response
    model, schema, read_schema = (Reading, ReadingCreate, ReadingRead) if payload.entity == "readings" else (LabAnalysis, LabAnalysisCreate, LabAnalysisRead)
    if payload.operation == "update" and model is Reading:
        raise HTTPException(422, "Sensor readings are immutable in offline synchronization.")
    if set(payload.payload) - set(schema.model_fields):
        raise HTTPException(422, "Unknown fields in operation payload.")
    try:
        values = schema.model_validate(payload.payload)
    except ValidationError as error:
        raise HTTPException(422, "Invalid soil operation payload.") from error
    parcel = await db.get(Parcel, values.parcel_id)
    if parcel is None or parcel.farm_id != farm.id:
        raise HTTPException(403, "This parcel is not available in the selected farm.")
    record = (await db.execute(select(model).where(model.id == payload.entity_id).with_for_update())).scalar_one_or_none()
    if payload.operation == "create":
        if record is not None or payload.expected_revision is not None:
            raise HTTPException(409, {"code": "entity_exists"})
        try:
            record_values = values.orm_values(entity_id=payload.entity_id) if model is Reading else {"id": payload.entity_id, **values.model_dump(exclude_none=True)}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        record = model(**record_values)
        db.add(record)
    else:
        if record is None:
            raise HTTPException(409, {"code": "remote_deleted", "remote": None})
        if record.parcel_id != parcel.id:
            raise HTTPException(403, "Cannot move soil records between parcels.")
        if payload.expected_revision != record.revision:
            raise HTTPException(409, {"code": "revision_conflict", "remote": read_schema.model_validate(record).model_dump(mode="json")})
        for key, value in values.model_dump().items():
            setattr(record, key, value)
    try:
        await db.flush()
        await db.refresh(record)
        response = {"operation_id": str(payload.operation_id), "entity": payload.entity,
                    "data": read_schema.model_validate(record).model_dump(mode="json")}
        db.add(SyncReceipt(user_id=current_user.id, operation_id=payload.operation_id,
                           request_hash=request_hash, response=response))
        await db.commit()
        return response
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, {"code": "sample_code_conflict", "message": "Sample code or entity already exists."}) from error


@router.get("/changes")
async def changes(
    cursor: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(UTC)
    await db.execute(text("SELECT pg_advisory_xact_lock(73190641012001)"))
    after, until = 0, None
    if cursor is not None:
        checkpoint = await db.get(SyncCursor, cursor)
        if checkpoint is None or checkpoint.user_id != current_user.id:
            raise HTTPException(400, "Invalid synchronization cursor.")
        if checkpoint.expires_at <= now:
            raise HTTPException(410, "Synchronization cursor expired; prepare a new snapshot.")
        after, until = checkpoint.after_sequence, checkpoint.until_sequence
    if until is None:
        until = (await db.execute(select(func.max(SyncChange.sequence)))).scalar() or 0
    rows = list((await db.execute(select(SyncChange).where(
        SyncChange.user_id == current_user.id, SyncChange.sequence > after,
        SyncChange.sequence <= until,
    ).order_by(SyncChange.sequence).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    accessible_farms = set((await db.execute(select(Farm.id).where(
        Farm.id.in_({row.farm_id for row in rows}), Farm.user_id == current_user.id,
    ))).scalars())
    # Random persisted cursors carry scope and page boundary on the server,
    # rather than trusting a client-supplied sequence or account ID.
    checkpoint = SyncCursor(user_id=current_user.id,
                            after_sequence=rows[-1].sequence if more else until,
                            until_sequence=until if more else None,
                            expires_at=now + timedelta(days=30))
    db.add(checkpoint)
    await db.flush()
    result = {"changes": [{"sequence": row.sequence, "farm_id": str(row.farm_id),
                           "entity": row.entity, "entity_id": str(row.entity_id),
                           "operation": row.operation if row.farm_id in accessible_farms else "delete",
                           "data": row.data if row.farm_id in accessible_farms else {}} for row in rows],
              "cursor": str(checkpoint.id), "has_more": more}
    await db.commit()
    return result
