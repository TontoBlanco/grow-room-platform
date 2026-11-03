import re

import pytest
from fastapi.testclient import TestClient

from sensor_service.main import create_app
from sensor_service.models import DeviceReading, ProbeReading, Reading
from sensor_service.mood import BANDS, HEURISTIC_NOTE
from sensor_service.sources import SimulatorSource
from sensor_service.stage import load_growth_stage
from sensor_service.vpd import vpd_kpa


class BrokenSource:
    def read(self) -> Reading:
        raise RuntimeError("controller offline")


def _gauge(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[-1])
    raise AssertionError(f"{name} not in metrics")


def client(source=None, growth_stage=None):
    # Empty env keeps the suite on the veg default even if the shell has GROW_STAGE.
    stage = load_growth_stage({}) if growth_stage is None else growth_stage
    return TestClient(
        create_app(
            source or SimulatorSource(seed=1),
            leaf_offset=0.0,
            growth_stage=stage,
        )
    )


def test_healthz():
    resp = client().get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readings_shape():
    data = client().get("/readings").json()
    for key in ("temperature_c", "temperature_f", "humidity_percent", "vpd_kpa", "co2_ppm"):
        assert key in data
    assert data["vpd_kpa"] >= 0
    assert data["controller"]["temperature_c"] == data["temperature_c"]
    assert data["controller"]["vpd_kpa"] is None
    assert data["probe"] is None
    assert data["ports"] == {}
    assert "controller_vpd_kpa" not in data


def test_metrics_prometheus_format():
    resp = client().get("/metrics")
    assert resp.status_code == 200
    assert "grow_vpd_kpa" in resp.text
    assert "text/plain" in resp.headers["content-type"]


def test_readings_503_when_source_fails():
    resp = client(BrokenSource()).get("/readings")
    assert resp.status_code == 503


def test_metrics_still_served_when_source_fails():
    stage = load_growth_stage({"GROW_STAGE": "late_flower"})
    resp = client(BrokenSource(), growth_stage=stage).get("/metrics")
    assert resp.status_code == 200
    assert "grow_read_errors" in resp.text
    assert "grow_room_stage_info{" in resp.text
    assert 'stage="late_flower"' in resp.text
    assert "grow_vpd_target_low_kpa" in resp.text
    assert "grow_vpd_target_high_kpa" in resp.text


def test_stage_endpoint_and_readings_follow_the_band():
    veg = client(StaticSource(Reading(temperature_c=25.0, humidity_percent=60.0)))
    stage = veg.get("/stage")
    assert stage.status_code == 200
    body = stage.json()
    assert body["growth_stage"] == "veg"
    assert body["display"] == "veg"
    assert body["vpd_target_low_kpa"] == 0.8
    assert body["vpd_target_high_kpa"] == 1.2
    assert "Pulse Grow" in body["note"]

    reading = veg.get("/readings").json()
    assert reading["growth_stage"] == "veg"
    assert reading["vpd_target_low_kpa"] == 0.8
    assert reading["vpd_target_high_kpa"] == 1.2
    # 25 C at 60% RH is about 1.27 kPa, outside the veg band.
    assert reading["vpd_in_target_band"] is False

    # 25 C at 60% RH is about 1.27 kPa, inside the flower band.
    flower = load_growth_stage({"GROW_STAGE": "flower"})
    http = client(StaticSource(Reading(temperature_c=25.0, humidity_percent=60.0)), flower)
    data = http.get("/readings").json()
    assert data["growth_stage"] == "flower"
    assert data["vpd_target_low_kpa"] == 1.2
    assert data["vpd_target_high_kpa"] == 1.5
    assert data["vpd_in_target_band"] is True
    assert http.get("/stage").json()["display"] == "flower"

    metrics = http.get("/metrics").text
    assert 'stage="flower"' in metrics
    assert 'display="flower"' in metrics
    assert "grow_vpd_in_target_band 1.0" in metrics


def test_stage_endpoint_does_not_need_a_sensor():
    resp = client(BrokenSource()).get("/stage")
    assert resp.status_code == 200
    assert resp.json()["growth_stage"] == "veg"


def test_create_app_reads_grow_stage_from_the_environment(monkeypatch):
    monkeypatch.setenv("GROW_STAGE", "clone")
    for key in (
        "VPD_TARGET_LOW_KPA",
        "VPD_TARGET_HIGH_KPA",
        "VPD_BAND_SEEDLING",
        "VPD_BAND_VEG",
        "VPD_BAND_FLOWER",
        "VPD_BAND_LATE_FLOWER",
    ):
        monkeypatch.delenv(key, raising=False)
    http = TestClient(create_app(SimulatorSource(seed=1), leaf_offset=0.0))
    body = http.get("/stage").json()
    assert body["growth_stage"] == "seedling"
    assert body["display"] == "seedling/clone"
    assert body["vpd_target_low_kpa"] == 0.4
    assert body["vpd_target_high_kpa"] == 0.8
    metrics = http.get("/metrics").text
    assert 'stage="seedling"' in metrics
    assert 'display="seedling/clone"' in metrics
    assert "grow_vpd_target_low_kpa 0.4" in metrics
    assert "grow_vpd_target_high_kpa 0.8" in metrics


def _mood_samples(body: str) -> dict[str, float]:
    return {
        band: float(value)
        for band, value in re.findall(r'grow_room_plant_mood\{band="([a-z_]+)"\} (\S+)', body)
    }


def test_mood_endpoint_shape_and_metric():
    http = client(StaticSource(Reading(temperature_c=25.0, humidity_percent=68.5)))
    reading = http.get("/readings").json()
    resp = http.get("/mood")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mood"] == "cozy"
    assert data["emoji"] == "🌿"
    assert data["band"] == "ideal"
    assert data["score"] == 3
    assert data["message"] == "Sweet spot — stomata are vibing"
    assert data["note"] == HEURISTIC_NOTE
    assert data["vpd_kpa"] == reading["vpd_kpa"]
    assert 0.8 <= data["vpd_kpa"] <= 1.2
    assert data["temperature_c"] == reading["temperature_c"]
    assert data["humidity_percent"] == reading["humidity_percent"]

    samples = _mood_samples(http.get("/metrics").text)
    assert set(samples) == {band.band for band in BANDS}
    assert samples["ideal"] == 3.0
    assert all(samples[band.band] == 0.0 for band in BANDS if band.band != "ideal")


def test_mood_503_when_source_fails():
    resp = client(BrokenSource()).get("/mood")
    assert resp.status_code == 503


class StaticSource:
    def __init__(self, reading: Reading):
        self.reading = reading

    def read(self) -> Reading:
        return self.reading


def test_readings_and_metrics_include_probe_and_ports():
    reading = Reading(
        temperature_c=25.0,
        humidity_percent=60.0,
        source="homeassistant",
        controller_vpd_kpa=1.241056,
        controller_vpd_raw=0.18,
        controller_vpd_unit="psi",
        controller_status="on",
        probe=ProbeReading(
            temperature_c=24.0,
            humidity_percent=64.0,
            vpd_kpa=1.103161,
            vpd_raw=0.16,
            vpd_unit="psi",
        ),
        ports={
            "port_1": DeviceReading(status="on", state="on", current_power=6, active_mode="Auto"),
            "humidifier": DeviceReading(
                status="off", state="off", current_power=0, active_mode="Off"
            ),
            "unused": DeviceReading(),
        },
    )
    http = client(StaticSource(reading))
    data = http.get("/readings").json()
    assert data["controller"]["vpd_kpa"] == 1.241
    assert data["controller"]["vpd_raw"] == 0.18
    assert data["controller"]["vpd_unit"] == "psi"
    assert data["controller"]["status"] == "on"
    assert data["probe"]["temperature_c"] == 24.0
    assert data["probe"]["humidity_percent"] == 64.0
    assert data["probe"]["vpd_kpa"] == 1.103
    assert data["ports"]["port_1"]["current_power"] == 6
    assert data["ports"]["humidifier"]["status"] == "off"
    assert "unused" not in data["ports"]
    # Leaf offset changes computed VPD and leaves the device-reported VPD alone.
    shifted = reading.to_dict(leaf_offset_c=-2.0)
    assert shifted["vpd_kpa"] != data["vpd_kpa"]
    assert shifted["controller"]["vpd_kpa"] == data["controller"]["vpd_kpa"]

    metrics = http.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.text
    assert "grow_probe_temperature_celsius" in body
    assert "grow_probe_humidity_percent" in body
    assert "grow_probe_vpd_kpa" in body
    # Calculated from the probe's own temp/RH with no leaf offset.
    assert _gauge(body, "grow_probe_calculated_vpd_kpa") == pytest.approx(vpd_kpa(24.0, 64.0, 0.0))
    assert "grow_controller_vpd_kpa" in body
    assert "grow_controller_status" in body
    assert 'grow_port_current_power{device="port_1"}' in body
    assert 'grow_port_current_power{device="humidifier"}' in body
    assert 'grow_port_status{device="port_1"}' in body
    assert 'grow_port_status{device="humidifier"}' in body


def test_probe_calculated_vpd_ignores_leaf_offset():
    reading = Reading(
        temperature_c=25.0,
        humidity_percent=60.0,
        source="homeassistant",
        controller_vpd_kpa=1.2,
        probe=ProbeReading(temperature_c=24.0, humidity_percent=64.0),
    )
    http = TestClient(
        create_app(
            StaticSource(reading),
            leaf_offset=-2.0,
            growth_stage=load_growth_stage({}),
        )
    )
    value = _gauge(http.get("/metrics").text, "grow_probe_calculated_vpd_kpa")
    assert value == pytest.approx(vpd_kpa(24.0, 64.0, 0.0))
    assert value != pytest.approx(vpd_kpa(24.0, 64.0, -2.0))


def test_impossible_probe_humidity_still_serves_metrics():
    reading = Reading(
        temperature_c=25.0,
        humidity_percent=60.0,
        probe=ProbeReading(temperature_c=24.0, humidity_percent=150.0),
    )
    resp = client(StaticSource(reading)).get("/metrics")
    assert resp.status_code == 200
    assert "grow_vpd_kpa" in resp.text
