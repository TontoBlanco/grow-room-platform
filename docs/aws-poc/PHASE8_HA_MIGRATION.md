# Phase 8 — Home Assistant moves with the session

This page is the move between the PC and a short EKS session. It is for someone who has the repo and has not watched the tent being built.

Home Assistant at home is one Docker Compose service. `docker-compose.yml` names it `homeassistant`. The image is `ghcr.io/home-assistant/home-assistant:stable`. The config folder is mounted at `/config`. It is gitignored. It holds the AC Infinity login, the long-lived token material, and `home-assistant_v2.db`.

On this PC the script runs from the Windows checkout `C:\src\grow-room-platform`, and Home Assistant runs from the WSL checkout. The container is `grow-room-platform-homeassistant-1`. Its `/config` mount is `/home/colem/src/grow-room-platform/ha-config`, which Windows sees as `\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config`. `home-assistant_v2.db` is in that folder. A dry run that only looks at `C:\src\grow-room-platform\ha-config` reports the database missing and never reads the real one.

`scripts/aws-poc.ps1 up` without `-WithHA` does not stop that container, does not read the folder, and does not install Home Assistant on EKS. Sensor-service on EKS stays on the simulator, which is what the 1 November and 3 November sessions did. `up -WithHA` points sensor-service at Home Assistant for that session. The paid run, and the 8 November check where I typed `no`, are the [7 November test session](../test-session/2026-11-07.md). Those are two different days.

## Which folder is backed up

The folder used for the database check, the backup, and the restore is chosen in this order:

1. `-HaConfigPath`
2. Environment variable `GROW_HA_CONFIG_PATH`
3. The same key in the gitignored `.env`
4. The `/config` mount of the Home Assistant container, when none of those is set
5. `ha-config` in the repo root

A relative path is joined to the repo root. A Windows path is used as given. Docker Desktop host mounts (`/run/desktop/mnt/host/c/...` and `/mnt/c/...`) become a drive letter such as `C:\...`. Any other Linux mount, including `/home/colem/...`, is mapped with the default WSL distro. The script runs `wsl.exe -l -q`, reads the bytes as UTF-16LE or UTF-8 (the console listing is UTF-16), and uses the first name. That is the default distro. `/home/colem/src/grow-room-platform/ha-config` with default distro `Ubuntu` becomes `\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config`.

The container is the one Docker reports. A running container whose Compose label `com.docker.compose.service` is `homeassistant` wins. If none is running, a stopped container with that label is used, so `down` can put the files back in the same folder. If there is no Compose label, a container whose name contains `homeassistant` matches (`grow-room-platform-homeassistant-1` on this PC).

Dry run prints `config path`, `config origin` (`explicit`, `container-mount`, or `repo-default`), and `container`. It does not stop that container, build a tar, upload, or create AWS resources.

```powershell
.\scripts\aws-poc.ps1 up -WithHA -DryRun -HaConfigPath '\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config'
```

Leave the parameter unset when the container mount is the right source. The `.env` line is the same path:

```powershell
GROW_HA_CONFIG_PATH=\\wsl.localhost\Ubuntu\home\colem\src\grow-room-platform\ha-config
```

## Stop, start, and the tar

Stop and start call `docker stop` and `docker start` with the inspected container name. They do not run `docker compose` against the `C:\` checkout. That checkout is a different project directory from the WSL one, so Compose there would miss `grow-room-platform-homeassistant-1`.

A folder on a drive letter, including the repo `ha-config` default, is still packed and restored by `scripts/ha_migration.py`. A `\\wsl.localhost\<distro>\...` folder is packed with `wsl.exe -d <distro> -u root -- tar` inside that distro. Root is required because the container writes `home-assistant_v2.db` as root, and the default WSL user cannot always read or rename those files. The gzip file is written to the Windows temp directory through `/mnt/<drive>/...`. PowerShell does not pipe those bytes. Windows PowerShell 5.1 corrupts binary pipeline data, and a Python walk of the `\\wsl.localhost` share is a poor reader for `home-assistant_v2.db`. Restore checks the archive in Python (the safe extract), copies the checked tree into the distro, and renames the live folder only after `home-assistant_v2.db` is non-empty. The distro needs GNU `tar`, `cp`, and `mv`. Ubuntu has them. `wsl -d` uses the distro name that is already in the UNC path.

## What moves

One gzip archive of the resolved config folder, including `home-assistant_v2.db`. The default folder is still `ha-config/` in the repo root. The script uploads it to the existing telemetry bucket `grow-room-telemetry-590183769702`, prefix `ha-backups/<timestamp>.tar.gz`. The object is encrypted with the existing key `alias/grow-room/telemetry`. The script checks the size, the SHA-256 checksum, and that header before it will continue. It does not print the archive or the token.

On EKS the archive is restored onto one Home Assistant pod. sensor-service in that session is pointed at `http://home-assistant.grow-room.svc.cluster.local:8123` and reads `HA_TOKEN` from the gitignored `.env`. The token is applied as a Kubernetes secret at runtime. It is not a Helm value and it is not committed.

`down` copies the pod's `/config` back to the same prefix, checks the object, writes it over the resolved config folder, starts that same container with `docker start`, and only then runs the teardown this repo already had, including the available-ENI cleanup.

The script keeps the newest 5 objects under `ha-backups/` (change it with `-HaBackupKeep`). A lifecycle rule on that prefix only aborts a multipart upload that never finished. It does not delete a finished backup on a timer, because "newest 5" is a count and lifecycle rules expire by age.

## What does not move

| Data | Where it stays | Why |
| --- | --- | --- |
| RDS `grow-room-poc-audit` | Thrown away with the session | It is test data written by `verify` and drills. A later sync with the laptop SQLite file is optional and is not built. |
| Prometheus | Wherever it was scraped | The laptop keeps the `grow-room-ha-host` history. The EKS Prometheus keeps the session. This move does not copy either TSDB. |
| S3 `readings/` and Athena | The telemetry stack | `down` does not delete them. The shipper role is still write-only on `readings/*`. The backup role cannot read that prefix. |

## Why only one copy

The AC Infinity integration logs into one cloud account from Home Assistant. Two running copies refresh that login and fight. The script refuses to start the EKS pod while the home container is running, and it refuses to start the home container while the EKS container is running. If both are already up, it stops and changes nothing.

## Cost

EKS is the paid part. `up` already warns about **0.70 USD per hour** while the stack is up. That figure is the script's planning warning, not a Cost Explorer measurement. The lines that move are the control plane (about 0.10 USD per hour), three NAT gateways (about 0.14), three `t3.large` nodes (about 0.25), Multi-AZ RDS (about 0.03), and the load balancer (about 0.02). WAF, KMS, and the 10 GiB Home Assistant volume are the rest of that warning. Apply time is already on the bill. The 25 USD budget sends email. It does not stop the spend.

Run `down` before you leave the machine. `down` keeps the state bucket, the state key, the OIDC roles, the budget, the hosted zone, and the telemetry stack. The backup role is part of that telemetry stack. It does not add a second KMS key.

The 7 November 2026 paid session is the [test session](../test-session/2026-11-07.md). `verify -WithHA` ended `ALL CHECKS PASSED`, and `down` destroyed 161 resources. Cost Explorer UnblendedCost from the 8 November read is pasted in [COSTS.md](COSTS.md), commit `2774570` at 8:32 AM MST. The commands use profile `GrowRoom`, the Cost Explorer API in `us-east-1`, daily granularity, and period `Start=2026-11-06,End=2026-11-09`. They do not pass `file://ce-filter.json`. The cluster was still `us-west-2`. Cost Explorer can lag up to 24 hours. [COSTS.md](COSTS.md) already says that. Daily totals: 2026-11-06 0.0672586299 USD, 2026-11-07 2.6880926014 USD, 2026-11-08 0.0170460668 USD. For 7 November, service groups greater than 0.01 USD: AWS Key Management Service 0.0986111119, AWS WAF 0.0315379174, EC2 - Other 0.7230693192, Amazon Elastic Compute Cloud - Compute 0.7643948866, Amazon Elastic Container Service for Kubernetes 0.318104639, Amazon Elastic Load Balancing 0.0225053118, Amazon Relational Database Service 0.1199012534, Amazon Virtual Private Cloud 0.241474528, and AmazonCloudWatch 0.36555855. The session and service tables in that file are still mostly blank, including the 1 November and 3 November dollar cells. On 8 November I typed `no` at `Type yes to continue:` and Terraform did not apply. That check is the last section of the same test session, so it stays separate from the 7 November bill.

## Before you pay

Apply the telemetry root once so the role `grow-room-ha-backup` exists. That apply does not create EKS. Then run the dry run. It checks Docker, the resolved database file, the role, the bucket prefix, and the KMS alias. It prints the config path and the container name. It does not stop Home Assistant, upload, or apply Terraform.

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

I ran this paid order on 7 November 2026. `verify -WithHA` ended `ALL CHECKS PASSED`. The hand fixes from that day, and the 8 November run where I typed `no`, are the [test session](../test-session/2026-11-07.md). There is no screenshot of either day in the repo.

## Failure modes

| What you see | What the script does | What you do |
| --- | --- | --- |
| Backup fails, or S3 does not match size, checksum, and `aws:kms` | `up` aborts. Terraform does not apply. If this move stopped the container, it runs `docker start` on that container. EKS Home Assistant is not installed. | Read the error. The config folder is still on disk. The message includes the path it checked. Fix Docker, the role, or the key, then dry-run again. |
| You answer `Type yes to continue:` with anything but yes (`no`, `n`, `No`, or Enter) | The plan is not applied. If this `up -WithHA` stopped the home container and the EKS copy is not running, the script starts that same container. When no EKS Home Assistant deployment is present, it records the move as home. yes, Yes, and YES still continue into the paid apply. | Home Assistant at home should be running again. If the EKS copy was already serving, the home container stays stopped. |
| Both copies are already running | The script refuses and changes nothing. | Stop the copy you do not want. Do not start the other one until the first is stopped. |
| Home is still running at the moment EKS would start | EKS Home Assistant is not installed. | The stop did not stick. Start Docker, stop the Compose service, and do not start a second copy by hand. |
| `down` cannot verify the EKS backup | EKS Home Assistant stays up. Compose is not started. Terraform destroy does not run. | The live config is still the pod. Fix the upload and run `down` again. |
| The file restore at home fails | The container is not started. Teardown does not run. If the pod was scaled to zero, the script scales it back to one. | The previous folder is renamed with a `.previous` suffix only after a good extract. A failed extract leaves the old folder in place. |
| The window was closed after the container stopped and before EKS was serving | `.ha-migration-state.json` says `moving`. The folder is still on disk. | Run `down`, or `docker start` on the home container after you are sure the EKS container is not running. |
| `up` without `-WithHA` while a `-WithHA` stack is still up | The plan does not pass `enable_ha_migration`. Terraform will want to remove the volume driver and the pod identity. | Do not plain-`up` over a live move. Use `down`, or `up -WithHA -SkipTerraform` if you are only repeating the Kubernetes half. |

The IAM role can `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, and `s3:ListBucket` on `ha-backups/` only, plus the KMS calls that key needs. It is not `s3:*`. The shipper role is unchanged.

Secrets stay out of git: `ha-config/`, `.env`, and `.ha-migration-state.json`. The state file stores `location` and the object key. It does not store the token. The script does not write the token or the archive bytes to the console. A Kubernetes error can still echo a secret manifest. If that happens, treat the token as exposed and make a new one in Home Assistant.
