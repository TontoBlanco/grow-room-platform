"""ship_readings keeps the Glue columns, including optional stage."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]


def _ship_readings():
    sys.modules.setdefault("boto3", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "ship_readings", ROOT / "scripts" / "ship_readings.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flatten_forwards_optional_stage_and_leaves_it_null_when_absent():
    flatten = _ship_readings().flatten
    bare = flatten({"temperature_c": 24.0, "humidity_percent": 55.0, "source": "homeassistant"})
    assert bare["stage"] is None
    assert bare["source"] == "homeassistant"
    assert bare["temperature_c"] == 24.0
    flower = flatten({"stage": "flower", "vpd_kpa": 1.3})
    assert flower["stage"] == "flower"
    assert flower["vpd_kpa"] == 1.3
