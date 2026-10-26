"""Append-only audit store with a SHA-256 hash chain.

SQLite is the default (stdlib, no extra service). ``AuditStore.from_env`` uses
Postgres when ``AUDIT_DATABASE_URL`` is set, or when ``DATABASE_URL`` is a
postgres URL. The state machine, hash preimage, and HTTP behavior match on
both backends.

Events are INSERT-only. Plants and batches are current-state projections.
The event stream is the history a caller can re-check.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

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
from sensor_service.audit.schema import AUDIT_CHAIN_LOCK_KEY, POSTGRES_SCHEMA, SQLITE_SCHEMA
from sensor_service.audit.states import can_transition, describe_allowed

GENESIS_HASH = "0" * 64
DEFAULT_DB_PATH = "./data/audit.db"
BackendName = Literal["sqlite", "postgres"]


class AuditError(Exception):
    """Base error for audit store operations."""


class NotFoundError(AuditError):
    pass


class ConflictError(AuditError):
    pass


class ImmutableViolation(AuditError):
    """Raised if anything tries to mutate past events."""


@dataclass(frozen=True)
class AuditTarget:
    """Resolved backend. ``from_env`` is the only constructor that reads URLs."""

    backend: BackendName
    db_path: str | None = None
    database_url: str | None = None


def _present(env: Mapping[str, str], key: str) -> str | None:
    raw = env.get(key)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


def resolve_audit_target(env: Mapping[str, str] | None = None) -> AuditTarget:
    """Pick SQLite or Postgres from the environment.

    Precedence:

    1. ``AUDIT_DATABASE_URL``, when set, must be a postgres URL.
    2. ``DATABASE_URL``, when it is already a postgres URL.
    3. ``AUDIT_DB_PATH``, otherwise ``./data/audit.db``.

    A non-postgres ``DATABASE_URL`` is left alone so this process can share
    that variable with other tools and stay on SQLite.
    """
    source = os.environ if env is None else env
    audit_url = _present(source, "AUDIT_DATABASE_URL")
    if audit_url is not None:
        if not _is_postgres_url(audit_url):
            raise AuditError("AUDIT_DATABASE_URL must start with postgres:// or postgresql://")
        return AuditTarget(backend="postgres", database_url=audit_url)
    database_url = _present(source, "DATABASE_URL")
    if database_url is not None and _is_postgres_url(database_url):
        return AuditTarget(backend="postgres", database_url=database_url)
    return AuditTarget(
        backend="sqlite",
        db_path=_present(source, "AUDIT_DB_PATH") or DEFAULT_DB_PATH,
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


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


def _load_metadata(value: Any) -> dict:
    loaded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(loaded, dict):
        raise AuditError("event metadata must be a JSON object")
    return loaded


def _psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise AuditError(
            "Postgres audit backend requires psycopg. "
            "Install it with: pip install 'grow-room-platform[postgres]'"
        ) from exc
    return psycopg, dict_row, Jsonb


class _Session:
    """One transaction. SQL is written with ``?`` placeholders for both engines."""

    def __init__(self, conn: Any, *, postgres: bool, jsonb: Any) -> None:
        self._conn = conn
        self._postgres = postgres
        self._jsonb = jsonb

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        statement = sql.replace("?", "%s") if self._postgres else sql
        cursor = self._conn.execute(statement, params)
        if cursor.description is None:
            return []
        return [dict(row) for row in cursor.fetchall()]

    def bind_metadata(self, metadata: dict) -> Any:
        if self._postgres:
            return self._jsonb(metadata)
        return json.dumps(metadata, sort_keys=True)


class SqliteDatabase:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SQLITE_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def session(self, *, append: bool = False) -> Iterator[_Session]:
        # isolation_level=None is autocommit, so BEGIN IMMEDIATE is really the
        # first statement. The default pysqlite isolation starts a deferred
        # transaction on DML only, which is too late to protect the chain tail.
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE" if append else "BEGIN")
            try:
                yield _Session(conn, postgres=False, jsonb=None)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()


class PostgresDatabase:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        psycopg, dict_row, _jsonb = _psycopg()
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def init_schema(self) -> None:
        conn = self._connect()
        try:
            for statement in POSTGRES_SCHEMA:
                conn.execute(statement)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def session(self, *, append: bool = False) -> Iterator[_Session]:
        _psycopg_mod, dict_row, jsonb = _psycopg()
        conn = _psycopg_mod.connect(self.database_url, row_factory=dict_row)
        try:
            # Fail a stuck chain lock instead of waiting out the CI job.
            conn.execute("SET lock_timeout = '10s'")
            if append:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (AUDIT_CHAIN_LOCK_KEY,),
                )
            try:
                yield _Session(conn, postgres=True, jsonb=jsonb)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()


class AuditStore:
    def __init__(self, db_path: str | None = None, *, database_url: str | None = None) -> None:
        if database_url is not None and db_path is not None:
            raise AuditError("pass db_path or database_url, not both")
        if database_url is not None:
            self.backend: BackendName = "postgres"
            self.database_url: str | None = database_url
            self.db_path = None
            self._db: SqliteDatabase | PostgresDatabase = PostgresDatabase(database_url)
        else:
            path = db_path if db_path is not None else os.environ.get("AUDIT_DB_PATH", "")
            path = path.strip() or DEFAULT_DB_PATH
            self.backend = "sqlite"
            self.database_url = None
            self.db_path = path
            self._db = SqliteDatabase(path)
        self._db.init_schema()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AuditStore:
        """Open the store selected by :func:`resolve_audit_target`."""
        target = resolve_audit_target(env)
        if target.backend == "postgres":
            if target.database_url is None:
                raise AuditError("postgres target is missing a database URL")
            return cls(database_url=target.database_url)
        if target.db_path is None:
            raise AuditError("sqlite target is missing a database path")
        return cls(db_path=target.db_path)

    # ---- Batches / plants (projections) ---------------------------------

    def create_batch(self, body: BatchCreate) -> Batch:
        batch = Batch(
            id=_new_id("batch"),
            name=body.name,
            strain=body.strain,
            notes=body.notes,
            created_at=utc_now_iso(),
        )
        with self._db.session() as db:
            db.execute(
                "INSERT INTO batches (id, name, strain, notes, created_at) VALUES (?, ?, ?, ?, ?)",
                (batch.id, batch.name, batch.strain, batch.notes, batch.created_at),
            )
        return batch

    def get_batch(self, batch_id: str) -> Batch:
        with self._db.session() as db:
            rows = db.execute("SELECT * FROM batches WHERE id = ?", (batch_id,))
        if not rows:
            raise NotFoundError(f"batch not found: {batch_id}")
        return Batch(**rows[0])

    def list_batches(self) -> list[Batch]:
        with self._db.session() as db:
            rows = db.execute("SELECT * FROM batches ORDER BY created_at")
        return [Batch(**row) for row in rows]

    def create_plant(self, body: PlantCreate) -> tuple[Plant, TransitionEvent]:
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
        with self._db.session(append=True) as db:
            rows = db.execute("SELECT id FROM batches WHERE id = ?", (body.batch_id,))
            if not rows:
                raise NotFoundError(f"batch not found: {body.batch_id}")
            # Birth event: from_state == to_state == seedling. The chain continues.
            event = self._insert_event(
                db,
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
        with self._db.session() as db:
            return self._get_plant(db, plant_id)

    def list_plants(self, batch_id: str | None = None) -> list[Plant]:
        with self._db.session() as db:
            if batch_id:
                rows = db.execute(
                    "SELECT * FROM plants WHERE batch_id = ? ORDER BY created_at",
                    (batch_id,),
                )
            else:
                rows = db.execute("SELECT * FROM plants ORDER BY created_at")
        return [self._row_to_plant(row) for row in rows]

    # ---- Transitions / history ------------------------------------------

    def transition(self, plant_id: str, body: TransitionRequest) -> TransitionEvent:
        now = utc_now_iso()
        with self._db.session(append=True) as db:
            # Re-read inside the chain lock so two writers cannot both pass
            # the state machine against the same current row.
            plant = self._get_plant(db, plant_id)
            if not can_transition(plant.state, body.to_state):
                allowed = describe_allowed(plant.state)
                raise ConflictError(
                    f"illegal transition {plant.state.value!r} → {body.to_state.value!r}; "
                    f"allowed from {plant.state.value!r}: {allowed or '(terminal)'}"
                )
            return self._insert_event(
                db,
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

    def history(self, plant_id: str) -> list[TransitionEvent]:
        with self._db.session() as db:
            self._get_plant(db, plant_id)
            rows = db.execute(
                "SELECT * FROM events WHERE plant_id = ? ORDER BY sequence",
                (plant_id,),
            )
        return [self._row_to_event(row) for row in rows]

    def verify_chain(self, plant_id: str | None = None) -> dict:
        """Recompute the global hash chain (optionally scoped report to one plant).

        Chain continuity is always global (sequence order). When plant_id is set,
        only events for that plant are counted in ``checked``, but intervening
        events are still walked so prev_hash links stay valid.
        """
        with self._db.session() as db:
            rows = db.execute("SELECT * FROM events ORDER BY sequence")
            return self._verify_rows(db, rows, plant_id)

    # Explicitly refuse mutation of past events (no public UPDATE/DELETE).
    def update_event(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise ImmutableViolation("audit events are append-only; UPDATE is forbidden")

    def delete_event(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise ImmutableViolation("audit events are append-only; DELETE is forbidden")

    # ---- internals ------------------------------------------------------

    def _verify_rows(self, db: _Session, rows: list[dict], plant_id: str | None) -> dict:
        prev = GENESIS_HASH
        checked = 0
        for row in rows:
            meta = _load_metadata(row["metadata_json"])
            expected = _hash_event(
                sequence=int(row["sequence"]),
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
            self._get_plant(db, plant_id)
        return {"ok": True, "checked": checked}

    def _get_plant(self, db: _Session, plant_id: str) -> Plant:
        rows = db.execute("SELECT * FROM plants WHERE id = ?", (plant_id,))
        if not rows:
            raise NotFoundError(f"plant not found: {plant_id}")
        return self._row_to_plant(rows[0])

    def _insert_event(
        self,
        db: _Session,
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
        rows = db.execute("SELECT sequence, event_hash FROM events ORDER BY sequence DESC LIMIT 1")
        if not rows:
            sequence, prev_hash = 1, GENESIS_HASH
        else:
            sequence = int(rows[0]["sequence"]) + 1
            prev_hash = str(rows[0]["event_hash"])
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
        event_id = _new_id("evt")
        if insert_plant is not None:
            db.execute(
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
        db.execute(
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
                db.bind_metadata(metadata),
                created_at,
                prev_hash,
                event_hash,
                sequence,
            ),
        )
        if update_plant_state is not None:
            db.execute(
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
    def _row_to_plant(row: dict) -> Plant:
        data = dict(row)
        data["state"] = PlantState(data["state"])
        return Plant(**data)

    @staticmethod
    def _row_to_event(row: dict) -> TransitionEvent:
        return TransitionEvent(
            id=row["id"],
            plant_id=row["plant_id"],
            batch_id=row["batch_id"],
            from_state=PlantState(row["from_state"]),
            to_state=PlantState(row["to_state"]),
            reason=row["reason"],
            actor=row["actor"],
            metadata=_load_metadata(row["metadata_json"]),
            created_at=row["created_at"],
            prev_hash=row["prev_hash"],
            event_hash=row["event_hash"],
            sequence=int(row["sequence"]),
        )
