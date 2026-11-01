<!-- docs/adr/0001-nat-gateway-per-az.md -->
# ADR-0001: One NAT gateway per Availability Zone

- Status: Accepted
- Date: 2026-11-01

## Context
Private subnets in 3 AZs need outbound internet (image pulls not covered by endpoints, AWS APIs).
A NAT gateway lives in ONE AZ. If that AZ fails, every private subnet routed to it loses egress.

## Decision
Three NAT gateways, one per AZ; each private route table points to the NAT in its own AZ.
An S3 gateway endpoint and ECR interface endpoints keep image and S3 traffic off NAT.

## Alternatives considered
| Option | Why not |
|--------|---------|
| One shared NAT gateway | Cheaper (1/3 of NAT hours) but one AZ failure breaks egress in all AZs; also cross-AZ data charges |
| NAT instance | Cheap, but I patch and scale it myself; no built-in HA |
| No NAT, endpoints only | Possible later; some pulls (GHCR, Helm charts) need the internet |

## Consequences
Good: AZ-independent egress, no cross-AZ NAT traffic.
Bad: 3x NAT hourly cost - the biggest idle cost of the stack, which is why it only runs during sessions.

## SAA exam tie-in
High availability for NAT = one NAT gateway per AZ. NAT gateway is AZ-scoped and managed; NAT instance is not managed.
Gateway endpoints (S3, DynamoDB) are free; interface endpoints are billed per hour per AZ.