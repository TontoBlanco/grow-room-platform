"""Postgres audit backend.

Skipped unless AUDIT_TEST_DATABASE_URL is set. CI sets that to a throwaway
service database. The tests create and drop schema ``audit_test`` only — they
do not truncate tables in ``public``.
"""

from __future__ import annotations

import os
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sensor_service.audit.api import create_audit_router
from sensor_service.audit.models import BatchCreate, PlantCreate, PlantState, TransitionRequest
from sensor_service.audit.store import AuditStore, ConflictError

pytestmark = pytest.mark.postgres


def _test_database_url() -> str:
    return os.environ.get("AUDIT_TEST_DATABASE_URL", "").strip()


def _schema_url(url: str) -> str:
    """Point libpq at the scratch schema without changing public."""
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}options=-csearch_path%3Daudit_test"


@pytest.fixture
def pg_store():
    url = _test_database_url()
    if not url:
        pytest.skip("set AUDIT_TEST_DATABASE_URL to run the Postgres audit tests")
    psycopg = pytest.importorskip("psycopg")
    admin = psycopg.connect(url)
    try:
        admin.execute("DROP SCHEMA IF EXISTS audit_test CASCADE")
        admin.execute("CREATE SCHEMA audit_test")
        admin.commit()
    finally:
        admin.close()
    store = AuditStore(database_url=_schema_url(url))
    yield store
    cleanup = psycopg.connect(url)
    try:
        cleanup.execute("DROP SCHEMA IF EXISTS audit_test CASCADE")
        cleanup.commit()
    finally:
        cleanup.close()


@pytest.fixture
def pg_client(pg_store: AuditStore):
    app = FastAPI()
    app.include_router(create_audit_router(pg_store))
    return TestClient(app)


def test_lifecycle_hash_chain_and_metadata(pg_store: AuditStore):
    assert pg_store.backend == "postgres"
    assert pg_store.db_path is None
    batch = pg_store.create_batch(BatchCreate(name="pg-lifecycle", strain="demo"))
    plant, birth = pg_store.create_plant(PlantCreate(batch_id=batch.id, tag="A1"))
    assert birth.sequence == 1
    assert birth.prev_hash == "0" * 64
    path = [
        PlantState.VEGETATIVE,
        PlantState.FLOWERING,
        PlantState.HARVESTED,
        PlantState.PACKAGED,
    ]
    for state in path:
        pg_store.transition(
            plant.id,
            TransitionRequest(
                to_state=state,
                actor="cole",
                reason="lab demo",
                metadata={"room": "tent-a", "pass": 1},
            ),
        )
    assert pg_store.get_plant(plant.id).state == PlantState.PACKAGED
    empty = pg_store.create_batch(BatchCreate(name="empty-lot"))
    assert [item.id for item in pg_store.list_batches()] == [batch.id, empty.id]
    assert [item.id for item in pg_store.list_plants(batch_id=batch.id)] == [plant.id]
    assert pg_store.list_plants(batch_id=empty.id) == []
    hist = pg_store.history(plant.id)
    assert [event.to_state for event in hist] == [PlantState.SEEDLING, *path]
    assert hist[-1].metadata == {"room": "tent-a", "pass": 1}
    result = pg_store.verify_chain()
    assert result == {"ok": True, "checked": len(hist)}
    scoped = pg_store.verify_chain(plant_id=plant.id)
    assert scoped == {"ok": True, "checked": len(hist)}


def test_illegal_transition_does_not_append(pg_store: AuditStore):
    batch = pg_store.create_batch(BatchCreate(name="pg-bad"))
    plant, _ = pg_store.create_plant(PlantCreate(batch_id=batch.id))
    with pytest.raises(ConflictError):
        pg_store.transition(plant.id, TransitionRequest(to_state=PlantState.HARVESTED))
    assert pg_store.get_plant(plant.id).state == PlantState.SEEDLING
    assert len(pg_store.history(plant.id)) == 1
    assert pg_store.verify_chain()["ok"] is True


def test_missing_batch_is_not_found(pg_store: AuditStore):
    from sensor_service.audit.store import NotFoundError

    with pytest.raises(NotFoundError):
        pg_store.create_plant(PlantCreate(batch_id="batch_missing"))


def test_direct_update_breaks_integrity(pg_store: AuditStore):
    psycopg = pytest.importorskip("psycopg")
    batch = pg_store.create_batch(BatchCreate(name="pg-tamper"))
    plant, _ = pg_store.create_plant(PlantCreate(batch_id=batch.id))
    pg_store.transition(plant.id, TransitionRequest(to_state=PlantState.VEGETATIVE))
    conn = psycopg.connect(pg_store.database_url)
    try:
        conn.execute(
            """
            UPDATE events
               SET to_state = %s
             WHERE plant_id = %s AND to_state = %s
            """,
            ("flowering", plant.id, "vegetative"),
        )
        conn.commit()
    finally:
        conn.close()
    result = pg_store.verify_chain()
    assert result["ok"] is False
    assert "mismatch" in result["detail"]


def test_schema_foreign_keys_indexes_and_jsonb(pg_store: AuditStore):
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(pg_store.database_url)
    try:
        fks = conn.execute(
            """
            SELECT kcu.table_name, kcu.column_name, ccu.table_name AS referenced
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.table_schema = current_schema()
              AND tc.constraint_type = 'FOREIGN KEY'
            """
        ).fetchall()
        indexes = conn.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = current_schema()
            """
        ).fetchall()
        metadata = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'events'
              AND column_name = 'metadata_json'
            """
        ).fetchone()
    finally:
        conn.close()

    links = {(row[0], row[1], row[2]) for row in fks}
    assert ("events", "plant_id", "plants") in links
    assert ("events", "batch_id", "batches") in links
    assert ("plants", "batch_id", "batches") in links
    names = {row[0] for row in indexes}
    assert {
        "idx_events_plant_sequence",
        "idx_events_batch_sequence",
        "idx_plants_batch_state",
    } <= names
    assert metadata is not None
    assert metadata[0] == "jsonb"


def test_concurrent_appends_keep_one_chain(pg_store: AuditStore):
    batch = pg_store.create_batch(BatchCreate(name="pg-parallel"))
    plants = []
    for index in range(6):
        plant, _birth = pg_store.create_plant(PlantCreate(batch_id=batch.id, tag=f"p{index}"))
        plants.append(plant)
    errors: list[BaseException] = []

    def advance(plant_id: str) -> None:
        try:
            pg_store.transition(
                plant_id,
                TransitionRequest(to_state=PlantState.VEGETATIVE, actor="worker"),
            )
        except Exception as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=advance, args=(plant.id,)) for plant in plants]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert pg_store.verify_chain() == {"ok": True, "checked": 12}
    sequences = []
    for plant in plants:
        sequences.extend(event.sequence for event in pg_store.history(plant.id))
    assert sorted(sequences) == list(range(1, 13))


def test_from_env_uses_audit_database_url(pg_store: AuditStore, monkeypatch):
    assert pg_store.database_url is not None
    monkeypatch.setenv("AUDIT_DATABASE_URL", pg_store.database_url)
    monkeypatch.setenv("DATABASE_URL", "postgresql://other@localhost/other")
    opened = AuditStore.from_env()
    assert opened.backend == "postgres"
    batch = opened.create_batch(BatchCreate(name="from-env"))
    assert pg_store.get_batch(batch.id).name == "from-env"


def test_api_transition_conflict_and_immutability(pg_client: TestClient):
    batch = pg_client.post("/audit/batches", json={"name": "pg-api", "strain": "x"}).json()
    plant = pg_client.post(
        "/audit/plants",
        json={"batch_id": batch["id"], "tag": "B2"},
    ).json()
    assert plant["state"] == "seedling"

    bad = pg_client.post(
        f"/audit/plants/{plant['id']}/transitions",
        json={"to_state": "packaged"},
    )
    assert bad.status_code == 409

    ok = pg_client.post(
        f"/audit/plants/{plant['id']}/transitions",
        json={"to_state": "vegetative", "actor": "cole", "reason": "transplant"},
    )
    assert ok.status_code == 201
    body = ok.json()
    assert body["to_state"] == "vegetative"
    assert body["prev_hash"]
    assert body["event_hash"]

    hist = pg_client.get(f"/audit/plants/{plant['id']}/history").json()
    assert len(hist) == 2
    integrity = pg_client.get("/audit/integrity").json()
    assert integrity == {"ok": True, "checked": 2}

    for method in ("put", "patch", "delete"):
        resp = getattr(pg_client, method)("/audit/events/evt_fake")
        assert resp.status_code == 405

    missing = pg_client.get("/audit/plants/plant_does_not_exist")
    assert missing.status_code == 404
