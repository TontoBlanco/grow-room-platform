# modules/network

Creates a VPC with public and private subnets across N availability zones,
an Internet Gateway, and an **optional** NAT Gateway.

## Inputs

| Name | Default | Notes |
|------|---------|-------|
| `name_prefix` | (required) | e.g. `grow-room-dev` |
| `vpc_cidr` | (required) | e.g. `10.42.0.0/16` |
| `az_count` | (required) | 2 or 3 |
| `enable_nat_gateway` | `false` | Set true only when you need private egress; costs money |
| `aws_region` | (required) | Used for AZ lookup |

## Outputs

`vpc_id`, `public_subnet_ids`, `private_subnet_ids`, `nat_gateway_id`, `availability_zones`

## Design choices

- **`for_each` over AZs** instead of `count`, so adding/removing an AZ does not
  reshuffle subnet indexes the way `count` would.
- **NAT off by default** so `terraform apply` on a study account does not
  quietly burn ~$32+/month.
- Subnet CIDRs come from `cidrsubnet()` so you never hardcode overlapping ranges.

## Kubernetes analogy

A VPC is roughly a cluster network fabric. Public subnets are like nodes that
can hold LoadBalancer Services; private subnets are like internal worker pools
that need a NAT (or VPC endpoints) to pull images.
