"""Data model shared by all sensor sources."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)


@dataclass
class ProbeReading:
    """Internal canopy/probe climate. VPD fields are the device reading."""

    temperature_c: float | None = None
    humidity_percent: float | None = None
    vpd_kpa: float | None = None
    vpd_raw: float | None = None
    vpd_unit: str | None = None

    def is_empty(self) -> bool:
        return (
            self.temperature_c is None
            and self.humidity_percent is None
            and self.vpd_kpa is None
            and self.vpd_raw is None
            and self.vpd_unit is None
        )


@dataclass
class DeviceReading:
    """One UIS port or named device: live state, not trigger settings."""

    status: str | None = None
    state: str | None = None
    current_power: float | None = None
    active_mode: str | None = None

    def is_empty(self) -> bool:
        return (
            self.status is None
            and self.state is None
            and self.current_power is None
            and self.active_mode is None
        )


@dataclass
class Reading:
    temperature_c: float
    humidity_percent: float
    co2_ppm: float | None = None  # AI+ has no CO2 sensor by default; may be None
    source: str = "simulator"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Home Assistant controller VPD, already converted to kPa when the unit is known.
    controller_vpd_kpa: float | None = None
    controller_vpd_raw: float | None = None
    controller_vpd_unit: str | None = None
    controller_status: str | None = None  # "on" / "off" from the controller binary sensor
    probe: ProbeReading | None = None
    ports: dict[str, DeviceReading] = field(default_factory=dict)

    def to_dict(self, leaf_offset_c: float = 0.0) -> dict:
        from sensor_service.vpd import c_to_f, vpd_kpa

        temp_c = round(self.temperature_c, 2)
        temp_f = round(c_to_f(self.temperature_c), 2)
        humidity = round(self.humidity_percent, 1)
        return {
            "temperature_c": temp_c,
            "temperature_f": temp_f,
            "humidity_percent": humidity,
            "co2_ppm": self.co2_ppm,
            "source": self.source,
            "timestamp": self.timestamp,
            # Computed from controller air temp/RH. Honors LEAF_TEMP_OFFSET_C.
            "vpd_kpa": vpd_kpa(self.temperature_c, self.humidity_percent, leaf_offset_c),
            "leaf_offset_c": leaf_offset_c,
            "controller": {
                "temperature_c": temp_c,
                "temperature_f": temp_f,
                "humidity_percent": humidity,
                # Device-reported VPD (HA), converted to kPa. Independent of leaf offset.
                "vpd_kpa": _round(self.controller_vpd_kpa, 3),
                "vpd_raw": _round(self.controller_vpd_raw, 4),
                "vpd_unit": self.controller_vpd_unit,
                "status": self.controller_status,
            },
            "probe": _probe_payload(self.probe),
            "ports": _ports_payload(self.ports),
        }


def _probe_payload(probe: ProbeReading | None) -> dict | None:
    from sensor_service.vpd import c_to_f

    if probe is None or probe.is_empty():
        return None
    temp_c = _round(probe.temperature_c, 2)
    temp_f = None if probe.temperature_c is None else round(c_to_f(probe.temperature_c), 2)
    return {
        "temperature_c": temp_c,
        "temperature_f": temp_f,
        "humidity_percent": _round(probe.humidity_percent, 1),
        "vpd_kpa": _round(probe.vpd_kpa, 3),
        "vpd_raw": _round(probe.vpd_raw, 4),
        "vpd_unit": probe.vpd_unit,
    }


def _ports_payload(ports: dict[str, DeviceReading]) -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for name, device in ports.items():
        if device.is_empty():
            continue
        payload[name] = {
            "status": device.status,
            "state": device.state,
            "current_power": _round(device.current_power, 2),
            "active_mode": device.active_mode,
        }
    return payload
