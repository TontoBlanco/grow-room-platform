<!-- docs/adr/0003-eks-pod-identity.md -->
# ADR-0003: EKS Pod Identity for AWS access from pods

- Status: Accepted
- Date: 2026-11-01

## Context
Controllers (LBC, ExternalDNS, ESO, exporter, Alertmanager) call AWS APIs. Access keys in Secrets are long-lived and leak.

## Decision
EKS Pod Identity: one IAM role per controller, associated to a namespace + service account. The
Pod Identity Agent hands the pod short-lived credentials; the role trusts pods.eks.amazonaws.com.

## Alternatives considered
| Option | Why not |
|--------|---------|
| IRSA (OIDC provider per cluster) | Works, but the role trust policy embeds the cluster OIDC URL, so every rebuild means new trust policies |
| Node instance role | Every pod on the node gets the same permissions - violates least privilege |
| Access keys in a Secret | Long-lived, must be rotated, can leak |

## Consequences
Good: least privilege per workload, no keys, roles reusable across cluster rebuilds.
Bad: needs the eks-pod-identity-agent add-on; SDK must be recent enough.

## SAA exam tie-in
Applications on AWS compute should use ROLES, never stored access keys (EC2 instance profile, Lambda execution role, ECS task role, EKS pod role).
STS issues the temporary credentials.