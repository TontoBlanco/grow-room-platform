# Week 5 — Audit history

I wanted an API that refuses a bad state change and can show that the history still matches its hashes. I did not want to call that a compliance product.

## What I built

Routes under `/audit` for batches, plants, transitions, history, and `GET /audit/integrity`.

Allowed path: `seedling` → `vegetative` → `flowering` → `harvested` → `packaged`. `destroyed` is allowed from a non-terminal state and then has no exit. Anything else returns 409. Updates and deletes of a stored event return 405.

Each event stores `prev_hash` and a SHA-256 `event_hash`. The hash covers the sequence, plant, batch, states, reason, actor, metadata, timestamp, and previous hash. The chain starts from 64 zeros. The plants table is the current state. The events table is the history.

The default file is SQLite. On the laptop that is `./data/audit.db`. In the container it is `/tmp/audit.db`, because uid 10001 cannot create `./data`. In k3d that file is on an `emptyDir` and disappears when the pod is replaced. `charts/snippets/audit-sqlite-pvc.yaml` is an example. It is not wired into the chart.

[PR #38](https://github.com/TontoBlanco/grow-room-platform/pull/38) added Postgres behind the same API. Set `AUDIT_DATABASE_URL`, or a `postgres://` `DATABASE_URL`. `AUDIT_DATABASE_URL` wins. The image already includes the driver. CI runs the Postgres tests against a `postgres:16-alpine` service. See [ADR-0007](../adr/0007-sqlite-and-postgres.md).

## Why

I work with change records. I wanted the same habits in an API: a named state machine, an append path, and a check I can run. SQLite let me do that with no extra process. Postgres was the shape I would use when a database already exists, which it did on the proof of concept.

## Data flow

```mermaid
flowchart TB
  REQ["POST transition"] --> CHECK{"Allowed state?"}
  CHECK -->|no| ERR["HTTP 409"]
  CHECK -->|yes| LOCK["One lock on the chain tail"]
  LOCK --> INSERT["Insert event and hash"]
  INSERT --> UPDATE["Update the plant row"]
```

## Rebuild

SQLite, from the Week 1 virtualenv:

```powershell
Set-Location C:\src\grow-room-platform
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
uvicorn sensor_service.main:app --reload
```

Create a batch. This is one command:

```powershell
curl.exe -s localhost:8000/audit/batches -X POST -H "content-type: application/json" -d "{\"name\":\"tent-a\",\"strain\":\"demo\"}"
```

Postgres on Compose:

```powershell
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

That starts Postgres 16 and sets the API URL to `postgresql://audit:audit@postgres:5432/audit`. That password is a local lab value in the Compose file. Do not reuse it anywhere else.

Run the Postgres tests only when the URL is set. Without it, those tests skip and the SQLite tests still run.

```powershell
$env:AUDIT_TEST_DATABASE_URL = "postgresql://audit:audit@localhost:5432/audit"
```

```powershell
pip install -e ".[dev,postgres]"
```

```powershell
pytest --cov=sensor_service --cov-fail-under=80
```

## Cost

Local SQLite and the Compose Postgres container do not create AWS resources. The Multi-AZ RDS instance was part of the proof of concept, not this week. Do not start `infra/aws-poc` to try the audit API.

## What I learned

Rejecting `DELETE` in the API is not the same as write-once storage. A person who can write the database can rewrite a row and recompute the hash. I say that whenever I show `/audit/integrity`, because the green check is easy to over-read.

The container path also caught me. The first layout used `./data`, and the non-root image could not create it. `/tmp` works and does not survive a new pod. I left that as an honest limit instead of pretending the example PVC was deployed.
