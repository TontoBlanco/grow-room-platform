<!-- docs/adr/0004-external-secrets-operator.md -->
# ADR-0004: External Secrets Operator with Secrets Manager

- Status: Accepted
- Date: 2026-11-01

## Context
The app needs the RDS password. RDS manages and rotates it in Secrets Manager (manage_master_user_password).

## Decision
ESO reads the secret through Pod Identity and writes a Kubernetes Secret the app consumes; refresh picks up rotations.

## Alternatives considered
| Option | Why not |
|--------|---------|
| Password in Helm values / Git | Secret in Git history forever |
| Secrets Store CSI driver | Mounts as files; extra syncing to get env vars |
| SSM Parameter Store SecureString | Cheaper, but no native RDS-managed rotation |

## Consequences
Good: no secret in Git; rotation handled by AWS.
Bad: a controller in the path; if ESO is down, existing Secrets keep working but changes stall.

## SAA exam tie-in
Secrets Manager = automatic rotation (built in for RDS), costs per secret per month.
Parameter Store = config + secrets, free standard tier, no built-in rotation.