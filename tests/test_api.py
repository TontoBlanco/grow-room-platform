from fastapi.testclient import TestClient

from sensor_service.main import create_app
from sensor_service.models import Reading
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


def test_metrics_prometheus_format():
    resp = client().get("/metrics")
    assert resp.status_code == 200
    assert "grow_vpd_kpa" in resp.text
    assert "text/plain" in resp.headers["content-type"]


def test_readings_503_when_source_fails():
    resp = client(BrokenSource()).get("/readings")
    assert resp.status_code == 503
