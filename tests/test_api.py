from fastapi.testclient import TestClient

from sensor_service.main import create_app
from sensor_service.models import DeviceReading, ProbeReading, Reading
from sensor_service.sources import SimulatorSource


class BrokenSource:
    def read(self) -> Reading:
        raise RuntimeError("controller offline")


def client(source=None):
    return TestClient(create_app(source or SimulatorSource(seed=1), leaf_offset=0.0))


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
    resp = client(BrokenSource()).get("/metrics")
    assert resp.status_code == 200
    assert "grow_read_errors" in resp.text


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
    assert "grow_controller_vpd_kpa" in body
    assert "grow_controller_status" in body
    assert 'grow_port_current_power{device="port_1"}' in body
    assert 'grow_port_current_power{device="humidifier"}' in body
    assert 'grow_port_status{device="port_1"}' in body
    assert 'grow_port_status{device="humidifier"}' in body
