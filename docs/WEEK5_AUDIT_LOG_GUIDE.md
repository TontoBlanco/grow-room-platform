# Week 5: METRC-style seed-to-sale audit log

Goal: add an **append-only plant/batch event stream** to grow-room-platform so
you can talk about compliance evidence the same way a cleared DoD engineer talks
about an authorization package — without inventing work experience, without
spending AWS money, and without claiming this is a licensed METRC integration.

By the end of the week you have:

1. A **domain model**: Batch → Plant → TransitionEvent, with a finite state
   machine (seedling → vegetative → flowering → harvested → packaged → destroyed).
2. An **append-only SQLite store** (INSERT only for events; optional SHA-256
   hash chain for tamper evidence).
3. **FastAPI routes** under `/audit` that create plants/batches, append legal
   transitions, list history, and reject illegal transitions + event mutations.
4. **Compliance notes** (STIG-style hardening, SBOM/signing, least privilege)
   you can defend in interviews — educational talking points only.
5. A **write-up outline** (architecture diagram + blog skeleton) ready to publish.
6. Still **$0** cloud — SQLite on disk (or optional Postgres later via the
   compose/k3d stack you already have). No `terraform apply` against a real
   AWS account for this week.

You already know Deployments, Services, Argo sync, and Prometheus scrapes.
This week adds an **immutable evidence trail** next to the mutable live objects
(sensor readings, Deployment replicas). Same mental model as GitOps: the log is
the source of truth; the plant row is a projection.

Framing for portfolio readers: legal personal hobby / controlled-environment
agriculture (CEA). Professional tone. Not selling product. Not a regulator
filing.

Try each local step before treating the Definition of Done as checked.

---

## Step 0: Copy the starter into your repo

From the unzipped week-5 pack:

```bash
# From your grow-room-platform clone root
cp -r path/to/grow-room-platform-week5/sensor_service/audit ./sensor_service/
cp path/to/grow-room-platform-week5/tests/test_audit.py ./tests/
mkdir -p data docs
cp path/to/grow-room-platform-week5/data/.gitignore ./data/
cp path/to/grow-room-platform-week5/data/.gitkeep ./data/ 2>/dev/null || touch ./data/.gitkeep
cp path/to/grow-room-platform-week5/docs/WEEK5_*.md ./docs/
cp path/to/grow-room-platform-week5/docs/main_patch.md ./docs/
# Optional PVC snippet (only if you want DB to survive Pod restarts on k3d):
mkdir -p charts/snippets
cp path/to/grow-room-platform-week5/charts/snippets/audit-sqlite-pvc.yaml ./charts/snippets/
# Merge README_WEEK5_SNIPPET.md into README.md by hand
```

**Do not** overwrite `sensor_service/__init__.py` or `sensor_service/main.py`
with pack stubs. Mount the router using `docs/main_patch.md`.

Create a branch:

```bash
git checkout -b audit-log-week5
```

Sanity-check **before** wiring the router into `main.py`:

```bash
# From pack root OR from the repo after copy (PYTHONPATH must see sensor_service)
PYTHONPATH=. pytest tests/test_audit.py -v

# After mount (see main_patch.md):
export AUDIT_DB_PATH=./data/audit.db
mkdir -p data
uvicorn sensor_service.main:app --reload
curl -s localhost:8000/audit/batches -X POST -H 'content-type: application/json' \
  -d '{"name":"tent-a","strain":"demo"}' | jq .
```

Commit and push when you are ready for GitHub / portfolio. Argo does not need
a new Application for Week 5 unless you opt into the PVC snippet.

---

## Step 1: Why seed-to-sale audit logs matter

Commercial cannabis (and many other regulated ag verticals) tracks **every plant
and every state change** so a regulator can reconstruct: where did this unit
come from, who moved it, when, and into what status? That trail is the difference
between "we think we are compliant" and "here is the evidence package."

### DoD / ATO analogy (use carefully)

You already know authorization packages: controls, evidence, continuous
monitoring. Map the ideas — **do not** claim you built METRC for a federal
system:

| Seed-to-sale idea | Rough ATO / platform analogue |
|---|---|
| Plant/batch ID | Asset inventory / CMDB entry |
| State transition event | Change record / audit log entry |
| Append-only log | Immutable evidence; SIEM retention |
| Illegal transition rejected | Validating admission / policy-as-code |
| Hash chain / integrity check | Tamper-evident logging / file integrity |
| Actor field on events | Attribution (who did the change) |
| `/audit/integrity` | Continuous monitoring control check |
| Destroyed / packaged terminal paths | Disposition / decommission records |

Interview line that stays accurate:

> "I built an append-only lifecycle event store for a personal CEA project so I
> could practice the same evidence patterns regulators and authorizing officials
> care about — identity of the unit, who changed it, legal state machine, and
> integrity verification — without standing up paid cloud."

---

## Step 2: Domain model

```text
Batch 1──* Plant 1──* TransitionEvent (append-only)
              │
              └── current state is a *projection* of the event stream
```

### States

| State | Meaning (portfolio model) |
|---|---|
| `seedling` | Newly tagged plant (birth state) |
| `vegetative` | Veg growth |
| `flowering` | Flower / fruiting stage |
| `harvested` | Removed from grow, pre-package |
| `packaged` | Inventoried as package/unit |
| `destroyed` | Culled / destroyed (terminal) |

### Allowed transitions (FSM)

```text
seedling ──► vegetative ──► flowering ──► harvested ──► packaged
    │            │              │             │            │
    └────────────┴──────────────┴─────────────┴────────────┴──► destroyed
```

- No skipping (seedling → flowering is **409 Conflict**).
- No reverse (harvested → flowering is illegal).
- `destroyed` is terminal.
- Birth writes a special event `seedling → seedling` with `reason=plant_created`
  so history starts with an attributable row.

Kubernetes analogy: the FSM is a **ValidatingAdmissionWebhook** for plant
lifecycle. Bad requests never become etcd objects — here, bad transitions never
become event rows.

---

## Step 3: Append-only design

### Rules

1. **Events table: INSERT only.** The store exposes `update_event` / `delete_event`
   only to raise `ImmutableViolation`. HTTP PUT/PATCH/DELETE on `/audit/events/{id}`
   returns **405**.
2. **Plants/Batches tables are projections.** Updating `plants.state` after a
   successful transition is like a Deployment status field — derived, not the
   audit trail itself.
3. **Hash chain (tamper evidence):** each event stores `prev_hash` + `event_hash`
   (SHA-256 over canonical JSON of sequence, plant, states, actor, metadata,
   timestamps, prev_hash). `GET /audit/integrity` recomputes the chain.
4. **Attribution:** every transition carries `actor` (default `operator`).

### What this is *not*

- Not a blockchain network.
- Not METRC API compatibility.
- Not sufficient alone for a licensed facility (real systems add authn/z,
  WORM storage, key management, retention legal hold, etc.).

### K8s / GitOps mental model

| Audit idea | GitOps / K8s analogue |
|---|---|
| Event stream | Git history / AuditSink / Events API |
| Plant current row | Live object in etcd (mutable status) |
| Illegal transition | Admission webhook deny |
| Hash chain verify | `git fsck` / signed commits (conceptual) |
| SQLite file on PVC | PersistentVolume holding state |
| Actor | `User.Info` on API requests |

GitOps lesson you already learned in Week 3: **desired state in Git is
append-only history**; the cluster converges. Here the event log is append-only;
the plant row converges to the latest `to_state`.

---

## Step 4: Local run path (SQLite, $0)

Default path: `AUDIT_DB_PATH` → `./data/audit.db` (stdlib `sqlite3`, no new pip
deps).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
mkdir -p data
export AUDIT_DB_PATH=./data/audit.db

# Pack-only verify (before merging into main.py):
PYTHONPATH=. pytest tests/test_audit.py -v

# After main_patch.md mount:
uvicorn sensor_service.main:app --reload
```

Happy-path curl script:

```bash
BATCH=$(curl -s localhost:8000/audit/batches -H 'content-type: application/json' \
  -d '{"name":"tent-a","strain":"demo"}')
echo "$BATCH" | jq .
BATCH_ID=$(echo "$BATCH" | jq -r .id)

PLANT=$(curl -s localhost:8000/audit/plants -H 'content-type: application/json' \
  -d "{\"batch_id\":\"$BATCH_ID\",\"tag\":\"A1\"}")
echo "$PLANT" | jq .
PLANT_ID=$(echo "$PLANT" | jq -r .id)

curl -s localhost:8000/audit/plants/$PLANT_ID/transitions \
  -H 'content-type: application/json' \
  -d '{"to_state":"vegetative","actor":"cole","reason":"transplant"}' | jq .

# Illegal skip — expect 409
curl -s -o /tmp/err.json -w "%{http_code}\n" localhost:8000/audit/plants/$PLANT_ID/transitions \
  -H 'content-type: application/json' \
  -d '{"to_state":"packaged"}'
cat /tmp/err.json | jq .

curl -s localhost:8000/audit/plants/$PLANT_ID/history | jq .
curl -s localhost:8000/audit/integrity | jq .
```

### Optional Postgres later

Not required for Week 5. When you want it: add a SQLAlchemy/psycopg store
behind the same `AuditStore` interface, point docker-compose at Postgres, keep
SQLite as the default for CI. Do **not** stand up RDS for this lab.

### Optional PVC on k3d

See `charts/snippets/audit-sqlite-pvc.yaml`. Only needed if the Pod restart
wiping `emptyDir` bothers you during demos.

---

## Step 5: API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/audit/batches` | Create batch |
| GET | `/audit/batches` | List batches |
| GET | `/audit/batches/{id}` | Get batch |
| GET | `/audit/batches/{id}/plants` | Plants in batch |
| POST | `/audit/plants` | Create plant (starts `seedling`) |
| GET | `/audit/plants` | List plants |
| GET | `/audit/plants/{id}` | Current projection |
| POST | `/audit/plants/{id}/transitions` | Append legal transition |
| GET | `/audit/plants/{id}/history` | Event stream for plant |
| GET | `/audit/integrity` | Recompute hash chain |
| PUT/PATCH/DELETE | `/audit/events/{id}` | **405** — append-only |

OpenAPI: `/docs` → tag **audit**.

---

## Step 6: Compliance companion docs

Read and lightly customize:

- `docs/WEEK5_COMPLIANCE_NOTES.md` — STIG-style chart/image checklist, Trivy/SBOM,
  least privilege on k3d.
- `docs/WEEK5_WRITEUP_OUTLINE.md` — mermaid architecture + blog outline.
- `docs/WEEK5_CI_NOTE.md` — optional pytest CI you author yourself.

These are **talking points**, not a claim that your home tent is STIGed or
ATO'd.

---

## Step 7: Definition of Done checklist

Code / local:

- [ ] `sensor_service/audit/` copied into the real repo
- [ ] `tests/test_audit.py` passes (`pytest tests/test_audit.py -v`)
- [ ] Router mounted per `docs/main_patch.md`
- [ ] Create batch → plant → vegetative transition via curl or `/docs`
- [ ] Illegal transition returns **409**
- [ ] PUT/DELETE on `/audit/events/{id}` returns **405**
- [ ] `/audit/integrity` returns `{"ok": true, ...}`
- [ ] `data/*.db` git-ignored

Docs / portfolio:

- [ ] README roadmap updated from `README_WEEK5_SNIPPET.md`
- [ ] Write-up drafted from `WEEK5_WRITEUP_OUTLINE.md` (publish when ready)
- [ ] Compliance notes skimmed; pick 3 bullets you can say out loud
- [ ] Terraform Associate practice started or exam booked (week goal from plan)

Out of scope for "code done":

- [ ] Blog actually published (you hit publish)
- [ ] Exam passed (you schedule / sit it)
- [ ] Real METRC credentials or production WORM storage

---

## Interview talking points

1. **Append-only vs mutable:** "Events are INSERT-only; the plant row is a
   projection — same idea as Git history vs working tree, or audit log vs
   current ConfigMap data."
2. **Policy before persistence:** "Illegal transitions fail closed with 409
   before any row is written — admission control for domain state."
3. **Tamper evidence:** "A SHA-256 hash chain lets `/audit/integrity` detect
   silent UPDATEs to historical rows; real deployments would add authn and
   WORM storage."
4. **$0 lab discipline:** "SQLite locally, k3d for the platform weeks, Terraform
   modules validated without applying paid EKS — budget as a first-class
   control."
5. **Security+ / cleared background without inventing jobs:** "I use the same
   vocabulary as authorization packages — evidence, attribution, integrity,
   least privilege — on a personal CEA portfolio so I can discuss it concretely."

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: sensor_service.audit` | Forgot to copy package or PYTHONPATH | Copy `sensor_service/audit/`; run from repo root |
| DB locked / read-only | Path on bad mount / permissions | Set `AUDIT_DB_PATH` to a writable dir; `mkdir -p data` |
| 409 on every transition | Skipping stages or already terminal | Follow FSM; check `GET /plants/{id}` |
| Integrity `ok: false` after demo | Manual SQL edit or mixed DB files | Delete `data/audit.db` and replay; do not hand-edit events |
| Tests fail after merge | Old pytest cache / wrong venv | `pip install -e '.[dev]'` and re-run |

---

## What "done" looks like for the 5-week plan canvas

Canvas Week 5 focus: *Compliance angle, write-up, and job push* — done when
**published write-up; exam booked or passed**. This pack gets you the technical
spine and the outline; publishing and booking are human steps only you can take.
