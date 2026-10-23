"""Configuration from environment variables only (never hardcode secrets)."""

import os

from sensor_service.sources import HomeAssistantSource, SimulatorSource, Source


def build_source(env: dict[str, str] | None = None) -> Source:
    env = dict(os.environ) if env is None else env
    kind = env.get("SENSOR_SOURCE", "simulator").lower()
    if kind == "simulator":
        return SimulatorSource()
    if kind == "homeassistant":
        return HomeAssistantSource(
            url=env.get("HA_URL", ""),
            token=env.get("HA_TOKEN", ""),
            temp_entity=env.get("HA_TEMP_ENTITY", "sensor.grow_tent_temperature"),
            humidity_entity=env.get("HA_HUMIDITY_ENTITY", "sensor.grow_tent_humidity"),
            co2_entity=env.get("HA_CO2_ENTITY") or None,
        )
    raise ValueError(f"Unknown SENSOR_SOURCE: {kind!r} (use simulator or homeassistant)")


def leaf_offset_c(env: dict[str, str] | None = None) -> float:
    env = dict(os.environ) if env is None else env
    return float(env.get("LEAF_TEMP_OFFSET_C", "0"))
