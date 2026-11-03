# ADR-0008: GitHub OIDC for Terraform, apply only by hand

- Status: Accepted
- Date: 2026-11-01

## Context

I wanted `terraform plan` on a pull request. A static AWS key in GitHub would have worked and would have been the wrong secret to store. The first design also applied on merge to `main`. That is a bill I can start by accident.

## Decision

GitHub Actions assumes `grow-room-gha-plan` for plans and `grow-room-gha-apply` for apply and destroy. The token comes from OIDC. Apply and destroy are `workflow_dispatch` only, and the job environment is `aws-poc`, which is what the apply role trusts. The apply role is still `AdministratorAccess`. That is a demo shortcut written in the bootstrap file.

## Alternatives considered

| Option | Why not |
| --- | --- |
| A long-lived access key in GitHub secrets | Another secret to leak and rotate |
| Apply on every merge to `main` | A merge at the end of the day starts the hourly bill |
| No CI plan | I would be the only person who sees the plan |

## Consequences

Good: no AWS key in GitHub. A plan comment on the pull request. A person has to approve the environment.

Bad / accepted risk: the apply role is wider than the job needs. The home IP has to be updated in two places, or plans fight. The OIDC subject is immutable, so the trust policy has to list that form.

## SAA exam tie-in

Prefer a short-lived identity over an access key. A trust policy is not least privilege if the role it trusts is still an administrator.
