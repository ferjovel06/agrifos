import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SyncOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: uuid.UUID
    entity_id: uuid.UUID
    farm_id: uuid.UUID
    entity: Literal["readings", "lab_analyses"]
    operation: Literal["create", "update"]
    payload_version: Literal[1]
    expected_revision: int | None = Field(default=None, ge=1)
    payload: dict
