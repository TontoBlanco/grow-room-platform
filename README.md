# grow-room-platform

I built this capstone to get hands-on experience with tools I kept seeing in
cloud, infrastructure, and DevOps job postings: Python, Docker, GitHub Actions,
Terraform, Kubernetes, Helm, Argo CD, Prometheus, and Grafana, plus the AWS
services used for a session-based EKS proof of concept (VPC, EKS, ALB, WAF,
Route 53, ACM, RDS, Secrets Manager, KMS, S3, Glue, Athena, IAM OIDC, and
Budgets). I wanted more than a tutorial I could say I finished. I wanted a
project I could set up, break, troubleshoot, and explain.

The use case is a 4x4 grow tent I run at home. The service reads climate data
from an AC Infinity controller through Home Assistant, provides an API and
Prometheus metrics, and puts the readings on a Grafana dashboard. I also added
an audit API to practice recording state changes and checking data integrity.

There are three places this runs. The daily lab is local. The expensive
cluster is not.

- **Local lab.** Kubernetes runs in **k3d** on my computer. The cluster uses
  simulated readings. Live tent readings stay on Docker Compose. The Terraform
  root in `infra/` is validated in CI and is not applied by a workflow. Its
  defaults are `cluster_mode = "local"` and `enable_eks = false`. That root
  has no `aws_eks_cluster` resource.
- **AWS proof of concept, one session at a time.** `infra/aws-poc` in
  `us-west-2`. I apply it with `scripts/aws-poc.ps1` when I am ready to pay,
  and I run `down` before I stop. The first apply was 1 November 2026. The
  paid test session on 3 November 2026 passed, including teardown. It is not
  a cluster I leave running. Phases 3 through 7 are done. The record is the
  [documentation site](docs/index.md), the
  [3 November test session](docs/test-session/2026-11-03.md), and the
  [1 November gallery](docs/aws-poc/README.md).
- **Telemetry that stays up.** `infra/telemetry` stores readings in S3 for
  Athena. It costs about 1 USD per month. `down` does not remove it. See
  [Phase 3](docs/phases/phase-3-telemetry.md).

For the longer explanation of the design and what I learned, see
[docs/CAPSTONE.md](docs/CAPSTONE.md). The full documentation site, including
the architecture, each build phase, the Grafana guide, and the security
notes, starts at [docs/index.md](docs/index.md). GitHub Actions builds that
site on every pull request and publishes it from `main` to
[GitHub Pages](https://tontoblanco.github.io/grow-room-platform/).

## Why I built it

My background is in configuration management, systems administration, and
supporting complex IT environments. I wanted to build practical experience
with containers, infrastructure as code, CI/CD, GitOps, and monitoring instead
of only reading about them.

I've also been growing in a controlled environment since 2018. My current
setup uses AC Infinity controls, tunable LEDs, and no-till living soil. Using
my own grow-room data made the project useful to me and gave me real problems
to work through, especially when I started connecting the equipment to the
monitoring stack.

## What I built

| Area | What is in the repo |
|------|---------------------|
| Python API | FastAPI service for climate readings, health checks, metrics, and audit events |
| Data sources | A simulator for repeatable testing and a read-only Home Assistant integration for live tent data |
| Containers and CI | Docker image, Ruff, pytest with an 80% coverage threshold, GHCR publishing, and Trivy scanning |
| Kubernetes and GitOps | k3d cluster, Helm chart, Argo CD app-of-apps, and image-tag update PRs |
| Infrastructure as code | Local Terraform modules checked with `fmt`, `validate`, and `tflint`. A separate root, `infra/aws-poc`, is what I apply for a paid session and then destroy. |
| AWS proof of concept | VPC across 3 AZs, EKS 1.36, ALB, WAF, ACM, Route 53, RDS PostgreSQL Multi-AZ, Secrets Manager, KMS, S3, Glue, Athena, Karpenter, and a $25 budget. Brought up by phase, not left running. Gallery in `docs/aws-poc/`. |
| Telemetry | S3, Glue, and Athena in `infra/telemetry`, kept between sessions, about 1 USD per month |
| Observability | Prometheus, Grafana Grow-room VPD dashboard, plant-mood gauge, three alert rules, and two lab SLOs |
| Audit history | SQLite-backed plant/batch events with state-transition checks and a SHA-256 hash chain |

I built the lab over five weeks, then seven numbered phases. Phases 3
through 7 are done. The page for each one is on the
[documentation site](docs/index.md). The 1 November gallery is
[docs/aws-poc/README.md](docs/aws-poc/README.md).

## How it fits together

I kept the live grow-room connection separate from the Kubernetes demo:

- **Docker Compose** runs Home Assistant and a sensor-service instance that
  reads the actual controller. It is read-only and uses a token stored outside
  Git.
- **k3d** runs a second sensor-service instance using simulated data, plus
  Argo CD, Prometheus, and Grafana. It can run without my equipment, Home
  Assistant account, or AWS credentials.

```mermaid
flowchart LR
  ACI["AC Infinity AI+"] -->|Wi-Fi / cloud account| HA["Home Assistant :8123"]
  HA -->|"GET /api/states"| CS["Compose sensor-service<br/>homeassistant :8000"]
  CS -->|"grow-room-ha-host<br/>host.k3d.internal:8000"| PROM[Prometheus]
  SIM["k3d sensor-service<br/>simulator"] -->|ServiceMonitor| PROM
  PROM --> GRAF["Grafana<br/>Grow-room VPD"]
  ARGO[Argo CD] -->|Helm| SIM
  ARGO -->|kube-prometheus-stack| PROM
```

The live data path is:

**AC Infinity → Home Assistant → Compose sensor-service → Prometheus → Grafana.**

I also keep a [living platform map](https://cursor.com/canvas/store-6a197a3b-901d-4b50-9079-9a539befde02/debaff3b-9e35-48ab-bab0-59761b62fb09)
with the layout, milestones, and design decisions. The diagram above is the
version kept in the repo.

## AWS deployment (proof of concept)

I do not leave this stack running. `scripts/aws-poc.ps1 up` applies
`infra/aws-poc` in `us-west-2`, `verify` checks it, and `down` removes the
expensive resources. The public name during a session is
`app.mygrowroom.click`. Pods run the simulator. Live tent data stays on
Compose.

The first session was 1 November 2026, and I destroyed it the same day.
The paid test session on 3 November 2026 passed: verify, the email alert
path, the exporter from EKS to S3 to Athena, and drills 1 through 4.
Teardown was clean. Cleanup from that day is pull request
[#75](https://github.com/TontoBlanco/grow-room-platform/pull/75), which is
merged. How the phases fit is
[Phase 2](docs/phases/phase-2-up-verify-down.md). The session record is
[the test session page](docs/test-session/2026-11-03.md).

What stays up after `down` is the state bucket, the state KMS key, the
GitHub OIDC roles, the budget, the hosted zone, and the telemetry stack
at about 1 USD per month.

The full gallery, with the architecture diagram and the limits, is
[docs/aws-poc/README.md](docs/aws-poc/README.md). The stack is
[`infra/aws-poc`](infra/aws-poc). Karpenter and the Secrets Manager store
are in [`k8s/aws-poc`](k8s/aws-poc). The EKS Argo CD Application is
[`gitops/eks/sensor-service.yaml`](gitops/eks/sensor-service.yaml). It
selects [`charts/sensor-service/values-eks.yaml`](charts/sensor-service/values-eks.yaml)
(three replicas, the ALB Ingress, and ExternalSecret `audit-db`). The k3d
Application in `gitops/apps/` is unchanged.

![Chrome on https://app.mygrowroom.click/readings, connection secure](docs/aws-poc/images/browser-readings-https_527f.png)

`/readings` over HTTPS. Chrome reports "Connection is secure". The JSON
`source` is `simulator`.

![Argo CD: monitoring and sensor-service Healthy and Synced](docs/aws-poc/images/argo-applications_f358.png)

Argo CD on the cluster. `monitoring` (kube-prometheus-stack `92.13.1`) and
`sensor-service` were Healthy and Synced from this repo.

![EKS console: grow-room-poc, Kubernetes 1.36, Active](docs/aws-poc/images/eks-cluster-info_2d79.png)

Cluster `grow-room-poc`, Kubernetes 1.36, status Active: 44 pods, 3 nodes,
5 add-ons, 6 pod identities.

## Run it locally

### Python service (simulator)

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check . && pytest --cov=sensor_service
uvicorn sensor_service.main:app --reload
```

Open `http://localhost:8000/readings` or `http://localhost:8000/docs`.
`SENSOR_SOURCE` defaults to `simulator`, so no physical sensors are needed.

### Docker Compose

```bash
docker compose up --build sensor-service  # API with simulated readings
curl localhost:8000/readings
```

Running `docker compose up` without a service name also starts Home Assistant
on port 8123. The sensor service is published on port 8000 so Prometheus in
k3d can scrape it through the Docker host.

### Connect the live controller

The AC Infinity AI+ does not have an official public API. I use the community
[homeassistant-acinfinity](https://github.com/dalinicus/homeassistant-acinfinity)
integration through HACS and read entities from Home Assistant. My code makes
`GET /api/states/<entity_id>` calls only. It does **not** change controller
settings or call Home Assistant services.

1. Run `docker compose up` and finish Home Assistant setup at `http://localhost:8123`.
2. Install [HACS](https://hacs.xyz/) and the AC Infinity integration, then connect the AC Infinity account.
3. Create a long-lived access token in Home Assistant.
4. Copy `.env.example` to `.env` and set `SENSOR_SOURCE=homeassistant`, `HA_URL=http://homeassistant:8123`, and `HA_TOKEN`.
5. Run `docker compose up` again.

The default `HA_DEVICE_PREFIX=the_garden` maps controller temperature,
humidity, VPD and status; the internal probe; and the devices `port_1`,
`humidifier`, `oscillating_fans`, and `ventilation_fan`. Ports 4–7 are not
included until added to `HA_PORT_DEVICES`. `HA_CO2_ENTITY` is optional and
empty by default; a blank `HA_*_ENTITY` value skips that reading.

`.env`, `ha-config/`, and `data/` are gitignored. The Home Assistant token is
not stored in the Helm values or monitoring configuration.

## API and sensor data

| Endpoint | Purpose |
|----------|---------|
| `GET /healthz` | Health check |
| `GET /readings` | Temperature (°C/°F), humidity, computed VPD (kPa), optional CO2, controller/probe details, device ports, and the growth-stage VPD target |
| `GET /mood` | Playful plant mood from the current leaf VPD (soft heuristic, not agronomy advice) |
| `GET /stage` | Configured growth stage and its leaf-VPD target band (no sensor read) |
| `GET /metrics` | Prometheus metrics |
| `GET /docs` | FastAPI OpenAPI documentation |
| `/audit/...` | Batches, plants, state changes, event history, and integrity checks |

The service calculates VPD with the Tetens equation. `LEAF_TEMP_OFFSET_C`
(default `-2.0` in the lab configuration) adjusts the calculation for leaf
temperature. When Home Assistant reports controller or probe VPD in psi, the
API provides a converted kPa value and preserves the original value and unit
as `vpd_raw` and `vpd_unit`.

Prometheus always has the simulator's climate gauges, including
`grow_temperature_celsius`, `grow_vpd_kpa`, and `grow_room_plant_mood`
(labeled by `band`; see below). The growth stage is config, so these are
present even when a sensor read fails:

- `grow_room_stage_info` (value 1; `stage` is the setting, `display` is the name)
- `grow_vpd_target_low_kpa`, `grow_vpd_target_high_kpa`

`grow_vpd_in_target_band` is 1 when computed leaf VPD is inside that inclusive
band and 0 when it is outside. It appears after a successful reading.

Additional controller, probe, and port gauges are created only after a
successful Home Assistant sample:

- `grow_probe_temperature_celsius`, `grow_probe_humidity_percent`, `grow_probe_vpd_kpa`
- `grow_controller_vpd_kpa`, `grow_controller_status`
- `grow_port_current_power`, `grow_port_status` (labeled by device)

### Plant mood

`GET /mood` is a small observability layer on the leaf VPD the service already
computes. It returns a band, a short grower-facing mood, and the same reading
sets `grow_room_plant_mood` so Grafana can chart it without scraping the JSON
endpoint. Inactive bands are 0, so `max by (job) (grow_room_plant_mood)` is
the current category. The score goes up as the air gets drier. It is a
category code, not a quality ranking.

These bands are a soft heuristic for a mixed tent. They are not agronomy
advice, not stage-specific targets (seedlings usually want less VPD than late
flower), and not a control signal.

| Leaf VPD (kPa) | Band | Mood | Score |
|----------------|------|------|-------|
| < 0.4 | `stressful_humid` | swampy | 1 |
| 0.4 ≤ VPD < 0.8 | `muggy` | muggy | 2 |
| 0.8 ≤ VPD ≤ 1.2 | `ideal` | cozy | 3 |
| 1.2 < VPD ≤ 1.6 | `too_dry` | thirsty | 4 |
| > 1.6 | `stressful_dry` | crispy | 5 |

Soup and crispy are both stressful, and they stay separate bands so the
Prometheus label does not hide which problem it is. The Grow-room VPD
dashboard has a Plant mood stat under the CO₂ panel, one tile per scrape job.

### Growth stage

`GROW_STAGE` is one tent-wide stage. It is separate from plant mood. Mood is
a mixed-tent heuristic. The stage selects the leaf-VPD target the dashboard
draws.

| `GROW_STAGE` | Also accepted | Leaf VPD target (kPa) |
|--------------|---------------|------------------------|
| `seedling` | `clone` | 0.4–0.8 |
| `veg` (default) | `vegetative` | 0.8–1.2 |
| `flower` | `flowering` | 1.2–1.5 |
| `late_flower` | `late-flower`, `late flower` | 1.4–1.6 |

Edges are inclusive, so 0.8 kPa is in band for both seedling and veg. Only
the selected stage is active. `clone` is stored as `seedling`.

These ranges are a rule of thumb for an indoor tent, not a prescription
for a particular plant. `GET /stage` returns the active stage and the band.
Pull request
[#77](https://github.com/TontoBlanco/grow-room-platform/pull/77) merged on
3 November 2026. The panels are in the
[Grafana guide](docs/grafana.md).

Override a stage without changing the name:

```bash
# flower band only, low,high in kPa
VPD_BAND_FLOWER=1.15,1.45
# or just the active stage's edges
VPD_TARGET_LOW_KPA=1.15
VPD_TARGET_HIGH_KPA=1.45
```

The same keys go in Helm `env`. A blank value is ignored. A low that is not
below the high, or a number outside 0–10 kPa, stops the process at startup.

Grafana's Grow-room VPD dashboard has a **Growth stage VPD target** row.
Stage, the low and high lines, and the IN/OUT stat all come from
`grow_room_stage_info`, `grow_vpd_target_low_kpa`, `grow_vpd_target_high_kpa`,
and `grow_vpd_in_target_band`. The lines move when the stage changes. The
colors on the top VPD stat are a fixed display scale, not this band.

`scripts/ship_readings.py` adds `stage` to each S3 JSON Lines row when
`/readings` includes `growth_stage`. Older objects omit it. The Glue tables
in `infra/telemetry` and `infra/aws-poc` have an optional `stage` string
column, so existing queries that do not select it stay the same and Athena
returns null for old objects. Nothing in this change sends email.

#### Change the stage on k3d

From a checkout, the Helm smoke-test release is `sensor`:

```bash
helm upgrade --install sensor ./charts/sensor-service -n grow-room --create-namespace \
  -f charts/sensor-service/values.yaml -f charts/sensor-service/values-k3d.yaml \
  --set env.GROW_STAGE=flower
```

Use `seedling`, `veg`, `flower`, or `late_flower`. `clone` is accepted and
reported as `seedling`.

The Argo CD app (`gitops/apps/sensor-service.yaml`) self-heals from Git, and
its Helm release name is `sensor-service`, not `sensor`. A `--set` on a
release Argo owns is reverted on the next sync. To keep the stage on that
cluster, set `env.GROW_STAGE` in `charts/sensor-service/values-k3d.yaml` and
sync. Until that sync, this updates the running Argo deployment:

```bash
kubectl -n grow-room set env deployment/sensor-service GROW_STAGE=flower
```

#### Change the stage in values

| File | Who reads it |
|------|----------------|
| `charts/sensor-service/values.yaml` | Chart default (`veg`) for every install |
| `charts/sensor-service/values-k3d.yaml` | k3d Argo app and the Helm command above |
| `charts/sensor-service/values-eks.yaml` | aws-poc Argo app (`gitops/eks/sensor-service.yaml`) |

```yaml
env:
  GROW_STAGE: flower
```

Helm merges `env`, so a values file only needs the keys it changes.

#### Change the stage on Docker Compose

The Home Assistant stack reads the same variable. Recreate the container
after changing it (the process reads the environment at startup):

```bash
GROW_STAGE=flower docker compose up -d sensor-service
```

Or set `GROW_STAGE` in `.env` and run that command without the prefix.

Check either install with `GET /stage` (for the Helm release `sensor`, the
Service is `sensor-sensor-service`; for Argo it is `sensor-service`):

```bash
kubectl -n grow-room port-forward svc/sensor-service 8000:8000
curl -s localhost:8000/stage
```

## Run the Kubernetes lab

Requires Docker, k3d, kubectl, and Helm.

```bash
./scripts/bootstrap-k3d.sh
kubectl apply -n argocd -f gitops/root-app.yaml
kubectl -n argocd get applications
```

The script creates `grow-room-dev` with two agents and installs Argo CD.
To reach the Argo CD UI:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
```

Open `http://localhost:8080` (HTTP). Port 443 with HTTPS resets TLS on this
lab; the HTTP port on the service is the path that works. The bootstrap
script prints the initial admin password while the secret is available.

The `grow-room-root` Application manages two child Applications:

| Application | Responsibility |
|-------------|----------------|
| `sensor-service` | Helm chart in the `grow-room` namespace, using simulated readings |
| `monitoring` | kube-prometheus-stack `92.13.1`, ServiceMonitor, alerts, and dashboard |

Argo CD is configured to prune and self-heal resources based on the Git
configuration. For a Helm-only smoke test without Argo:

```bash
helm upgrade --install sensor ./charts/sensor-service -n grow-room --create-namespace \
  -f charts/sensor-service/values.yaml -f charts/sensor-service/values-k3d.yaml
```

## CI/CD and Terraform

**GitHub Actions CI** (`.github/workflows/ci.yml`) runs Ruff and pytest with a
coverage threshold of 80%. A Buildx job creates the container image. Pushes
to `main` publish the commit-SHA and `latest` tags to
`ghcr.io/tontoblanco/grow-room-platform`. Trivy scans the `latest` image and
fails the job on unfixed HIGH or CRITICAL findings.

**GitOps deployment** (`.github/workflows/gitops-bump.yml`) runs after a
successful CI workflow on `main`. It opens a PR to update `image.tag` in
`charts/sensor-service/values.yaml` to `sha-<7-char>`. Merging that PR changes
the desired state; Argo CD then synchronizes the cluster. It is not an
unreviewed automatic deployment.

**Terraform** for the local lab lives in `infra/`. The workflow runs
`terraform fmt -check`, `terraform init -backend=false`, `terraform validate`,
and `tflint` using Terraform 1.9.8, with `infra/` as the working directory.
It does not run `plan` or `apply`, and it does not apply `infra/aws-poc`.

| Variable | Repo default | Meaning |
|----------|--------------|---------|
| `cluster_mode` | `local` | Local cluster output rather than the EKS branch |
| `enable_eks` | `false` | Leaves the EKS-related IAM/security-group branch disabled |
| `enable_nat_gateway` | `false` | Does not include the hourly-billed NAT gateway |

The EKS branch in that root module is not a cluster: it has an IAM role and
a security group, and the `aws_eks_cluster` resource is still commented out.
The network module does define real AWS VPC, subnet, and internet-gateway
resources. **Running `terraform apply` against the root module can create
AWS resources, even with the local cluster default.** CI does not apply it.
A `budget_reminder` output says to configure a $20/month AWS Budgets alert
before a paid apply. That output does not create the alert.

The cluster I did apply is a different root, `infra/aws-poc` (Terraform
`>= 1.11`, AWS provider `~> 6.71`). It uses the upstream EKS module
`21.29.0`, an S3 backend with a KMS key and S3 lockfile, and a $25 budget
in the bootstrap root. GitHub Actions OIDC roles exist for plan and apply.
The checked-in workflow does not assume them. I applied the stack by hand,
demoed it, and destroyed it. See
[docs/aws-poc/README.md](docs/aws-poc/README.md).

The Week 2 and Week 3 guides describe the local lab, not the proof of concept:
[Terraform guide](docs/weekly-guides/WEEK2_TERRAFORM_GUIDE.md) and
[GitOps guide](docs/weekly-guides/WEEK3_GITOPS_GUIDE.md).

## Monitoring

Prometheus and Grafana run in the `monitoring` namespace. The laptop-oriented
configuration uses 24-hour retention, a 30-second scrape interval, and single
replicas.

Prometheus has two scrape targets:

| Job | Data source |
|-----|-------------|
| `sensor-service` | In-cluster simulator through a ServiceMonitor |
| `grow-room-ha-host` | Compose service on `host.k3d.internal:8000` using `additionalScrapeConfigs` |

The second job has `sensor_source="homeassistant"` and
`instance="docker-compose-sensor-service"` labels. The dashboard uses those
labels to keep the live controller and probe readings separate from simulated
readings. It also groups scrape health by job so an old pod does not leave
extra DOWN tiles after a rollout. Tests in `tests/test_grafana_dashboard.py`
check the queries.

When the laptop sleeps, Docker Compose and k3d pause with it. Home Assistant
and the Compose sensor-service stop, so Prometheus stops scraping
`grow-room-ha-host` at `host.k3d.internal:8000` and Grow-room VPD goes flat
until the machine wakes. That is the lab host, not a Grafana bug. An always-on
Raspberry Pi running Home Assistant and sensor-service would keep that scrape
up. I have not built that.

```bash
kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

Prometheus targets: `http://127.0.0.1:9090/targets`.
Grafana: `http://127.0.0.1:3000` (lab credentials `admin` / `grow-room-lab`).
The live dashboard is **Grow-room VPD**, uid `grow-room-vpd`. Live-only panels show
**No HA sample** until Home Assistant has supplied readings and the host
scrape is UP.

**Grow-room History** (uid `grow-room-history`) reads the long-term tent
archive in Amazon Athena: database `grow_room_telemetry`, workgroup
`grow-room-telemetry`, region `us-west-2`. Grafana uses its own read-only
Roles Anywhere certificate. The shipper role stays write-only. Auto-refresh
is off. This landed in pull request
[#80](https://github.com/TontoBlanco/grow-room-platform/pull/80). Apply
steps are in [docs/ATHENA_GRAFANA.md](docs/ATHENA_GRAFANA.md).

This lab defines two starting-point SLOs for the in-cluster simulator:

- **Scrape availability:** 99% successful scrapes over seven days.
- **Prometheus sample freshness:** `grow_vpd_kpa` samples no older than 120
  seconds for 99% of observations over seven days. This checks sample age,
  not whether a physical sensor has stopped changing its value.

There are also alerts for sensor scrape failures (2 minutes), humidity outside
30–80% (5 minutes), and more than two sensor container restarts in 15 minutes.
The humidity rule applies to any matching series, including live and
simulated readings. See [monitoring/docs-slo.md](monitoring/docs-slo.md) and
the [observability guide](docs/weekly-guides/WEEK4_OBSERVABILITY_GUIDE.md).

## Audit log

The `/audit` routes let me practice event history and integrity checks using
a plant/batch model. This is **not** a state compliance system or a METRC
integration.

A plant follows these states:

`seedling` → `vegetative` → `flowering` → `harvested` → `packaged`

`destroyed` is allowed from any non-terminal state. Invalid transitions
return 409. The API rejects `PUT`, `PATCH`, and `DELETE` requests against
stored events with 405 responses.

Each event records its previous event's hash and its own SHA-256 hash.
`GET /audit/integrity` recomputes the chain to detect inconsistencies. The
plant table holds the current state; the event table holds the history.

```bash
curl -s localhost:8000/audit/batches -X POST -H 'content-type: application/json' \
  -d '{"name":"tent-a","strain":"demo"}'
```

By default the local database is `./data/audit.db` (SQLite, no extra service).
Docker Compose and the Helm chart use `/tmp/audit.db` so the non-root container
can write to it. In k3d, that database is on an `emptyDir` and **does not
survive replacement of the pod**. There is an example PVC at
`charts/snippets/audit-sqlite-pvc.yaml`, but it is not wired into the chart.

Postgres is optional. Set `AUDIT_DATABASE_URL` (or a `postgres://` /
`postgresql://` `DATABASE_URL`) and install the extra with
`pip install -e '.[postgres]'`. `AUDIT_DATABASE_URL` wins when both are set.
A non-postgres `DATABASE_URL` is ignored and the store stays on SQLite.
The image already includes the driver. Local Compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build
```

That starts one Postgres 16 container and points the API at
`postgresql://audit:audit@postgres:5432/audit` (a local lab password). CI runs
the same checks against a Postgres service container. k3d/Helm stay on SQLite
unless you set the URL yourself. The local lab does not provision RDS.
The AWS proof of concept did: Multi-AZ PostgreSQL in `infra/aws-poc`, with
the URL injected from Secrets Manager. That database was destroyed with the
rest of the stack. See [docs/aws-poc/README.md](docs/aws-poc/README.md).

Postgres adds a durable relational model: batches, plants, and events with
foreign keys, state checks, and indexes for plant history and batch lookups.
It still does not prove an immutable WORM archive, verified actor attribution,
or METRC connectivity. The hash chain detects a rewritten row. Someone who can
write the database can still rewrite a row and recompute the chain. The
`actor` field is recorded, not authenticated.

See the [audit guide](docs/weekly-guides/WEEK5_AUDIT_LOG_GUIDE.md) and
[compliance notes](docs/weekly-guides/WEEK5_COMPLIANCE_NOTES.md).

## Security and scope

The Helm chart uses a non-root user (uid 10001), a read-only root filesystem,
`allowPrivilegeEscalation: false`, dropped Linux capabilities, seccomp
`RuntimeDefault`, resource limits, health probes, and a ServiceAccount with
token automount disabled.

Those settings are a starting point for learning container hardening. This
project has no ATO, STIG assessment, FedRAMP authorization, or external state
traceability integration. The local lab's audit store is SQLite by default.
Optional Postgres there is a single local database, not multi-node HA and
not WORM storage.

The AWS proof of concept is a real EKS cluster with Multi-AZ RDS, a WAF,
and KMS on disks, secrets, and logs, for the hours I leave it up. I destroy
those resources at the end of the session. It is not a standing production
cluster, and it is not an authorization. The gaps (simulator data in the
cloud, WAF logging off, one-day log retention, apply role still
AdministratorAccess) are in
[docs/aws-poc/README.md](docs/aws-poc/README.md). The controls I can point
at in Git are on the [controls page](docs/security/controls.md).

## Repository layout

| Path | Contents |
|------|----------|
| `sensor_service/` | FastAPI app, data sources, VPD math, and audit implementation |
| `tests/` | API, math, Home Assistant fixture, audit, and dashboard tests |
| `charts/sensor-service/` | Helm chart |
| `gitops/` | Argo CD apps. `gitops/apps/` is the k3d lab. `gitops/eks/sensor-service.yaml` selects `values-eks.yaml` |
| `monitoring/` | Prometheus/Grafana configuration, SLOs, dashboard, and alerts |
| `infra/` | Local Terraform root and modules. Defaults stay `cluster_mode = "local"` |
| `infra/aws-poc/` | EKS proof-of-concept stack (VPC, EKS, edge, RDS, data, KMS, OIDC) |
| `infra/telemetry/` | Persistent S3, Glue, Athena, and the Roles Anywhere shipper. About 1 USD per month. |
| `k8s/aws-poc/` | Karpenter NodePool, ClusterSecretStore, Kyverno policy, and the sensor-exporter CronJob |
| `docs/aws-poc/` | 1 November 2026 gallery, cost record, and drill notes |
| `scripts/bootstrap-k3d.sh` | Local k3d bootstrap |
| `scripts/aws-poc.ps1` | `up`, `verify`, and `down` for a paid session |
| `docs/` | The [documentation site](docs/index.md), week notes, and the [capstone write-up](docs/CAPSTONE.md) |

## License

MIT © 2026 Cole Miller
