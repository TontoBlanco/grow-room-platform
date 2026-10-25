"""Configuration from environment variables only (never hardcode secrets)."""

import os
import re

from sensor_service.sources import HomeAssistantSource, SimulatorSource, Source, port_entity_map

_SLUG = re.compile(r"[a-z][a-z0-9_]*")

# The Garden: UIS Controller AI+ (CTR89Q) plus the plugged-in UIS devices.
# Ports 4–7 exist in HA and are left out because they are unused.
DEFAULT_DEVICE_PREFIX = "the_garden"
DEFAULT_PORT_DEVICES = (
    "port_1",
    "humidifier",
    "oscillating_fans",
    "ventilation_fan",
)


def _present(env: dict[str, str], key: str) -> str | None:
    """Stripped value for a key the caller has already found in env."""
    value = env[key].strip()
    return value or None


def _entity(env: dict[str, str], key: str, default: str | None) -> str | None:
    """Explicit env wins, including a blank value that disables the entity."""
    if key not in env:
        return default
    return _present(env, key)


def _prefix(env: dict[str, str]) -> str | None:
    if "HA_DEVICE_PREFIX" not in env:
        return DEFAULT_DEVICE_PREFIX
    prefix = _present(env, "HA_DEVICE_PREFIX")
    if prefix is None:
        return None
    prefix = prefix.lower()
    if not _SLUG.fullmatch(prefix):
        raise ValueError(f"invalid HA_DEVICE_PREFIX: {prefix!r}")
    return prefix


def _port_slugs(env: dict[str, str]) -> tuple[str, ...]:
    if "HA_PORT_DEVICES" not in env:
        raw = ",".join(DEFAULT_PORT_DEVICES)
    else:
        raw = env["HA_PORT_DEVICES"]
    slugs: list[str] = []
    for part in raw.split(","):
        slug = part.strip().lower()
        if not slug:
            continue
        if not _SLUG.fullmatch(slug):
            raise ValueError(f"invalid HA_PORT_DEVICES slug: {part.strip()!r}")
        slugs.append(slug)
    return tuple(slugs)


def _derived_entities(prefix: str | None) -> dict[str, str]:
    if not prefix:
        return {}
    return {
        "temp": f"sensor.{prefix}_controller_temperature",
        "humidity": f"sensor.{prefix}_controller_humidity",
        "vpd": f"sensor.{prefix}_controller_vpd",
        "status": f"binary_sensor.{prefix}_status",
        "probe_temp": f"sensor.{prefix}_probe_sensor_probe_temperature",
        "probe_humidity": f"sensor.{prefix}_probe_sensor_probe_humidity",
        "probe_vpd": f"sensor.{prefix}_probe_sensor_probe_vpd",
    }


def build_source(env: dict[str, str] | None = None) -> Source:
    env = dict(os.environ) if env is None else env
    kind = env.get("SENSOR_SOURCE", "simulator").lower()
    if kind == "simulator":
        return SimulatorSource()
    if kind == "homeassistant":
        prefix = _prefix(env)
        derived = _derived_entities(prefix)
        temp_entity = _entity(env, "HA_TEMP_ENTITY", derived.get("temp"))
        humidity_entity = _entity(env, "HA_HUMIDITY_ENTITY", derived.get("humidity"))
        if not temp_entity or not humidity_entity:
            raise ValueError(
                "HA_TEMP_ENTITY and HA_HUMIDITY_ENTITY must be set when HA_DEVICE_PREFIX is empty"
            )
        slugs = _port_slugs(env)
        if slugs and not prefix:
            raise ValueError("HA_DEVICE_PREFIX is required when HA_PORT_DEVICES is set")
        port_entities = {slug: port_entity_map(prefix, slug) for slug in slugs} if prefix else {}
        return HomeAssistantSource(
            url=env.get("HA_URL", ""),
            token=env.get("HA_TOKEN", ""),
            temp_entity=temp_entity,
            humidity_entity=humidity_entity,
            co2_entity=_entity(env, "HA_CO2_ENTITY", None),
            vpd_entity=_entity(env, "HA_VPD_ENTITY", derived.get("vpd")),
            status_entity=_entity(env, "HA_STATUS_ENTITY", derived.get("status")),
            probe_temp_entity=_entity(env, "HA_PROBE_TEMP_ENTITY", derived.get("probe_temp")),
            probe_humidity_entity=_entity(
                env, "HA_PROBE_HUMIDITY_ENTITY", derived.get("probe_humidity")
            ),
            probe_vpd_entity=_entity(env, "HA_PROBE_VPD_ENTITY", derived.get("probe_vpd")),
            port_entities=port_entities,
        )
    raise ValueError(f"Unknown SENSOR_SOURCE: {kind!r} (use simulator or homeassistant)")


def leaf_offset_c(env: dict[str, str] | None = None) -> float:
    env = dict(os.environ) if env is None else env
    return float(env.get("LEAF_TEMP_OFFSET_C", "0"))
