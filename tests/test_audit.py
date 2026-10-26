"""Offline tests for the Week 5 seed-to-sale audit module."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sensor_service.audit.api import create_audit_router
from sensor_service.audit.models import BatchCreate, PlantCreate, PlantState, TransitionRequest
from sensor_service.audit.states import can_transition
from sensor_service.audit.store import (
    AuditError,
    AuditStore,
    ConflictError,
    ImmutableViolation,
    resolve_audit_target,
)


@pytest.fixture
def store(tmp_path):
    return AuditStore(db_path=str(tmp_path / "audit.db"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "audit-api.db")
    monkeypatch.setenv("AUDIT_DB_PATH", db)
    app = FastAPI()
    app.include_router(create_audit_router(AuditStore(db_path=db)))
    return TestClient(app)


def test_allowed_happy_path_transitions():
    assert can_transition(PlantState.SEEDLING, PlantState.VEGETATIVE)
    assert can_transition(PlantState.VEGETATIVE, PlantState.FLOWERING)
    assert can_transition(PlantState.FLOWERING, PlantState.HARVESTED)
    assert can_transition(PlantState.HARVESTED, PlantState.PACKAGED)
    assert can_transition(PlantState.PACKAGED, PlantState.DESTROYED)


def test_illegal_skips_and_self_transition():
    assert not can_transition(PlantState.SEEDLING, PlantState.FLOWERING)
    assert not can_transition(PlantState.SEEDLING, PlantState.SEEDLING)
    assert not can_transition(PlantState.DESTROYED, PlantState.VEGETATIVE)


def test_create_batch_and_plant(store: AuditStore):
    batch = store.create_batch(BatchCreate(name="tent-a-week5", strain="demo"))
    plant, birth = store.create_plant(PlantCreate(batch_id=batch.id, tag="A1"))
    assert plant.state == PlantState.SEEDLING
    assert birth.to_state == PlantState.SEEDLING
    assert birth.sequence == 1
    hist = store.history(plant.id)
    assert len(hist) == 1


def test_full_lifecycle_and_hash_chain(store: AuditStore):
    batch = store.create_batch(BatchCreate(name="lifecycle"))
    plant, _ = store.create_plant(PlantCreate(batch_id=batch.id))
    path = [
        PlantState.VEGETATIVE,
        PlantState.FLOWERING,
        PlantState.HARVESTED,
        PlantState.PACKAGED,
    ]
    for state in path:
        store.transition(
            plant.id,
            TransitionRequest(to_state=state, actor="cole", reason="lab demo"),
        )
    plant = store.get_plant(plant.id)
    assert plant.state == PlantState.PACKAGED
    empty = store.create_batch(BatchCreate(name="empty-lot"))
    assert [item.id for item in store.list_batches()] == [batch.id, empty.id]
    assert [item.id for item in store.list_plants(batch_id=batch.id)] == [plant.id]
    assert store.list_plants(batch_id=empty.id) == []
    assert [item.id for item in store.list_plants()] == [plant.id]
    hist = store.history(plant.id)
    assert [e.to_state for e in hist] == [
        PlantState.SEEDLING,
        *path,
    ]
    result = store.verify_chain()
    assert result["ok"] is True
    assert result["checked"] == len(hist)


def test_illegal_transition_raises(store: AuditStore):
    batch = store.create_batch(BatchCreate(name="bad"))
    plant, _ = store.create_plant(PlantCreate(batch_id=batch.id))
    with pytest.raises(ConflictError):
        store.transition(
            plant.id,
            TransitionRequest(to_state=PlantState.HARVESTED),
        )
    assert len(store.history(plant.id)) == 1
    assert store.get_plant(plant.id).state == PlantState.SEEDLING


def test_events_are_append_only(store: AuditStore):
    with pytest.raises(ImmutableViolation):
        store.update_event("evt_x")
    with pytest.raises(ImmutableViolation):
        store.delete_event("evt_x")


def test_tamper_breaks_verify(store: AuditStore):
    batch = store.create_batch(BatchCreate(name="tamper"))
    plant, _ = store.create_plant(PlantCreate(batch_id=batch.id))
    store.transition(plant.id, TransitionRequest(to_state=PlantState.VEGETATIVE))
    # Direct SQL mutation — what an attacker with DB write would do.
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE events SET to_state = ? WHERE plant_id = ? AND to_state = ?",
            ("flowering", plant.id, "vegetative"),
        )
    result = store.verify_chain()
    assert result["ok"] is False
    assert "mismatch" in result["detail"]


def test_api_create_transition_history(client: TestClient):
    batch = client.post("/audit/batches", json={"name": "api-batch", "strain": "x"}).json()
    plant = client.post(
        "/audit/plants",
        json={"batch_id": batch["id"], "tag": "B2"},
    ).json()
    assert plant["state"] == "seedling"

    bad = client.post(
        f"/audit/plants/{plant['id']}/transitions",
        json={"to_state": "packaged"},
    )
    assert bad.status_code == 409

    ok = client.post(
        f"/audit/plants/{plant['id']}/transitions",
        json={"to_state": "vegetative", "actor": "cole", "reason": "transplant"},
    )
    assert ok.status_code == 201
    assert ok.json()["to_state"] == "vegetative"
    assert ok.json()["prev_hash"]
    assert ok.json()["event_hash"]

    hist = client.get(f"/audit/plants/{plant['id']}/history").json()
    assert len(hist) == 2

    integrity = client.get("/audit/integrity").json()
    assert integrity["ok"] is True


def test_api_rejects_event_mutation(client: TestClient):
    for method in ("put", "patch", "delete"):
        resp = getattr(client, method)("/audit/events/evt_fake")
        assert resp.status_code == 405


def test_api_unknown_plant_404(client: TestClient):
    resp = client.get("/audit/plants/plant_does_not_exist")
    assert resp.status_code == 404


def test_sqlite_schema_links_events_to_plants_and_batches(store: AuditStore):
    assert store.db_path is not None
    with sqlite3.connect(store.db_path) as conn:
        referenced = {row[2] for row in conn.execute("PRAGMA foreign_key_list(events)")}
        event_indexes = {row[1] for row in conn.execute("PRAGMA index_list(events)")}
        plant_indexes = {row[1] for row in conn.execute("PRAGMA index_list(plants)")}
    assert referenced == {"plants", "batches"}
    assert "idx_events_plant_sequence" in event_indexes
    assert "idx_events_batch_sequence" in event_indexes
    assert "idx_plants_batch_state" in plant_indexes


def test_store_rejects_two_locations(tmp_path):
    with pytest.raises(AuditError, match="not both"):
        AuditStore(db_path=str(tmp_path / "audit.db"), database_url="postgresql://localhost/audit")


def test_explicit_sqlite_path_ignores_postgres_url(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DATABASE_URL", "postgresql://audit@localhost/audit")
    monkeypatch.setenv("DATABASE_URL", "postgresql://other@localhost/other")
    opened = AuditStore(db_path=str(tmp_path / "audit.db"))
    assert opened.backend == "sqlite"
    assert opened.database_url is None
    batch = opened.create_batch(BatchCreate(name="still-sqlite"))
    assert opened.get_batch(batch.id).name == "still-sqlite"


def test_router_uses_sqlite_when_no_database_url(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "from-env.db"))
    app = FastAPI()
    app.include_router(create_audit_router())
    local = TestClient(app)
    resp = local.post("/audit/batches", json={"name": "env-batch"})
    assert resp.status_code == 201
    assert (tmp_path / "from-env.db").exists()


def test_resolve_audit_target_precedence(monkeypatch):
    monkeypatch.delenv("AUDIT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
    assert resolve_audit_target().backend == "sqlite"
    assert resolve_audit_target().db_path == "./data/audit.db"

    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/not-ours.db")
    monkeypatch.setenv("AUDIT_DB_PATH", "./data/custom-audit.db")
    target = resolve_audit_target()
    assert target.backend == "sqlite"
    assert target.db_path == "./data/custom-audit.db"

    monkeypatch.setenv("DATABASE_URL", "postgresql://audit@localhost/from-generic")
    target = resolve_audit_target()
    assert target.backend == "postgres"
    assert target.database_url == "postgresql://audit@localhost/from-generic"

    monkeypatch.setenv("AUDIT_DATABASE_URL", "postgres://audit@localhost/specific")
    target = resolve_audit_target()
    assert target.backend == "postgres"
    assert target.database_url == "postgres://audit@localhost/specific"

    monkeypatch.setenv("AUDIT_DATABASE_URL", "   ")
    target = resolve_audit_target()
    assert target.backend == "postgres"
    assert target.database_url == "postgresql://audit@localhost/from-generic"


def test_resolve_rejects_non_postgres_audit_url():
    with pytest.raises(AuditError, match="AUDIT_DATABASE_URL"):
        resolve_audit_target({"AUDIT_DATABASE_URL": "mysql://localhost/audit"})
