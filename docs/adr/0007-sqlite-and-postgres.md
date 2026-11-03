# ADR-0007: SQLite by default, Postgres when a URL is set

- Status: Accepted
- Date: 2026-10-26

## Context

The audit API needs a place to store batches, plants, and the hash chain. The laptop lab should run with no extra process. The proof of concept already had a Postgres database. I did not want two APIs.

## Decision

SQLite is the default. `AUDIT_DATABASE_URL`, or a `postgres://` `DATABASE_URL`, selects Postgres. `AUDIT_DATABASE_URL` wins. The image includes the driver. k3d stays on SQLite unless that URL is set.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Postgres only | The lab would need a database just to boot |
| SQLite only | The RDS work would have had no application behind it |
| A second audit service | Two code paths to keep honest |

## Consequences

Good: one API, tests for both, a local file when I am offline.

Bad / accepted risk: the k3d file is on `emptyDir` and does not survive a new pod. Neither store is write-once. A person who can write the database can recompute the chain.

## SAA exam tie-in

Pick the data store for the availability you actually need. Multi-AZ is for the database failing over. It is not a property of the application hash.
