"""Sensor sources: where readings come from.

- SimulatorSource: fake but realistic tent data (default; used in CI/demos).
- HomeAssistantSource: READ-ONLY pull of AC Infinity entities from Home
  Assistant's REST API (dalinicus/homeassistant-acinfinity integration).
  It only ever issues GET requests; it never sends control commands.
"""

import math
import random
import time
from typing import Protocol

import httpx

from sensor_service.models import Reading
from sensor_service.vpd import f_to_c


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


class HomeAssistantSource:
    """Reads sensor entity states via GET /api/states/<entity_id>.

    Entity IDs depend on what you named the controller in the AC Infinity
    app; find yours in HA under Settings -> Devices & services.
    """

    def __init__(
        self,
        url: str,
        token: str,
        temp_entity: str,
        humidity_entity: str,
        co2_entity: str | None = None,
        client: httpx.Client | None = None,
    ):
        if not url or not token:
            raise ValueError("HA_URL and HA_TOKEN must be set for the homeassistant source")
        self.temp_entity = temp_entity
        self.humidity_entity = humidity_entity
        self.co2_entity = co2_entity
        self._client = client or httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )

    def _state(self, entity_id: str) -> tuple[float, str]:
        resp = self._client.get(f"/api/states/{entity_id}")
        resp.raise_for_status()
        body = resp.json()
        unit = body.get("attributes", {}).get("unit_of_measurement", "")
        try:
            return float(body["state"]), unit
        except (KeyError, ValueError) as exc:  # "unavailable", "unknown", etc.
            raise ValueError(f"{entity_id} has no numeric state: {body.get('state')}") from exc

    def read(self) -> Reading:
        temp, unit = self._state(self.temp_entity)
        temp_c = f_to_c(temp) if "F" in unit else temp
        rh, _ = self._state(self.humidity_entity)
        co2 = self._state(self.co2_entity)[0] if self.co2_entity else None
        return Reading(
            temperature_c=temp_c, humidity_percent=rh, co2_ppm=co2, source="homeassistant"
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
