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


def _state(value: str, unit: str | None = None) -> dict:
    attributes = {} if unit is None else {"unit_of_measurement": unit}
    return {"state": value, "attributes": attributes}


GARDEN_STATES = {
    "sensor.the_garden_controller_temperature": _state("77.0", "°F"),
    "sensor.the_garden_controller_humidity": _state("60", "%"),
    "sensor.the_garden_controller_vpd": _state("0.180", "psi"),
    "binary_sensor.the_garden_status": _state("on"),
    "sensor.the_garden_probe_sensor_probe_temperature": _state("75.2", "°F"),
    "sensor.the_garden_probe_sensor_probe_humidity": _state("64", "%"),
    "sensor.the_garden_probe_sensor_probe_vpd": _state("0.160", "psi"),
    "binary_sensor.the_garden_port_1_status": _state("on"),
    "binary_sensor.the_garden_port_1_state": _state("on"),
    "sensor.the_garden_port_1_current_power": _state("6"),
    "select.the_garden_port_1_active_mode": _state("Auto"),
    "binary_sensor.the_garden_humidifier_status": _state("on"),
    "binary_sensor.the_garden_humidifier_state": _state("off"),
    "sensor.the_garden_humidifier_current_power": _state("0"),
    "select.the_garden_humidifier_active_mode": _state("Auto"),
    "binary_sensor.the_garden_oscillating_fans_status": _state("on"),
    "binary_sensor.the_garden_oscillating_fans_state": _state("on"),
    "sensor.the_garden_oscillating_fans_current_power": _state("4"),
    "select.the_garden_oscillating_fans_active_mode": _state("On"),
    "binary_sensor.the_garden_ventilation_fan_status": _state("on"),
    "binary_sensor.the_garden_ventilation_fan_state": _state("unavailable"),
    "sensor.the_garden_ventilation_fan_current_power": _state("8"),
    "select.the_garden_ventilation_fan_active_mode": _state("VPD"),
}


def test_default_garden_entity_ids():
    src = build_source(
        {"SENSOR_SOURCE": "homeassistant", "HA_URL": "http://ha.local:8123", "HA_TOKEN": "t"}
    )
    src._client.close()
    assert src.temp_entity == "sensor.the_garden_controller_temperature"
    assert src.humidity_entity == "sensor.the_garden_controller_humidity"
    assert src.vpd_entity == "sensor.the_garden_controller_vpd"
    assert src.status_entity == "binary_sensor.the_garden_status"
    assert src.probe_temp_entity == "sensor.the_garden_probe_sensor_probe_temperature"
    assert src.probe_humidity_entity == "sensor.the_garden_probe_sensor_probe_humidity"
    assert src.probe_vpd_entity == "sensor.the_garden_probe_sensor_probe_vpd"
    assert list(src.port_entities) == [
        "port_1",
        "humidifier",
        "oscillating_fans",
        "ventilation_fan",
    ]
    assert "port_4" not in src.port_entities
    assert src.port_entities["ventilation_fan"] == {
        "status": "binary_sensor.the_garden_ventilation_fan_status",
        "state": "binary_sensor.the_garden_ventilation_fan_state",
        "current_power": "sensor.the_garden_ventilation_fan_current_power",
        "active_mode": "select.the_garden_ventilation_fan_active_mode",
    }


def test_entity_overrides_and_extra_port():
    src = build_source(
        {
            "SENSOR_SOURCE": "homeassistant",
            "HA_URL": "http://ha.local:8123",
            "HA_TOKEN": "t",
            "HA_DEVICE_PREFIX": "The_Garden",
            "HA_VPD_ENTITY": "",
            "HA_PROBE_TEMP_ENTITY": "sensor.custom_probe_temp",
            "HA_PORT_DEVICES": "port_1,port_4",
            "HA_CO2_ENTITY": "sensor.the_garden_co2",
        }
    )
    src._client.close()
    assert src.temp_entity == "sensor.the_garden_controller_temperature"
    assert src.vpd_entity is None
    assert src.probe_temp_entity == "sensor.custom_probe_temp"
    assert src.co2_entity == "sensor.the_garden_co2"
    assert list(src.port_entities) == ["port_1", "port_4"]
    assert src.port_entities["port_4"]["current_power"] == "sensor.the_garden_port_4_current_power"


def test_blank_prefix_requires_explicit_climate_entities():
    with pytest.raises(ValueError):
        build_source(
            {
                "SENSOR_SOURCE": "homeassistant",
                "HA_URL": "http://ha.local",
                "HA_TOKEN": "t",
                "HA_DEVICE_PREFIX": "",
                "HA_PORT_DEVICES": "",
            }
        )


def test_invalid_prefix():
    with pytest.raises(ValueError):
        build_source(
            {
                "SENSOR_SOURCE": "homeassistant",
                "HA_URL": "http://ha.local",
                "HA_TOKEN": "t",
                "HA_DEVICE_PREFIX": "9garden",
            }
        )


def test_blank_port_entries_are_skipped():
    src = build_source(
        {
            "SENSOR_SOURCE": "homeassistant",
            "HA_URL": "http://ha.local:8123",
            "HA_TOKEN": "t",
            "HA_PORT_DEVICES": "port_1, ,humidifier",
        }
    )
    src._client.close()
    assert list(src.port_entities) == ["port_1", "humidifier"]


def test_invalid_port_slug():
    with pytest.raises(ValueError):
        build_source(
            {
                "SENSOR_SOURCE": "homeassistant",
                "HA_URL": "http://ha.local",
                "HA_TOKEN": "t",
                "HA_PORT_DEVICES": "port 4",
            }
        )


def test_ports_need_a_prefix():
    with pytest.raises(ValueError):
        build_source(
            {
                "SENSOR_SOURCE": "homeassistant",
                "HA_URL": "http://ha.local",
                "HA_TOKEN": "t",
                "HA_DEVICE_PREFIX": "",
                "HA_TEMP_ENTITY": "sensor.x_temperature",
                "HA_HUMIDITY_ENTITY": "sensor.x_humidity",
                "HA_PORT_DEVICES": "port_1",
            }
        )


def _client_for(states: dict, seen: list[str], paths: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        paths.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer test-token"
        entity = request.url.path.rsplit("/", 1)[-1]
        if entity not in states:
            return httpx.Response(404)
        payload = states[entity]
        if payload == "error":
            return httpx.Response(500)
        return httpx.Response(200, json=payload)

    return httpx.Client(
        base_url="http://ha.local:8123",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(handler),
    )


def test_garden_reading_converts_psi_and_nests_ports():
    seen: list[str] = []
    paths: list[str] = []
    configured = build_source(
        {"SENSOR_SOURCE": "homeassistant", "HA_URL": "http://ha.local:8123", "HA_TOKEN": "t"}
    )
    configured._client.close()
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity=configured.temp_entity,
        humidity_entity=configured.humidity_entity,
        vpd_entity=configured.vpd_entity,
        status_entity=configured.status_entity,
        probe_temp_entity=configured.probe_temp_entity,
        probe_humidity_entity=configured.probe_humidity_entity,
        probe_vpd_entity=configured.probe_vpd_entity,
        port_entities=configured.port_entities,
        client=_client_for(GARDEN_STATES, seen, paths),
    )
    data = src.read().to_dict()
    assert data["temperature_c"] == 25.0
    assert data["humidity_percent"] == 60.0
    assert data["source"] == "homeassistant"
    assert data["controller"]["status"] == "on"
    assert data["controller"]["vpd_unit"] == "psi"
    assert data["controller"]["vpd_raw"] == 0.18
    assert data["controller"]["vpd_kpa"] == 1.241
    assert data["probe"]["temperature_c"] == 24.0
    assert data["probe"]["temperature_f"] == 75.2
    assert data["probe"]["humidity_percent"] == 64.0
    assert data["probe"]["vpd_kpa"] == 1.103
    assert data["probe"]["vpd_unit"] == "psi"
    assert data["ports"]["port_1"] == {
        "status": "on",
        "state": "on",
        "current_power": 6.0,
        "active_mode": "Auto",
    }
    assert data["ports"]["humidifier"]["current_power"] == 0.0
    assert data["ports"]["humidifier"]["state"] == "off"
    assert data["ports"]["oscillating_fans"]["active_mode"] == "On"
    assert data["ports"]["ventilation_fan"]["state"] is None
    assert data["ports"]["ventilation_fan"]["active_mode"] == "VPD"
    assert "port_4" not in data["ports"]
    assert set(seen) == {"GET"}
    entities = {path.rsplit("/", 1)[-1] for path in paths}
    domains = {entity.split(".", 1)[0] for entity in entities}
    assert domains <= {"sensor", "binary_sensor", "select"}
    assert not any(entity.startswith(("number.", "switch.", "time.")) for entity in entities)
    assert all(path.startswith("/api/states/") for path in paths)


def test_optional_misses_leave_controller_air_intact():
    states = {
        "sensor.tent_temperature": _state("25.0", "°C"),
        "sensor.tent_humidity": _state("55", "%"),
        "sensor.tent_vpd": "error",
        "sensor.tent_probe_temperature": _state("unavailable"),
        "sensor.tent_probe_humidity": _state("not-a-number", "%"),
        "sensor.tent_co2": _state("812", "ppm"),
    }
    seen: list[str] = []
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        co2_entity="sensor.tent_co2",
        vpd_entity="sensor.tent_vpd",
        probe_temp_entity="sensor.tent_probe_temperature",
        probe_humidity_entity="sensor.tent_probe_humidity",
        port_entities={
            "port_4": {
                "status": "binary_sensor.tent_port_4_status",
                "state": "binary_sensor.tent_port_4_state",
                "current_power": "sensor.tent_port_4_current_power",
                "active_mode": "select.tent_port_4_active_mode",
            }
        },
        client=_client_for(states, seen, []),
    )
    data = src.read().to_dict()
    assert data["temperature_c"] == 25.0
    assert data["co2_ppm"] == 812.0
    assert data["controller"]["vpd_kpa"] is None
    assert data["controller"]["vpd_raw"] is None
    assert data["probe"] is None
    assert data["ports"] == {}
    assert set(seen) == {"GET"}


def test_unknown_vpd_unit_is_labeled_and_not_converted():
    states = {
        "sensor.tent_temperature": _state("25", "°C"),
        "sensor.tent_humidity": _state("50", "%"),
        "sensor.tent_vpd": _state("1.2", "banana"),
    }
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        vpd_entity="sensor.tent_vpd",
        client=_client_for(states, [], []),
    )
    controller = src.read().to_dict()["controller"]
    assert controller["vpd_kpa"] is None
    assert controller["vpd_raw"] == 1.2
    assert controller["vpd_unit"] == "banana"


def test_missing_required_entity():
    with pytest.raises(ValueError):
        make([], humidity="sensor.missing").read()


def test_required_entity_with_non_object_payload():
    states = {
        "sensor.tent_temperature": ["nope"],
        "sensor.tent_humidity": _state("50", "%"),
    }
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        client=_client_for(states, [], []),
    )
    with pytest.raises(ValueError, match="unexpected payload"):
        src.read()


def test_required_non_numeric_state():
    states = {
        "sensor.tent_temperature": _state("hot", "°C"),
        "sensor.tent_humidity": _state("50", "%"),
    }
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        client=_client_for(states, [], []),
    )
    with pytest.raises(ValueError):
        src.read()


def test_optional_non_dict_payload_is_skipped():
    states = {
        "sensor.tent_temperature": _state("25", "°C"),
        "sensor.tent_humidity": _state("50", "%"),
        "sensor.tent_vpd": ["not", "an", "entity"],
        "select.tent_port_1_active_mode": {"state": None, "attributes": {}},
        "select.tent_port_1_mode_off": _state("unavailable"),
    }
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        vpd_entity="sensor.tent_vpd",
        port_entities={
            "port_1": {
                "status": "binary_sensor.missing_status",
                "state": "binary_sensor.missing_state",
                "current_power": "sensor.missing_power",
                "active_mode": "select.tent_port_1_active_mode",
            },
            "spare": {
                "status": "binary_sensor.missing_status",
                "state": "binary_sensor.missing_state",
                "current_power": "sensor.missing_power",
                "active_mode": "select.tent_port_1_mode_off",
            },
        },
        client=_client_for(states, [], []),
    )
    data = src.read().to_dict()
    assert data["controller"]["vpd_kpa"] is None
    assert data["ports"] == {}


def test_vpd_without_a_unit_stays_raw():
    states = {
        "sensor.tent_temperature": _state("25", "°C"),
        "sensor.tent_humidity": _state("50", "%"),
        "sensor.tent_vpd": _state("0.18"),
    }
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        vpd_entity="sensor.tent_vpd",
        client=_client_for(states, [], []),
    )
    controller = src.read().to_dict()["controller"]
    assert controller["vpd_kpa"] is None
    assert controller["vpd_raw"] == 0.18
    assert controller["vpd_unit"] is None


def test_kpa_vpd_is_not_rescaled():
    states = {
        "sensor.tent_temperature": _state("25", "°C"),
        "sensor.tent_humidity": _state("50", "%"),
        "sensor.tent_vpd": _state("1.25", "kPa"),
    }
    src = HomeAssistantSource(
        url="http://ha.local:8123",
        token="test-token",
        temp_entity="sensor.tent_temperature",
        humidity_entity="sensor.tent_humidity",
        vpd_entity="sensor.tent_vpd",
        client=_client_for(states, [], []),
    )
    controller = src.read().to_dict()["controller"]
    assert controller["vpd_kpa"] == 1.25
    assert controller["vpd_unit"] == "kPa"
