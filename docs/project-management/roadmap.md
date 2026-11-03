# Roadmap

This is the order of the remaining work. The growth-stage setting is already on `main`.

## 1. Plant stage and VPD bands

Done on `main`. Pull request [#77](https://github.com/TontoBlanco/grow-room-platform/pull/77) merged on 3 November 2026.

`GROW_STAGE` is one tent-wide stage. The default is `veg`. It selects an inclusive leaf-VPD band: seedling 0.4–0.8, veg 0.8–1.2, flower 1.2–1.5, late flower 1.4–1.6, in kilopascals. Plant mood is still the separate mixed-tent gauge. The dashboard row is **Growth stage VPD target**. The panels are in the [Grafana guide](../grafana.md).

## 2. Athena as a data source in local Grafana

Done and working. Pull request [#80](https://github.com/TontoBlanco/grow-room-platform/pull/80) added **Grow-room History** (uid `grow-room-history`) on the k3d Grafana. Pull request [#86](https://github.com/TontoBlanco/grow-room-platform/pull/86) fixed the plugin credentials. The datasource health check returns OK. The query role is `grow-room-grafana-reader`. The shipper role stays write-only. The steps and the three install lessons are in [Athena in Grafana](../ATHENA_GRAFANA.md).

## 3. Grow alerts the controller cannot see

Done. The write-up is [Grow alerts](../GROW_ALERTS.md). Each alert has its own Helm switch. `charts/grow-alerts/values.yaml` keeps every switch off. The k3d overlay `values-k3d.yaml` turns probe drift on. An off switch renders no object.

The four alerts are a stale S3 shipper, a day of VPD outside the stage band, certificate expiry, and probe drift against the controller's reported VPD. They do not repeat the app's temperature and humidity alarms. The earlier candidates (the host scrape being down, and a port reporting power 0) are not in this set. The host scrape is the laptop path, and the controller already shows port power.

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
