"""Growth-stage leaf-VPD targets.

One tent-wide stage, chosen with ``GROW_STAGE`` (default ``veg``). The active
stage picks an inclusive leaf-VPD band in kPa. The bands are a cannabis-tent
rule of thumb, not a cultivar prescription:

- seedling / clone: 0.4–0.8
- veg: 0.8–1.2
- flower: 1.2–1.5
- late flower: 1.4–1.6

Those ranges are the ones commonly printed on cannabis VPD charts. Pulse
Grow's chart puts propagation around 0.4–0.8 kPa and vegetative growth around
0.8–1.2 kPa. Flower charts usually step up to about 1.2–1.5 kPa, and late
flower is often held near 1.4–1.6 kPa to ease botrytis pressure. A reading on
a shared edge counts as in band for whichever single stage is selected.

Override a stage's defaults with ``VPD_BAND_<STAGE>=low,high``
(``VPD_BAND_SEEDLING``, ``VPD_BAND_VEG``, ``VPD_BAND_FLOWER``,
``VPD_BAND_LATE_FLOWER``). ``VPD_TARGET_LOW_KPA`` and
``VPD_TARGET_HIGH_KPA`` replace the active band's edges after that, including
when only one side is set.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

BAND_SOURCE = (
    "Leaf-VPD rule of thumb for cannabis in a tent: seedling/clone 0.4-0.8, "
    "veg 0.8-1.2, flower 1.2-1.5, late flower 1.4-1.6 kPa. "
    "Compiled from widely used cannabis VPD charts (Pulse Grow's propagation "
    "and vegetative bands, and the drier flower / late-flower steps used to "
    "limit botrytis). Inclusive edges. Not a cultivar prescription."
)

DEFAULT_STAGE = "veg"

# Inclusive leaf VPD, kPa.
_DEFAULT_BANDS: dict[str, tuple[float, float]] = {
    "seedling": (0.4, 0.8),
    "veg": (0.8, 1.2),
    "flower": (1.2, 1.5),
    "late_flower": (1.4, 1.6),
}

_DISPLAY = {
    "seedling": "seedling/clone",
    "veg": "veg",
    "flower": "flower",
    "late_flower": "late flower",
}

_ALIASES = {
    "clone": "seedling",
    "clones": "seedling",
    "seedling_clone": "seedling",
    "vegetative": "veg",
    "vegetation": "veg",
    "flowering": "flower",
    "lateflower": "late_flower",
}

_BAND_ENV = {
    "seedling": "VPD_BAND_SEEDLING",
    "veg": "VPD_BAND_VEG",
    "flower": "VPD_BAND_FLOWER",
    "late_flower": "VPD_BAND_LATE_FLOWER",
}

_TARGET_LOW = "VPD_TARGET_LOW_KPA"
_TARGET_HIGH = "VPD_TARGET_HIGH_KPA"
_MAX_KPA = 10.0


@dataclass(frozen=True)
class GrowthStage:
    """Active stage and the inclusive leaf-VPD band it selected."""

    name: str
    low_kpa: float
    high_kpa: float

    @property
    def display(self) -> str:
        return _DISPLAY[self.name]

    def contains(self, vpd_kpa: float) -> bool:
        return self.low_kpa <= vpd_kpa <= self.high_kpa

    def to_api(self) -> dict:
        return {
            "growth_stage": self.name,
            "display": self.display,
            "vpd_target_low_kpa": self.low_kpa,
            "vpd_target_high_kpa": self.high_kpa,
            "note": BAND_SOURCE,
        }


def load_growth_stage(env: dict[str, str] | None = None) -> GrowthStage:
    """Resolve ``GROW_STAGE`` and the band overrides from an env mapping.

    ``None`` reads the process environment. A mapping (including an empty one)
    is used as-is, so tests do not pick up the developer environment.
    """
    env = dict(os.environ) if env is None else env
    name = _stage_name(env)
    low, high = _DEFAULT_BANDS[name]
    for stage_name, key in _BAND_ENV.items():
        if key not in env or not env[key].strip():
            continue
        parsed = _parse_pair(env[key], key)
        _validate_band(*parsed, key)
        if stage_name == name:
            low, high = parsed
    low, high = _apply_active_override(low, high, env)
    _validate_band(low, high, "VPD target")
    return GrowthStage(name=name, low_kpa=low, high_kpa=high)


def _stage_name(env: dict[str, str]) -> str:
    if "GROW_STAGE" not in env:
        return DEFAULT_STAGE
    raw = env["GROW_STAGE"].strip()
    if not raw:
        raise ValueError("GROW_STAGE is blank; set seedling, veg, flower, or late_flower")
    key = _normalize(raw)
    canonical = key if key in _DEFAULT_BANDS else _ALIASES.get(key)
    if canonical is None:
        raise ValueError(
            f"invalid GROW_STAGE: {raw!r} "
            "(use seedling, veg, flower, or late_flower; clone is an alias for seedling)"
        )
    return canonical


def _normalize(raw: str) -> str:
    text = raw.casefold().replace("-", "_").replace("/", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _apply_active_override(low: float, high: float, env: dict[str, str]) -> tuple[float, float]:
    overridden_low = _optional_float(env, _TARGET_LOW)
    overridden_high = _optional_float(env, _TARGET_HIGH)
    if overridden_low is not None:
        low = overridden_low
    if overridden_high is not None:
        high = overridden_high
    return low, high


def _parse_pair(raw: str, key: str) -> tuple[float, float]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid {key}: {raw!r} (use low,high in kPa)")
    try:
        low = float(parts[0])
        high = float(parts[1])
    except ValueError as exc:
        raise ValueError(f"invalid {key}: {raw!r} (use low,high in kPa)") from exc
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError(f"invalid {key}: {raw!r} (use low,high in kPa)")
    return low, high


def _optional_float(env: dict[str, str], key: str) -> float | None:
    if key not in env:
        return None
    raw = env[key].strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"invalid {key}: {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"invalid {key}: {raw!r}")
    return value


def _validate_band(low: float, high: float, label: str) -> None:
    if not (0.0 <= low < high <= _MAX_KPA):
        raise ValueError(
            f"{label} band must satisfy 0 <= low < high <= {_MAX_KPA:g} kPa, got {low}..{high}"
        )
