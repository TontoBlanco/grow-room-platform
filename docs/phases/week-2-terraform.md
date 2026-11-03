# Week 2 — Terraform for the local lab

I wanted to author Terraform myself: a network module, a cluster module, variables, and a CI check. I did not want that check to create a bill.

## What I built

`infra/` is the local root. `infra/modules/network` can build a VPC, public and private subnets, an internet gateway, and an optional NAT gateway. `infra/modules/cluster` prints local outputs, or an IAM role and a security group when the EKS branch is turned on. The `aws_eks_cluster` resource in that root is still commented out. This root is not the cluster I later applied. That is `infra/aws-poc`.

`.github/workflows/terraform.yml` runs in `infra/` with Terraform `1.9.8`:

- `terraform fmt -check`
- `terraform init -backend=false`
- `terraform validate`
- `tflint`

It does not plan and it does not apply.

The defaults in the root are `cluster_mode = "local"`, `enable_eks = false`, and `enable_nat_gateway = false`.

## Why

I wanted the module practice without leaving a VPC behind. A later week could still point the same ideas at a real account. When I did that, I used a separate root so the lab defaults could stay local.

## Data flow

```mermaid
flowchart LR
  PR["Pull request"] --> FMT["fmt and validate"]
  FMT --> LINT["tflint"]
  LINT --> STOP["Stop. No apply."]
```

## Rebuild

```powershell
Set-Location C:\src\grow-room-platform
```

```powershell
terraform -chdir=infra fmt -check
```

```powershell
terraform -chdir=infra init -backend=false
```

```powershell
terraform -chdir=infra validate
```

The workflow uses Terraform 1.9.8. If your `terraform` is older or newer, install 1.9.8 before you compare results with CI.

## Cost

!!! warning "Do not apply this root"
    `terraform validate` does not create resources. `terraform apply` in `infra/` can. The network module contains a real VPC, subnets, and an internet gateway. Those exist even when `cluster_mode` is `local`. A NAT gateway, if you set `enable_nat_gateway = true`, bills by the hour. CI does not apply this root. A `budget_reminder` output tells you to set a 20 USD monthly budget before a paid apply. That output does not create the budget.

## What I learned

A green validate only means the files parse. I said that out loud a few times after the proof of concept, because it is easy to slide from "the module is valid" to "the network exists." They are different facts. I also learned to keep the lab root and the paid root apart, so a workflow aimed at `infra/` cannot accidentally plan `infra/aws-poc`.
