# Week 4: Prometheus + Grafana Observability on k3d

Goal: make the grow-room sensor service **observable** the same way production
platforms do — scrape metrics into Prometheus, graph them in Grafana, page on
symptoms with Alertmanager, and write two short SLOs you can defend in an
interview.

By the end of the week you have:

1. **kube-prometheus-stack** installed via an Argo CD Application (Helm + values
   from Git) into namespace `monitoring`.
2. A **ServiceMonitor** so Prometheus scrapes `sensor-service` `/metrics`.
3. A **Grafana VPD dashboard** (temp, humidity, computed VPD, scrape health, and
   Home Assistant controller / probe / port panels when those series exist).
4. **PrometheusRules** for humidity out of range, scrape down, and pod restarts.
5. **Two SLOs** (ingest availability, data freshness) + one runbook.
6. Still **$0** cloud — same k3d cluster `grow-room-dev` from Week 3.

You already know Deployments, Services, and Argo sync. This week adds the
monitoring *control plane* that watches those objects. The sensor chart already
exposes Prometheus gauges (`grow_temperature_celsius`, `grow_humidity_percent`,
`grow_vpd_kpa`, `grow_co2_ppm`) and carries `prometheus.io/*` pod annotations —
Week 4 wires the scraper and the UI. With `SENSOR_SOURCE=homeassistant` the
scrape can also include `grow_probe_temperature_celsius`,
`grow_probe_humidity_percent`, `grow_probe_vpd_kpa`, `grow_controller_vpd_kpa`
(device VPD converted to kPa), `grow_controller_status`,
`grow_port_current_power`, and `grow_port_status` (label `device`). The
simulator does not export that second set.

Try each step on the cluster before treating the Definition of Done as checked.

---

## Step 0: Copy the starter into your repo

From the unzipped week-4 pack:

```bash
# From your grow-room-platform clone root
cp -r path/to/grow-room-platform-week4/monitoring ./
cp path/to/grow-room-platform-week4/gitops/apps/monitoring.yaml ./gitops/apps/
# Merge monitoring.yaml into gitops/apps/kustomization.yaml resources:
#   - monitoring.yaml
cp path/to/grow-room-platform-week4/docs/WEEK4_OBSERVABILITY_GUIDE.md ./docs/
cp path/to/grow-room-platform-week4/docs/WEEK4_CI_NOTE.md ./docs/
# Optionally paste README_WEEK4_SNIPPET.md into README.md roadmap
```

Use the pack file `gitops/apps/kustomization.snippet.yaml` as the target shape
for `gitops/apps/kustomization.yaml`.

Create a branch:

```bash
git checkout -b observability-week4
```

Sanity-check files **before** any sync:

```bash
# JSON dashboard
jq empty monitoring/dashboards/grow-room-vpd.json

# Manifests parse as YAML (kubectl client-side)
kubectl apply --dry-run=client -f monitoring/manifests/

# Optional: render the upstream chart with your values (large output)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm template monitoring prometheus-community/kube-prometheus-stack \
  --version 92.13.1 \
  -f monitoring/values-k3d.yaml \
  -n monitoring >/tmp/monitoring-rendered.yaml
wc -l /tmp/monitoring-rendered.yaml
```

Commit and **push** `monitoring/`, `gitops/apps/monitoring.yaml`, the updated
kustomization, and docs. Argo CD pulls from **GitHub**, not from Downloads —
same lesson as Weeks 2–3.

---

## Step 1: Mental model (for Kubernetes YAML folks)

| Observability idea | What it is | Kubernetes analogy you already know |
|---|---|---|
| `/metrics` on the app | Text exposition of gauges/counters | A read-only API like `/healthz`, but for numbers |
| `prometheus.io/scrape` annotations | Hints on Pods (optional in operator world) | Labels that *document* intent; not always enforced |
| **ServiceMonitor** / PodMonitor | CR: "scrape these Endpoints this way" | Ingress / NetworkPolicy — a CR that selects Services |
| Prometheus Operator | Controller that turns Monitors → scrape config | Deployment controller, but for scrape jobs |
| Prometheus | Time-series DB + scraper + rule evaluator | etcd for metrics (with a HTTP query API) |
| PromQL | Query language over time series | `kubectl get` + jsonpath, but across time |
| Grafana | Dashboards / Explore UI on PromQL | Kubernetes Dashboard — visualization, not source of truth |
| Alertmanager | Routes firing alerts to receivers | A Service in front of notification backends |
| PrometheusRule | CR: recording + alerting rules | ValidatingWebhook config — declarative policy-as-YAML |
| Recording rule | Precompute a PromQL expression | A CronJob that writes a derived ConfigMap (conceptually) |
| Alerting rule | Condition → alert that Alertmanager routes | A probe that pages instead of restarting |
| SLO | Target reliability for a user-facing indicator | PodDisruptionBudget — a contract, not a controller |
| Error budget | Allowed unreliability from the SLO | Disruption budget remaining |
| kube-prometheus-stack | Helm umbrella: operator + Prometheus + Grafana + Alertmanager + node-exporter + kube-state-metrics | App-of-apps style chart for the monitoring plane |

```text
sensor-service Pod  ──/metrics──►  Service (grow-room)
                                      │
                                      ▼
                              ServiceMonitor (monitoring ns)
                                      │
                                      ▼
                           Prometheus Operator reconcile
                                      │
                                      ▼
                              Prometheus scrape + store
                          ┌───────────┴───────────┐
                          ▼                       ▼
                       Grafana                 Alertmanager
                    (dashboards)              (routes/pages)
                          ▲
                          │
              ConfigMap grafana_dashboard=1
```

### Annotations vs ServiceMonitor (important)

Week 3 put these on the Pod template:

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/metrics"
```

The **old** standalone Prometheus Helm chart could scrape those annotations
via kubernetes_sd + relabel. **kube-prometheus-stack** (operator-based) prefers
**ServiceMonitor** / **PodMonitor** CRs. Annotations alone will **not** make
targets appear unless you add `additionalScrapeConfigs` (commented example in
`monitoring/values-k3d.yaml`).

This pack ships a ServiceMonitor. Keep the annotations anyway — they document
intent and help other tools.

### Key differences from "just kubectl port-forward and curl"

- **Scrapes are continuous.** Prometheus pulls every `scrapeInterval` (30s here).
  A one-off `curl /metrics` proves the app; it does not prove the pipeline.
- **Labels become dimensions.** `job`, `namespace`, `pod` turn one gauge into
  many series — like label selectors on Pods.
- **Alerts are desired state too.** A PrometheusRule in Git is GitOps for
  paging, same as a Deployment in Git is GitOps for compute.
- **Grafana is not the source of truth.** Dashboards can live in Git (this pack)
  so they survive a cluster wipe — like ConfigMaps vs "I clicked Save in the UI."

### Build it incrementally

1. Copy files; dry-run manifests; optional `helm template` (Step 0).
2. Merge Application + kustomization; push; wait for Argo sync (Steps 2–3).
3. Confirm Prometheus targets include sensor-service (Step 4).
4. Open Grafana; confirm VPD dashboard (Step 5).
5. Fire a test alert (Step 6).
6. Write / review SLOs + runbook (Step 7).
7. Definition of done (Step 8).

---

## Step 2: What Argo is syncing

| File | Role |
|------|------|
| `gitops/apps/monitoring.yaml` | Argo Application (multi-source Helm + manifests) |
| `monitoring/values-k3d.yaml` | Helm values for kube-prometheus-stack on small k3d |
| `monitoring/manifests/sensor-servicemonitor.yaml` | Scrape grow-room Service |
| `monitoring/manifests/grow-room-prometheusrule.yaml` | Alert rules |
| `monitoring/manifests/grafana-dashboard-grow-room-vpd.yaml` | Dashboard ConfigMap for Grafana sidecar |
| `monitoring/dashboards/grow-room-vpd.json` | Same dashboard as raw JSON (import / review). Keep it identical to the ConfigMap |
| `monitoring/alerts/grow-room-rules.yaml` | Human-readable copy of the rule CR |
| `monitoring/docs-slo.md` | Two SLOs + scrape-down runbook |

### Multi-source Application (new vs Week 3)

Week 3's `sensor-service` Application pointed at **one** Git path (the Helm
chart in-repo). Monitoring uses **three sources**:

1. **Upstream Helm repo** — `prometheus-community/kube-prometheus-stack` pinned
   to `92.13.1`.
2. **`$values` ref** — same GitHub repo; supplies
   `monitoring/values-k3d.yaml` without vendoring the whole chart.
3. **`monitoring/manifests`** — plain YAML (ServiceMonitor, PrometheusRule,
   dashboard ConfigMap) applied into namespace `monitoring`.

Analogy: source 1 is installing Traefik from a chart repo; source 2 is your
`values-prod.yaml` in Git; source 3 is a couple of Ingress objects you own.

Edit `repoURL` if your fork path differs.

### App-of-apps hookup

`grow-room-root` already syncs everything under `gitops/apps/`. After you add
`monitoring.yaml` (and list it in `kustomization.yaml` for manual `-k` boots),
the root Application should create a child named `monitoring`.

```bash
kubectl -n argocd get applications
# expect: grow-room-root, sensor-service, monitoring
```

---

## Step 3: Sync and wait (first install is chunky)

First sync installs CRDs + operator + Prometheus + Grafana + Alertmanager +
node-exporter + kube-state-metrics. On a laptop this can take **several
minutes** and a few refresh cycles.

```bash
# After push — hard refresh root if the child does not appear
kubectl -n argocd annotate application grow-room-root \
  argocd.argoproj.io/refresh=hard --overwrite

kubectl -n argocd get applications
kubectl -n monitoring get pods
```

`ServerSideApply=true` is set on the Application because CRDs are large (avoids
annotation-size pain). If sync fails on CRDs once, Refresh + Sync again — the
operator pattern often needs CRDs before CRs.

**Windows / WSL:** prefer running `kubectl` / `helm` from **WSL2** against the
same Docker Desktop engine you used for k3d. If RAM is tight (Prometheus OOM),
lower `prometheus.prometheusSpec.resources` further in `values-k3d.yaml` or
stop other Docker workloads.

Tear-down later (optional): delete the Application (cascade) or
`k3d cluster delete grow-room-dev` for a full lab reset.

---

## Step 4: Verify Prometheus scrapes sensor-service

### 4a. Workloads up

```bash
kubectl -n monitoring get deploy,sts,pods
kubectl -n monitoring get servicemonitor,prometheusrule
kubectl -n grow-room get pods,svc
```

### 4b. Metrics still work on the app

```bash
kubectl -n grow-room port-forward svc/sensor-service 8000:8000
# other terminal
curl -sS http://127.0.0.1:8000/metrics | grep grow_
```

You should see `grow_temperature_celsius`, `grow_humidity_percent`,
`grow_vpd_kpa`, and friends (gauges refresh on each `/metrics` hit).

### 4c. Targets UI

```bash
kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090
```

Open `http://127.0.0.1:9090/targets`. Find a target related to
`sensor-service` / ServiceMonitor `monitoring/sensor-service`. State should be
**UP**.

PromQL smoke:

```promql
up{job="sensor-service"}
grow_vpd_kpa
grow_humidity_percent
```

After a Home Assistant sample has been scraped, these series exist too (they
are absent on the simulator):

```promql
grow_probe_temperature_celsius
grow_probe_humidity_percent
grow_probe_vpd_kpa
grow_controller_vpd_kpa
grow_controller_status
grow_port_current_power
grow_port_status
```

If `job` label differs slightly, use the Targets page label set — operator
versions sometimes prefix names. Adjust alert expressions to match. The
dashboard queries the `grow_*` gauges without a `job` filter, so a prefixed
job name still matches the climate panels.

### 4d. If the target is missing

| Check | Command / action |
|-------|------------------|
| ServiceMonitor exists | `kubectl -n monitoring get servicemonitor sensor-service -o yaml` |
| Service labels match selector | `kubectl -n grow-room get svc --show-labels` |
| Prometheus picks all ServiceMonitors | `serviceMonitorSelectorNilUsesHelmValues: false` in values |
| App serving on port `http` | Service port name must be `http` (Week 3 chart) |

---

## Step 5: Grafana VPD dashboard

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

Login (lab defaults from values):

- User: `admin`
- Password: `grow-room-lab` (change if you expose beyond localhost)

Open **Dashboards** → **Grow-room VPD** (uid `grow-room-vpd`). The sidecar loads
ConfigMaps labeled `grafana_dashboard=1`. The top of the board is unchanged:
temperature, humidity, computed leaf VPD (`grow_vpd_kpa`), scrape health, and
CO₂ (CO₂ may be empty if the sensor leaves it unset).

Further down:

- **Controller air and probe canopy** — controller status and device VPD, probe
  canopy temp / RH / VPD, and charts that compare controller air
  (`grow_temperature_celsius`, `grow_humidity_percent`) with the probe series.
- **UIS ports** — `grow_port_status` and `grow_port_current_power`, one series
  per `device` label (for example `port_1`, `humidifier`). Power is the level
  the UIS device reports.

Those Home Assistant gauges are created on the first real sample. On the
simulator the new panels say **No HA sample**. That empty state is expected
until Prometheus has scraped `SENSOR_SOURCE=homeassistant`.

### Reload after the dashboard JSON changes

Argo applies `monitoring/manifests/` from the revision it tracks (usually
`main`). Once this ConfigMap is in that revision, sync (or let auto-sync run),
then confirm the live object mentions a probe gauge:

```bash
kubectl -n monitoring get cm grafana-dashboard-grow-room-vpd \
  -o jsonpath='{.data.grow-room-vpd\.json}' | grep -o grow_probe_temperature_celsius | head
```

The sidecar writes the JSON into Grafana's provisioning directory and calls
the dashboard reload API. Refresh the **Grow-room VPD** tab. If the old seven
panels are still all you see:

```bash
kubectl apply -f monitoring/manifests/grafana-dashboard-grow-room-vpd.yaml
kubectl -n monitoring rollout restart deploy/monitoring-grafana
kubectl -n monitoring rollout status deploy/monitoring-grafana
```

`kubectl apply` from a branch Argo is not tracking will stick only until the
next self-heal. For a preview before merge, use the import path below.

**Manual import:** Dashboards → New → Import → upload
`monitoring/dashboards/grow-room-vpd.json`. Choose the Prometheus datasource
and overwrite uid `grow-room-vpd` when Grafana asks. Prefer the ConfigMap once
Git has the change, so the next sidecar reload does not put the old board back.

The JSON datasource uid is `prometheus`, the same uid the original VPD panels
use. Point the import at that Prometheus datasource if Grafana asks.

---

## Step 6: Fire a test alert

### Path A — scrape down (simplest critical path)

Scale the sensor to zero briefly:

```bash
kubectl -n grow-room scale deploy/sensor-service --replicas=0
# wait ~2+ minutes for GrowRoomSensorScrapeDown (for: 2m)
```

Watch Alertmanager / Prometheus **Alerts**:

```bash
kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093
# UI: http://127.0.0.1:9093
# Prometheus Alerts: http://127.0.0.1:9090/alerts
```

Restore:

```bash
kubectl -n grow-room scale deploy/sensor-service --replicas=1
# Argo self-heal may also restore replicas if it owns the Deployment —
# if scale fights you, pause auto-sync on sensor-service for the test or
# delete the pod instead and hold it with an image pull failure, etc.
```

**Note:** With Argo `selfHeal: true`, a manual `kubectl scale` may be reverted.
For a clean test either:

- Temporarily disable auto-sync on `sensor-service`, or
- Break scrapes another way (wrong ServiceMonitor path) and fix it, or
- Use the humidity alert with a temporary PromQL tweak.

### Path B — humidity out of range

In Prometheus **Graph**, confirm `grow_humidity_percent`. The simulator usually
stays inside 30–80. To test the rule without faking sensors, temporarily widen
the expression in Git (e.g. `> 0`) on a branch, sync, see it fire, then revert.
That exercises the **GitOps alert loop** — preferred for a portfolio story.

### Path C — pod restarts

```bash
kubectl -n grow-room delete pod -l app.kubernetes.io/name=sensor-service
# repeat a few times within 15m to exceed increase(...[15m]) > 2
```

---

## Step 7: SLOs and the runbook

Read and optionally tweak `monitoring/docs-slo.md`. Copy or link it from your
main docs if you want it visible in the README.

**SLO 1 — Ingest availability:** 99% of scrapes succeed over 7d  
(`avg_over_time(up{job="sensor-service"}[7d])`).

**SLO 2 — Data freshness:** gauges not older than ~2 minutes for 99% of
samples (`time() - timestamp(grow_vpd_kpa)`).

**Runbook:** `GrowRoomSensorScrapeDown` — Pod → curl `/metrics` → ServiceMonitor
→ Prometheus `/targets` → Argo health. Practice once while the test alert fires.

Interview framing: SLOs are product/platform contracts; alerts are symptoms;
runbooks are how humans close the loop. You do not need a full SRE team to
write two honest SLOs for one service.

---

## Step 8: Cost — stay at $0

| Path | Cost |
|------|------|
| k3d + kube-prometheus-stack on your PC | **$0** |
| Public GHCR pulls | **$0** |
| Managed Prometheus / Grafana Cloud | Real money — not this week |
| EKS + scrape agents | Real money — Budgets first (Week 2) |

Do not point this Application at EKS until you deliberately accept cloud cost.

---

## Step 9: Definition of done (Week 4)

- [ ] `monitoring/` + `gitops/apps/monitoring.yaml` merged to GitHub
- [ ] `gitops/apps/kustomization.yaml` lists `monitoring.yaml`
- [ ] Argo Application `monitoring` is Synced / Healthy (or progressing then Healthy)
- [ ] Prometheus `/targets` shows sensor-service **UP**
- [ ] Grafana shows **Grow-room VPD** with live temp / humidity / VPD (probe and port panels fill in after a Home Assistant scrape)
- [ ] At least one alert proven to fire and resolve (scrape down or humidity test)
- [ ] Two SLOs + scrape-down runbook reviewed (`monitoring/docs-slo.md`)
- [ ] README roadmap Week 4 checkbox updated
- [ ] Still **$0** AWS for this week
- [ ] Notes / study log updated (what you wired and why)

Week 5 is hardening, docs polish, and Terraform Associate prep.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Child `monitoring` never appears | YAML not on Git revision / not under `gitops/apps/` | Push; hard-refresh `grow-room-root` |
| Sync fail on CRDs | First install race / annotation size | Re-sync; keep `ServerSideApply=true` |
| ServiceMonitor/PrometheusRule "no matches for kind" | CRDs not ready yet | Wait for operator; Refresh/Sync again (manifests use sync-wave 5) |
| Prometheus OOMKilled | Laptop RAM | Lower memory limits; disable defaultDashboards; reduce retention |
| No sensor target | ServiceMonitor selector / namespace | Compare labels; confirm `serviceMonitorSelectorNilUsesHelmValues: false` |
| Target DOWN | Pod not Ready / wrong port name | `kubectl -n grow-room get endpoints`; port must be named `http` |
| Dashboard missing in Grafana | ConfigMap label / sidecar | Label `grafana_dashboard=1`; check sidecar logs; import JSON manually |
| Dashboard still shows only the original panels | ConfigMap on the cluster is the old revision, or Grafana has not reloaded it | `grep grow_probe_temperature_celsius` on the ConfigMap (Step 5). Restart `deploy/monitoring-grafana`, or import `monitoring/dashboards/grow-room-vpd.json` over uid `grow-room-vpd` |
| Probe / port panels say "No HA sample" | Simulator, or Prometheus has not scraped an HA sample yet | `SENSOR_SOURCE=homeassistant`, then confirm the `grow_probe_*` / `grow_port_*` series in Prometheus. Empty is expected before that |
| Alerts never fire | Wrong `job` label / `for:` not elapsed | Match labels from `/targets`; wait out `for:` |
| Scale test snapped back | Argo self-heal | Pause sync or test via PromQL/Git change |
| `helm template` huge / slow | Expected for this chart | Redirect to a file; do not commit rendered YAML |
| WSL cannot reach port-forward | Forward ran in wrong environment | Run kubectl port-forward in the same WSL distro that owns the kubeconfig |

---

## Interview talking points (mid-level DevOps)

1. **Operator vs annotations:** "Annotations are hints; with
   kube-prometheus-stack I ship a ServiceMonitor so the operator owns scrape
   config — same idea as Ingress vs hand-edited nginx.conf."
2. **GitOps for alerts:** "PrometheusRule lives in Git next to the app.
   Changing a threshold is a PR, not an SSH to Prometheus."
3. **SLOs vs alerts:** "SLOs define enough reliability; alerts are symptoms that
   burn budget. I wrote ingest availability and freshness for a sensor API."
4. **Honest boundary:** "I operate delivery-side Helm/Argo at work. This
   portfolio is where I own metrics → dashboards → alerts on a cluster I
   control, at zero cloud cost."

Avoid claiming you ran enterprise Observability platforms or on-call for this
lab unless you actually did.

---

## Extra credit

- Add AlertmanagerConfig (or Helm values receivers) to send a test webhook to a
  Slack incoming webhook — still optional; not required for DoD.
- Recording rules for `grow:vpd:avg5m` to show mixin-style hygiene.
- NetworkPolicy limiting scrape egress/ingress once you harden in Week 5.
- Second ServiceMonitor for a future watering / irrigation service.

---

## Runbook anchor — sensor scrape down

<a id="runbook-sensor-scrape-down"></a>

See the full checklist in [`monitoring/docs-slo.md`](../monitoring/docs-slo.md).
Short form: Pod Ready → curl `/metrics` → ServiceMonitor → `/targets` → Argo.
