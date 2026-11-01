<!-- docs/adr/0002-karpenter-for-node-scaling.md -->
# ADR-0002: Karpenter for workload nodes, small managed node group for system pods

- Status: Accepted
- Date: 2026-11-01

## Context
Pods need EC2 capacity that matches their requests, ideally Spot, without me pre-sizing groups.

## Decision
A 3-node managed node group (t3.large) runs controllers. Karpenter launches extra EC2 instances
directly (no Auto Scaling group) from a NodePool allowing Spot and On-Demand, and removes empty or underused ones.
Spot interruption notices arrive through an SQS queue fed by EventBridge.

## Alternatives considered
| Option | Why not |
|--------|---------|
| Cluster Autoscaler + ASGs | Scales whole groups of one instance type; slower; more groups to manage |
| Only managed node groups | Simple but I size by hand and pay for idle capacity |
| Fargate | No DaemonSets, per-pod pricing higher for steady load |

## Consequences
Good: right-sized, Spot-friendly capacity in under a minute.
Bad: one more controller to upgrade; teardown must delete the NodePool first or EC2 instances outlive the cluster.

## SAA exam tie-in
Spot = up to ~90% off, can be reclaimed with a 2-minute warning (EventBridge event).
Use Spot for stateless, interruptible work; On-Demand/Reserved/Savings Plans for the steady baseline.