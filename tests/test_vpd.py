import pytest

from sensor_service.vpd import c_to_f, f_to_c, saturation_vapor_pressure_kpa, vpd_kpa


def test_svp_known_values():
    assert saturation_vapor_pressure_kpa(25.0) == pytest.approx(3.17, abs=0.01)
    assert saturation_vapor_pressure_kpa(20.0) == pytest.approx(2.34, abs=0.01)


def test_air_vpd():
    # 25 C at 60% RH -> about 1.27 kPa
    assert vpd_kpa(25.0, 60.0) == pytest.approx(1.268, abs=0.01)


def test_leaf_offset_lowers_vpd():
    assert vpd_kpa(25.0, 60.0, leaf_offset_c=-2.0) < vpd_kpa(25.0, 60.0)


def test_saturated_air_is_zero():
    assert vpd_kpa(25.0, 100.0) == 0.0


def test_rh_out_of_range():
    with pytest.raises(ValueError):
        vpd_kpa(25.0, 120.0)


def test_unit_conversion_roundtrip():
    assert f_to_c(77.0) == pytest.approx(25.0)
    assert c_to_f(f_to_c(80.5)) == pytest.approx(80.5)
