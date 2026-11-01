<!-- docs/adr/0006-rds-multi-az.md -->
# ADR-0006: RDS PostgreSQL Multi-AZ (instance deployment)

- Status: Accepted
- Date: 2026-11-01

## Context
The audit log must survive an AZ failure and maintenance without manual recovery.

## Decision
RDS Multi-AZ: synchronous standby in another AZ; on failure or reboot-with-failover, the DNS name
moves to the standby (typically 60-120 s). Demonstrated in the Phase 4 failover drill.

## Alternatives considered
| Option | Why not |
|--------|---------|
| Single-AZ | Half the cost; AZ outage = downtime until restore |
| Read replica | Asynchronous, for read scaling; promotion is manual |
| Multi-AZ DB cluster (2 readable standbys) | Faster failover, more expensive, fewer instance classes |
| Aurora | Storage replicated across 3 AZs; higher minimum cost |

## Consequences
Good: automatic failover, backups taken from standby.
Bad: ~2x instance cost; the standby cannot serve reads.

## SAA exam tie-in
Multi-AZ = high AVAILABILITY (synchronous, same endpoint, standby not readable).
Read replicas = read SCALING (asynchronous, own endpoint, can be cross-region).