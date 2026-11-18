# Phase 5 — Signing, the software bill of materials, and the scan gate

The scan has been in CI since Week 1. This phase pinned the actions, added the bill of materials and keyless signing, and added a Kyverno policy. The policy pull request is [#62](https://github.com/TontoBlanco/grow-room-platform/pull/62). The cosign pin that Kyverno can actually see landed in [#75](https://github.com/TontoBlanco/grow-room-platform/pull/75).

A software bill of materials is the list of what is inside the image. Keyless signing means the signature comes from a short-lived certificate, not from a private key stored in the repository. Kyverno is the admission policy in the cluster.

## What I built

On a push to `main`, job `build` in `.github/workflows/ci.yml`:

1. Builds the image locally and does not push yet.
2. Runs Trivy `v0.36.0`, pinned by commit SHA, severity `CRITICAL,HIGH`, `ignore-unfixed: true`, exit code 1.
3. Pushes the digest and tags.
4. Writes an SPDX JSON bill of materials with Syft `v0.24.3`.
5. Signs the digest with cosign `v2.6.5` and `--registry-referrers-mode=legacy`, then attests the bill of materials.
6. Runs `cosign verify` with certificate identity `https://github.com/TontoBlanco/grow-room-platform/.github/workflows/ci.yml@refs/heads/main` and issuer `https://token.actions.githubusercontent.com`.

The job has `id-token: write` so cosign can get the GitHub token. The signature is on the digest, not on a moving tag.

`k8s/aws-poc/kyverno-verify-images.yaml` is a ClusterPolicy named `verify-grow-room-images`. It matches pods in namespace `grow-room` whose image is `ghcr.io/tontoblanco/grow-room-platform*`. `failureAction` is `Enforce`. `mutateDigest` and `verifyDigest` are true. Enforce was validated on 18 November 2026 after an Audit pass. The same identity string as CI is the attestor. Rekor is `https://rekor.sigstore.dev`. The record is the [18 November test session](../test-session/2026-11-18.md).

The Terraform Trivy scan is in `aws-poc-plan.yml`, same action pin, with `skip-dirs: "**/examples"` so example YAML inside modules is not the finding list.

## Why

I wanted a failed scan to stop the push, and I wanted a signature a cluster policy could check later. I did not want to store a cosign key. See the supply-chain rows in [Controls](../security/controls.md).

## Data flow

```mermaid
flowchart LR
  BUILD["local image"] --> TRIVY["Trivy gate"]
  TRIVY --> PUSH["push digest"]
  PUSH --> SBOM["Syft SPDX"]
  SBOM --> SIGN["cosign sign digest"]
  SIGN --> VERIFY["cosign verify in the log"]
  VERIFY --> KYV["Kyverno Enforce on EKS"]
```

## Rebuild

Signing runs only on a push to `main`. A pull request build scans and does not sign. Merge through a pull request. After the `ci` workflow on `main` is green, the log should contain `verified ghcr.io/tontoblanco/grow-room-platform@sha256:...`.

Kyverno is optional and only while the cluster is up. That is a paid session.

```powershell
helm repo add kyverno https://kyverno.github.io/kyverno/
```

```powershell
helm upgrade --install kyverno kyverno/kyverno -n kyverno --create-namespace --version 3.9.2 --wait
```

`--version 3.9.2` is the pin. That chart is Kyverno v1.19.2, which is what the 18 November session installed. Chart 3.10.0 is Kyverno v1.20.0. `ClusterPolicy` `verifyImages` is slated for removal in v1.20.0, so this install stays on 3.9.2. Then:

```powershell
kubectl apply -f k8s/aws-poc/kyverno-verify-images.yaml
```

The file in Git is already Enforce. On 18 November 2026, Audit PolicyReports for `ghcr.io/tontoblanco/grow-room-platform:sha-c8985e5` were `pass=1` and `fail=0` on the sensor-service pods, the ReplicaSets, and the Deployment. `failureAction`, `mutateDigest`, and `verifyDigest` then changed together to `Enforce`, `true`, and `true`. Kyverno rejects `mutateDigest: true` while the action is Audit. Images signed only as cosign 3 referrers still fail the check. The dry-run of `sha-8b294a9` that day was denied with `no signatures found`. The session is [18 November](../test-session/2026-11-18.md).

The policy kind `ClusterPolicy` with `verifyImages` is deprecated in Kyverno 1.19 in favor of `ImageValidatingPolicy`. I have not migrated it. That migration is a later task.

## Cost

GHCR for this public repository, and the public Rekor and Fulcio services, are not an AWS bill. Installing Kyverno requires the EKS session. Do not leave the cluster up only to watch a policy report.

## What I learned

CI said the image was signed. Kyverno on 3 November said `no signatures found`. Both were telling the truth about different lookups. Cosign 3 wrote an OCI referrer. Kyverno 1.19 looked up the legacy tag `sha256-<digest>.sig`. Pinning cosign `v2.6.5` and `--registry-referrers-mode=legacy` publishes the tag Kyverno reads. Kyverno 1.19 still only sees that legacy `.sig` tag.

Enforce is validated. On 18 November 2026 the Audit reports passed, and the policy in Git is Enforce with `mutateDigest: true` and `verifyDigest: true`. A rollout restart admitted `sha-c8985e5` and Kyverno pinned `sha256:2393330813cde2b85a3af42a35e69910741ae4a2325deefdab2f20c1f0871c58`. The same lessons are on the [troubleshooting page](../troubleshooting.md) and the [18 November test session](../test-session/2026-11-18.md).
