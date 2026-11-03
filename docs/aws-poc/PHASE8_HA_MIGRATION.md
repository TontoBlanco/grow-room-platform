# Phase 8 — Home Assistant moves with the session

This page is the move between the PC and a short EKS session. It is for someone who has the repo and has not watched the tent being built.

Home Assistant at home is one Docker Compose service. `docker-compose.yml` names it `homeassistant`. The image is `ghcr.io/home-assistant/home-assistant:stable`. The whole config folder is `ha-config/` in the repo root, mounted at `/config`. That folder is gitignored. It holds the AC Infinity login, the long-lived token material, and `home-assistant_v2.db`.

`scripts/aws-poc.ps1 up` without `-WithHA` does not stop that container, does not read the folder, and does not install Home Assistant on EKS. Sensor-service on EKS stays on the simulator, the same as the November sessions.

## What moves

One gzip archive of `ha-config/`, including `home-assistant_v2.db`. The script uploads it to the existing telemetry bucket `grow-room-telemetry-590183769702`, prefix `ha-backups/<timestamp>.tar.gz`. The object is encrypted with the existing key `alias/grow-room/telemetry`. The script checks the size, the SHA-256 checksum, and that header before it will continue. It does not print the archive or the token.

On EKS the archive is restored onto one Home Assistant pod. sensor-service in that session is pointed at `http://home-assistant.grow-room.svc.cluster.local:8123` and reads `HA_TOKEN` from the gitignored `.env`. The token is applied as a Kubernetes secret at runtime. It is not a Helm value and it is not committed.

`down` copies the pod's `/config` back to the same prefix, checks the object, writes it over `ha-config/`, starts the Compose service, and only then runs the teardown this repo already had, including the available-ENI cleanup.

The script keeps the newest 5 objects under `ha-backups/` (change it with `-HaBackupKeep`). A lifecycle rule on that prefix only aborts a multipart upload that never finished. It does not delete a finished backup on a timer, because "newest 5" is a count and lifecycle rules expire by age.

## What does not move

| Data | Where it stays | Why |
| --- | --- | --- |
| RDS `grow-room-poc-audit` | Thrown away with the session | It is test data written by `verify` and drills. A later sync with the laptop SQLite file is optional and is not built. |
| Prometheus | Wherever it was scraped | The laptop keeps the `grow-room-ha-host` history. The EKS Prometheus keeps the session. This move does not copy either TSDB. |
| S3 `readings/` and Athena | The telemetry stack | `down` does not delete them. The shipper role is still write-only on `readings/*`. The backup role cannot read that prefix. |

## Why only one copy

The AC Infinity integration logs into one cloud account from Home Assistant. Two running copies refresh that login and fight. The script refuses to start the EKS pod while the Compose service is running, and it refuses to start the Compose service while the EKS container is running. If both are already up, it stops and changes nothing.

## Cost

EKS is the paid part. `up` already warns about **0.70 USD per hour** while the stack is up. That figure is the script's planning warning, not a Cost Explorer measurement. The lines that move are the control plane (about 0.10 USD per hour), three NAT gateways (about 0.14), three `t3.large` nodes (about 0.25), Multi-AZ RDS (about 0.03), and the load balancer (about 0.02). WAF, KMS, and the 10 GiB Home Assistant volume are the rest of that warning. Apply time is already on the bill. The 25 USD budget sends email. It does not stop the spend.

Run `down` before you leave the machine. `down` keeps the state bucket, the state key, the OIDC roles, the budget, the hosted zone, and the telemetry stack. The backup role is part of that telemetry stack. It does not add a second KMS key.

## Before you pay

Apply the telemetry root once so the role `grow-room-ha-backup` exists. That apply does not create EKS. Then run the dry run. It checks Docker, the database file, the role, the bucket prefix, and the KMS alias. It does not stop Home Assistant, upload, or apply Terraform.

```powershell
Set-Location C:\src\grow-room-platform
```

```powershell
$env:AWS_PROFILE = "GrowRoom"
```

```powershell
$env:AWS_REGION = "us-west-2"
```

```powershell
terraform -chdir=infra/telemetry init
```

```powershell
terraform -chdir=infra/telemetry apply
```

```powershell
.\scripts\aws-poc.ps1 up -WithHA -DryRun
```

A passing dry run prints `DRY RUN` and leaves the Compose service where it was.

## A paid session

```powershell
.\scripts\aws-poc.ps1 up -WithHA
```

Type `yes` only when the plan is the one you mean. When the public URL is up:

```powershell
.\scripts\aws-poc.ps1 verify -WithHA
```

`verify -WithHA` still runs the old checks, and it also requires `/readings` to say `"source": "homeassistant"`.

When you are finished:

```powershell
.\scripts\aws-poc.ps1 down
```

```powershell
kubectl config use-context k3d-grow-room-dev
```

`down` does not need `-WithHA`. If a move is in progress it reverses that move, then tears the stack down. Your k3d context name on this PC is `k3d-grow-room-dev`. `up` points kubectl at EKS. The last command puts it back.

## Failure modes

| What you see | What the script does | What you do |
| --- | --- | --- |
| Backup fails, or S3 does not match size, checksum, and `aws:kms` | `up` aborts. Terraform does not apply. If this move stopped Compose, it starts `homeassistant` again. EKS Home Assistant is not installed. | Read the error. The config folder is still on disk. Fix Docker, the role, or the key, then dry-run again. |
| Both copies are already running | The script refuses and changes nothing. | Stop the copy you do not want. Do not start the other one until the first is stopped. |
| Home is still running at the moment EKS would start | EKS Home Assistant is not installed. | The stop did not stick. Start Docker, stop the Compose service, and do not start a second copy by hand. |
| `down` cannot verify the EKS backup | EKS Home Assistant stays up. Compose is not started. Terraform destroy does not run. | The live config is still the pod. Fix the upload and run `down` again. |
| The file restore at home fails | Compose is not started. Teardown does not run. If the pod was scaled to zero, the script scales it back to one. | The previous `ha-config/` is renamed `ha-config.previous/` only after a good extract. A failed extract leaves the old folder in place. |
| The window was closed after Compose stopped and before EKS was serving | `.ha-migration-state.json` says `moving`. The folder is still on disk. | Run `down`, or `docker compose up -d --no-deps homeassistant` after you are sure the EKS container is not running. |
| `up` without `-WithHA` while a `-WithHA` stack is still up | The plan does not pass `enable_ha_migration`. Terraform will want to remove the volume driver and the pod identity. | Do not plain-`up` over a live move. Use `down`, or `up -WithHA -SkipTerraform` if you are only repeating the Kubernetes half. |

The IAM role can `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, and `s3:ListBucket` on `ha-backups/` only, plus the KMS calls that key needs. It is not `s3:*`. The shipper role is unchanged.

Secrets stay out of git: `ha-config/`, `.env`, and `.ha-migration-state.json`. The state file stores `location` and the object key. It does not store the token. The script does not write the token or the archive bytes to the console. A Kubernetes error can still echo a secret manifest. If that happens, treat the token as exposed and make a new one in Home Assistant.
