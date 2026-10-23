"""Data model shared by all sensor sources."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass
class Reading:
    temperature_c: float
    humidity_percent: float
    co2_ppm: float | None = None  # AI+ has no CO2 sensor by default; may be None
    source: str = "simulator"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self, leaf_offset_c: float = 0.0) -> dict:
        from sensor_service.vpd import c_to_f, vpd_kpa

        data = asdict(self)
        data["temperature_c"] = round(self.temperature_c, 2)
        data["temperature_f"] = round(c_to_f(self.temperature_c), 2)
        data["humidity_percent"] = round(self.humidity_percent, 1)
        data["vpd_kpa"] = vpd_kpa(self.temperature_c, self.humidity_percent, leaf_offset_c)
        data["leaf_offset_c"] = leaf_offset_c
        return data
