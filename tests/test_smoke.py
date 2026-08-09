"""Phase 0 smoke tests — package import and basic scaffolding."""

import pytest

import gokart
from gokart import units


def test_package_import() -> None:
    assert gokart.__version__ == "0.1.0"


def test_speed_unit_roundtrip() -> None:
    speed_mps = 12.5
    assert units.kmh_to_mps(units.mps_to_kmh(speed_mps)) == speed_mps


def test_rpm_unit_roundtrip() -> None:
    rpm = 3000.0
    assert units.rads_to_rpm(units.rpm_to_rads(rpm)) == pytest.approx(rpm)


def test_celsius_to_kelvin() -> None:
    assert units.c_to_k(0.0) == 273.15
    assert units.c_to_k(25.0) == 298.15
