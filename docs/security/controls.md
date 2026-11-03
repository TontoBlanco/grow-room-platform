# Controls

I checked these against the files on `main` after pull request [#75](https://github.com/TontoBlanco/grow-room-platform/pull/75). **Verified** means the control is in the repository and I can point at it. **Reported** means a session said it worked and I do not have a new artifact in this change. **Planned** means it is not in force.

| Control | Status | Where I looked |
| --- | --- | --- |
| IAM Roles Anywhere, write-only shipper | Verified in Git. The live upload is reported from the telemetry work and from the 3 November exporter path. | `infra/telemetry/main.tf`. Role `grow-room-home-shipper`, policy `put-readings`, actions `s3:PutObject` on `readings/*` only, plus `kms:GenerateDataKey` and `kms:Decrypt` on the telemetry key. Trust requires CN `grow-room-home-shipper` and trust anchor `grow-room-home-ca`. |
| KMS | Verified for the keys listed in [IAM and secrets](iam-and-secrets.md). Not universal. | `infra/aws-poc/kms.tf`, bootstrap, `infra/telemetry/main.tf`. The SNS topic uses `alias/aws/sns` on purpose (`AWS-0136`). The Athena query-results bucket in the proof of concept uses SSE-S3 (`AWS-0132` in `.trivyignore`). |
| EKS Pod Identity | Verified in Terraform. It exists only while the cluster exists. | Add-on `eks-pod-identity-agent` in `infra/aws-poc/eks.tf`. Associations in `pod-identity.tf` and `alerting.tf`. No access keys in those files. |
| Kyverno with keyless cosign | Partial. Signing is verified in CI. Admission is Audit, not Enforce. The 3 November cluster reported `no signatures found` before the cosign 2.6.5 pin. I have not seen a passing PolicyReport since that pin. | `.github/workflows/ci.yml` installs cosign `v2.6.5`, signs with `--registry-referrers-mode=legacy`, verifies the identity. `k8s/aws-poc/kyverno-verify-images.yaml` has `failureAction: Audit`, `mutateDigest: false`, `verifyDigest: false`. Enforce is documented in that file and not applied. |
| Trivy | Verified. | Image scan in `ci.yml` before push. Config scan in `aws-poc-plan.yml`. Action pin `aquasecurity/trivy-action` at `ed142fd0673e97e23eac54620cfb913e5ce36c25` (`v0.36.0`). Fails on HIGH and CRITICAL. Image scan sets `ignore-unfixed: true`. Config ignores are the five ids in `infra/aws-poc/.trivyignore`, each with a reason. |
| OIDC for CI | Verified. | Bootstrap trust in `infra/aws-poc/bootstrap/main.tf`. Plan workflow assumes `grow-room-gha-plan` with `id-token: write`. Apply and destroy are manual and use environment `aws-poc`. |
| Non-root, read-only root filesystem | Verified. | `Dockerfile` user 10001. `charts/sensor-service/values.yaml` sets `runAsUser: 10001`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, seccomp `RuntimeDefault`, service account `automount: false`. |
| Image signing and SBOM | Verified on push to `main` only. Pull request builds do not sign. | `ci.yml` steps `syft SBOM` and `cosign sign + attest`. |
| WAF on the load balancer | Verified in Terraform. It was attached during the 1 November session, reported in the gallery. Logging was off. | `infra/aws-poc/edge.tf`, `enable_waf` default true. Rules: `AWSManagedRulesCommonRuleSet` and a rate limit. |
| S3 public access block and TLS-only telemetry bucket | Verified. | `infra/telemetry/main.tf` and the sensor bucket in `infra/aws-poc/data.tf`. |
| RDS not public, Multi-AZ | Verified in Terraform. Failover on 3 November is reported on the [test session](../test-session/2026-11-03.md) page. | `infra/aws-poc/data.tf`. Security group allows 5432 from the node security group. |
| NetworkPolicy | Not found. Planned only as a note in the Week 4 guide. | No `NetworkPolicy` manifest in the chart or in `k8s/`. |
| Kyverno Enforce | Planned. The switch is a comment in the policy file. | Do not describe the cluster as rejecting unsigned images. |
| Dependabot or Renovate | Not found. On the [roadmap](../project-management/roadmap.md). | No `.github/dependabot.yml` and no Renovate config. |
| WAF logging, one-day log retention, admin apply role | These are the settings, and they are weak on purpose for a one-day lab. I am not listing them as controls that hold. | Gallery limits, `.trivyignore`, bootstrap comments. |

If a row says reported, I am telling you what the session record says. I am not upgrading it to verified because the stack is already destroyed.
