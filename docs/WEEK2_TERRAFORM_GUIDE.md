# Week 2: Author Terraform Modules (from scratch)

Goal: you **write** the Terraform for this project yourself — not just tweak
someone else's. By the end of the week you have:

1. A reusable **`modules/network`** (VPC, subnets, IGW, optional NAT).
2. A reusable **`modules/cluster`** (`local` k3d path + `eks` IAM/SG stubs).
3. A root **`infra/`** that composes them with variables and outputs.
4. CI checks: **`terraform fmt`**, **`validate`**, **`tflint`** (and later a
   safe `plan`).
5. A remote-state stub and an AWS Budgets **$20** reminder before any paid apply.

You already modify Terraform at work. Job forms ask whether you have authored
modules from scratch — this week is the evidence in a public repo.

Try each step before peeking at the reference CI workflow at the bottom.

---

## Step 0: Copy the starter into your repo

From the unzipped week-2 pack:

```bash
# From your grow-room-platform clone root
cp -r path/to/grow-room-platform-week2/infra ./
cp path/to/grow-room-platform-week2/docs/WEEK2_TERRAFORM_GUIDE.md ./docs/
# Optionally paste README_WEEK2_SNIPPET.md into README.md roadmap
```

Create a branch:

```bash
git checkout -b terraform-week2
```

Install tools locally (Windows: use `winget` / Chocolatey / the HashiCorp zip):

```bash
terraform version   # >= 1.6
tflint --version    # optional but used in CI
```

---

## Step 1: Mental model (for Kubernetes YAML folks)

| Terraform idea | What it is | Kubernetes analogy |
|---|---|---|
| Root module (`infra/*.tf`) | The composition layer you run `plan`/`apply` against | An umbrella Helm chart / App-of-apps |
| Child module (`modules/...`) | Reusable package with its own inputs/outputs | A subchart or a CRD controller's API |
| `variable` | Input to a module | Helm `values.yaml` keys / Deployment args |
| `output` | Exported value other modules or humans consume | Chart `NOTES.txt` + exported Service name |
| `resource` | Something Terraform creates/updates/deletes | A Kubernetes object in etcd |
| `data` source | Read-only lookup of something that already exists | A read of an existing ConfigMap/Secret |
| State (`terraform.tfstate`) | Source of truth for what Terraform manages | etcd (for *cloud* objects, not Pods) |
| Backend + lock | Shared state + mutual exclusion | etcd + lease/leader election |
| `for_each` / `count` | Create N similar objects | A loop generating N Deployments |
| Provider | Plugin that talks to an API (AWS, etc.) | A cloud controller / CCI |
| `terraform.tfvars` | Concrete values for variables | An env-specific values file |

```hcl
# Root (infra/main.tf) — like values that call subcharts
module "network" {
  source = "./modules/network"   # path to child module
  vpc_cidr = var.vpc_cidr        # pass inputs down
}

# Child (modules/network/outputs.tf) — export for siblings/root
output "vpc_id" {
  value = aws_vpc.this.id
}
```

### Key differences from Kubernetes YAML

- **Terraform is graph-oriented, not list-oriented.** Resources form a
  dependency graph. You rarely need explicit `depends_on`; references like
  `aws_vpc.this.id` create edges automatically (similar to ownerReferences,
  but for create/destroy order).
- **State is mandatory.** `kubectl apply` is mostly server-side declarative.
  Terraform compares desired config → provider API ← recorded state. Lose
  state without a backup and Terraform forgets what it owns.
- **Plan before apply.** Always read `terraform plan`. It is your dry-run /
  server-side-apply diff.
- **Modules are just folders.** There is no separate "module registry" required
  for local `./modules/...` paths. Publishing to the public registry is optional.
- **`count` vs `for_each`.** Prefer `for_each` with stable keys (AZ names,
  map keys). `count` with a list reshuffles indexes when you insert an item —
  like renaming indexed StatefulSet pods by accident.

### Build it incrementally

1. Read the starter modules; run `fmt` / `validate` locally (Step 2).
2. Change a variable default; re-validate.
3. Add Terraform CI jobs (Step 6) — write the workflow yourself.
4. Only when you are ready: AWS Budgets alert → optional `plan` with real creds.
5. Do **not** enable NAT or `cluster_mode=eks` until you understand the bill.

---

## Step 2: Format and validate (no AWS account required)

From `infra/`:

```bash
terraform fmt -recursive -check   # non-zero exit if files need formatting
terraform fmt -recursive          # rewrite files to canonical style
terraform init -backend=false     # download providers; skip remote state
terraform validate
```

**Why `-backend=false`?** CI and laptops without an S3 backend should still
check that the configuration is syntactically and referentially valid.
`validate` does **not** call AWS. It does not need credentials.

**Why this matters in interviews:** you can explain the difference between
*static* checks (`fmt`, `validate`, `tflint`) and *dynamic* checks (`plan`
against a real account). Mid-level DevOps expects both in CI.

---

## Step 3: Module vs root — what you authored

```
infra/
  main.tf                 # wires modules (composition only)
  variables.tf            # root inputs
  outputs.tf              # root exports
  versions.tf             # required_version + required_providers
  providers.tf            # provider "aws" { ... }
  backend.tf.example      # remote state template (not active until renamed)
  terraform.tfvars.example
  modules/
    network/              # YOU authored: VPC, subnets, IGW, optional NAT
    cluster/              # YOU authored: local outputs OR eks IAM+SG stubs
```

**Root responsibilities:** choose names, pass variables, expose outputs, pick
backends/providers. Keep root thin.

**Module responsibilities:** own a bounded piece of infrastructure. The network
module should not create IAM roles; the cluster module should not create the VPC.
That separation is what "authoring modules" means on a resume.

### Exercise

In `modules/network/main.tf`, find the `for_each` on `aws_subnet.public`.
Answer for yourself: what happens to resource addresses if you switch that to
`count` and later change `az_count` from 2 to 3? (Hint: indexes shift;
`for_each` keyed by AZ name does not.)

---

## Step 4: Local vs EKS path (cost safety)

| Setting | Default | Effect |
|---------|---------|--------|
| `cluster_mode` | `"local"` | Cluster module creates **no** AWS resources; prints a `k3d` command |
| `enable_eks` | `false` | Forces `eks` mode when true (root local maps this) |
| `enable_nat_gateway` | `false` | NAT Gateway costs money; leave off for study |

Daily workflow this week:

```bash
# No terraform apply required for app work
k3d cluster create grow-room-dev --agents 2
# ... Week 3 will deploy the sensor Helm chart here
```

When you intentionally study AWS networking:

1. Create an **AWS Budgets** alert at **$20/month** (email yourself).
2. Use a dedicated study AWS account if you have one.
3. `cp terraform.tfvars.example terraform.tfvars`
4. Keep `enable_nat_gateway = false` and `cluster_mode = "local"` until you
   are ready.
5. `terraform plan` (needs AWS credentials) — read every resource.
6. Apply only what you understand how to destroy (`terraform destroy`).

VPC, subnets, and IGW are inexpensive. **NAT Gateway** and **EKS control plane**
are the usual surprise bills.

---

## Step 5: Remote state and locking

Local `terraform.tfstate` is fine while learning alone. Teams (and CI) need:

- **S3 bucket** (versioning on, public access blocked, encryption on) for state.
- **DynamoDB table** with partition key `LockID` for state locking.

Copy `backend.tf.example` → `backend.tf`, fill in names, then:

```bash
terraform init -reconfigure
```

**Kubernetes analogy:** etcd holds cluster state; only one writer should mutate
a given key at a time. Terraform's lock prevents two applies from corrupting
state the same way.

Never commit `*.tfstate` or real access keys. The example backend file stays
secret-free (bucket names are OK; credentials come from the environment / OIDC).

---

## Step 6: Add Terraform CI (you write the workflow)

Create `.github/workflows/terraform.yml` yourself. Minimum jobs:

1. **`fmt`** — `terraform fmt -recursive -check`
2. **`validate`** — `init -backend=false` then `validate`
3. **`tflint`** — install tflint, `tflint --init`, `tflint`

Triggers: pull requests that touch `infra/**`, and pushes to `main` for those
paths. Use `working-directory: infra` or `cd infra`.

Optional later (needs AWS OIDC role — Week 3/5 territory):

- `terraform plan` on PRs with read-only credentials
- Post the plan as a PR comment
- Never `apply` from CI until you have reviews + protection rules

Hints:

- HashiCorp's `hashicorp/setup-terraform@v3` action pins the CLI version.
- Cache plugin dirs if runs are slow; not required for week 2.
- Fail the job on fmt drift — same philosophy as `ruff format --check`.

A full reference workflow is at the **bottom of this guide**. Write yours first.

---

## Step 7: TFLint

From `infra/` (config file `.tflint.hcl` is included):

```bash
tflint --init
tflint
```

TFLint catches AWS-specific smells (invalid instance types, deprecated
attributes) that `validate` will not. Treat it like `kube-linter` / `kubeval`
for Terraform.

---

## Step 8: Associate 004 exam prep outline

Target: **HashiCorp Terraform Associate (004)**. Use this project as the lab.

| Domain (approx.) | Study with this repo |
|---|---|
| IaC concepts | Explain root vs module using `infra/` |
| Terraform purpose / CLI | `fmt`, `init`, `validate`, `plan`, `apply`, `destroy`, `state` |
| Providers / state / backends | `providers.tf`, `backend.tf.example`, why locking |
| Modules | Author `network` + `cluster`; inputs/outputs |
| Read/generate config | Variables, locals, `for_each`, `cidrsubnet`, `try` |
| Run / maintain | CI fmt/validate/tflint; drift; import (read docs) |

Suggested cadence (evenings):

1. Read one Associate objective list section.
2. Change one thing in a module; `fmt` + `validate`.
3. Write 3 flashcards (e.g. "count vs for_each", "state vs backend", "soft vs hard dependency").
4. After Week 3–5, book the exam when practice tests are consistently >80%.

Official docs beat random dumps: <https://developer.hashicorp.com/terraform/tutorials/certification-003> (check current 004 links on HashiCorp's site).

---

## Step 9: Interview talking points (mid-level DevOps)

Practice saying these out loud against this repo:

1. **Authorship:** "I wrote the network and cluster modules from scratch for my
   grow-room sensor platform — VPC with `for_each` subnets, optional NAT, and
   EKS IAM/SG stubs gated behind a local/k3d default."
2. **Cost control:** "NAT and EKS are opt-in. I set a $20 AWS Budget before any
   paid apply. Daily work uses k3d."
3. **CI vs CD:** "CI runs fmt/validate/tflint on every infra PR. Apply stays
   manual or later GitOps-gated — I am not auto-applying to production from a
   push to main."
4. **State:** "Remote state in S3 with DynamoDB locks; state files never go in
   git; CI uses `-backend=false` for static validation."
5. **Honest boundary:** "At work I modify existing Terraform. This portfolio is
   where I demonstrate greenfield module design."

Avoid claiming production EKS operations you have not done. Claiming **authored
modules + CI validation + cost guards** is accurate once this week is merged.

---

## Step 10: Definition of done (Week 2)

- [ ] `infra/` merged to your GitHub repo on a branch/PR
- [ ] `terraform fmt -check` and `terraform validate` pass locally
- [ ] `tflint` passes (or is wired in CI)
- [ ] `.github/workflows/terraform.yml` you wrote goes green
- [ ] README roadmap Week 2 checkbox updated
- [ ] AWS Budgets $20 alert exists **before** any `apply` with NAT/EKS
- [ ] Notes bot / study log updated with what you authored and why

Week 3 will add Helm + Argo CD on k3d, then wire `aws_eks_cluster` into the
cluster module when you choose to spend AWS money deliberately.

---

## Reference: sample Terraform workflow

Try writing your own first. Collapse / copy only if stuck.

```yaml
# .github/workflows/terraform.yml
name: terraform

on:
  push:
    branches: [main]
    paths:
      - "infra/**"
      - ".github/workflows/terraform.yml"
  pull_request:
    paths:
      - "infra/**"
      - ".github/workflows/terraform.yml"

permissions:
  contents: read

defaults:
  run:
    working-directory: infra

jobs:
  fmt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.9.8"
      - run: terraform fmt -recursive -check

  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.9.8"
      - run: terraform init -backend=false
      - run: terraform validate

  tflint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: "v0.53.0"
      - run: tflint --init
      - run: tflint -f compact
```

Pin versions to whatever is current when you write the file. The Node 20
deprecation notices from Week 1 are harmless warnings until actions publish
newer majors.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `validate` wants credentials | You ran `plan` or a data source refresh | Use `init -backend=false` + `validate` for CI; configure AWS creds only for plan |
| Provider not found | Skipped `init` | `terraform init -backend=false` |
| Fmt check red in CI | Local files not formatted | `terraform fmt -recursive` then commit |
| TFLint plugin errors | Missing `tflint --init` | Run init once; commit `.tflint.hcl` |
| Accidental NAT cost | `enable_nat_gateway = true` | Set false; `terraform apply` to destroy NAT; check Budgets |
| State lock stuck | Cancelled apply | `terraform force-unlock LOCK_ID` only if you are sure no other apply runs |

---

## Extra credit

- Add a `modules/network` unit test with `terraform test` (Terraform 1.6+).
- Document a destroy runbook in `docs/DESTROY.md`.
- Replace the wide-open SG ingress CIDR with the VPC CIDR output once you
  enable `eks` mode.
