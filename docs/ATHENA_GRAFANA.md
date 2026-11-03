# Athena history in local Grafana

Local Grafana is the Grafana from kube-prometheus-stack in the k3d cluster
`grow-room-dev`, release `monitoring`, namespace `monitoring`. Docker Compose
does not run Grafana. `docker-compose.yml` is sensor-service and Home Assistant
only. The values file is `monitoring/values-k3d.yaml` (chart
`kube-prometheus-stack` `92.13.1`, Grafana `13.2.4`). The EKS app layers
that same file; without the secret below, the credential sidecar sleeps and
the pod still starts.

The datasource uid `athena-grow-room` uses auth type `default`. That path is
grafana-aws-sdk `LoadDefaultConfig`, the AWS SDK for Go v2 default chain.
Grafana 13 starts `grafana-athena-datasource` with a stripped environment and
then copies `AWS_CONTAINER_CREDENTIALS_FULL_URI` (plus the IRSA and region
names) because the plugin id is listed in `[aws] forward_settings_to_plugins`.
`AWS_EC2_METADATA_SERVICE_ENDPOINT` is not copied, so an IMDSv2 listener on
`127.0.0.1:9911` never becomes the plugin's endpoint. The sidecar runs
`aws_signing_helper credential-process` and serves the ECS credential document
(`AccessKeyID`, `SecretAccessKey`, `Token`, `Expiration`) at
`http://127.0.0.1:9911/credentials`. The Grafana container sets
`AWS_CONTAINER_CREDENTIALS_FULL_URI` to that URL. The SDK selects it before
EC2 IMDS. `[plugins] forward_host_env_vars` is a list of plugin ids, and this
chart does not set it.

The board **Grow-room History** (uid `grow-room-history`) queries Glue database
`grow_room_telemetry`, table `readings`, Athena workgroup `grow-room-telemetry`,
region `us-west-2`. The bucket is the terraform output `bucket`
(`grow-room-telemetry-` plus the account id). Objects land at
`readings/dt=YYYY-MM-DD/` from `scripts/ship_readings.py`.

Grafana does not use the shipper role. `grow-room-home-shipper` stays
`s3:PutObject` on `readings/*` plus the KMS calls that encrypt those objects.
The new role is `grow-room-grafana-reader`, profile `grow-room-grafana`,
certificate CN `grow-room-grafana-reader`, same home CA trust anchor
(`C:\src\grow-room-pki\ca.pem`). The private key and the Kubernetes Secret stay
on this machine.

Each panel sends its own query. The dashboard time range defaults to 30 days,
timezone UTC, auto-refresh off. Grafana substitutes the date macros before
Athena sees the SQL, so the predicate is `dt >= 'YYYY-MM-DD' AND dt <= 'YYYY-MM-DD'`
on the partition column. Athena skips every other day. The console copy is
`analytics/athena/history_by_day.sql`.

Athena on-demand in us-west-2 is $5 per TB scanned. `ship_readings.py` defaults
to one reading a minute and uploads every 10 rows, on the order of a few
hundred KB per day. Thirty days is about 10-20 MB. One panel is well under a
cent. A full load is six queries, still well under a cent. The workgroup
`bytes_scanned_cutoff_per_query` is 1 GiB, about half a cent, and then Athena
cancels the query.

`stage` is the optional `growth_stage` from `/readings` (`seedling`, `veg`,
`flower`, `late_flower`). The history board uses the same edges as
`sensor_service.stage`: seedling 0.4 to 0.8 kPa, veg 0.8 to 1.2, flower 1.2
to 1.5, late_flower 1.4 to 1.6. Null, blank, and any other value use the veg
band. Rows shipped before the column existed have a null `stage`.

Run the blocks from the repository root. One command per block. Apply uses
the same AWS credentials that already manage `infra/telemetry` (the S3 backend
in `infra/telemetry/versions.tf`). The shipper certificate cannot apply this
plan.

The account id:

```powershell
aws sts get-caller-identity --query Account --output text
```

```bash
aws sts get-caller-identity --query Account --output text
```

## 1. Apply the telemetry root

PowerShell. The CA default in `infra/telemetry/main.tf` is
`C:/src/grow-room-pki/ca.pem`.

```powershell
terraform -chdir=infra/telemetry init
```

```powershell
terraform -chdir=infra/telemetry plan -out=grafana-reader.tfplan
```

```powershell
terraform -chdir=infra/telemetry apply grafana-reader.tfplan
```

bash from WSL. Pass the CA path because the default is a Windows path. The
plan file is gitignored (`infra/telemetry/*.tfplan`).

```bash
terraform -chdir=infra/telemetry init
```

```bash
terraform -chdir=infra/telemetry plan -var=ca_cert_file=/mnt/c/src/grow-room-pki/ca.pem -out=grafana-reader.tfplan
```

```bash
terraform -chdir=infra/telemetry apply grafana-reader.tfplan
```

Confirm the new outputs. `trust_anchor_arn` is the existing home CA anchor.

```powershell
terraform -chdir=infra/telemetry output -raw bucket
```

```powershell
terraform -chdir=infra/telemetry output -raw trust_anchor_arn
```

```powershell
terraform -chdir=infra/telemetry output -raw grafana_profile_arn
```

```powershell
terraform -chdir=infra/telemetry output -raw grafana_role_arn
```

```bash
terraform -chdir=infra/telemetry output -raw bucket
```

```bash
terraform -chdir=infra/telemetry output -raw trust_anchor_arn
```

```bash
terraform -chdir=infra/telemetry output -raw grafana_profile_arn
```

```bash
terraform -chdir=infra/telemetry output -raw grafana_role_arn
```

## 2. Issue the Grafana reader certificate

The CN must be `grow-room-grafana-reader`. The shipper cert
(`grow-room-home-shipper`) cannot assume this role. OpenSSL 3 signs with the
CA key that matches `ca.pem`. The commands below use
`C:\src\grow-room-pki\ca.key` when the key sits next to the cert. The CA key
may live on a separate drive; point `-CAkey` at that file. The leaf can be
`grafana-reader.crt` or `grafana-reader.pem`. The Secret key is `tls.crt`
either way. The key, CSR, and cert stay under `C:\src\grow-room-pki`. Do not
copy them into the repo.

PowerShell uses the Git for Windows OpenSSL.

```powershell
& "C:\Program Files\Git\usr\bin\openssl.exe" req -new -newkey rsa:2048 -nodes -keyout C:\src\grow-room-pki\grafana-reader.key -out C:\src\grow-room-pki\grafana-reader.csr -subj "/CN=grow-room-grafana-reader" -addext "basicConstraints=critical,CA:FALSE" -addext "keyUsage=critical,digitalSignature" -addext "extendedKeyUsage=clientAuth"
```

```powershell
& "C:\Program Files\Git\usr\bin\openssl.exe" x509 -req -in C:\src\grow-room-pki\grafana-reader.csr -CA C:\src\grow-room-pki\ca.pem -CAkey C:\src\grow-room-pki\ca.key -CAcreateserial -CAserial C:\src\grow-room-pki\ca.srl -out C:\src\grow-room-pki\grafana-reader.crt -days 825 -sha256 -copy_extensions copy
```

```powershell
& "C:\Program Files\Git\usr\bin\openssl.exe" x509 -in C:\src\grow-room-pki\grafana-reader.crt -noout -subject
```

The subject line is `subject=CN = grow-room-grafana-reader`.

bash (WSL):

```bash
openssl req -new -newkey rsa:2048 -nodes -keyout /mnt/c/src/grow-room-pki/grafana-reader.key -out /mnt/c/src/grow-room-pki/grafana-reader.csr -subj "/CN=grow-room-grafana-reader" -addext "basicConstraints=critical,CA:FALSE" -addext "keyUsage=critical,digitalSignature" -addext "extendedKeyUsage=clientAuth"
```

```bash
openssl x509 -req -in /mnt/c/src/grow-room-pki/grafana-reader.csr -CA /mnt/c/src/grow-room-pki/ca.pem -CAkey /mnt/c/src/grow-room-pki/ca.key -CAcreateserial -CAserial /mnt/c/src/grow-room-pki/ca.srl -out /mnt/c/src/grow-room-pki/grafana-reader.crt -days 825 -sha256 -copy_extensions copy
```

```bash
openssl x509 -in /mnt/c/src/grow-room-pki/grafana-reader.crt -noout -subject
```

## 3. Create the Kubernetes Secret from local files

Point kubectl at the lab cluster, then write the three ARN files. They are
not secrets, but they are created here so the chart does not hardcode the
trust-anchor id.

```powershell
kubectl config use-context k3d-grow-room-dev
```

```powershell
terraform -chdir=infra/telemetry output -raw trust_anchor_arn | Set-Content -NoNewline -Encoding ascii C:\src\grow-room-pki\grafana-trust-anchor-arn
```

```powershell
terraform -chdir=infra/telemetry output -raw grafana_profile_arn | Set-Content -NoNewline -Encoding ascii C:\src\grow-room-pki\grafana-profile-arn
```

```powershell
terraform -chdir=infra/telemetry output -raw grafana_role_arn | Set-Content -NoNewline -Encoding ascii C:\src\grow-room-pki\grafana-role-arn
```

`--from-file=tls.crt=` accepts `grafana-reader.crt` or `grafana-reader.pem`.
The key stored in the Secret stays `tls.crt`.

```powershell
kubectl -n monitoring create secret generic grafana-athena-identity --from-file=tls.crt=C:\src\grow-room-pki\grafana-reader.crt --from-file=tls.key=C:\src\grow-room-pki\grafana-reader.key --from-file=trust-anchor-arn=C:\src\grow-room-pki\grafana-trust-anchor-arn --from-file=profile-arn=C:\src\grow-room-pki\grafana-profile-arn --from-file=role-arn=C:\src\grow-room-pki\grafana-role-arn --dry-run=client -o yaml | Set-Content -Encoding ascii C:\src\grow-room-pki\grafana-athena-identity.yaml
```

```powershell
kubectl apply -f C:\src\grow-room-pki\grafana-athena-identity.yaml
```

bash (WSL). `output -raw` does not add a newline.

```bash
kubectl config use-context k3d-grow-room-dev
```

```bash
terraform -chdir=infra/telemetry output -raw trust_anchor_arn > /mnt/c/src/grow-room-pki/grafana-trust-anchor-arn
```

```bash
terraform -chdir=infra/telemetry output -raw grafana_profile_arn > /mnt/c/src/grow-room-pki/grafana-profile-arn
```

```bash
terraform -chdir=infra/telemetry output -raw grafana_role_arn > /mnt/c/src/grow-room-pki/grafana-role-arn
```

```bash
kubectl -n monitoring create secret generic grafana-athena-identity --from-file=tls.crt=/mnt/c/src/grow-room-pki/grafana-reader.crt --from-file=tls.key=/mnt/c/src/grow-room-pki/grafana-reader.key --from-file=trust-anchor-arn=/mnt/c/src/grow-room-pki/grafana-trust-anchor-arn --from-file=profile-arn=/mnt/c/src/grow-room-pki/grafana-profile-arn --from-file=role-arn=/mnt/c/src/grow-room-pki/grafana-role-arn --dry-run=client -o yaml | kubectl apply -f -
```

The secret is not in git. Argo will not delete it: prune only removes objects
Argo itself applied.

## 4. Upgrade the monitoring release

Create the secret before this upgrade. The pod mounts it as optional. The
cert is read only in the `athena-rolesanywhere` sidecar, which serves
`http://127.0.0.1:9911/credentials`. Grafana's Athena plugin uses auth type
`default` and `AWS_CONTAINER_CREDENTIALS_FULL_URI`. The chart installs
`grafana-athena-datasource@3.4.2`. The first start also downloads
`aws_signing_helper` 1.8.5 (sha256-checked) and that plugin, so the rollout
can sit at 0/1 for a few minutes. The machine needs
egress to `public.ecr.aws`, `rolesanywhere.amazonaws.com`, and `grafana.com`.

PowerShell:

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
```

```powershell
helm repo update
```

```powershell
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.13.1 -n monitoring --create-namespace -f monitoring/values-k3d.yaml
```

```powershell
kubectl apply -f monitoring/manifests/grafana-dashboard-grow-room-history.yaml
```

```powershell
kubectl -n monitoring rollout status deploy/monitoring-grafana
```

bash:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
```

```bash
helm repo update
```

```bash
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.13.1 -n monitoring --create-namespace -f monitoring/values-k3d.yaml
```

```bash
kubectl apply -f monitoring/manifests/grafana-dashboard-grow-room-history.yaml
```

```bash
kubectl -n monitoring rollout status deploy/monitoring-grafana
```

If the Argo CD app `monitoring` is auto-syncing `main` with self-heal, it
will put this helm upgrade back until git `HEAD` contains these values. After
this change is on that branch, refresh the app instead of fighting the
upgrade:

```powershell
kubectl -n argocd annotate application monitoring argocd.argoproj.io/refresh=hard --overwrite
```

```bash
kubectl -n argocd annotate application monitoring argocd.argoproj.io/refresh=hard --overwrite
```

The secret still has to exist before that rollout. If you created the secret
after the pod started, restart Grafana so the volume is mounted.

`grafana.ini` is mounted from a ConfigMap. Changing it, including `[aws]
forward_settings_to_plugins` or `allowed_auth_providers`, needs a restart.
Argo only updates the ConfigMap. Grafana reads `grafana.ini` at process start.

After this change is on `main`, sync from that revision, then restart so the
new ConfigMap and `AWS_CONTAINER_CREDENTIALS_FULL_URI` are what the process
starts with. One command per block. The port-forward stays open; run the
health curl in a second window. `"status":"OK"` is the auth check.

```powershell
kubectl config use-context k3d-grow-room-dev
```

```powershell
Set-Content -Encoding ascii "$env:TEMP\monitoring-refresh.json" '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
```

```powershell
kubectl -n argocd patch application monitoring --type merge --patch-file "$env:TEMP\monitoring-refresh.json"
```

```powershell
kubectl -n argocd get application monitoring
```

Wait until the Deployment spec contains the container credential URI, then
restart. The restart is what loads `grafana.ini`. Argo only updates the
ConfigMap.

```powershell
$synced = $false; for ($i = 0; $i -lt 36; $i++) { $spec = kubectl -n monitoring get deploy monitoring-grafana -o yaml; if ($spec -match 'AWS_CONTAINER_CREDENTIALS_FULL_URI') { $synced = $true; break }; Start-Sleep -Seconds 5 }; if (-not $synced) { throw 'monitoring-grafana does not have AWS_CONTAINER_CREDENTIALS_FULL_URI yet' }
```

```powershell
kubectl -n monitoring rollout restart deploy/monitoring-grafana
```

```powershell
kubectl -n monitoring rollout status deploy/monitoring-grafana
```

```bash
kubectl -n monitoring rollout restart deploy/monitoring-grafana
```

```bash
kubectl -n monitoring rollout status deploy/monitoring-grafana
```

## 5. Verify the panel loads

The init container should print the helper version. The sidecar should log
`container credentials listening on http://127.0.0.1:9911/credentials`.

```powershell
kubectl -n monitoring logs deploy/monitoring-grafana -c fetch-aws-signing-helper
```

```powershell
kubectl -n monitoring logs deploy/monitoring-grafana -c athena-rolesanywhere --tail=40
```

```bash
kubectl -n monitoring logs deploy/monitoring-grafana -c fetch-aws-signing-helper
```

```bash
kubectl -n monitoring logs deploy/monitoring-grafana -c athena-rolesanywhere --tail=40
```

Leave this port-forward running and use a second terminal for the curls.

```powershell
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

```bash
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

PowerShell `curl` is an alias. Use `curl.exe`. Lab login is `admin` /
`grow-room-lab`. `"status":"OK"` means the plugin assumed
`grow-room-grafana-reader` and reached the workgroup.

```powershell
curl.exe -s -u admin:grow-room-lab http://127.0.0.1:3000/api/datasources/uid/athena-grow-room/health
```

```powershell
curl.exe -s -u admin:grow-room-lab http://127.0.0.1:3000/api/dashboards/uid/grow-room-history
```

```bash
curl -s -u admin:grow-room-lab http://127.0.0.1:3000/api/datasources/uid/athena-grow-room/health
```

```bash
curl -s -u admin:grow-room-lab http://127.0.0.1:3000/api/dashboards/uid/grow-room-history
```

Open `http://127.0.0.1:3000/d/grow-room-history`. The time picker defaults to
the last 30 days. The daily VPD, temperature, humidity, band, and source
panels each run one pruned query. Empty charts mean those `dt` partitions
have no objects yet; the health check above is still the auth check. The
Athena console query for the same shape is `analytics/athena/history_by_day.sql`.

## What the reader role can do

Allowed: Athena query actions on workgroup `grow-room-telemetry`, Glue read on
database `grow_room_telemetry` and its tables, `s3:GetObject` on `readings/*`
and `athena-results/*`, `s3:PutObject` on `athena-results/*` only, and
`kms:Decrypt`, `kms:GenerateDataKey`, and `kms:DescribeKey` on
`alias/grow-room/telemetry`. `GenerateDataKey` is what S3 needs to write the
SSE-KMS result objects. An explicit deny blocks `s3:PutObject`,
`s3:DeleteObject`, and `s3:AbortMultipartUpload` on `readings/*`.

A few Athena list calls (`ListWorkGroups`, `ListDataCatalogs`, and the table
metadata lists) only accept `Resource "*"`. They do not grant `StartQueryExecution`
on any other workgroup, and they do not grant `s3:GetObject` outside the two
prefixes.