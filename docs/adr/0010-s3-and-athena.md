# ADR-0010: S3 and Athena for reading history

- Status: Accepted
- Date: 2026-11-02

## Context

I want daily VPD after Prometheus has expired its 24 hour disk. I do not want to run another database at home for a table I query by hand.

## Decision

`ship_readings.py` writes JSON Lines to S3, partitioned by `dt`. Glue table `grow_room_telemetry.readings` uses partition projection. Workgroup `grow-room-telemetry` enforces its output location, encrypts results with the telemetry key, and stops a query at 1 GB. The saved query is `analytics/athena/vpd_by_day.sql`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Longer Prometheus retention | The laptop disk, and it still is not a table I can query in SQL |
| Postgres for every reading | A database to patch, back up, and pay for, for a lab query |
| Only the EKS sensor bucket | That bucket is destroyed with the session, and it receives simulator rows |

## Consequences

Good: the home stack survives `down`. The query is in Git. The scan cap is in the workgroup, not in my memory.

Bad / accepted risk: about 1 USD per month for the KMS key, for as long as the stack exists. Athena still charges for what it scans under that cap. The Glue schema is the flattened columns only.

## SAA exam tie-in

S3 is the store. Glue is the catalog. Athena is the query. A workgroup is where you put the bytes-scanned limit and the result location.
