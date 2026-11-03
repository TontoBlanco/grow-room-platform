# Threat model

This is a STRIDE pass over the system as it is in Git, plus what the 1 November and 3 November sessions showed. STRIDE is a checklist: spoofing, tampering, repudiation, information disclosure, denial of service, and elevation of privilege. I am not claiming an assessment or an authorization.

The grower is an indoor plant grow tent. The service is read-only toward the controller.

## What I am protecting

| Asset | Where it sits |
| --- | --- |
| Home Assistant token `HA_TOKEN` | `.env`, gitignored |
| Tent readings | Compose, Prometheus for 24 hours, the telemetry bucket |
| Audit history | SQLite, optional Postgres, or RDS during a session |
| Container image | `ghcr.io/tontoblanco/grow-room-platform` |
| AWS credentials | OIDC for CI, Pod Identity on EKS, Roles Anywhere on the PC |
| Terraform state | The state bucket encrypted with alias `alias/grow-room/tfstate` |

## Spoofing

Someone who has `HA_TOKEN` can read the same entities the service reads. The service does not call Home Assistant services, so the token as I use it cannot change a setpoint. A stolen token is still a read of the tent.

The home shipper is trusted if it presents a certificate with CN `grow-room-home-shipper` signed by `grow-room-home-ca`. A stolen client key is the spoofing path. There is no AWS access key on that PC to steal instead.

GitHub Actions is trusted by the OIDC subject. The plan role accepts the repository. The apply role accepts only the `aws-poc` environment. A workflow that forgets `environment: aws-poc` cannot assume the apply role. A workflow that has it, and a person who approves the environment, can.

## Tampering

The audit hash detects a changed row only if the attacker does not recompute the chain. I do not have an external anchor.

S3 objects can be overwritten by anything that has `s3:PutObject` on that key. The shipper role has that on `readings/*`. It does not have delete. Overwrite is still tampering.

Image tags move. CI signs the digest. Kyverno is in Audit, so a bad image is reported, not rejected.

## Repudiation

The audit `actor` is a field the client sends. I do not authenticate it. Alert emails show the alert name and the summary. They do not prove who scaled a deployment. CloudTrail would, for AWS API calls, and I am not pasting a trail review here. I have not documented a CloudTrail digest check in this repository.

## Information disclosure

`/metrics` and `/readings` on the Compose port are not authenticated. The port is published on the Docker host so k3d can scrape it. On a shared network that is a read of the climate.

The telemetry bucket blocks public access and denies non-TLS. The role cannot list. An object URL still needs a principal that can get the object. The shipper cannot.

Grafana's lab password is in `monitoring/values-k3d.yaml`. That file is in Git. It is a lab password on localhost, and it is still a password in the repository.

The Terraform backend file names the state bucket and the KMS key id. I am not copying those values into this site. They are already in `infra/aws-poc/versions.tf`.

Email alerts leave AWS and land in an inbox. The 3 November screenshots originally showed the inbox address and, on the confirmation, the topic ARN. The copies under `docs/assets/test-session/` have those blurred.

## Denial of service

The laptop lid stops the live scrape. That is availability of the chart, not of the tent. The controller keeps running.

WAF `grow-room-poc-alb` has the common rule set and a rate limit of 500 requests per five minutes per IP, when the stack is up. WAF logging was off.

Scaling `sensor-service` to zero on EKS makes the site fail and fires `SensorDataStale`. Drill 4 does that on purpose and then restores the replicas.

The Athena workgroup stops a query at 1 GB so a wide scan does not become the outage or the bill.

## Elevation of privilege

`grow-room-gha-apply` is `AdministratorAccess`. A person who can approve environment `aws-poc` can do more than apply this stack. I have not narrowed that role.

Pod Identity roles are narrower: the shipper on EKS can put `raw/*`, Alertmanager can publish to one topic, ExternalDNS can edit one hosted zone, External Secrets can read the RDS secret. Those are the policies in `infra/aws-poc/pod-identity.tf` and `alerting.tf`.

The container is non-root with a read-only root filesystem. There is no NetworkPolicy in the chart. A compromised pod is not boxed in by a policy I wrote.

## What I am not modeling

I am not modeling a hostile roommate with physical access to the tent, and I am not modeling a supply-chain attack on the GitHub-hosted runners beyond the pinned actions and the scan. Those are real and they are outside what I have evidence for.
