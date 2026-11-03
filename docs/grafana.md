# Grafana guide

Both dashboards are loaded from ConfigMaps in `monitoring/manifests`. Argo CD syncs them into namespace `monitoring`. The lab login is the value of `grafana.adminPassword` in `monitoring/values-k3d.yaml`. I am not copying that password into this page.

Open Grafana from the laptop:

```powershell
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

Then open `http://127.0.0.1:3000`. The climate dashboard uid is `grow-room-vpd`. The service level objective dashboard uid is `grow-room-slo`.

Prometheus is on a second port-forward:

```powershell
kubectl -n monitoring port-forward svc/monitoring-prometheus 9090:9090
```

Targets are at `http://127.0.0.1:9090/targets`. You should see job `sensor-service` and, on k3d only, job `grow-room-ha-host`.

## The two jobs

| Job | What it is | What the charts should do with it |
| --- | --- | --- |
| `sensor-service` | The simulator inside the cluster | Climate tiles and the scrape-up tile for that job |
| `grow-room-ha-host` | Compose on the Docker host, label `sensor_source=homeassistant` | The same climate tiles, plus the controller, probe, and port panels |

A fresh Prometheus sample does not prove the physical probe took a new reading. Prometheus stamps the scrape time. The value can be unchanged.

When the laptop sleeps, both jobs stop. The live panels go flat. That is expected.

## Grow-room VPD

The JSON is `monitoring/dashboards/grow-room-vpd.json`. Tests in `tests/test_grafana_dashboard.py` lock the queries.

### Scrape up

Query: `max by (job) (up{job=~"sensor-service|grow-room-ha-host"})`.

`up` is 1 when the scrape worked and 0 when it did not. `max by (job)` drops the pod name and the instance, so one tile per job. After a rollout, the old pod does not stay on the board as its own DOWN tile. That was [PR #32](https://github.com/TontoBlanco/grow-room-platform/pull/32). Green text **UP** is 1. Red text **DOWN** is 0.

### Temperature °C

Query: `grow_temperature_celsius`.

This is the air temperature the service exports, in Celsius. The tile is blue under 18, green from 18 up to 32, and red at 32 and above. On the live path this is the controller air temperature. The simulator exports the same metric name, so you can see more than one series until a panel aggregates.

### Humidity %

Query: `grow_humidity_percent`.

Relative humidity. Red under 30, green from 30 up to 80, red at 80 and above. The same band is the alert `GrowRoomHumidityOutOfRange`, which waits 5 minutes. The alert does not filter by job, so either the simulator or the tent can fire it.

### VPD kPa

Query: `grow_vpd_kpa`.

Leaf VPD computed by the service, in kilopascals, from air temperature, humidity, and `LEAF_TEMP_OFFSET_C`. Blue under 0.8, green from 0.8 up to 1.4, yellow from 1.4 up to 1.8, red at 1.8 and above. The controller's own VPD is a different metric, further down the page.

### Climate (temp / humidity / VPD)

Three queries on one time series: `grow_temperature_celsius`, `grow_humidity_percent`, and `grow_vpd_kpa`.

This is the history behind the three tiles. The units share one axis, so I use it to see the shape of the day, not to read a precise humidity off the VPD scale.

### Scrape health + read errors

Queries:

- `max by (job) (up{job=~"sensor-service|grow-room-ha-host"})`
- `sum by (job) (rate(grow_read_errors[5m]))`

The first line is the same up/down signal as the tiles, drawn over time. The second line is how often the service failed to read a sample, per second, over five minutes, summed by job. A spike here with `up` still at 1 means the process is alive and the read is failing. For the live job, that is usually Home Assistant or the token.

### CO₂ ppm (if sensor reports it)

Query: `grow_co2_ppm`.

Parts per million, only if something reports CO₂. `HA_CO2_ENTITY` is empty by default, so this panel stays empty on my tent. An empty panel is not a failed scrape.

### Plant mood

Query: `max by (job) (grow_room_plant_mood)`.

This is a category code from leaf VPD, one tile per job. Inactive bands are 0, so the max is the current band. It is not a quality score and it is not a control signal. The bands are for a mixed tent. Seedlings usually want a lower VPD than later growth, and this gauge does not know the stage. That is the open pull request on the roadmap.

| Leaf VPD (kPa) | Band | Words on the tile | Score |
| --- | --- | --- | --- |
| under 0.4 | `stressful_humid` | swampy | 1 |
| 0.4 up to 0.8 | `muggy` | muggy | 2 |
| 0.8 through 1.2 | `ideal` | cozy | 3 |
| above 1.2 through 1.6 | `too_dry` | thirsty | 4 |
| above 1.6 | `stressful_dry` | crispy | 5 |

No sample yet prints **no sample**.

### Controller air and probe canopy

The next panels are the Home Assistant series. Each query requires `sensor_source="homeassistant"` and uses `max by (sensor_source)` or `max by (device)`, so the simulator cannot draw a second line and an old scrape cannot duplicate the legend. That cleanup was [PR #29](https://github.com/TontoBlanco/grow-room-platform/pull/29). Until a live sample exists, the panel prints **No HA sample**. A healthy simulator does not hide a dead host scrape.

| Panel | Query | Plain meaning |
| --- | --- | --- |
| Controller status | `max by (sensor_source) (grow_controller_status{sensor_source="homeassistant"})` | 1 if the controller entity is on, 0 if it is not |
| Controller VPD | `max by (sensor_source) (grow_controller_vpd_kpa{sensor_source="homeassistant"})` | The controller's own VPD, converted to kPa |
| Probe canopy °C | `max by (sensor_source) (grow_probe_temperature_celsius{sensor_source="homeassistant"})` | Internal probe temperature |
| Probe canopy RH | `max by (sensor_source) (grow_probe_humidity_percent{sensor_source="homeassistant"})` | Internal probe relative humidity |
| Probe canopy VPD | `max by (sensor_source) (grow_probe_vpd_kpa{sensor_source="homeassistant"})` | Internal probe VPD, converted to kPa |
| Air vs canopy temperature | controller `grow_temperature_celsius` and probe `grow_probe_temperature_celsius`, both filtered to `homeassistant` | How far the leaf-level probe sits from the controller air sensor |
| Air vs canopy humidity | the matching humidity pair | The same comparison for humidity |
| VPD: computed, controller, probe | `grow_vpd_kpa`, `grow_controller_vpd_kpa`, and `grow_probe_vpd_kpa`, all `homeassistant` | My leaf calculation next to the two device readings |

The leaf calculation uses the air reading plus the leaf-temperature offset. It will not match the controller number exactly. That difference is the point of the panel.

### UIS ports

These are the switched devices on the controller. The default set is `port_1`, `humidifier`, `oscillating_fans`, and `ventilation_fan`.

| Panel | Query | Plain meaning |
| --- | --- | --- |
| Port status | `max by (device) (grow_port_status{sensor_source="homeassistant"})` | On or off, one series per device |
| Port power | `max by (device) (grow_port_current_power{sensor_source="homeassistant"})` | The power level the controller reports |
| Port status over time | the same status query as a time series | When a device turned on or off |
| Port power over time | the same power query as a time series | How the level moved |

**No HA sample** on these panels means Compose has not exported port gauges yet. The gauges are created only after a successful Home Assistant read.

### Growth stage VPD target

`GROW_STAGE` is one stage for the whole tent. The default is `veg`. It is not the plant-mood score. Mood stays the mixed-tent category. The stage picks the leaf-VPD band the bottom row draws. Pull request [#77](https://github.com/TontoBlanco/grow-room-platform/pull/77) merged on 3 November 2026.

| `GROW_STAGE` | Inclusive leaf VPD (kPa) |
| --- | --- |
| `seedling` (`clone` is stored as seedling) | 0.4–0.8 |
| `veg` | 0.8–1.2 |
| `flower` | 1.2–1.5 |
| `late_flower` | 1.4–1.6 |

| Panel | Query | Plain meaning |
| --- | --- | --- |
| Growth stage | `max by (job, stage) (grow_room_stage_info)` | The configured stage. The sample value is always 1. Read the `stage` label. |
| VPD in band | `max by (job) (grow_vpd_in_target_band)` | 1 when computed leaf VPD is inside the inclusive band, otherwise 0. Missing until a reading succeeds. |
| Target low kPa | `max by (job) (grow_vpd_target_low_kpa)` | Lower edge of the active band. |
| Target high kPa | `max by (job) (grow_vpd_target_high_kpa)` | Upper edge of the active band. |
| VPD vs stage target | `grow_vpd_kpa` plus the two target gauges, each `max by (job)` | Leaf VPD with the band drawn around it. The lines move when the stage changes. |
| How the target band is chosen | Text panel, no query | Says the band comes from `GROW_STAGE`, not from a number typed into the dashboard. |

## grow-room SLOs

The JSON is inside `monitoring/manifests/grafana-dashboard-grow-room-slo.yaml`. The time range is seven days. The recording rules are in `monitoring/manifests/grow-room-slo-rules.yaml`.

A service level objective here is a target for the simulator job, not for the tent scrape. I left `grow-room-ha-host` out so a bad token does not spend the simulator's error budget. An error budget is the amount of failure the target allows. For 99 percent availability, the budget is 1 percent.

| Panel | Query | Plain meaning |
| --- | --- | --- |
| Availability (7d) - target 99% | `avg_over_time(slo:sensor_availability:ratio_rate5m[7d])` | Share of successful `sensor-service` scrapes. Green at 0.99 and above. |
| Error budget remaining (7d) | `1 - ((1 - avg_over_time(slo:sensor_availability:ratio_rate5m[7d])) / 0.01)` | How much of that 1 percent is left. Red under 25 percent left, orange from 25 to 50, green above 50. |
| Data freshness - target <= 120 s | `slo:sensor_freshness_seconds` | Age of the newest `grow_vpd_kpa` sample. Green under 120 seconds, red at 120 and above. |
| Burn rate (1 = spending budget exactly on schedule) | `(1 - slo:sensor_availability:ratio_rate1h) / 0.01` and the same for 6 hours | 1 means the last window is using the 1 percent budget at the planned pace. Higher means the budget will run out early. |

`slo:sensor_freshness_seconds` is `max(time() - timestamp(grow_vpd_kpa))`. It measures sample age in Prometheus. It does not measure when the probe last changed.

## Alerts you may see in email

Alertmanager on EKS sends to the SNS topic `grow-room-poc-alerts`. The subject is `[grow-room]` plus `FIRING` or `RESOLVED` plus the alert name. SNS is Simple Notification Service, the email topic. The lab k3d stack does not have that email route.

| Alert | Rule file | When it fires |
| --- | --- | --- |
| `GrowRoomSensorScrapeDown` | `monitoring/alerts/grow-room-rules.yaml` | `up{job="sensor-service"} == 0` for 2 minutes |
| `GrowRoomHumidityOutOfRange` | same file | Humidity under 30 or over 80 for 5 minutes, any series |
| `GrowRoomSensorPodRestarts` | same file | More than two restarts of container `sensor-service` in 15 minutes |
| `SensorAvailabilityBudgetBurnFast` | `monitoring/manifests/grow-room-slo-rules.yaml` | Both the 1 hour and the 5 minute windows are worse than 14.4 times the 1 percent budget, for 2 minutes |
| `SensorAvailabilityBudgetBurnSlow` | same file | The 6 hour and 30 minute windows are worse than 6 times the budget, for 15 minutes |
| `SensorDataStale` | same file | Freshness over 120 seconds, or `grow_vpd_kpa` is absent, for 5 minutes |
| `TargetDown` | kube-prometheus-stack, not my rule file | A target in a job is unreachable. On 3 November this was `grow-room-ha-host` on EKS, which should not be scraped there. |

`GrowRoomTestAlert` in the 3 November mail was a test message, not a climate rule.
