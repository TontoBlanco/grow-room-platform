# ADR-0011: k3d on the PC instead of a Raspberry Pi

- Status: Accepted
- Date: 2026-10-25

## Context

The live scrape dies when the laptop sleeps. An always-on computer next to the tent would keep Home Assistant and the sensor service up. I do not own that setup in this repository.

## Decision

Daily Kubernetes is k3d cluster `grow-room-dev` on the PC. The live service stays on Docker Compose on the same PC. Ansible roles `base` and `k8s_tools` are written so I can reuse them on a small host later. No Pi image, hostname, or playbook host is in the inventory. The only host is `batcomputer`, connection local.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Buy a Pi and move Home Assistant now | More hardware, and the GitOps practice did not need it |
| Run the live token inside k3d | The token would be in the cluster, and CI would be closer to the house |
| Skip local Kubernetes and use EKS every day | The hourly bill, for a lab I close the lid on |

## Consequences

Good: I can rebuild the cluster from `scripts/bootstrap-k3d.sh` with no AWS charge. The simulator keeps demos working.

Bad / accepted risk: the Grafana tent charts follow the laptop's power state. I have not built the always-on edge. Phase 8 is the Home Assistant move between the house and a short EKS session, and that paid verify is done. It is not this Pi.

## SAA exam tie-in

This decision is about where the workload runs, not about an AWS service. The matching cloud question is still: do not leave NAT gateways and a control plane up for a laptop-shaped lab.
