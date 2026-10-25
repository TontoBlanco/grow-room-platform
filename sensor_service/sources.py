"""Sensor sources: where readings come from.

- SimulatorSource: fake but realistic tent data (default; used in CI/demos).
- HomeAssistantSource: READ-ONLY pull of AC Infinity entities from Home
  Assistant's REST API (dalinicus/homeassistant-acinfinity integration).
  It only ever issues GET /api/states/<entity_id>; it never calls services
  or changes tent settings.
"""

import math
import random
import time
from typing import Protocol

import httpx

from sensor_service.models import DeviceReading, ProbeReading, Reading
from sensor_service.vpd import pressure_to_kpa, temperature_to_c

_MISSING_STATES = {"unavailable", "unknown", "none", ""}


class Source(Protocol):
    def read(self) -> Reading: ...


class SimulatorSource:
    """Smooth day/night-ish cycle plus a little noise, clamped to sane ranges."""

    TEMP_RANGE_C = (18.0, 32.0)
    RH_RANGE = (35.0, 75.0)
    CO2_RANGE = (400.0, 1500.0)

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)  # noqa: S311 - not crypto

    def read(self) -> Reading:
        phase = math.sin(time.time() / 3600.0)  # slow wave
        temp = 25.0 + 3.0 * phase + self._rng.uniform(-0.5, 0.5)
        rh = 55.0 - 8.0 * phase + self._rng.uniform(-2.0, 2.0)
        co2 = 800.0 + 200.0 * phase + self._rng.uniform(-50.0, 50.0)
        return Reading(
            temperature_c=_clamp(temp, *self.TEMP_RANGE_C),
            humidity_percent=_clamp(rh, *self.RH_RANGE),
            co2_ppm=round(_clamp(co2, *self.CO2_RANGE)),
            source="simulator",
        )


def port_entity_map(prefix: str, slug: str) -> dict[str, str]:
    """Entity IDs for one UIS device: status, state, current power, active mode."""
    return {
        "status": f"binary_sensor.{prefix}_{slug}_status",
        "state": f"binary_sensor.{prefix}_{slug}_state",
        "current_power": f"sensor.{prefix}_{slug}_current_power",
        "active_mode": f"select.{prefix}_{slug}_active_mode",
    }


class HomeAssistantSource:
    """Reads sensor entity states via GET /api/states/<entity_id>.

    Controller air temperature and humidity are required. Controller VPD,
    controller status, the internal probe, CO2, and port state are optional:
    a missing or unavailable optional entity is omitted instead of failing
    the reading.

    Entity IDs depend on the controller name in the AC Infinity app. The
    Garden defaults live in ``sensor_service.config``.
    """

    def __init__(
        self,
        url: str,
        token: str,
        temp_entity: str,
        humidity_entity: str,
        co2_entity: str | None = None,
        vpd_entity: str | None = None,
        status_entity: str | None = None,
        probe_temp_entity: str | None = None,
        probe_humidity_entity: str | None = None,
        probe_vpd_entity: str | None = None,
        port_entities: dict[str, dict[str, str]] | None = None,
        client: httpx.Client | None = None,
    ):
        url = url.strip()
        token = token.strip()
        if not url or not token:
            raise ValueError("HA_URL and HA_TOKEN must be set for the homeassistant source")
        self.temp_entity = temp_entity
        self.humidity_entity = humidity_entity
        self.co2_entity = co2_entity
        self.vpd_entity = vpd_entity
        self.status_entity = status_entity
        self.probe_temp_entity = probe_temp_entity
        self.probe_humidity_entity = probe_humidity_entity
        self.probe_vpd_entity = probe_vpd_entity
        self.port_entities = port_entities or {}
        self._client = client or httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )

    def _body(self, entity_id: str, *, required: bool) -> dict | None:
        resp = self._client.get(f"/api/states/{entity_id}")
        if resp.status_code == 404:
            if required:
                raise ValueError(f"{entity_id} not found")
            return None
        if not required and resp.status_code >= 400:
            return None
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            if required:
                raise ValueError(f"{entity_id} returned an unexpected payload")
            return None
        return body

    def _numeric(self, entity_id: str, *, required: bool) -> tuple[float, str] | None:
        body = self._body(entity_id, required=required)
        if body is None:
            return None
        raw = body.get("state")
        text = "" if raw is None else str(raw).strip()
        attributes = body.get("attributes") or {}
        unit = ""
        if isinstance(attributes, dict):
            unit = str(attributes.get("unit_of_measurement") or "")
        if text.casefold() in _MISSING_STATES:
            if required:
                raise ValueError(f"{entity_id} has no numeric state: {raw}")
            return None
        try:
            return float(text), unit
        except ValueError as exc:
            if required:
                raise ValueError(f"{entity_id} has no numeric state: {raw}") from exc
            return None

    def _require_numeric(self, entity_id: str) -> tuple[float, str]:
        parsed = self._numeric(entity_id, required=True)
        if parsed is None:
            raise ValueError(f"{entity_id} has no numeric state")
        return parsed

    def _on_off(self, entity_id: str) -> str | None:
        body = self._body(entity_id, required=False)
        if body is None:
            return None
        text = str(body.get("state", "")).strip().casefold()
        if text in {"on", "off"}:
            return text
        return None

    def _choice(self, entity_id: str) -> str | None:
        body = self._body(entity_id, required=False)
        if body is None:
            return None
        raw = body.get("state")
        if raw is None:
            return None
        text = str(raw).strip()
        if text.casefold() in _MISSING_STATES:
            return None
        return text

    def _pressure(self, entity_id: str | None) -> tuple[float | None, str | None, float | None]:
        """Return (raw_value, unit, kpa) for an optional pressure entity."""
        if not entity_id:
            return None, None, None
        parsed = self._numeric(entity_id, required=False)
        if parsed is None:
            return None, None, None
        raw, unit = parsed
        unit_out = unit.strip() or None
        kpa = None if unit_out is None else pressure_to_kpa(raw, unit_out)
        return raw, unit_out, kpa

    def _read_probe(self) -> ProbeReading | None:
        if not any((self.probe_temp_entity, self.probe_humidity_entity, self.probe_vpd_entity)):
            return None
        temp_c = None
        if self.probe_temp_entity:
            parsed = self._numeric(self.probe_temp_entity, required=False)
            if parsed is not None:
                value, unit = parsed
                temp_c = temperature_to_c(value, unit)
        humidity = None
        if self.probe_humidity_entity:
            parsed = self._numeric(self.probe_humidity_entity, required=False)
            if parsed is not None:
                humidity = parsed[0]
        raw, unit, kpa = self._pressure(self.probe_vpd_entity)
        probe = ProbeReading(
            temperature_c=temp_c,
            humidity_percent=humidity,
            vpd_kpa=kpa,
            vpd_raw=raw,
            vpd_unit=unit,
        )
        if probe.is_empty():
            return None
        return probe

    def _read_ports(self) -> dict[str, DeviceReading]:
        found: dict[str, DeviceReading] = {}
        for slug, entities in self.port_entities.items():
            power = self._numeric(entities["current_power"], required=False)
            device = DeviceReading(
                status=self._on_off(entities["status"]),
                state=self._on_off(entities["state"]),
                current_power=None if power is None else power[0],
                active_mode=self._choice(entities["active_mode"]),
            )
            if not device.is_empty():
                found[slug] = device
        return found

    def read(self) -> Reading:
        temp, temp_unit = self._require_numeric(self.temp_entity)
        humidity, _humidity_unit = self._require_numeric(self.humidity_entity)
        co2 = None
        if self.co2_entity:
            parsed = self._numeric(self.co2_entity, required=False)
            if parsed is not None:
                co2 = parsed[0]
        vpd_raw, vpd_unit, vpd_kpa = self._pressure(self.vpd_entity)
        status = self._on_off(self.status_entity) if self.status_entity else None
        return Reading(
            temperature_c=temperature_to_c(temp, temp_unit),
            humidity_percent=humidity,
            co2_ppm=co2,
            source="homeassistant",
            controller_vpd_kpa=vpd_kpa,
            controller_vpd_raw=vpd_raw,
            controller_vpd_unit=vpd_unit,
            controller_status=status,
            probe=self._read_probe(),
            ports=self._read_ports(),
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
