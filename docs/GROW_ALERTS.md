# Grow alerts

These are email alerts for problems the AC Infinity app does not already show on a phone. The app notifies you about basic temperature and humidity. None of the four alerts below repeat that.

Each alert has its own on/off switch. An off switch does not create the Kubernetes object for that alert. The chart defaults in `charts/grow-alerts/values.yaml` keep all four **off**. CI renders that file alone and expects an empty release. The k3d lab does not edit those defaults. It layers `charts/grow-alerts/values-k3d.yaml`, which turns probe drift on and leaves the other three off. Argo CD app `grow-alerts` loads both files, the same way the monitoring app loads `monitoring/values-k3d.yaml`, on context `k3d-grow-room-dev`, namespace `monitoring`.

| Alert | Switch | What it watches |
| --- | --- | --- |
| Stale shipper | `alerts.staleShipper.enabled` | No new object under `readings/` in `s3://grow-room-telemetry-590183769702` for 30 minutes |
| VPD out of band | `alerts.vpdOutOfBand.enabled` | A day whose VPD sat outside the stage band for more than 60% of samples |
| Certificate expiry | `alerts.certExpiry.enabled` | `shipper.pem` or `grafana-reader.pem` within 30 days of expiring |
| Probe drift | `alerts.probeDrift.enabled` | Calculated probe VPD and the controller's reported VPD differ by more than 0.15 kPa for 1 hour |

## How the mail is sent

The mail path is **Alertmanager email**, not the SNS topic `grow-room-poc-alerts`.

That topic belongs to the paid proof-of-concept stack. `down` deletes it. These alerts are about the home shipper, the probe, and the certificates, which matter on days that stack is gone. The Grafana reader role can query Athena and list `readings/`. It cannot publish to SNS, and this change does not add that permission.

On the laptop cluster, a firing alert shows up in the Alertmanager UI as soon as its switch is on. Mail leaves only after `delivery.email.enabled` is true and an SMTP secret exists. The secret is created on the machine. It is not committed.

On EKS, while a proof-of-concept session is up, the monitoring app already sends every firing alert to `grow-room-poc-alerts`. This chart does not add a second copy of that route.

`grafana.ini` is not part of this change. Grafana reads that ConfigMap only when the process starts. If a later sync changes it, restart Grafana. One command:

```powershell
kubectl -n monitoring rollout restart deploy/monitoring-grafana
```

## 1. Stale shipper

The home PC runs `scripts/ship_readings.py`. About every ten minutes it writes a JSON Lines object to `readings/dt=YYYY-MM-DD/` in the telemetry bucket. The shipper role can put objects. It cannot list them, so it cannot answer "when was the last upload?"

Prometheus does not have a series for that object time. `SensorDataStale` is the simulator scrape going quiet. That is a different failure. The AC Infinity app does not know the archive exists.

The check lists only two prefixes: today's `readings/dt=` and yesterday's. It does not list the whole bucket. If the newest object is 30 minutes old or older, or both prefixes are empty, Alertmanager gets `GrowShipperStale`.

The alert text says the shipper may have stopped, or the PC may be asleep. **PC sleep is a known lab limit.** The cluster and the shipper share the laptop. Closing the lid stops both. You get the mail after the laptop wakes, which is the only time it can send mail.

S3 LIST is about $0.005 per 1,000 requests. Each run is two requests unless a day prefix is longer than 1,000 keys. A day of uploads is about 144 objects.

The job runs every five minutes. It installs `boto3` into the pod and reads temporary credentials from the `grow-alerts-credentials` service. That service uses the same `grafana-athena-identity` secret as Grafana. Create that secret before turning this alert on. The steps are in [Athena in Grafana](ATHENA_GRAFANA.md).

## 2. VPD outside the stage band for most of a day

The stage bands are the ones in `sensor_service/stage.py`:

| Stage stored on the row | Band (kPa) |
| --- | --- |
| seedling, or clone | 0.4 to 0.8 |
| veg, or a blank stage | 0.8 to 1.2 |
| flower | 1.2 to 1.5 |
| late_flower | 1.4 to 1.6 |

Each sample uses the `stage` column on that row. That is the stage that was current when the shipper wrote it. A blank stage uses the veg band, same as the history board. The column the query reads is `vpd_kpa`, the leaf VPD the service calculated, and only rows with `source = 'homeassistant'`.

The app can alarm when the live number crosses a line. It does not score how much of a whole day sat outside the band. The default is more than 60 percent of the samples. Exactly 60 percent does not fire. A day with no samples does not fire either. That silence is the stale-shipper alert.

The query is yesterday only (one `dt` partition). `alerts.vpdOutOfBand.lookbackDays` may be 1 or 2. Any other value is rejected so a typo cannot scan a month. The predicate is `dt = 'YYYY-MM-DD'` or `dt IN ('YYYY-MM-DD', 'YYYY-MM-DD')`. It does not use `current_date` or an interval, so Athena can skip every other day.

Athena on-demand in `us-west-2` is $5 per TB scanned, with a 10 MB minimum per query. One day of `ship_readings.py` is a few hundred KB. The bill for this check is the 10 MB minimum, about $0.00005. The workgroup `grow-room-telemetry` cancels a query that would scan more than 1 GiB. The job log prints `DataScannedInBytes` and that estimate. The default schedule is 07:15 UTC, after yesterday is a finished day.

The same credential secret as the shipper check is required.

## 3. Certificate expiry

Two leaves live outside the repo, under `C:\src\grow-room-pki`:

| File | Configured notAfter | What it is |
| --- | --- | --- |
| `shipper.pem` | 2027-01-31 00:00 UTC | Roles Anywhere leaf for the home shipper. Subject CN `grow-room-home-shipper`. |
| `grafana-reader.pem` | 2029-02-05 00:00 UTC | Roles Anywhere leaf for Grafana Athena. Subject CN `grow-room-grafana-reader`. |

The chart stores those dates, not the files. A path is optional and empty in git. If you set a path, that file wins over the date. The check never prints the certificate or the key.

"Within 30 days" includes the 30th day and a certificate that is already expired. The app has no idea these files exist.

This job does not call AWS. You can point `--cert-path` at the PEM when you run the script on the PC. The cluster job uses the dates unless you set a path inside the pod, which means mounting a secret you create yourself.

To read the real timestamp:

```powershell
openssl x509 -enddate -noout -in C:\src\grow-room-pki\shipper.pem
```

```powershell
openssl x509 -enddate -noout -in C:\src\grow-room-pki\grafana-reader.pem
```

Replace the `notAfter` value in the chart if the hour is not midnight UTC. Do not commit the PEM or the key.

## 4. Probe drift

Sensor-service already exports the controller's reported VPD as `grow_controller_vpd_kpa`. It now also exports `grow_probe_calculated_vpd_kpa`: air VPD from the probe temperature and humidity, using the same formula as the rest of the service, with **no leaf-temperature offset**. The controller's own VPD is an air number. A leaf offset would look like a bad probe.

The Prometheus rule fires when the absolute difference stays above 0.15 kPa for 1 hour. Both series have to come from the Home Assistant scrape (`sensor_source="homeassistant"`), which is the `grow-room-ha-host` job. The in-cluster simulator does not export these series, so it cannot trip the rule.

The app shows the probe and the controller. It does not alarm when the two VPD numbers drift apart. That gap is the calibration signal.

No CronJob and no AWS call. Turning the switch on renders one `PrometheusRule` and nothing else.

The live series comes from the Docker Compose sensor-service on port 8000, which Prometheus scrapes as `grow-room-ha-host`. Rebuild that container after this change so the new gauge is actually exported:

```powershell
docker compose up -d --build sensor-service
```

## Turn one alert on

Leave `charts/grow-alerts/values.yaml` all off. That file is the chart default, and CI fails if any switch there is true. The lab switches are in `charts/grow-alerts/values-k3d.yaml`. Probe drift is already true there. To turn another alert on, set that alert's `enabled` flag in the overlay and leave the others false.

Argo CD will put a live-only change back. Commit the overlay and let the `grow-alerts` app sync.

From `C:\src\grow-room-platform`:

```powershell
Set-Location C:\src\grow-room-platform
```

```powershell
kubectl config use-context k3d-grow-room-dev
```

```powershell
Set-Content -Encoding ascii -Path "$env:TEMP\grow-alerts-refresh.json" -Value '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
```

```powershell
kubectl -n argocd patch application grow-alerts --type merge --patch-file "$env:TEMP\grow-alerts-refresh.json"
```

Render the same two files the app uses. The k3d overlay should show one `PrometheusRule` named `grow-probe-drift` and no CronJob:

```powershell
helm template grow-alerts charts/grow-alerts -n monitoring -f charts/grow-alerts/values.yaml -f charts/grow-alerts/values-k3d.yaml
```

A one-shot install uses those files too. Argo will revert it on the next sync if git differs:

```powershell
helm upgrade --install grow-alerts charts/grow-alerts -n monitoring --create-namespace -f charts/grow-alerts/values.yaml -f charts/grow-alerts/values-k3d.yaml
```

The shipper and VPD jobs need secret `grafana-athena-identity` in namespace `monitoring` before they can succeed. The certificate job does not.

## Confirm GrowProbeDrift is loaded

After the `grow-alerts` app is Synced, Prometheus should list the rule even when it is not firing. Leave the port-forward open:

```powershell
kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090
```

In a second window:

```powershell
$rules = Invoke-RestMethod -Uri "http://127.0.0.1:9090/api/v1/rules?type=alert"; $rules.data.groups.rules | Where-Object name -eq GrowProbeDrift | Select-Object name, state, query
```

The UI for the same list is [http://127.0.0.1:9090/alerts](http://127.0.0.1:9090/alerts). `GrowProbeDrift` is loaded when it appears there. `inactive` means the rule is loaded and the difference is not over 0.15 kPa right now. The series exists only after the Compose sensor-service is rebuilt, because that process exports `grow_probe_calculated_vpd_kpa`.

## Turn mail on

Create the SMTP secret on the cluster. The password stays in that secret.

```powershell
kubectl -n monitoring create secret generic grow-alerts-smtp --from-literal=password="replace-me"
```

Then set these in `charts/grow-alerts/values-k3d.yaml` and sync the `grow-alerts` app the same way as a toggle. Leave the chart defaults in `values.yaml` alone:

```yaml
delivery:
  email:
    enabled: true
    to: you@example.com
    from: grow-alerts@example.com
    smarthost: smtp.example.com:587
    authUsername: you@example.com
    existingSecret: grow-alerts-smtp
    secretKey: password
```

`smarthost` is `host:port`. `requireTLS` is on. The password key is `password`. Rendering with email enabled and any of those fields empty fails the template, so a half-finished switch does not install a broken receiver.

## Send a test alert

Start the port-forward and leave it open:

```powershell
kubectl -n monitoring port-forward svc/monitoring-alertmanager 9093:9093
```

In a second window, write the payload and post it. The labels match the email route (`grow_alert=true` and `namespace=monitoring`).

```powershell
Set-Content -Encoding ascii -Path "$env:TEMP\grow-alert-test.json" -Value '[{"labels":{"alertname":"GrowAlertsTest","severity":"warning","grow_alert":"true","namespace":"monitoring","room":"grow-room"},"annotations":{"summary":"Test grow alert","description":"Sent by hand to check Alertmanager."}}]'
```

```powershell
curl.exe -sS -X POST "http://127.0.0.1:9093/api/v2/alerts" -H "Content-Type: application/json" --data-binary "@$env:TEMP\grow-alert-test.json"
```

Open Alertmanager at `http://127.0.0.1:9093`. `GrowAlertsTest` should be firing. Mail arrives only after the email switch and the secret are in place. Without them the UI is still the check that the route received it.

## Run a check on the PC

Profile `GrowRoom`, region `us-west-2`. These dry runs do not query AWS and do not post.

```powershell
$env:AWS_PROFILE = "GrowRoom"
```

```powershell
$env:AWS_REGION = "us-west-2"
```

```powershell
$env:AWS_DEFAULT_REGION = "us-west-2"
```

```powershell
python scripts/grow_alerts.py vpd-day --dry-run --lookback-days 1
```

```powershell
python scripts/grow_alerts.py certs --dry-run
```

```powershell
python scripts/grow_alerts.py shipper --dry-run
```

A real VPD or shipper run needs `boto3` (`pip install boto3`) and the port-forward above. Drop `--dry-run` and add the Alertmanager URL:

```powershell
python scripts/grow_alerts.py vpd-day --lookback-days 1 --alertmanager-url "http://127.0.0.1:9093"
```

The job log line is the scan size. A one-day query should say it scanned a few hundred KB and billed the 10 MB minimum.

To compare a certificate file instead of the configured date:

```powershell
python scripts/grow_alerts.py certs --dry-run --cert "shipper=2027-01-31T00:00:00Z" --cert-path "shipper=C:\src\grow-room-pki\shipper.pem"
```

## What stays out of git

`*.pem` and `*.key` are gitignored. The chart's certificate entries are dates and empty paths. Do not commit `shipper.pem`, `grafana-reader.pem`, a private key, or the SMTP password.
