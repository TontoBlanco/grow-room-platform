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
