"""Vapor pressure deficit (VPD) math.

VPD is the gap between how much water the air *could* hold at a given
temperature and how much it actually holds. Growers use it to tune
transpiration. We use the Tetens equation for saturation vapor pressure.
"""

import math


def f_to_c(temp_f: float) -> float:
    return (temp_f - 32.0) * 5.0 / 9.0


def c_to_f(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


# Exact conversion factor (1 psi = 6.894757293168361 kPa).
_PSI_TO_KPA = 6.894757293168361
_INHG_TO_KPA = 3.386388640341


def temperature_to_c(value: float, unit: str) -> float:
    """Convert a Home Assistant temperature state to Celsius.

    Fahrenheit units are converted. Everything else (including °C and a missing
    unit) is treated as already Celsius.
    """
    normalized = unit.strip().casefold().replace("°", "").replace("º", "")
    if normalized in {"f", "fahrenheit"}:
        return f_to_c(value)
    return value


def pressure_to_kpa(value: float, unit: str) -> float | None:
    """Convert a pressure reading to kPa.

    AC Infinity VPD sensors often show up in Home Assistant as psi because the
    pressure device class follows the user's unit system. Returns None when the
    unit is missing or unrecognized so the caller can keep the raw number and
    unit instead of guessing.
    """
    normalized = unit.strip().casefold().replace(" ", "").replace("°", "")
    if normalized in {"kpa", "kilopascal", "kilopascals"}:
        return value
    if normalized in {"psi", "psia", "psig"}:
        return value * _PSI_TO_KPA
    if normalized in {"pa", "pascal", "pascals"}:
        return value / 1000.0
    if normalized in {"hpa", "mbar", "mb", "millibar"}:
        return value / 10.0
    if normalized == "bar":
        return value * 100.0
    if normalized in {"inhg", "inhg."}:
        return value * _INHG_TO_KPA
    return None


def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    """Tetens equation: SVP in kPa for a temperature in Celsius."""
    return 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def vpd_kpa(air_temp_c: float, rh_percent: float, leaf_offset_c: float = 0.0) -> float:
    """Leaf VPD in kPa.

    leaf_offset_c: how much cooler (negative) or warmer the leaf is than the
    air. Leaves are often ~1-2 C cooler than air under LEDs, e.g. -2.0.
    With offset 0 this is plain air VPD.
    """
    if not 0.0 <= rh_percent <= 100.0:
        raise ValueError("relative humidity must be between 0 and 100")
    leaf_svp = saturation_vapor_pressure_kpa(air_temp_c + leaf_offset_c)
    actual_vp = saturation_vapor_pressure_kpa(air_temp_c) * rh_percent / 100.0
    return round(max(leaf_svp - actual_vp, 0.0), 3)
