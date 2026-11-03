"""GROW_STAGE selects one inclusive leaf-VPD band."""

from pathlib import Path

import pytest

from sensor_service.stage import load_growth_stage

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("raw", "name", "low", "high", "display"),
    [
        ("veg", "veg", 0.8, 1.2, "veg"),
        ("SEEDLING", "seedling", 0.4, 0.8, "seedling/clone"),
        ("clone", "seedling", 0.4, 0.8, "seedling/clone"),
        ("clones", "seedling", 0.4, 0.8, "seedling/clone"),
        ("seedling/clone", "seedling", 0.4, 0.8, "seedling/clone"),
        ("vegetative", "veg", 0.8, 1.2, "veg"),
        ("flower", "flower", 1.2, 1.5, "flower"),
        ("flowering", "flower", 1.2, 1.5, "flower"),
        ("late_flower", "late_flower", 1.4, 1.6, "late flower"),
        ("late-flower", "late_flower", 1.4, 1.6, "late flower"),
        ("late flower", "late_flower", 1.4, 1.6, "late flower"),
        ("late--flower", "late_flower", 1.4, 1.6, "late flower"),
    ],
)
def test_stage_selects_inclusive_band(raw, name, low, high, display):
    stage = load_growth_stage({"GROW_STAGE": raw})
    assert stage.name == name
    assert stage.display == display
    assert stage.low_kpa == low
    assert stage.high_kpa == high
    assert stage.contains(low)
    assert stage.contains(high)
    assert stage.contains((low + high) / 2)
    assert not stage.contains(low - 0.001)
    assert not stage.contains(high + 0.001)


def test_missing_stage_defaults_to_veg():
    stage = load_growth_stage({})
    assert stage.name == "veg"
    assert (stage.low_kpa, stage.high_kpa) == (0.8, 1.2)
    payload = stage.to_api()
    assert payload["growth_stage"] == "veg"
    assert "0.4-0.8" in payload["note"]
    assert "not a cultivar prescription" in payload["note"].lower()


def test_band_env_overrides_the_named_stage_only():
    stage = load_growth_stage(
        {
            "GROW_STAGE": "flower",
            "VPD_BAND_FLOWER": "1.15, 1.45",
            "VPD_BAND_VEG": "0.7,1.1",
        }
    )
    assert (stage.low_kpa, stage.high_kpa) == (1.15, 1.45)


def test_active_edge_override_can_replace_one_side():
    stage = load_growth_stage({"VPD_TARGET_HIGH_KPA": "1.0"})
    assert stage.name == "veg"
    assert (stage.low_kpa, stage.high_kpa) == (0.8, 1.0)


def test_blank_overrides_are_ignored():
    stage = load_growth_stage(
        {
            "GROW_STAGE": "veg",
            "VPD_TARGET_LOW_KPA": "  ",
            "VPD_TARGET_HIGH_KPA": "",
            "VPD_BAND_VEG": " ",
        }
    )
    assert (stage.low_kpa, stage.high_kpa) == (0.8, 1.2)


def test_inactive_band_override_still_has_to_parse():
    with pytest.raises(ValueError, match="VPD_BAND_FLOWER"):
        load_growth_stage({"GROW_STAGE": "veg", "VPD_BAND_FLOWER": "nope"})


@pytest.mark.parametrize(
    "env",
    [
        {"GROW_STAGE": "bloom"},
        {"GROW_STAGE": "  "},
        {"GROW_STAGE": "flower", "VPD_BAND_FLOWER": "1.5,1.2"},
        {"GROW_STAGE": "flower", "VPD_BAND_FLOWER": "1.2"},
        {"VPD_TARGET_LOW_KPA": "nope"},
        {"VPD_TARGET_HIGH_KPA": "nan"},
        {"VPD_TARGET_LOW_KPA": "-0.1"},
        {"VPD_TARGET_HIGH_KPA": "12"},
        {"VPD_TARGET_LOW_KPA": "1.2", "VPD_TARGET_HIGH_KPA": "1.2"},
        {"VPD_BAND_VEG": "nope,1"},
        {"VPD_BAND_VEG": "nan,1.2"},
        {"VPD_BAND_VEG": "1.2,"},
    ],
)
def test_invalid_stage_config_raises(env):
    with pytest.raises(ValueError):
        load_growth_stage(env)


def test_chart_and_compose_default_stage_to_veg():
    values = (ROOT / "charts/sensor-service/values.yaml").read_text()
    k3d = (ROOT / "charts/sensor-service/values-k3d.yaml").read_text()
    eks = (ROOT / "charts/sensor-service/values-eks.yaml").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "GROW_STAGE: veg" in values
    assert "GROW_STAGE: veg" in k3d
    assert "GROW_STAGE: veg" in eks
    assert "GROW_STAGE: ${GROW_STAGE:-veg}" in compose


def test_athena_tables_add_optional_stage_column():
    for relative in ("infra/telemetry/main.tf", "infra/aws-poc/data.tf"):
        text = (ROOT / relative).read_text()
        assert 'name = "stage"' in text
        assert 'type = "string"' in text
