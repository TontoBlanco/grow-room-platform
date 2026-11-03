# modules/cluster

Week 2 cluster module: **local** (k3d-friendly outputs, no AWS resources from this module) or
**eks** (security group + IAM role stubs for a future `aws_eks_cluster`).

This module is not the cluster I apply. That root is `infra/aws-poc`, and I
bring it up for a session. See the [documentation site](../../../docs/index.md).

## Modes

| `cluster_mode` | Creates AWS resources? | Use when |
|----------------|------------------------|----------|
| `local` | No | Daily study on your PC with k3d/kind |
| `eks` | Yes: SG + IAM role + policy attachments | Preparing for Week 3 EKS |

## Why stubs instead of full EKS in Week 2?

Authoring a complete EKS cluster (node groups, OIDC, add-ons) is a large
chunk. Week 2 focuses on **module boundaries, variables/outputs, and IAM/SG
foundations**. You will add `aws_eks_cluster` in Week 3 once Helm/GitOps
layout is ready — and only after an AWS Budgets **$20** alert is in place.

## Kubernetes analogy

- IAM role for EKS ≈ the cloud identity the API server runs as
- Cluster security group ≈ NetworkPolicy / apiserver listen restrictions at the VPC layer
- `k3d_create_command` output ≈ documenting how you bootstrap a local kind/k3d cluster in a runbook
