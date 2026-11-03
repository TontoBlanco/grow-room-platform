# ADR-0009: IAM Roles Anywhere for the home shipper

- Status: Accepted
- Date: 2026-11-02

## Context

The PC by the tent is not in the VPC. It needs to upload readings. An access key on that PC would be a long-lived secret next to the grow equipment.

## Decision

A private CA is the trust anchor `grow-room-home-ca`. Profile `grow-room-home` lets certificate CN `grow-room-home-shipper` assume role `grow-room-home-shipper` for one hour. The role policy `put-readings` allows `s3:PutObject` on `readings/*` and the two KMS calls the bucket encryption needs.

## Alternatives considered

| Option | Why not |
| --- | --- |
| An IAM user access key on the PC | Long-lived, and easy to grant too much |
| Run the shipper only inside EKS | The tent path is not in the cluster, and the cluster is down most days |
| No archive | Prometheus on the laptop keeps 24 hours |

## Consequences

Good: no AWS key on the PC. The role cannot delete or list.

Bad / accepted risk: I still hold a private key, and it is not an AWS key. The CA file path is outside Git. Losing the key means issuing another certificate, not rotating an access key I copied into a dotfile.

## SAA exam tie-in

Roles Anywhere is for a workload outside AWS that can present a certificate. It is not Pod Identity, and it is not an access key.
