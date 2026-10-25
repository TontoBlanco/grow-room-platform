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
    1: {"h": 4, "w": 4, "x": 0, "y": 0},
    2: {"h": 4, "w": 5, "x": 4, "y": 0},
    3: {"h": 4, "w": 5, "x": 9, "y": 0},
    4: {"h": 4, "w": 5, "x": 14, "y": 0},
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
        'up{job="sensor-service"}',
        "rate(grow_read_errors[5m])",
    ]
    assert [target["expr"] for target in panels[7]["targets"]] == ["grow_co2_ppm"]
    for panel_id, grid in ORIGINAL_GRIDS.items():
        assert panels[panel_id]["gridPos"] == grid


def test_garden_panels_cover_probe_controller_and_ports():
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}
    assert panels[15]["targets"][0]["expr"] == "grow_temperature_celsius"
    assert panels[15]["targets"][1]["expr"] == "grow_probe_temperature_celsius"
    assert panels[16]["targets"][1]["expr"] == "grow_probe_humidity_percent"
    assert [target["expr"] for target in panels[17]["targets"]] == [
        "grow_vpd_kpa",
        "grow_controller_vpd_kpa",
        "grow_probe_vpd_kpa",
    ]
    assert panels[10]["targets"][0]["expr"] == "grow_controller_status"
    assert panels[19]["targets"][0]["expr"] == "grow_port_status"
    assert panels[19]["targets"][0]["legendFormat"] == "{{device}}"
    assert panels[20]["targets"][0]["expr"] == "grow_port_current_power"
    assert panels[22]["targets"][0]["legendFormat"] == "{{device}}"


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
