"""SQLite append-only audit store with optional hash-chain tamper evidence.

Design rules:
- Events are INSERT-only. There are no UPDATE/DELETE helpers for events.
- Plants/Batches tables hold *current projections* for fast reads; the event
  stream remains the compliance source of truth.
- Each event's event_hash covers sequence + plant + states + payload + prev_hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

from sensor_service.audit.models import (
    Batch,
    BatchCreate,
    Plant,
    PlantCreate,
    PlantState,
    TransitionEvent,
    TransitionRequest,
    utc_now_iso,
)
from sensor_service.audit.states import can_transition, describe_allowed

GENESIS_HASH = "0" * 64
DEFAULT_DB_PATH = "./data/audit.db"


class AuditError(Exception):
    """Base error for audit store operations."""


class NotFoundError(AuditError):
    pass


class ConflictError(AuditError):
    pass


class ImmutableViolation(AuditError):
    """Raised if anything tries to mutate past events."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _canonical_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_event(
    *,
    sequence: int,
    plant_id: str,
    batch_id: str,
    from_state: str,
    to_state: str,
    reason: str | None,
    actor: str,
    metadata: dict,
    created_at: str,
    prev_hash: str,
) -> str:
    material = _canonical_payload(
        {
            "sequence": sequence,
            "plant_id": plant_id,
            "batch_id": batch_id,
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "actor": actor,
            "metadata": metadata,
            "created_at": created_at,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.environ.get("AUDIT_DB_PATH", DEFAULT_DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    strain TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plants (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(id),
                    tag TEXT NOT NULL,
                    state TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT NOT NULL REFERENCES plants(id),
                    batch_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    reason TEXT,
                    actor TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    sequence INTEGER NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_events_plant ON events(plant_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_plants_batch ON plants(batch_id);
                """
            )

    # ---- Batches / plants (projections) ---------------------------------

    def create_batch(self, body: BatchCreate) -> Batch:
        batch = Batch(
            id=_new_id("batch"),
            name=body.name,
            strain=body.strain,
            notes=body.notes,
            created_at=utc_now_iso(),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO batches (id, name, strain, notes, created_at) VALUES (?, ?, ?, ?, ?)",
                (batch.id, batch.name, batch.strain, batch.notes, batch.created_at),
            )
        return batch

    def get_batch(self, batch_id: str) -> Batch:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"batch not found: {batch_id}")
        return Batch(**dict(row))

    def list_batches(self) -> list[Batch]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM batches ORDER BY created_at").fetchall()
        return [Batch(**dict(r)) for r in rows]

    def create_plant(self, body: PlantCreate) -> tuple[Plant, TransitionEvent]:
        self.get_batch(body.batch_id)  # ensure batch exists
        now = utc_now_iso()
        plant = Plant(
            id=_new_id("plant"),
            batch_id=body.batch_id,
            tag=body.tag or _new_id("tag"),
            state=PlantState.SEEDLING,
            notes=body.notes,
            created_at=now,
            updated_at=now,
        )
        # Birth event: from_state == to_state == seedling, sequence continues chain.
        event = self._append_event_unlocked(
            plant_id=plant.id,
            batch_id=plant.batch_id,
            from_state=PlantState.SEEDLING,
            to_state=PlantState.SEEDLING,
            reason="plant_created",
            actor="system",
            metadata={"tag": plant.tag},
            created_at=now,
            insert_plant=plant,
        )
        return plant, event

    def get_plant(self, plant_id: str) -> Plant:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"plant not found: {plant_id}")
        data = dict(row)
        data["state"] = PlantState(data["state"])
        return Plant(**data)

    def list_plants(self, batch_id: str | None = None) -> list[Plant]:
        with self._connect() as conn:
            if batch_id:
                rows = conn.execute(
                    "SELECT * FROM plants WHERE batch_id = ? ORDER BY created_at",
                    (batch_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM plants ORDER BY created_at").fetchall()
        out: list[Plant] = []
        for r in rows:
            data = dict(r)
            data["state"] = PlantState(data["state"])
            out.append(Plant(**data))
        return out

    # ---- Transitions / history ------------------------------------------

    def transition(self, plant_id: str, body: TransitionRequest) -> TransitionEvent:
        plant = self.get_plant(plant_id)
        if not can_transition(plant.state, body.to_state):
            allowed = describe_allowed(plant.state)
            raise ConflictError(
                f"illegal transition {plant.state.value!r} → {body.to_state.value!r}; "
                f"allowed from {plant.state.value!r}: {allowed or '(terminal)'}"
            )
        now = utc_now_iso()
        event = self._append_event_unlocked(
            plant_id=plant.id,
            batch_id=plant.batch_id,
            from_state=plant.state,
            to_state=body.to_state,
            reason=body.reason,
            actor=body.actor,
            metadata=body.metadata,
            created_at=now,
            update_plant_state=body.to_state,
        )
        return event

    def history(self, plant_id: str) -> list[TransitionEvent]:
        self.get_plant(plant_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE plant_id = ? ORDER BY sequence",
                (plant_id,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def verify_chain(self, plant_id: str | None = None) -> dict:
        """Recompute the global hash chain (optionally scoped report to one plant).

        Chain continuity is always global (sequence order). When plant_id is set,
        only events for that plant are counted in `checked`, but intervening
        events are still walked so prev_hash links stay valid.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY sequence").fetchall()

        prev = GENESIS_HASH
        checked = 0
        for row in rows:
            meta = json.loads(row["metadata_json"])
            expected = _hash_event(
                sequence=row["sequence"],
                plant_id=row["plant_id"],
                batch_id=row["batch_id"],
                from_state=row["from_state"],
                to_state=row["to_state"],
                reason=row["reason"],
                actor=row["actor"],
                metadata=meta,
                created_at=row["created_at"],
                prev_hash=row["prev_hash"],
            )
            if expected != row["event_hash"]:
                return {
                    "ok": False,
                    "checked": checked,
                    "failed_event_id": row["id"],
                    "detail": "event_hash mismatch",
                }
            if row["prev_hash"] != prev:
                return {
                    "ok": False,
                    "checked": checked,
                    "failed_event_id": row["id"],
                    "detail": f"prev_hash mismatch (expected {prev})",
                }
            if plant_id is None or row["plant_id"] == plant_id:
                checked += 1
            prev = row["event_hash"]
        if plant_id is not None and checked == 0:
            # Distinguish "plant has no events" from "empty db".
            try:
                self.get_plant(plant_id)
            except NotFoundError:
                raise
        return {"ok": True, "checked": checked}

    # Explicitly refuse mutation of past events (no public UPDATE/DELETE).
    def update_event(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise ImmutableViolation("audit events are append-only; UPDATE is forbidden")

    def delete_event(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise ImmutableViolation("audit events are append-only; DELETE is forbidden")

    # ---- internals ------------------------------------------------------

    def _next_sequence_and_prev(self, conn: sqlite3.Connection) -> tuple[int, str]:
        row = conn.execute(
            "SELECT sequence, event_hash FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 1, GENESIS_HASH
        return int(row["sequence"]) + 1, str(row["event_hash"])

    def _append_event_unlocked(
        self,
        *,
        plant_id: str,
        batch_id: str,
        from_state: PlantState,
        to_state: PlantState,
        reason: str | None,
        actor: str,
        metadata: dict,
        created_at: str,
        insert_plant: Plant | None = None,
        update_plant_state: PlantState | None = None,
    ) -> TransitionEvent:
        event_id = _new_id("evt")
        with self._connect() as conn:
            sequence, prev_hash = self._next_sequence_and_prev(conn)
            event_hash = _hash_event(
                sequence=sequence,
                plant_id=plant_id,
                batch_id=batch_id,
                from_state=from_state.value,
                to_state=to_state.value,
                reason=reason,
                actor=actor,
                metadata=metadata,
                created_at=created_at,
                prev_hash=prev_hash,
            )
            if insert_plant is not None:
                conn.execute(
                    """
                    INSERT INTO plants
                      (id, batch_id, tag, state, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        insert_plant.id,
                        insert_plant.batch_id,
                        insert_plant.tag,
                        insert_plant.state.value,
                        insert_plant.notes,
                        insert_plant.created_at,
                        insert_plant.updated_at,
                    ),
                )
            conn.execute(
                """
                INSERT INTO events (
                    id, plant_id, batch_id, from_state, to_state, reason, actor,
                    metadata_json, created_at, prev_hash, event_hash, sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    plant_id,
                    batch_id,
                    from_state.value,
                    to_state.value,
                    reason,
                    actor,
                    json.dumps(metadata, sort_keys=True),
                    created_at,
                    prev_hash,
                    event_hash,
                    sequence,
                ),
            )
            if update_plant_state is not None:
                conn.execute(
                    "UPDATE plants SET state = ?, updated_at = ? WHERE id = ?",
                    (update_plant_state.value, created_at, plant_id),
                )
        return TransitionEvent(
            id=event_id,
            plant_id=plant_id,
            batch_id=batch_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor=actor,
            metadata=metadata,
            created_at=created_at,
            prev_hash=prev_hash,
            event_hash=event_hash,
            sequence=sequence,
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> TransitionEvent:
        return TransitionEvent(
            id=row["id"],
            plant_id=row["plant_id"],
            batch_id=row["batch_id"],
            from_state=PlantState(row["from_state"]),
            to_state=PlantState(row["to_state"]),
            reason=row["reason"],
            actor=row["actor"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            prev_hash=row["prev_hash"],
            event_hash=row["event_hash"],
            sequence=row["sequence"],
        )
