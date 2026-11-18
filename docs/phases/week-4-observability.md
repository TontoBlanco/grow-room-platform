# Week 4 — Observability and the live tent

I wanted the charts to show the tent, and I wanted the cluster tests to keep working when the tent was off.

## What I built

kube-prometheus-stack `92.13.1` in namespace `monitoring`. Retention is 24 hours. The scrape interval is 30 seconds. Replicas stay at one. That fits a laptop.

Two scrape jobs, described in [Architecture](../architecture.md) and panel by panel in the [Grafana guide](../grafana.md).

Three alert rules in `monitoring/alerts/grow-room-rules.yaml`:

| Alert | Condition |
| --- | --- |
| `GrowRoomSensorScrapeDown` | Simulator job down for 2 minutes |
| `GrowRoomHumidityOutOfRange` | Humidity under 30 or over 80 for 5 minutes |
| `GrowRoomSensorPodRestarts` | More than two restarts in 15 minutes |

The live controller work landed after the first monitoring merge:

- [PR #12](https://github.com/TontoBlanco/grow-room-platform/pull/12) exposed probe, controller VPD, and ports
- [PR #14](https://github.com/TontoBlanco/grow-room-platform/pull/14) put those series on the dashboard
- [PR #25](https://github.com/TontoBlanco/grow-room-platform/pull/25) added the host scrape
- [PR #29](https://github.com/TontoBlanco/grow-room-platform/pull/29) collapsed duplicate legends
- [PR #32](https://github.com/TontoBlanco/grow-room-platform/pull/32) made scrape-up one tile per job
- [PR #43](https://github.com/TontoBlanco/grow-room-platform/pull/43) added the plant-mood gauge

## Why

A ServiceMonitor can scrape the simulator, because that pod is a Kubernetes Service. It cannot see the controller. Those gauges appear only after Compose has read Home Assistant. I added a second job instead of pointing the simulator at my token.

## Data flow

```mermaid
flowchart LR
  ACI["AC Infinity AI+"] --> HA["Home Assistant :8123"]
  HA --> CS["Compose sensor-service :8000"]
  CS --> HOST["job grow-room-ha-host"]
  SIM["in-cluster simulator"] --> SM["ServiceMonitor"]
  SM --> PROM["Prometheus"]
  HOST --> PROM
  PROM --> GRAF["Grafana Grow-room VPD"]
```

## Rebuild

Home Assistant runs on the Raspberry Pi `berry` at `http://10.0.0.62:8123`. The PC Compose file does not start it. Copy the example env file and edit it outside Git. Set `SENSOR_SOURCE` to `homeassistant`. `HA_URL` in `.env.example` is already `http://10.0.0.62:8123`. Set `HA_TOKEN` to a long-lived token from the Pi. Leave the token out of the shell history if you can. The entity defaults in `.env.example` already match prefix `the_garden`.

The playbook, the nightly backup, and the rollback to profile `local-ha` are in [Phase 9](phase-9-pi-edge.md).

```powershell
Set-Location C:\src\grow-room-platform
```

```powershell
Copy-Item .env.example .env
```

Start sensor-service. Do not pass `--profile local-ha` while the Pi container is running.

```powershell
docker compose up --build sensor-service
```

In WSL2, with the k3d cluster from Week 3 already up:

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

The host job target is `host.k3d.internal:8000`. Compose must publish `8000:8000`, not `127.0.0.1:8000:8000`. The loopback bind is reachable from the host and not from the k3d gateway. If the target stays down, the comments in `monitoring/values-k3d.yaml` list the fallback addresses. Change the single target. Do not add a second `prometheus:` key or YAML will drop the block.

## Cost

This week is local. No AWS resources. The 24 hour retention is a disk choice on the laptop, not an S3 bill.

## What I learned

Two healthy scrapes can still make a bad dashboard. The first live panels mixed the simulator with the tent, and every old pod left a DOWN tile. The fix was labels plus `max by`, and a test so the queries do not drift.

The other lesson was the laptop lid. I spent time looking for a scrape bug that was just sleep. I wrote that down next to the dashboard so I would not chase it again. As of 18 November 2026, Home Assistant itself stays up on the Pi. The charts still go flat, because sensor-service and Prometheus are on the PC.

Docker Desktop has to be running before Compose, or sensor-service does not start. A 401 from Home Assistant is a bad or missing `HA_TOKEN`, or the onboarding page on the Pi. It is not a bad scrape query. More cases are on the [troubleshooting page](../troubleshooting.md).
