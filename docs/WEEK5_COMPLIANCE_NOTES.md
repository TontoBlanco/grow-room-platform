# Week 5 compliance notes (educational)

Personal CEA / portfolio talking points. **Not** a claim that this home lab is
STIGed, FedRAMP authorized, or METRC-certified. Use these as interview vocabulary
backed by artifacts in *this* repo.

Cole's Security+ and cleared DoD background are real credentials — describe
them as *background*, not as "I STIGed grow-room-platform in production."

---

## 1. STIG-style hardening checklist (chart / image)

Treat each row as a **lab control**. Mark what you already do from Weeks 1–4.

| Control theme | Lab practice in this repo | Status to fill |
|---|---|---|
| Minimal base image | Dockerfile uses a slim/official Python image | [ ] confirm tag |
| Non-root container | Run as non-root USER in Dockerfile / securityContext | [ ] |
| Read-only root FS where possible | Pod `securityContext.readOnlyRootFilesystem` + emptyDir for tmp | [ ] |
| No privileged | `privileged: false`; drop caps | [ ] |
| Resource limits | Helm values set CPU/memory requests+limits (Week 3 chart) | [ ] |
| Health probes | `/healthz` liveness/readiness already on sensor Service | [ ] |
| Network least privilege | k3d NetworkPolicy optional; no public LoadBalancer needed | [ ] |
| Secrets not in Git | `.env` git-ignored; HA token never committed (Week 1) | [ ] |
| Image provenance | GHCR images from CI; pin digests when ready | [ ] |
| Vulnerability scan | Trivy in Week 1 CI | [ ] |
| Audit evidence | Week 5 `/audit` append-only events + integrity check | [ ] |
| IaC review before spend | Terraform `fmt`/`validate`/`tflint`; no surprise `apply` (Week 2) | [ ] |

Kubernetes analogy: STIGs are long checklists; your Helm values + CI gates are
the **executable subset** you can show in a demo.

### Example Pod securityContext snippet (optional)

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  fsGroup: 10001
  seccompProfile:
    type: RuntimeDefault
containers:
  - name: sensor-service
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
```

If you enable `readOnlyRootFilesystem`, mount a volume for `AUDIT_DB_PATH`
(emptyDir or the PVC snippet) and for any temp dirs uvicorn needs.

---

## 2. SBOM, signing, and Trivy (conceptual)

| Idea | What it means | What you can say honestly |
|---|---|---|
| SBOM | Software Bill of Materials — inventory of dependencies | "I can generate one with Syft/Trivy image SBOM in CI when I add the step" |
| Image signing | Cosign/Sigstore attestations that the digest came from your pipeline | "Not wired yet; GHCR + branch protection is the current trust path" |
| Trivy | Scanner you already run in Week 1 CI | "Fails the build on HIGH/CRITICAL per the workflow I authored" |
| Provenance | Link commit → image digest → cluster tag | "GitOps bump of `image.tag` (Week 3) is the deploy attestation trail" |

Practical Week 5 add (optional, you author CI):

```bash
# Local / CI idea — not a finished workflow file
trivy image --exit-code 1 --severity HIGH,CRITICAL ghcr.io/<you>/sensor-service:<tag>
trivy image --format cyclonedx --output sbom.cdx.json ghcr.io/<you>/sensor-service:<tag>
```

Do **not** paste a complete Actions workflow from this pack — see
`WEEK5_CI_NOTE.md`.

---

## 3. Least-privilege IAM / RBAC (k3d / local)

Stay on k3d for daily work. Map cloud IAM ideas to what you already touch:

| Concern | Local / k3d practice | Cloud note (do not apply yet) |
|---|---|---|
| Cluster admin | Your kubeconfig is admin on the hobby cluster — accept that for labs | EKS: separate break-glass vs deployer roles |
| Deploy rights | Argo CD reconciles from Git; humans merge PRs | IRSA / workload identity later |
| App runtime | Sensor Service needs read to HA token (secret) + write to audit DB path | No AWS keys in the Pod |
| Metrics | Prometheus scrapes `/metrics` only | NetworkPolicy to monitoring ns later |
| Audit DB | File permissions on PVC/emptyDir; no anonymous write API beyond app | RDS IAM auth is out of scope for $0 week |

Interview line:

> "On the lab cluster I treat Git as the control plane and keep runtime
> credentials to the minimum the Pod needs — Home Assistant read token and a
> local SQLite path — instead of long-lived cloud keys."

---

## 4. Audit log as a compliance control

Week 5's `/audit` module supports conversations about:

- **Identification** — stable plant/batch IDs
- **Attribution** — `actor` on every event
- **Integrity** — hash chain + `/audit/integrity`
- **Non-repudiation (light)** — append-only API surface (405 on mutate)
- **Disposition** — `destroyed` / `packaged` terminal paths

Gaps to name out loud (shows maturity): no mutual TLS, no SSO, no WORM bucket,
no external timestamp authority, SQLite is not multi-node HA. Naming gaps beats
overclaiming.

---

## 5. Resume / portfolio accuracy

Allowed:

- Personal project implementing append-only lifecycle auditing for CEA.
- Discussing STIG-*style* hardening and authorization-package analogies.
- Listing Security+, clearance eligibility/status as *your* credentials.

Avoid:

- Implying this repo was deployed for a regulated licensee or DoD system.
- Listing METRC, Leaf Data, or state APIs as integrations you shipped.
- Inventing production incident response stories from this lab.

---

## 6. Quick demo script for interviews

1. Show Grafana VPD (Week 4) — operations telemetry.
2. Show `/audit/history` for a plant — compliance evidence.
3. Flip to `WEEK5_COMPLIANCE_NOTES.md` checklist — security mindset.
4. Mention Terraform modules validated without unpaid `apply` — cost control.
