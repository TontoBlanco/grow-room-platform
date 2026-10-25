"""FastAPI router for the seed-to-sale audit log.

Mount with:

    from sensor_service.audit import create_audit_router
    app.include_router(create_audit_router())

See docs/WEEK5_AUDIT_LOG_GUIDE.md and docs/main_patch.md.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from sensor_service.audit.models import (
    Batch,
    BatchCreate,
    Plant,
    PlantCreate,
    TransitionEvent,
    TransitionRequest,
)
from sensor_service.audit.store import AuditStore, ConflictError, NotFoundError


def create_audit_router(store: AuditStore | None = None) -> APIRouter:
    db_path = os.environ.get("AUDIT_DB_PATH")
    audit = store or AuditStore(db_path=db_path)
    router = APIRouter(prefix="/audit", tags=["audit"])

    @router.post("/batches", response_model=Batch, status_code=201)
    def create_batch(body: BatchCreate) -> Batch:
        return audit.create_batch(body)

    @router.get("/batches", response_model=list[Batch])
    def list_batches() -> list[Batch]:
        return audit.list_batches()

    @router.get("/batches/{batch_id}", response_model=Batch)
    def get_batch(batch_id: str) -> Batch:
        try:
            return audit.get_batch(batch_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/batches/{batch_id}/plants", response_model=list[Plant])
    def list_batch_plants(batch_id: str) -> list[Plant]:
        try:
            audit.get_batch(batch_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return audit.list_plants(batch_id=batch_id)

    @router.post("/plants", response_model=Plant, status_code=201)
    def create_plant(body: PlantCreate) -> Plant:
        try:
            plant, _event = audit.create_plant(body)
            return plant
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/plants", response_model=list[Plant])
    def list_plants() -> list[Plant]:
        return audit.list_plants()

    @router.get("/plants/{plant_id}", response_model=Plant)
    def get_plant(plant_id: str) -> Plant:
        try:
            return audit.get_plant(plant_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/plants/{plant_id}/transitions",
        response_model=TransitionEvent,
        status_code=201,
    )
    def transition_plant(plant_id: str, body: TransitionRequest) -> TransitionEvent:
        try:
            return audit.transition(plant_id, body)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/plants/{plant_id}/history", response_model=list[TransitionEvent])
    def plant_history(plant_id: str) -> list[TransitionEvent]:
        try:
            return audit.history(plant_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/integrity")
    def integrity(plant_id: str | None = None) -> dict:
        return audit.verify_chain(plant_id=plant_id)

    def _mutate_event_forbidden(event_id: str) -> None:
        raise HTTPException(
            status_code=405,
            detail=f"audit events are append-only; refusing mutation of {event_id}",
        )

    router.add_api_route(
        "/events/{event_id}",
        _mutate_event_forbidden,
        methods=["PUT", "PATCH", "DELETE"],
    )

    return router


