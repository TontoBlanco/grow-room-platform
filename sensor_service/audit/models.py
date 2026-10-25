"""Domain models for the seed-to-sale audit log.

Plant and Batch are mutable *current-state* projections. The append-only
TransitionEvent stream is the source of truth for compliance evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PlantState(StrEnum):
    """Lifecycle stages roughly aligned with seed-to-sale tracking systems.

    Educational / portfolio model — not a METRC API client and not legal advice.
    """

    SEEDLING = "seedling"
    VEGETATIVE = "vegetative"
    FLOWERING = "flowering"
    HARVESTED = "harvested"
    PACKAGED = "packaged"
    DESTROYED = "destroyed"


class BatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    strain: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=1024)


class Batch(BaseModel):
    id: str
    name: str
    strain: str | None = None
    notes: str | None = None
    created_at: str


class PlantCreate(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)
    tag: str | None = Field(
        default=None,
        max_length=64,
        description="Optional human tag (e.g. tent position). Auto-generated if omitted.",
    )
    notes: str | None = Field(default=None, max_length=1024)


class Plant(BaseModel):
    id: str
    batch_id: str
    tag: str
    state: PlantState
    notes: str | None = None
    created_at: str
    updated_at: str


class TransitionRequest(BaseModel):
    to_state: PlantState
    reason: str | None = Field(default=None, max_length=512)
    actor: str = Field(
        default="operator",
        max_length=64,
        description="Who initiated the change (user id, system, CI job name).",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransitionEvent(BaseModel):
    """Immutable audit row. Never updated or deleted after insert."""

    id: str
    plant_id: str
    batch_id: str
    from_state: PlantState
    to_state: PlantState
    reason: str | None = None
    actor: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    prev_hash: str
    event_hash: str
    sequence: int


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
