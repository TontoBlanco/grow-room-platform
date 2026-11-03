# Troubleshooting

These are the failures I actually hit. The phase pages have the rebuild steps. This page is the short list.

## Docker Desktop is not running

Home Assistant comes up in its first-run onboarding screen, and sensor-service gets HTTP 401 from Home Assistant. Start Docker Desktop, wait until the engine answers, then start Compose again. A 401 with Docker already running is a bad or missing `HA_TOKEN`, not this case.

## Kyverno Audit and `mutateDigest`

While `failureAction` is `Audit`, `mutateDigest` must be `false`. Kyverno rejects the policy otherwise. `verifyDigest` stays `false` too, because the chart deploys a tag. Enforce is a later change, and only after a PolicyReport pass. The file is `k8s/aws-poc/kyverno-verify-images.yaml`. See [Phase 5](phases/phase-5-supply-chain.md).

## Kyverno 1.19 and cosign tags

Kyverno 1.19 looks up the legacy tag `sha256-<digest>.sig`. Cosign 3 wrote referrer bundles, and the cluster reported `no signatures found` even though `cosign verify` in CI passed. CI now pins cosign `v2.6.5` and signs with `--registry-referrers-mode=legacy`. Images signed before that pin still fail the policy until a new `main` build replaces them.

## Load balancer 502 on pod delete and node drain

On 3 November, drills 1 and 2 each returned one HTTP 502. The load balancer was still sending traffic after the process had exited. `values-eks.yaml` now sleeps 30 seconds in `preStop`, sets `terminationGracePeriodSeconds` to 45, sets the target-group deregistration delay to 20 seconds, and adds a PodDisruptionBudget with `minAvailable: 2`. The k3d values do not.

## EKS access entry

The access entry has to be the full SSO role ARN, including the path. The shape is:

`arn:aws:iam::ACCOUNT:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_SUFFIX`

`ACCOUNT` and `SUFFIX` stay in `admin_principal_arn` and in the GitHub variable `ADMIN_PRINCIPAL_ARN`. I do not print them here. Dropping `aws-reserved/sso.amazonaws.com` is what made `kubectl` ask for credentials.

## RDS failover

Drill 3 on 3 November moved the primary in about 30 seconds. The usual range I still quote is 60 to 120 seconds. `/healthz` can stay 200 through it. `/audit` is what fails and then recovers. The steps are in [the drill notes](aws-poc/DRILLS.md).

## `down` and an orphaned network interface

`terraform destroy` sat on a private subnet because an available elastic network interface named like `aws-K8S-...` was still in the proof-of-concept VPC. `scripts/aws-poc.ps1 down` now deletes available interfaces in that VPC before destroy, and again while destroy runs. In-use interfaces are left alone. If destroy still stops, run `down` again. It is safe to repeat.

## The tagging API after delete

`aws resourcegroupstaggingapi get-resources` with `Project=grow-room` keeps listing resources that are already gone. That lag is the API, not a resource I failed to delete. I confirm with the service's own describe call before I treat a tagged name as still billed.

## SNS email missing after `up`

The first `up` created the topic `grow-room-poc-alerts` and no subscription, because `alert_email` was empty. Alerts were dropped. `up` now takes the address from `$env:ALERT_EMAIL`, then from `terraform.tfvars`, then from the GitHub variable `ALERT_EMAIL`. A subscription at `PendingConfirmation` still needs the inbox click. A second `up` does not send another confirmation once that click is done.

## Athena plugin install format

Grafana installs a plugin from `id@version`. The chart value is `grafana-athena-datasource@3.4.2` in `monitoring/values-k3d.yaml`. `grafana-athena-datasource 3.4.2`, with a space, does not install it. The datasource then has nothing to run a health check against.

## A `grafana.ini` change needs a restart

Grafana reads `grafana.ini` when the process starts. Argo CD updates the ConfigMap and does not, by itself, restart Grafana. After `[aws] forward_settings_to_plugins` or `allowed_auth_providers` changes, roll the `monitoring-grafana` deployment so the new file is the one the process opened. The commands are in [Athena in Grafana](ATHENA_GRAFANA.md).

## Athena credentials are not IMDS

The first sidecar spoke IMDSv2 on `127.0.0.1:9911`. The health check failed. Grafana 13 starts `grafana-athena-datasource` with a stripped environment and does not copy `AWS_EC2_METADATA_SERVICE_ENDPOINT` into the plugin, so that listener was never the plugin's endpoint.

The sidecar now runs the Roles Anywhere helper and serves a container-credentials document at `http://127.0.0.1:9911/credentials`. The Grafana container sets `AWS_CONTAINER_CREDENTIALS_FULL_URI` to that URL. `forward_settings_to_plugins` lists `grafana-athena-datasource`, which is what copies that variable into the plugin. The AWS SDK selects the container-credentials URI before it tries EC2 IMDS. Pull request [#86](https://github.com/TontoBlanco/grow-room-platform/pull/86) is that fix. The datasource health check now returns OK. No access key is in the chart or in this page.

## Where the longer notes are

| Symptom | Page |
| --- | --- |
| Home Assistant and the live scrape | [Week 4](phases/week-4-observability.md) |
| OIDC subject and the apply button | [Phase 1](phases/phase-1-oidc.md) |
| `up`, `verify`, `down` | [Phase 2](phases/phase-2-up-verify-down.md) |
| Drill order and `SensorDataStale` | [Phase 4](phases/phase-4-slos-and-drills.md) and [DRILLS.md](aws-poc/DRILLS.md) |
| Signing and Kyverno | [Phase 5](phases/phase-5-supply-chain.md) |
| The 3 November emails | [Test session](test-session/2026-11-03.md) |
| Athena plugin, restart, and credentials | [Athena in Grafana](ATHENA_GRAFANA.md) and [Phase 3](phases/phase-3-telemetry.md) |
