"""Relational model shared by the SQLite and Postgres audit backends.

Three tables, same jobs on both engines:

- ``batches`` is a cultivation lot.
- ``plants`` is the mutable current-state projection. It points at a batch.
- ``events`` is the append-only history. Each row points at a plant and a
  batch, and carries the previous event's hash.

Postgres states the rules in the catalog: foreign keys with ``ON DELETE
RESTRICT`` (history must not disappear because a projection row was removed),
``CHECK`` constraints for the lifecycle vocabulary, ``JSONB`` metadata, and
indexes for the reads the API actually does (one plant's history, one batch's
timeline, plants in a batch filtered by state). SQLite enforces the same
foreign keys, checks, and indexes. ``metadata_json`` is ``TEXT`` there because
the stdlib driver has no JSONB type; the application still stores one JSON
object per event.

``created_at`` is ``TEXT`` on both engines. The hash preimage is the exact ISO
string the API wrote. A ``timestamptz`` round-trip can change that formatting
and make a valid chain look broken.

The chain is one global sequence, not one sequence per plant. Postgres
appends take ``pg_advisory_xact_lock`` on ``AUDIT_CHAIN_LOCK_KEY`` so two
writers cannot hash the same tail. SQLite takes ``BEGIN IMMEDIATE``, which is
the single-writer equivalent on a file database.
"""

from __future__ import annotations

# Stable int for pg_advisory_xact_lock. One chain, one writer at a time.
AUDIT_CHAIN_LOCK_KEY = 582_019

_STATE_CHECK = "'seedling', 'vegetative', 'flowering', 'harvested', 'packaged', 'destroyed'"

SQLITE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    strain TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plants (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    tag TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ({_STATE_CHECK})),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    plant_id TEXT NOT NULL REFERENCES plants(id) ON DELETE RESTRICT,
    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    from_state TEXT NOT NULL CHECK (from_state IN ({_STATE_CHECK})),
    to_state TEXT NOT NULL CHECK (to_state IN ({_STATE_CHECK})),
    reason TEXT,
    actor TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    sequence INTEGER NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_events_plant_sequence ON events(plant_id, sequence);
CREATE INDEX IF NOT EXISTS idx_events_batch_sequence ON events(batch_id, sequence);
CREATE INDEX IF NOT EXISTS idx_plants_batch_state ON plants(batch_id, state);
"""

# Separate statements: psycopg's execute() runs one command at a time.
POSTGRES_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS batches (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        strain TEXT,
        notes TEXT,
        created_at TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS plants (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES batches (id) ON DELETE RESTRICT,
        tag TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ({_STATE_CHECK})),
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        plant_id TEXT NOT NULL REFERENCES plants (id) ON DELETE RESTRICT,
        batch_id TEXT NOT NULL REFERENCES batches (id) ON DELETE RESTRICT,
        from_state TEXT NOT NULL CHECK (from_state IN ({_STATE_CHECK})),
        to_state TEXT NOT NULL CHECK (to_state IN ({_STATE_CHECK})),
        reason TEXT,
        actor TEXT NOT NULL,
        metadata_json JSONB NOT NULL,
        created_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        event_hash TEXT NOT NULL UNIQUE,
        sequence BIGINT NOT NULL UNIQUE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_plant_sequence
        ON events (plant_id, sequence)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_batch_sequence
        ON events (batch_id, sequence)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_plants_batch_state
        ON plants (batch_id, state)
    """,
    """
    COMMENT ON TABLE events IS
        'Append-only hash-chained plant transitions. Application code inserts only.'
    """,
)
