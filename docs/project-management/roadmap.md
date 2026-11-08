# Roadmap

This is the order I kept after the five-week lab. Items 1 through 4 are done. Item 5 is not started.

## 1. Plant stage and VPD bands

Done on `main`. Pull request [#77](https://github.com/TontoBlanco/grow-room-platform/pull/77) merged on 3 November 2026.

`GROW_STAGE` is one tent-wide stage. The default is `veg`. It selects an inclusive leaf-VPD band: seedling 0.4–0.8, veg 0.8–1.2, flower 1.2–1.5, late flower 1.4–1.6, in kilopascals. Plant mood is still the separate mixed-tent gauge. The dashboard row is **Growth stage VPD target**. The panels are in the [Grafana guide](../grafana.md).

## 2. Athena as a data source in local Grafana

Done and working. Pull request [#80](https://github.com/TontoBlanco/grow-room-platform/pull/80) added **Grow-room History** (uid `grow-room-history`) on the k3d Grafana. Pull request [#86](https://github.com/TontoBlanco/grow-room-platform/pull/86) fixed the plugin credentials. The datasource health check returns OK. The query role is `grow-room-grafana-reader`. The shipper role stays write-only. The steps and the three install lessons are in [Athena in Grafana](../ATHENA_GRAFANA.md).

## 3. Grow alerts the controller cannot see

Done. The write-up is [Grow alerts](../GROW_ALERTS.md). Each alert has its own Helm switch. `charts/grow-alerts/values.yaml` keeps every switch off. The k3d overlay `values-k3d.yaml` turns probe drift on. An off switch renders no object.

The four alerts are a stale S3 shipper, a day of VPD outside the stage band, certificate expiry, and probe drift against the controller's reported VPD. They do not repeat the app's temperature and humidity alarms. The earlier candidates (the host scrape being down, and a port reporting power 0) are not in this set. The host scrape is the laptop path, and the controller already shows port power.

## 4. Phase 8 — Home Assistant moves between the house and AWS

Done. Paid verify on 7 November 2026, plus the hotfixes from that run.

`scripts/aws-poc.ps1 up -WithHA` stops the Home Assistant container with `docker stop` (the running `homeassistant` container, including one started from the WSL checkout), uploads that config folder (including `home-assistant_v2.db`) to the existing telemetry bucket under `ha-backups/`, and restores that archive into one EKS pod. `down` copies it back, runs `docker start` on the same container, then runs the old teardown. `-HaConfigPath` or `GROW_HA_CONFIG_PATH` overrides the folder. The write-up is [Phase 8](../aws-poc/PHASE8_HA_MIGRATION.md). The paid run is the [7 November test session](../test-session/2026-11-07.md).

`ha-config/` stays gitignored. The backup role is `grow-room-ha-backup` on prefix `ha-backups/` only, using `alias/grow-room/telemetry`. Plain `up` does not move Home Assistant. RDS audit rows on AWS stay throwaway test data. A sync with the laptop SQLite file is not built.

The merged code:

- Pull request [#95](https://github.com/TontoBlanco/grow-room-platform/pull/95), "Move Home Assistant onto EKS with aws-poc up -WithHA", merged 3 November 2026 at 6:08 PM MST.
- Pull request [#97](https://github.com/TontoBlanco/grow-room-platform/pull/97), "Fix PowerShell 5.1 $HOME collision on aws-poc -WithHA", merged 3 November 2026 at 6:27 PM MST.
- Pull request [#99](https://github.com/TontoBlanco/grow-room-platform/pull/99), "Find the Home Assistant config when Compose runs from WSL", merged 4 November 2026 at 7:33 AM MST.
- Pull request [#101](https://github.com/TontoBlanco/grow-room-platform/pull/101), "Fix the Nov 7 Home Assistant migration session failures", merged 7 November 2026 at 5:45 PM MST, commit `56c95d87`.
- Pull request [#103](https://github.com/TontoBlanco/grow-room-platform/pull/103), "Restart home Home Assistant when the paid up prompt is declined", merged 7 November 2026 at 10:04 PM MST, commit `6f41afa`.

On 7 November I ran `up -WithHA`, then `verify -WithHA`, which ended `ALL CHECKS PASSED`, then `down`. Terraform destroyed 161 resources. The leftover sweep was 0 for EKS clusters, load balancers, NAT gateways, Elastic IPs, running instances, unattached EBS volumes, available ENIs, RDS instances, and EKS log groups. Home Assistant was back on `grow-room-platform-homeassistant-1`. kubectl was on `k3d-grow-room-dev`. The run hit failures I fixed by hand. Those fixes are #101: `restore.sh` uses `sha256sum` and installs `tar` and `gzip` with `dnf`, then `yum`, then `microdnf`; the deployment checksums the scripts ConfigMap and sets `progressDeadlineSeconds` to 900; `kubectl cp` goes to a relative leaf and is piped to `Out-Null`; `ha_migration.py` uses a direct `mv`, with rollback `mv -T`; and `aws-poc.ps1` treats a null `Start-Process` `ExitCode` as a warning so the leftover sweep still runs. The same pull request upgrades `zlib1g` for DSA-6613-1.

On 8 November I pulled `main` through `6f41afa`, ran `up -WithHA`, and typed `no` at `Type yes to continue:`. The script printed `You did not type yes. The paid stack will not change.`, started `grow-room-platform-homeassistant-1` again, and threw `Stopped by you.` Terraform apply did not run. That is #103. It is not the 7 November bill. Both days are on the test-session page.

Cost Explorer UnblendedCost from the 8 November read is pasted in [COSTS.md](../aws-poc/COSTS.md), commit `2774570` at 8:32 AM MST. I am not changing those numbers. The commands use profile `GrowRoom`, the Cost Explorer API in `us-east-1`, daily granularity, and period `Start=2026-11-06,End=2026-11-09`. They do not pass `file://ce-filter.json`. The cluster was still `us-west-2`. Cost Explorer can lag up to 24 hours. Daily totals: 2026-11-06 0.0672586299 USD, 2026-11-07 2.6880926014 USD, 2026-11-08 0.0170460668 USD. For 7 November, service groups greater than 0.01 USD: AWS Key Management Service 0.0986111119, AWS WAF 0.0315379174, EC2 - Other 0.7230693192, Amazon Elastic Compute Cloud - Compute 0.7643948866, Amazon Elastic Container Service for Kubernetes 0.318104639, Amazon Elastic Load Balancing 0.0225053118, Amazon Relational Database Service 0.1199012534, Amazon Virtual Private Cloud 0.241474528, and AmazonCloudWatch 0.36555855. The session and service tables in that file are still mostly blank. The 1 November and 3 November dollar cells are blank. The script's about 0.70 USD per hour line is a planning warning, not that read.

## 5. Dependabot or Renovate

Not started. There is no `.github/dependabot.yml` and no Renovate config. Actions are pinned by SHA in the newer workflows, and chart versions are pinned in Git. They still go stale. The stage work, the alerts, and Phase 8 are done. I have not added the bot.

## Explicitly later

- A Raspberry Pi or other always-on host. [ADR-0011](../adr/0011-k3d-instead-of-a-pi.md) still stands. Phase 8 is the Home Assistant move, and that paid verify is done. It is not this machine.
- Kyverno `failureAction: Enforce`, after a PolicyReport pass on a cosign 2.6.5 image.
- Replacing `AdministratorAccess` on `grow-room-gha-apply`.
- `docs/aws-poc/COSTS.md` now has the 8 November 2026 Cost Explorer read for 6–8 November (commit `2774570`, 8:32 AM MST). UnblendedCost from that paste: 2026-11-06 0.0672586299 USD, 2026-11-07 2.6880926014 USD, 2026-11-08 0.0170460668 USD. The 7 November service groups greater than 0.01 USD are in the Phase 8 item above and in the file: AWS Key Management Service 0.0986111119, AWS WAF 0.0315379174, EC2 - Other 0.7230693192, Amazon Elastic Compute Cloud - Compute 0.7643948866, Amazon Elastic Container Service for Kubernetes 0.318104639, Amazon Elastic Load Balancing 0.0225053118, Amazon Relational Database Service 0.1199012534, Amazon Virtual Private Cloud 0.241474528, and AmazonCloudWatch 0.36555855. The commands do not pass `file://ce-filter.json`. Cost Explorer can lag up to 24 hours. The structured session and service tables are still mostly blank. The 1 November and 3 November session dollar cells are still blank. I did not copy the paste into those cells. The old task was to fill the file the day after the 3 November session. That day's dollar cell is still blank.
