"""Display and boundary unit conversions.

Internal calculations use SI units everywhere (m, m/s, rad/s, °C, etc.).
These helpers are for presentation layers (dashboard, reports) and hardware
boundaries (e.g. VESC RPM fields) only — never use them inside physics,
control, or safety logic.
"""

import math

_KMH_PER_MPS = 3.6
_RPM_PER_RAD_S = 60.0 / (2.0 * math.pi)
_RAD_S_PER_RPM = (2.0 * math.pi) / 60.0


def mps_to_kmh(speed_mps: float) -> float:
    """Convert metres per second to kilometres per hour."""
    return speed_mps * _KMH_PER_MPS


def kmh_to_mps(speed_kmh: float) -> float:
    """Convert kilometres per hour to metres per second."""
    return speed_kmh / _KMH_PER_MPS


def rpm_to_rads(rpm: float) -> float:
    """Convert revolutions per minute to radians per second."""
    return rpm * _RAD_S_PER_RPM


def rads_to_rpm(rad_s: float) -> float:
    """Convert radians per second to revolutions per minute."""
    return rad_s * _RPM_PER_RAD_S


def c_to_k(temp_c: float) -> float:
    """Convert degrees Celsius to kelvin."""
    return temp_c + 273.15
