"""The Week 4 Grafana board stays aligned with gauges sensor-service exports."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "monitoring" / "dashboards" / "grow-room-vpd.json"
CONFIGMAP_PATH = ROOT / "monitoring" / "manifests" / "grafana-dashboard-grow-room-vpd.yaml"

# Names from sensor_service.main plus the Prometheus scrape target gauge.
EXPORTED = {
    "grow_temperature_celsius",
    "grow_humidity_percent",
    "grow_vpd_kpa",
    "grow_room_plant_mood",
    "grow_co2_ppm",
    "grow_read_errors",
    "grow_controller_vpd_kpa",
    "grow_controller_status",
    "grow_probe_temperature_celsius",
    "grow_probe_humidity_percent",
    "grow_probe_vpd_kpa",
    "grow_port_current_power",
    "grow_port_status",
    "up",
}

ORIGINAL_GRIDS = {
    # Scrape up is wide enough for one tile per job (sensor-service and
    # grow-room-ha-host). Climate stats keep their size and slide right.
    1: {"h": 4, "w": 9, "x": 0, "y": 0},
    2: {"h": 4, "w": 5, "x": 9, "y": 0},
    3: {"h": 4, "w": 5, "x": 14, "y": 0},
    4: {"h": 4, "w": 5, "x": 19, "y": 0},
    5: {"h": 10, "w": 16, "x": 0, "y": 4},
    6: {"h": 10, "w": 8, "x": 16, "y": 4},
    7: {"h": 8, "w": 24, "x": 0, "y": 14},
}


def _dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text())


def _exprs(dashboard: dict) -> list[str]:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            expr = node.get("expr")
            if isinstance(expr, str):
                found.append(expr)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(dashboard)
    return found


def _metric_names(expr: str) -> set[str]:
    return set(re.findall(r"\b(?:grow_[a-z0-9_]+|up)\b", expr))


def _embedded_dashboard() -> dict:
    text = CONFIGMAP_PATH.read_text()
    marker = "grow-room-vpd.json: |\n"
    body = text.split(marker, 1)[1]
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("    "):
            lines.append(line[4:])
        elif line.strip() == "":
            lines.append("")
        else:
            break
    return json.loads("\n".join(lines))


def test_dashboard_json_matches_grafana_configmap():
    assert _embedded_dashboard() == _dashboard()
    text = CONFIGMAP_PATH.read_text()
    assert 'grafana_dashboard: "1"' in text
    assert "namespace: monitoring" in text
    assert "name: grafana-dashboard-grow-room-vpd" in text


def test_dashboard_queries_only_exported_metrics():
    dashboard = _dashboard()
    assert dashboard["uid"] == "grow-room-vpd"
    assert dashboard["title"] == "Grow-room VPD"
    names: set[str] = set()
    for expr in _exprs(dashboard):
        found = _metric_names(expr)
        assert found, expr
        names.update(found)
    assert names == EXPORTED


def test_original_vpd_panels_keep_their_queries_and_layout():
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}
    assert [target["expr"] for target in panels[2]["targets"]] == ["grow_temperature_celsius"]
    assert [target["expr"] for target in panels[3]["targets"]] == ["grow_humidity_percent"]
    assert [target["expr"] for target in panels[4]["targets"]] == ["grow_vpd_kpa"]
    assert [target["expr"] for target in panels[5]["targets"]] == [
        "grow_temperature_celsius",
        "grow_humidity_percent",
        "grow_vpd_kpa",
    ]
    assert [target["expr"] for target in panels[6]["targets"]] == [
        'max by (job) (up{job=~"sensor-service|grow-room-ha-host"})',
        "sum by (job) (rate(grow_read_errors[5m]))",
    ]
    assert [target["expr"] for target in panels[7]["targets"]] == ["grow_co2_ppm"]
    for panel_id, grid in ORIGINAL_GRIDS.items():
        assert panels[panel_id]["gridPos"] == grid


def test_plant_mood_panel_sits_between_co2_and_the_controller_row():
    """One stat per scrape job, from the gauge, not from the JSON endpoint."""
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}
    mood = panels[23]
    co2 = panels[7]
    controller_row = panels[8]
    assert mood["type"] == "stat"
    assert mood["title"] == "Plant mood"
    assert [target["expr"] for target in mood["targets"]] == ["max by (job) (grow_room_plant_mood)"]
    assert mood["targets"][0]["legendFormat"] == "{{job}}"
    assert "heuristic" in mood["description"].lower()
    assert "agronomy" in mood["description"].lower()
    mapping = mood["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert mapping["3"]["text"] == "🌿 cozy"
    assert mapping["1"]["text"] == "🫠 swampy"
    assert mapping["5"]["text"] == "🥵 crispy"
    assert co2["gridPos"]["y"] + co2["gridPos"]["h"] == mood["gridPos"]["y"]
    assert mood["gridPos"]["y"] + mood["gridPos"]["h"] == controller_row["gridPos"]["y"]
    assert mood["gridPos"] == {"h": 4, "w": 24, "x": 0, "y": 22}


def test_scrape_panels_collapse_rolled_instances_to_one_series_per_job():
    """A dead pod IP must not remain its own Scrape up tile or legend row."""
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}
    collapsed_up = 'max by (job) (up{job=~"sensor-service|grow-room-ha-host"})'
    for panel_id in (1, 6):
        target = panels[panel_id]["targets"][0]
        assert target["expr"] == collapsed_up
        assert target["legendFormat"] == "{{job}}"
        assert "instance" not in target["expr"]
        assert "pod" not in target["expr"]
    assert panels[6]["targets"][1]["expr"] == "sum by (job) (rate(grow_read_errors[5m]))"
    assert panels[6]["targets"][1]["legendFormat"] == "read_errors/s {{job}}"

    # The live pod, the rolled pod from the k3d diagnosis, and the Compose HA
    # target. max by (job) keeps one series per job and drops the pod IP.
    rolled = [
        {
            "job": "sensor-service",
            "instance": "10.42.2.13:8000",
            "pod": "sensor-service-68ffc755b5-lgcjt",
        },
        {
            "job": "sensor-service",
            "instance": "10.42.2.14:8000",
            "pod": "sensor-service-current",
        },
        {
            "job": "grow-room-ha-host",
            "instance": "docker-compose-sensor-service",
        },
        {"job": "kubelet", "instance": "node:10250"},
    ]
    jobs = {"sensor-service", "grow-room-ha-host"}
    selected = [sample for sample in rolled if sample["job"] in jobs]
    collapsed = _series_after_max_by(selected, ("job",), {})
    assert sorted(sample["job"] for sample in collapsed) == [
        "grow-room-ha-host",
        "sensor-service",
    ]
    assert all(set(sample) == {"job"} for sample in collapsed)


def _ha(metric: str) -> str:
    """One Home Assistant series, ignoring pod/instance/job cardinality."""
    return f'max by (sensor_source) ({metric}{{sensor_source="homeassistant"}})'


def _ha_device(metric: str) -> str:
    """One series per UIS device on the Home Assistant scrape."""
    return f'max by (device) ({metric}{{sensor_source="homeassistant"}})'


def test_garden_panels_cover_probe_controller_and_ports():
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}
    assert [(t["expr"], t["legendFormat"]) for t in panels[15]["targets"]] == [
        (_ha("grow_temperature_celsius"), "controller air"),
        (_ha("grow_probe_temperature_celsius"), "probe canopy"),
    ]
    assert [(t["expr"], t["legendFormat"]) for t in panels[16]["targets"]] == [
        (_ha("grow_humidity_percent"), "controller air"),
        (_ha("grow_probe_humidity_percent"), "probe canopy"),
    ]
    assert [(t["expr"], t["legendFormat"]) for t in panels[17]["targets"]] == [
        (_ha("grow_vpd_kpa"), "computed leaf"),
        (_ha("grow_controller_vpd_kpa"), "controller"),
        (_ha("grow_probe_vpd_kpa"), "probe canopy"),
    ]
    for panel_id in (15, 16, 17):
        names = [target["legendFormat"] for target in panels[panel_id]["targets"]]
        assert len(names) == len(set(names))
        assert all("{{" not in name for name in names)
    assert panels[10]["targets"][0]["expr"] == _ha("grow_controller_status")
    assert panels[11]["targets"][0]["expr"] == _ha("grow_controller_vpd_kpa")
    assert panels[12]["targets"][0]["expr"] == _ha("grow_probe_temperature_celsius")
    assert panels[13]["targets"][0]["expr"] == _ha("grow_probe_humidity_percent")
    assert panels[14]["targets"][0]["expr"] == _ha("grow_probe_vpd_kpa")
    for panel_id in (19, 21):
        target = panels[panel_id]["targets"][0]
        assert target["expr"] == _ha_device("grow_port_status")
        assert target["legendFormat"] == "{{device}}"
    for panel_id in (20, 22):
        target = panels[panel_id]["targets"][0]
        assert target["expr"] == _ha_device("grow_port_current_power")
        assert target["legendFormat"] == "{{device}}"


def _series_after_max_by(
    series: list[dict[str, str]],
    by: tuple[str, ...],
    selector: dict[str, str],
) -> list[dict[str, str]]:
    """Collapse label sets the way `max by (...) (metric{selector})` does."""
    matched = [sample for sample in series if all(sample.get(k) == v for k, v in selector.items())]
    grouped: dict[tuple[str, ...], dict[str, str]] = {}
    for sample in matched:
        key = tuple(sample.get(label, "") for label in by)
        grouped[key] = {label: sample.get(label, "") for label in by}
    return list(grouped.values())


def test_homeassistant_aggregation_drops_simulator_pod_history():
    # grow_temperature_celsius is exported by every rolled simulator pod and by
    # the Compose scrape. A fixed legendFormat repeats once per series.
    climate = [
        {"job": "sensor-service", "instance": "10.0.0.1:8000", "pod": "sensor-service-aaa"},
        {"job": "sensor-service", "instance": "10.0.0.2:8000", "pod": "sensor-service-bbb"},
        {"job": "sensor-service", "instance": "10.0.0.3:8000", "pod": "sensor-service-ccc"},
        {
            "job": "grow-room-ha-host",
            "instance": "docker-compose-sensor-service",
            "sensor_source": "homeassistant",
        },
    ]
    assert _series_after_max_by(
        climate, ("sensor_source",), {"sensor_source": "homeassistant"}
    ) == [{"sensor_source": "homeassistant"}]

    ports = [
        {
            "device": "port_1",
            "sensor_source": "homeassistant",
            "instance": "docker-compose-sensor-service",
            "job": "grow-room-ha-host",
        },
        {
            "device": "humidifier",
            "sensor_source": "homeassistant",
            "instance": "docker-compose-sensor-service",
            "job": "grow-room-ha-host",
        },
        {
            "device": "port_1",
            "sensor_source": "homeassistant",
            "instance": "10.0.0.9:8000",
            "job": "other",
        },
    ]
    collapsed = _series_after_max_by(ports, ("device",), {"sensor_source": "homeassistant"})
    assert sorted(sample["device"] for sample in collapsed) == ["humidifier", "port_1"]


def test_panels_do_not_overlap():
    boxes: list[tuple[int, int, int, int, int]] = []
    for panel in _dashboard()["panels"]:
        grid = panel["gridPos"]
        assert grid["w"] > 0 and grid["h"] > 0
        assert 0 <= grid["x"] and grid["x"] + grid["w"] <= 24
        boxes.append(
            (
                panel["id"],
                grid["x"],
                grid["y"],
                grid["x"] + grid["w"],
                grid["y"] + grid["h"],
            )
        )
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            separate = (
                left[3] <= right[1]
                or right[3] <= left[1]
                or left[4] <= right[2]
                or right[4] <= left[2]
            )
            assert separate, f"panels {left[0]} and {right[0]} overlap"
