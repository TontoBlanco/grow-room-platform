"""Grow-room History stays partition-pruned and aligned with its ConfigMap."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "monitoring" / "dashboards" / "grow-room-history.json"
CONFIGMAP_PATH = ROOT / "monitoring" / "manifests" / "grafana-dashboard-grow-room-history.yaml"
VALUES_PATH = ROOT / "monitoring" / "values-k3d.yaml"
SQL_PATH = ROOT / "analytics" / "athena" / "history_by_day.sql"

DT_FROM = "dt >= '${__from:date:YYYY-MM-DD}'"
DT_TO = "dt <= '${__to:date:YYYY-MM-DD}'"
FLOWER = "lower(trim(coalesce(stage, ''))) IN ('flower', 'flowering', 'bloom')"


def _dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text())


def _sqls(dashboard: dict) -> list[str]:
    found: list[str] = []
    for panel in dashboard["panels"]:
        for target in panel["targets"]:
            found.append(target["rawSQL"])
    return found


def _embedded_dashboard() -> dict:
    text = CONFIGMAP_PATH.read_text()
    marker = "grow-room-history.json: |\n"
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


def _band(stage: str | None) -> tuple[float, float]:
    """Veg unless the reading names a flower stage. Null and blank are veg."""
    normalized = (stage or "").strip().lower()
    if normalized in {"flower", "flowering", "bloom"}:
        return (1.2, 1.5)
    return (0.8, 1.2)


def test_dashboard_json_matches_grafana_configmap():
    assert _embedded_dashboard() == _dashboard()
    text = CONFIGMAP_PATH.read_text()
    assert 'grafana_dashboard: "1"' in text
    assert "namespace: monitoring" in text
    assert "name: grafana-dashboard-grow-room-history" in text


def test_history_dashboard_defaults_and_datasource():
    dashboard = _dashboard()
    assert dashboard["title"] == "Grow-room History"
    assert dashboard["uid"] == "grow-room-history"
    assert dashboard["time"] == {"from": "now-30d", "to": "now"}
    assert dashboard["timezone"] == "utc"
    assert dashboard["refresh"] == ""
    assert "under a cent" in dashboard["description"]
    assert "1 GiB" in dashboard["description"]
    values = VALUES_PATH.read_text()
    assert "uid: athena-grow-room" in values
    assert "defaultRegion: us-west-2" in values
    assert "workgroup: grow-room-telemetry" in values
    assert "database: grow_room_telemetry" in values
    for panel in dashboard["panels"]:
        assert panel["datasource"] == {
            "type": "grafana-athena-datasource",
            "uid": "athena-grow-room",
        }
        target = panel["targets"][0]
        assert target["datasource"]["uid"] == "athena-grow-room"
        assert target["connectionArgs"]["region"] == "us-west-2"
        assert target["connectionArgs"]["database"] == "grow_room_telemetry"
        assert target["connectionArgs"]["catalog"] == "AwsDataCatalog"
        assert target["connectionArgs"]["resultReuseEnabled"] is False


def test_every_query_is_partition_pruned_on_dt():
    sqls = _sqls(_dashboard())
    assert len(sqls) == 6
    for sql in sqls:
        assert "FROM grow_room_telemetry.readings" in sql
        assert DT_FROM in sql
        assert DT_TO in sql
        assert "SELECT *" not in sql
        where = sql.split("WHERE", 1)[1]
        assert "date_parse(dt" not in where
        assert "cast(dt" not in where


def test_stage_band_is_null_safe_and_matches_the_console_sql():
    sqls = _sqls(_dashboard())
    band_sqls = [sql for sql in sqls if "pct_in_band" in sql]
    assert len(band_sqls) == 2
    for sql in band_sqls:
        assert sql.count(FLOWER) == 2
        assert "ELSE 0.8" in sql
        assert "ELSE 1.2" in sql
        assert "coalesce(stage, '')" in sql
    console = SQL_PATH.read_text()
    assert console.count(FLOWER) == 2
    assert "ELSE 0.8" in console
    assert "dt >= date_format(current_date - interval '30' day, '%Y-%m-%d')" in console
    assert _band(None) == (0.8, 1.2)
    assert _band("") == (0.8, 1.2)
    assert _band("  veg  ") == (0.8, 1.2)
    assert _band("seedling") == (0.8, 1.2)
    assert _band("vegetative") == (0.8, 1.2)
    assert _band(" Flower ") == (1.2, 1.5)
    assert _band("flowering") == (1.2, 1.5)
    assert _band("bloom") == (1.2, 1.5)


def test_source_counts_treat_blank_source_as_unknown():
    sqls = _sqls(_dashboard())
    source = next(sql for sql in sqls if "AS source" in sql)
    assert "coalesce(nullif(trim(source), ''), 'unknown')" in source
    assert "GROUP BY dt, coalesce(nullif(trim(source), ''), 'unknown')" in source


def test_history_panels_do_not_overlap():
    boxes: list[tuple[int, int, int, int, int]] = []
    for panel in _dashboard()["panels"]:
        grid = panel["gridPos"]
        assert grid["w"] > 0 and grid["h"] > 0
        assert 0 <= grid["x"] and grid["x"] + grid["w"] <= 24
        boxes.append(
            (panel["id"], grid["x"], grid["y"], grid["x"] + grid["w"], grid["y"] + grid["h"])
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


def test_chart_formats_and_daily_aggregates():
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}
    assert [panel["type"] for panel in panels.values()] == [
        "timeseries",
        "timeseries",
        "timeseries",
        "timeseries",
        "timeseries",
        "table",
    ]
    assert panels[1]["targets"][0]["format"] == 0
    assert "avg_vpd" in panels[1]["targets"][0]["rawSQL"]
    assert "min_vpd" in panels[1]["targets"][0]["rawSQL"]
    assert "max_vpd" in panels[1]["targets"][0]["rawSQL"]
    assert "avg_temp_c" in panels[2]["targets"][0]["rawSQL"]
    assert "avg_rh" in panels[3]["targets"][0]["rawSQL"]
    assert panels[6]["targets"][0]["format"] == 1
    assert "AS samples" in panels[6]["targets"][0]["rawSQL"]
