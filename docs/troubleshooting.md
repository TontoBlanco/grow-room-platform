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

## Where the longer notes are

| Symptom | Page |
| --- | --- |
| Home Assistant and the live scrape | [Week 4](phases/week-4-observability.md) |
| OIDC subject and the apply button | [Phase 1](phases/phase-1-oidc.md) |
| `up`, `verify`, `down` | [Phase 2](phases/phase-2-up-verify-down.md) |
| Drill order and `SensorDataStale` | [Phase 4](phases/phase-4-slos-and-drills.md) and [DRILLS.md](aws-poc/DRILLS.md) |
| Signing and Kyverno | [Phase 5](phases/phase-5-supply-chain.md) |
| The 3 November emails | [Test session](test-session/2026-11-03.md) |
