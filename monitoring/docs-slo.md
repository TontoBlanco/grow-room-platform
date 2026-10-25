# Grow-room sensor SLOs + runbook (Week 4)

Keep these short enough to say in an interview. Numbers are **lab starting
points** for a single simulator-backed service on k3d — retune when real
sensors and multi-room scale land.

## SLO 1 — Ingest availability

**Statement:** 99% of Prometheus scrape attempts against `sensor-service`
succeed over a rolling 7-day window.

| Piece | Choice |
|-------|--------|
| Indicator | `avg_over_time(up{job="sensor-service"}[7d])` |
| Target | ≥ 0.99 |
| Window | 7 days rolling |
| Error budget | 1% ≈ 1.68 hours down / week |

**Why this SLO:** If scrapes fail, Grafana goes stale and humidity/VPD alerts
cannot fire. Availability of *telemetry ingest* is the platform concern;
plant outcomes are a product concern on top.

**Rough PromQL for a burn view (1h):**

```promql
avg_over_time(up{job="sensor-service"}[1h])
```

## SLO 2 — Data freshness

**Statement:** 99% of successful scrapes observe sensor gauges that were
refreshed within the last 2 minutes (scrape interval 30s × small slack).

| Piece | Choice |
|-------|--------|
| Indicator | Time since last successful scrape / sample |
| Proxy on Prometheus | `time() - timestamp(grow_vpd_kpa)` (when series exists) |
| Target | Freshness ≤ 120s for ≥ 99% of evaluation samples over 7d |
| Window | 7 days rolling |

**Why this SLO:** A green `up` with frozen gauges (stuck process, bad lock,
simulator hung) still leaves growers blind. Freshness catches “alive but
stale.”

**PromQL sketch:**

```promql
(time() - timestamp(grow_vpd_kpa)) > 120
```

Alert when that is true for several minutes (see scrape-down / freshness
notes in the main guide).

## Runbook — GrowRoomSensorScrapeDown

**Symptom:** Alert `GrowRoomSensorScrapeDown` firing; Grafana VPD panels empty
or `up{job="sensor-service"} == 0`.

**Impact:** No live climate metrics; humidity/VPD alerts unreliable; SLO 1
burning error budget.

**Checks (in order):**

1. Pod Ready?
   ```bash
   kubectl -n grow-room get pods,svc
   kubectl -n grow-room describe pod -l app.kubernetes.io/name=sensor-service
   ```
2. Metrics endpoint locally?
   ```bash
   kubectl -n grow-room port-forward svc/sensor-service 8000:8000
   curl -sS http://127.0.0.1:8000/healthz
   curl -sS http://127.0.0.1:8000/metrics | head
   ```
3. ServiceMonitor present and selecting the Service?
   ```bash
   kubectl -n monitoring get servicemonitor sensor-service -o yaml
   kubectl -n grow-room get svc -l app.kubernetes.io/name=sensor-service --show-labels
   ```
4. Prometheus targets UI: port-forward Prometheus; open `/targets`; find
   `serviceMonitor/monitoring/sensor-service` (name may vary slightly).
5. Argo: is `monitoring` Synced/Healthy? Did a values change drop selectors?

**Mitigations:**

- Fix CrashLoop / ImagePull first (no scrape until Ready).
- If target missing: fix ServiceMonitor labels / `namespaceSelector`.
- If target down: app bug or NetworkPolicy — check logs and endpoints.
- After fix: confirm `up == 1` and silence/resolve the alert.

**Escalate when:** Repeated scrapes fail after Pod is Ready and ServiceMonitor
looks correct — likely cluster DNS/network or Prometheus Operator config;
capture `/targets` screenshot + `kubectl -n monitoring logs` from prometheus.
