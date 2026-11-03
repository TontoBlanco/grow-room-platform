# Roadmap

This is the order I will do the remaining work. Items above the line are not started in `main`, except the growth-stage pull request, which is open.

## 1. Plant stage and VPD bands

Pull request [#77](https://github.com/TontoBlanco/grow-room-platform/pull/77), branch `cursor/growth-stage-vpd-1ef8`, is open. The title is "Add a growth-stage setting so VPD targets follow the stage."

Today the plant-mood gauge uses one set of bands for a mixed tent. Seedlings usually want a lower vapor pressure deficit than later growth. The gauge does not know the stage. This change is the one that teaches it.

## 2. Athena as a data source in local Grafana

The query `analytics/athena/vpd_by_day.sql` runs in workgroup `grow-room-telemetry`. Grafana on k3d does not have that workgroup as a data source yet. I want a panel for daily VPD next to the 24 hour Prometheus charts, without sending the Grafana admin credential to AWS as a long-lived key. I have not chosen the credential shape. It should not be an access key in `monitoring/values-k3d.yaml`.

## 3. Grow alerts the controller cannot see

AC Infinity already alarms on its own sensors. I do not want a second email for the same humidity reading. The alerts I still want are the ones the controller does not see, and I want them easy to turn off.

Candidates, none of them scheduled:

- The host scrape `grow-room-ha-host` is down, while the simulator is up. That is the laptop path, not the tent's own alarm.
- Freshness of the live series, as opposed to `SensorDataStale` on the simulator job.
- A port that should be on and is reporting power 0.

They should be toggleable. A single Helm value is enough. I will not add them by copying the controller's humidity rule.

## 4. Phase 8 — Home Assistant moves between the house and AWS

I want to stop treating the Home Assistant config as a folder that only exists on one disk. The move is backup and restore through S3: take a backup at home, put it in a bucket, and restore it on a session in `us-west-2`, then the other direction.

This is not built. There is no backup script, no bucket policy, and no restore test. When I write it I will:

- Keep `ha-config/` gitignored. The backup will contain secrets.
- Use a dedicated bucket and a KMS key, with a cost note. A bucket left behind is a monthly bill, small until the backups pile up.
- Not put the AC Infinity password or `HA_TOKEN` in the documentation.
- Test restore on a scratch Home Assistant, not on the live tent, the first time.

## 5. Dependabot or Renovate

There is no `.github/dependabot.yml` and no Renovate config. Actions are pinned by SHA in the newer workflows, and chart versions are pinned in Git. They still go stale. I will add a dependency bot after the items above, so the noise does not land in the middle of the stage and alert work.

## Explicitly later

- A Raspberry Pi or other always-on host. [ADR-0011](../adr/0011-k3d-instead-of-a-pi.md) still stands.
- Kyverno `failureAction: Enforce`, after a PolicyReport pass on a cosign 2.6.5 image.
- Replacing `AdministratorAccess` on `grow-room-gha-apply`.
- Filling `docs/aws-poc/COSTS.md` from Cost Explorer the day after the 3 November session.
