# Week 3: Helm Chart + Argo CD GitOps on k3d

Goal: wire **continuous delivery** for the grow-room sensor service the same way
production platforms do — Git is the desired state, Argo CD converges the
cluster, Helm packages the Kubernetes objects you already know how to write.

By the end of the week you have:

1. A **`charts/sensor-service`** Helm chart (Deployment, Service, SA, optional HPA).
2. A **`gitops/`** App-of-apps layout Argo CD can sync.
3. A local **k3d** cluster named `grow-room-dev` with Argo CD installed ($0 cloud).
4. A manual sync loop: change a value → commit/push → Argo sync → Pod rolls.
5. A clear plan for the later **CI → GitOps** handoff (bump `image.tag`) — you
   write that workflow yourself (sample at the bottom only).

You already operate Helm and Argo CD on the delivery side at work. This week is
the portfolio evidence that you can also **own the path from GHCR image → GitOps
values → running Pod** on a cluster you control, with zero AWS spend.

Try each step before peeking at the sample CI bump workflow at the bottom.

---

## Step 0: Copy the starter into your repo

From the unzipped week-3 pack:

```bash
# From your grow-room-platform clone root
cp -r path/to/grow-room-platform-week3/charts ./
cp -r path/to/grow-room-platform-week3/gitops ./
cp -r path/to/grow-room-platform-week3/scripts ./
cp path/to/grow-room-platform-week3/docs/WEEK3_GITOPS_GUIDE.md ./docs/
cp path/to/grow-room-platform-week3/docs/WEEK3_CI_NOTE.md ./docs/
# Optionally paste README_WEEK3_SNIPPET.md into README.md roadmap
```

Create a branch:

```bash
git checkout -b gitops-week3
```

Validate the chart **before** any cluster:

```bash
helm lint charts/sensor-service
helm template sensor charts/sensor-service >/tmp/sensor-rendered.yaml
# Optional: also render k3d overrides
helm template sensor charts/sensor-service -f charts/sensor-service/values-k3d.yaml | head
```

Commit and push `charts/`, `gitops/`, `scripts/`, and the docs. Argo CD pulls
from **GitHub**, not from your Downloads folder — same lesson as Week 2 when
`infra/` was missing from the Actions runner.

---

## Step 1: Mental model (for Kubernetes YAML folks)

| GitOps / Helm idea | What it is | Kubernetes analogy you already know |
|---|---|---|
| Helm chart (`charts/sensor-service`) | Parameterized package of manifests | A folder of YAML + a smart `envsubst` |
| `values.yaml` | Defaults for the package | ConfigMap data / Deployment args you used to hardcode |
| `values-k3d.yaml` | Env-specific overlay | A second overlays/`kustomization` patch |
| Templates (`templates/*.yaml`) | Go-templated Kubernetes objects | The Deployment/Service you write by hand |
| `helm template` | Dry-run render to YAML | `kubectl apply --dry-run=client -o yaml` on steroids |
| `helm upgrade --install` | Imperative install/upgrade | `kubectl apply` for a whole related set |
| Argo CD `Application` | CR that says "sync this Git path to this cluster/ns" | A long-lived `kubectl apply -f` that re-runs itself |
| App-of-apps (`root-app.yaml`) | Parent Application whose children are more Applications | Umbrella chart / Root `kustomization` that lists apps |
| Sync | Apply desired Git state to the live cluster | Controller reconcile loop |
| Health | Argo's opinion of Ready (Pods, Deployments, …) | `kubectl rollout status` + Ready conditions |
| Self-heal | Revert manual `kubectl` drift back to Git | Admission + controller fighting snowflakes |
| Image tag in values | The deployable version pointer | Changing `image:` in a Deployment |
| CI builds image; GitOps deploys it | Separation of CI vs CD | Build once → promote by Git commit, not by SSH |

```text
GitHub main
  charts/sensor-service/     ← Helm package (what to run)
  gitops/apps/*.yaml         ← Argo Applications (where/how to sync)
        │
        ▼
   Argo CD (in-cluster)
        │  helm template + apply
        ▼
   Deployment / Service / SA in namespace grow-room
        │
        ▼
   Pod pulls ghcr.io/tontoblanco/grow-room-platform:<tag>
```

### Key differences from "just kubectl apply"

- **Git is the API you edit.** Changing the live cluster by hand is drift; Argo
  self-heal puts Git back in charge (like a Deployment controller resetting a
  Pod you deleted — except for *all* managed objects).
- **Helm is a renderer, Argo is a reconciler.** You can use either alone.
  Together: Argo runs Helm (or plain YAML/Kustomize) on every sync.
- **Image digests/tags are the promotion knob.** CI pushes
  `ghcr.io/...:abc1234`. CD is a Git commit that sets `image.tag: abc1234`.
  That split is what interviews mean by "CI builds, GitOps deploys."
- **App-of-apps scales better than one giant chart.** Each child Application
  has its own sync window, health, and RBAC story — like separate Deployments
  instead of one Pod with twenty containers.

### Build it incrementally

1. Lint/template the chart with no cluster (Step 0).
2. Install tools; create k3d; install Argo CD (Steps 2–3).
3. Optional: `helm upgrade --install` once for a smoke test without GitOps.
4. Push to GitHub; apply `root-app.yaml`; watch Applications go Healthy.
5. Change a value; sync; confirm the Pod rolled.
6. Later: extend CI to bump `image.tag` (you write it; sample at the bottom).

---

## Step 2: Install tools (Windows-friendly)

You need **Docker**, **k3d**, **kubectl**, and **helm**. On Windows, **WSL2 +
Docker Desktop (WSL2 backend)** is the path of least pain for k3d. Git Bash can
run the script if Docker is reachable, but k3d issues show up less often in WSL2.

### Docker

Install Docker Desktop and enable the WSL2 backend. Confirm from WSL or PowerShell:

```bash
docker version
docker info
```

### kubectl

```bash
winget install Kubernetes.kubectl
kubectl version --client
```

### Helm

```bash
winget install Helm.Helm
helm version
```

### k3d

```bash
winget install k3d.k3d
k3d version
```

If winget IDs differ on your machine, use the official installers:

- Helm: <https://helm.sh/docs/intro/install/>
- k3d: <https://k3d.io/stable/#installation>
- kubectl: <https://kubernetes.io/docs/tasks/tools/>

### Sanity check

```bash
docker info && kubectl version --client && helm version && k3d version
```

You do **not** need an AWS account, `eksctl`, or Terraform apply for Week 3.

---

## Step 3: Create the k3d cluster

From WSL2 (recommended) or any shell where the tools work:

```bash
k3d cluster create grow-room-dev --agents 2
kubectl get nodes
```

Or use the helper (also installs Argo CD):

```bash
# From repo root, after copying scripts/
./scripts/bootstrap-k3d.sh
```

**Why k3d?** It is a lightweight Kubernetes (k3s) inside Docker. Same API as
EKS for Deployments, Services, Helm, and Argo CD — without a VPC, NAT gateway,
or control-plane bill. Week 2's `cluster_mode = "local"` was pointing at this
world.

Tear down when you want the RAM back:

```bash
k3d cluster delete grow-room-dev
```

---

## Step 4: Install Argo CD and open the UI

If you did not use the bootstrap script:

```bash
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --version 7.7.12 \
  --set configs.params."server\.insecure"=true \
  --wait
```

Port-forward:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

Open `https://localhost:8080` (self-signed cert is expected). Login:

- User: `admin`
- Password:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Change the password after first login in a real shared cluster; for a disposable
k3d lab the initial secret is fine.

**Analogy:** Argo CD's Application controller is a Deployment controller for
*Git paths*. Instead of reconciling Pod template hash → Pods, it reconciles
Git commit → live objects.

---

## Step 5: App-of-apps and the sensor Application

### What you are applying

| File | Role |
|------|------|
| `gitops/root-app.yaml` | Parent Application; source path `gitops/apps` |
| `gitops/apps/sensor-service.yaml` | Child Application; Helm path `charts/sensor-service` |
| `gitops/apps/kustomization.yaml` | Optional; helps `kubectl apply -k` manual boots |

Edit `repoURL` in both Application manifests if your fork path differs (default
assumes `https://github.com/TontoBlanco/grow-room-platform.git`).

### Apply the root

**Prerequisite:** `charts/` and `gitops/` are on GitHub `main` (or the
`targetRevision` you set).

```bash
kubectl apply -n argocd -f gitops/root-app.yaml
kubectl -n argocd get applications
```

Within a minute you should see `grow-room-root` and `sensor-service`. The child
creates namespace `grow-room` and syncs the chart.

```bash
kubectl -n grow-room get deploy,svc,pods
```

### Optional smoke without GitOps first

Useful if you want a Pod before the GitHub round-trip:

```bash
helm upgrade --install sensor ./charts/sensor-service \
  -n grow-room --create-namespace \
  -f ./charts/sensor-service/values-k3d.yaml
kubectl -n grow-room port-forward svc/sensor-sensor-service 8000:8000
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readings
```

Delete that release before letting Argo manage the same names, or use a
different release name, so you do not fight ownership.

---

## Step 6: Chart walkthrough (values → templates → Pod)

Open `charts/sensor-service/values.yaml` and map each knob to a template:

| Value | Lands in | Why it matters |
|-------|----------|----------------|
| `image.repository` / `image.tag` | Deployment container image | **Promotion knob** for CI→CD |
| `imagePullSecrets` | Pod spec | Empty for public GHCR; set name for private |
| `replicaCount` | Deployment `spec.replicas` | Ignored when HPA enabled |
| `env.SENSOR_SOURCE` | Container env | Default `simulator` → no secrets for demos |
| `env.LEAF_TEMP_OFFSET_C` | Container env | Leaf VPD offset (tent calibration) |
| `homeAssistant.existingSecret` | optional `HA_TOKEN` envFrom | HA path off by default |
| `probes.*.path` | liveness/readiness | `/healthz` — cheap, no sensor I/O |
| `service.port` | Service + containerPort | FastAPI listens on **8000** |
| `podSecurityContext` / `securityContext` | Pod/container | Non-root UID 10001, drop caps, read-only root |
| `autoscaling.enabled` | HPA template gated | Default `false` for k3d simplicity |

`values-k3d.yaml` overlays LoadBalancer + Always pull + a sample leaf offset.
Argo's Application lists both files under `helm.valueFiles` (later files win on
key conflicts — same idea as Helm CLI `-f a -f b`).

Render locally whenever you change a template:

```bash
helm template sensor charts/sensor-service \
  -f charts/sensor-service/values-k3d.yaml \
  --set image.tag=deadbeef | less
```

If the rendered YAML looks wrong, Argo will deploy the wrong thing too — fix
the chart before you sync.

---

## Step 7: Manual sync loop (feel the GitOps)

1. In Git, change something safe, e.g. in `charts/sensor-service/values-k3d.yaml`:

   ```yaml
   env:
     LEAF_TEMP_OFFSET_C: "-1.5"
   ```

2. Commit and push to the branch Argo tracks (`HEAD` / `main`).
3. In the Argo UI, open `sensor-service` → **Refresh** → **Sync** (or wait for
   auto-sync).
4. Watch the Deployment roll:

   ```bash
   kubectl -n grow-room rollout status deploy/sensor-service
   kubectl -n grow-room get pods -w
   ```

5. Port-forward and confirm `/readings` still works.

**What you just practiced:** desired state changed in Git; the cluster
converged without `kubectl apply` from your laptop. That is the CD half of
CI/CD.

---

## Step 8: Cost — stay at $0 this week

| Path | Cost |
|------|------|
| k3d on your PC/WSL2 | **$0** |
| Argo CD on k3d | **$0** |
| Public GHCR pulls | **$0** |
| EKS + NAT (Week 2 module, later) | Real money — Budgets **$20** alert first |

Do **not** point these Applications at EKS until you deliberately flip Week 2
flags and accept the bill. This pack never runs `terraform apply`.

---

## Step 9: GHCR public vs private (ImagePullBackOff)

Week 1 pushed `ghcr.io/tontoblanco/grow-room-platform`. New GHCR packages are
**private by default**.

- **Public package:** cluster pulls with no credentials. Leave
  `imagePullSecrets: []`.
- **Private package:** create a pull Secret and set it on the chart:

  ```bash
  kubectl -n grow-room create secret docker-registry ghcr-pull \
    --docker-server=ghcr.io \
    --docker-username=YOUR_GITHUB_USER \
    --docker-password=YOUR_GHCR_PAT \
    --docker-email=you@example.com
  ```

  Then in values (or Argo Helm parameters):

  ```yaml
  imagePullSecrets:
    - name: ghcr-pull
  ```

PAT needs at least `read:packages`. Prefer a fine-grained token scoped to that
package. Never commit the PAT into Git.

Make the package public (GitHub → Packages → package settings) if you want
recruiters and k3d nodes to pull without auth.

---

## Step 10: Definition of done (Week 3)

- [ ] `charts/`, `gitops/`, `scripts/`, and docs merged to GitHub
- [ ] `helm lint` and `helm template` pass locally
- [ ] k3d cluster `grow-room-dev` runs Argo CD
- [ ] `grow-room-root` + `sensor-service` Applications are Synced/Healthy
- [ ] Manual value change syncs and rolls the Pod
- [ ] `/healthz` and `/readings` work via port-forward (simulator)
- [ ] README roadmap Week 3 checkbox updated
- [ ] You have **not** spent AWS money for this week
- [ ] Notes / study log updated with what you wired and why

Week 4 adds Prometheus scraping `/metrics` and a Grafana VPD dashboard on the
same cluster.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Application `ComparisonError` / repo not found | `charts/` or `gitops/` not on the Git revision Argo tracks | Push to GitHub; check `repoURL` / `targetRevision` |
| `ImagePullBackOff` | Private GHCR or wrong tag | Make package public, fix tag, or add `imagePullSecrets` |
| `CrashLoopBackOff` | Bad env / app error | `kubectl -n grow-room logs deploy/…`; confirm image runs with `SENSOR_SOURCE=simulator` |
| Sync failed, schema error | Chart rendered invalid YAML | `helm template …` locally; fix templates |
| Health Degraded | Readiness failing | Hit `/healthz` via port-forward; check probe paths/ports |
| Service has no endpoints | Label selector mismatch | Compare Deployment template labels vs Service selector |
| k3d cannot start on Windows | Docker not using WSL2 / virtualization off | Enable WSL2 backend; run bootstrap from WSL |
| `helm upgrade` fights Argo | Two managers of same objects | Uninstall the manual release or disable Argo auto-sync while experimenting |
| Root synced but no child | Child YAML not in `gitops/apps/` or invalid Application CR | `kubectl -n argocd describe app grow-room-root` |
| Port-forward UI blank | Wrong port / HTTP vs HTTPS | Use `https://localhost:8080` with the insecure chart setting above |

---

## Interview talking points (mid-level DevOps)

Practice saying these against this repo:

1. **CI vs CD:** "CI builds and scans the image to GHCR. CD is Argo CD syncing a
   Helm chart; promotion is a Git change to `image.tag`, not a kubectl from my
   laptop."
2. **App-of-apps:** "A root Application owns the apps folder; each child is its
   own sync/health boundary — same idea as an umbrella chart without one giant
   release."
3. **Local first:** "I prove the chart and GitOps loop on k3d at zero cost, then
   the same manifests can target EKS when a budget alert is in place."
4. **Honest boundary:** "At work I operate Helm/Argo on the delivery side. This
   portfolio is where I own the full path from Dockerfile → GHCR → values bump →
   synced Deployment for a real sensor API."

Avoid claiming you built the org's Argo platform or ran production EKS for this
project until you actually do those things.

---

## Reference: SAMPLE only — CI bump of `image.tag`

**Do not** copy this blindly into production. Write your own workflow when you
are ready (see `docs/WEEK3_CI_NOTE.md`). This sample shows the *shape* of the
hand-off: after a successful image push, open a PR or commit that updates the
tag Argo deploys.

```yaml
# SAMPLE ONLY — .github/workflows/gitops-bump-image.sample.yml
# Label: SAMPLE. Prefer a PR bot (update values → review → merge) over
# direct pushes to main until you are comfortable with the blast radius.
name: gitops-bump-image-SAMPLE

on:
  workflow_run:
    workflows: ["ci"]          # name must match your real CI workflow
    types: [completed]
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  bump:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Derive tag (example — use the same tag CI pushed)
        id: meta
        run: echo "tag=${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"

      - name: SAMPLE — patch values tag
        run: |
          # Prefer yq in real life; sed is shown for minimal dependencies.
          sed -i "s/^  tag: .*/  tag: \"${{ steps.meta.outputs.tag }}\"/" \
            charts/sensor-service/values.yaml

      - name: SAMPLE — open PR for Argo to pick up after merge
        uses: peter-evans/create-pull-request@v6
        with:
          commit-message: "gitops: bump sensor-service to ${{ steps.meta.outputs.tag }}"
          title: "gitops: bump sensor-service to ${{ steps.meta.outputs.tag }}"
          body: |
            Automated tag bump after CI published the image.
            Argo CD syncs after merge (SAMPLE workflow).
          branch: gitops/bump-${{ steps.meta.outputs.tag }}
```

Better production shapes (study when you extend CI yourself):

- CI outputs the exact tag/digest as an artifact; bump job consumes it.
- Update `values.yaml` **or** set Helm parameters on the Application via
  ApplicationSet / PR — avoid two sources of truth.
- Require PR review on `charts/**` and `gitops/**` even if CI is automated.

---

## Extra credit

- Add a second Application for a future `prometheus` stack (Week 4 preview).
- Pin images by digest (`@sha256:…`) in values for stronger supply-chain story.
- Replace LoadBalancer with an Ingress + k3d Traefik routes.
- Point `destination` at a second kubecontext (remote) once EKS exists — same
  Application CR shape, different API server.
