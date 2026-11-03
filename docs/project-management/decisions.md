# Decisions

I keep one file per decision so I can say what I chose and what I turned down. The template is [ADR-0000](../adr/0000-template.md).

| ID | Decision | Status |
| --- | --- | --- |
| [0001](../adr/0001-nat-gateway-per-az.md) | One NAT gateway per availability zone | Accepted |
| [0002](../adr/0002-karpenter-for-node-scaling.md) | Karpenter for extra nodes | Accepted |
| [0003](../adr/0003-eks-pod-identity.md) | EKS Pod Identity | Accepted |
| [0004](../adr/0004-external-secrets-operator.md) | External Secrets for the database URL | Accepted |
| [0005](../adr/0005-aws-waf-on-alb.md) | WAF on the Application Load Balancer | Accepted |
| [0006](../adr/0006-rds-multi-az.md) | Multi-AZ RDS | Accepted |
| [0007](../adr/0007-sqlite-and-postgres.md) | SQLite by default, Postgres by URL | Accepted |
| [0008](../adr/0008-oidc-for-terraform-ci.md) | GitHub OIDC, manual apply | Accepted |
| [0009](../adr/0009-roles-anywhere-shipper.md) | Roles Anywhere for the home shipper | Accepted |
| [0010](../adr/0010-s3-and-athena.md) | S3, Glue, and Athena for history | Accepted |
| [0011](../adr/0011-k3d-instead-of-a-pi.md) | k3d on the PC, not a Pi yet | Accepted |

The first six were merged in pull request [#58](https://github.com/TontoBlanco/grow-room-platform/pull/58). The last five are the records for choices the code already made: the audit store, CI identity, the home shipper, the reading archive, and the local cluster.
