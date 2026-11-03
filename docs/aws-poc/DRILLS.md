# PoC failure drills

Run these only while `grow-room-poc` is up (`scripts/aws-poc.ps1 up` / `verify`).
Cluster `grow-room-poc`, region `us-west-2`, app `https://app.mygrowroom.click/healthz`.

Keep this loop in a second PowerShell window for every drill:

```powershell
$end = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $end) {
  $c = curl.exe -s -o NUL -m 5 -w "%{http_code}" https://app.mygrowroom.click/healthz
  "{0:HH:mm:ss}  {1}" -f (Get-Date), $c
  Start-Sleep -Seconds 1
}
```

The November 3, 2026 session saw one `502` each on drill 1 and drill 2. The chart
now keeps the pod process up longer than the ALB deregistration delay
(`preStop` 30s, `terminationGracePeriodSeconds` 45,
`deregistration_delay.timeout_seconds=20`) and adds a PodDisruptionBudget
(`minAvailable: 2` on the 3 replicas). The next session should see only `200`s
on those two drills.

## Drill 1 - delete a pod

Expect: curl loop stays `200`. A replacement pod is `Running` in about 20s.
The deleted pod stays `Terminating` for about 30s while the preStop sleep runs.
That wait is the ALB drain, not a stuck pod.

```powershell
kubectl -n grow-room get pods -o wide
$pod = kubectl -n grow-room get pods -l app.kubernetes.io/name=sensor-service -o jsonpath="{.items[0].metadata.name}"
kubectl -n grow-room delete pod $pod
kubectl -n grow-room get pods -w
```

## Drill 2 - drain a node

Expect: the pod on that node moves, curl stays `200`. The PDB allows one
disruption. Karpenter may add a node. Uncordon when you are done.

```powershell
$node = kubectl -n grow-room get pod -l app.kubernetes.io/name=sensor-service -o jsonpath="{.items[0].spec.nodeName}"
kubectl drain $node --ignore-daemonsets --delete-emptydir-data --timeout=5m
kubectl -n grow-room get pods -o wide
kubectl uncordon $node
```

## Drill 3 - RDS Multi-AZ failover

Expect: `/audit/batches` errors for about 60-120s, then recovery. Primary and
standby AZs swap. `/healthz` can stay `200` through this; it does not use RDS.

```powershell
aws rds describe-db-instances --db-instance-identifier grow-room-poc-audit --query "DBInstances[0].{Primary:AvailabilityZone,Standby:SecondaryAvailabilityZone}"
aws rds reboot-db-instance --db-instance-identifier grow-room-poc-audit --force-failover --query "DBInstance.DBInstanceStatus"
aws rds describe-events --source-identifier grow-room-poc-audit --source-type db-instance --duration 30 --query "Events[].{t:Date,m:Message}"
aws rds describe-db-instances --db-instance-identifier grow-room-poc-audit --query "DBInstances[0].{Primary:AvailabilityZone,Standby:SecondaryAvailabilityZone}"
```

## Drill 4 - pause Argo auto-sync and scale to 0

Argo self-heal would undo a manual scale. Pause auto-sync first.

```powershell
Set-Content -Encoding ascii nosync.json '{"spec":{"syncPolicy":{"automated":null}}}'
kubectl -n argocd patch application sensor-service --type merge --patch-file nosync.json
kubectl -n grow-room scale deployment sensor-service --replicas=0
```

### What actually fires

The November 3 session expected a `SensorAvailabilityBudgetBurnFast` email in
about 5-8 minutes. `SensorDataStale` fired first. BurnFast takes longer, and
it may not fire during a short drill.

| Alert | When it fires | Email |
| --- | --- | --- |
| `SensorDataStale` (warning) | Freshness crosses 120s about 2 min after scrapes stop, then `for: 5m`. Fires about **7 min** after the scale. | `[grow-room] FIRING SensorDataStale` about 30s later (`group_wait`). **This is the email to screenshot.** |
| `SensorAvailabilityBudgetBurnFast` (critical) | Both the 5m and the 1h availability windows must be worse than 14.4x the 1% budget, then `for: 2m`. The 1h window needs about **8.6 min of `up=0`**, so the alert is about **11 min** after the scale, not 5-8. | Separate email, later, only if `up` is actually 0. |
| `GrowRoomSensorScrapeDown` | `up{job="sensor-service"} == 0` for 2 min. | Only if the target stays and reports 0. |

With zero ready endpoints Prometheus often **drops** the target instead of
storing `up=0`. Then `GrowRoomSensorScrapeDown` does not fire, and BurnFast
does not either, because `avg_over_time(up[1h])` never sees a zero. `SensorDataStale`
still fires: `slo:sensor_freshness_seconds > 120` or `absent(grow_vpd_kpa)`.

Do not treat a missing BurnFast email at minute 8 as a failed drill.

### Restore

```powershell
Set-Content -Encoding ascii sync.json '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
kubectl -n argocd patch application sensor-service --type merge --patch-file sync.json
```

Argo scales back to 3 within about a minute.

- `SensorDataStale` resolves within a few minutes of fresh `grow_vpd_kpa`
  samples. Expect `[grow-room] RESOLVED SensorDataStale`.
- BurnFast, if it fired, stays firing until the bad samples leave the **1h**
  window (on the order of an hour after the outage started). Do not wait on
  that RESOLVED email before `scripts/aws-poc.ps1 down`.

Rules: `monitoring/manifests/grow-room-slo-rules.yaml`. Alertmanager
`group_wait` is 30s in `monitoring/values-eks.yaml`.
