"""S3 shipper flattens /readings and adds stage only when the API sent one."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "ship_readings", ROOT / "scripts" / "ship_readings.py"
)
ship = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(ship)

BASE_KEYS = {
    "timestamp",
    "temperature_c",
    "humidity_percent",
    "vpd_kpa",
    "controller_vpd_kpa",
    "probe_temperature_c",
    "probe_humidity_percent",
    "co2_ppm",
    "source",
    "host",
}


def _reading(**extra):
    payload = {
        "timestamp": "2026-11-03T00:00:00+00:00",
        "temperature_c": 25.0,
        "humidity_percent": 60.0,
        "vpd_kpa": 1.268,
        "co2_ppm": None,
        "source": "homeassistant",
        "controller": {"vpd_kpa": 1.2},
        "probe": {"temperature_c": 24.0, "humidity_percent": 64.0},
    }
    payload.update(extra)
    return payload


def test_flatten_keeps_the_existing_columns_without_stage():
    row = ship.flatten(_reading())
    assert set(row) == BASE_KEYS
    assert row["controller_vpd_kpa"] == 1.2
    assert row["probe_temperature_c"] == 24.0
    assert row["probe_humidity_percent"] == 64.0
    assert row["host"]


def test_flatten_adds_stage_when_the_reading_has_one():
    row = ship.flatten(_reading(growth_stage=" late_flower "))
    assert set(row) == BASE_KEYS | {"stage"}
    assert row["stage"] == "late_flower"


def test_flatten_skips_a_blank_stage():
    row = ship.flatten(_reading(growth_stage="  "))
    assert "stage" not in row
