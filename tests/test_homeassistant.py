import httpx
import pytest

from sensor_service.config import build_source
from sensor_service.sources import HomeAssistantSource, SimulatorSource

STATES = {
    "sensor.tent_temperature": {"state": "77.0", "attributes": {"unit_of_measurement": "°F"}},
    "sensor.tent_humidity": {"state": "60", "attributes": {"unit_of_measurement": "%"}},
    "sensor.tent_offline": {"state": "unavailable", "attributes": {}},
}


def mock_client(seen_methods: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen_methods.append(request.method)
        assert request.headers["Authorization"] == "Bearer test-token"
        entity = request.url.path.rsplit("/", 1)[-1]
        if entity not in STATES:
            return httpx.Response(404)
        return httpx.Response(200, json=STATES[entity])

    return httpx.Client(
        base_url="http://ha.local:8123",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    )


def make(seen, humidity="sensor.tent_humidity"):
    return HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity=humidity,
        client=mock_client(seen),
    )


def test_parses_fahrenheit_and_humidity():
    seen: list[str] = []
    r = make(seen).read()
    assert r.temperature_c == pytest.approx(25.0)
    assert r.humidity_percent == 60.0
    assert r.co2_ppm is None
    assert r.source == "homeassistant"
    assert set(seen) == {"GET"}  # read-only: never POSTs control commands


def test_unavailable_state_raises():
    with pytest.raises(ValueError):
        make([], humidity="sensor.tent_offline").read()


def test_missing_credentials():
    with pytest.raises(ValueError):
        build_source({"SENSOR_SOURCE": "homeassistant"})


def test_default_is_simulator():
    assert isinstance(build_source({}), SimulatorSource)


def test_unknown_source():
    with pytest.raises(ValueError):
        build_source({"SENSOR_SOURCE": "nope"})
