"""Aerodynamic drag model."""

import math

from gokart.physics.constants import AIR_DENSITY_KG_M3, GRAVITY_MPS2


def aero_drag_force_n(
    speed_mps: float,
    drag_coefficient: float,
    frontal_area_m2: float,
    air_density_kg_m3: float = AIR_DENSITY_KG_M3,
) -> float:
    """Longitudinal aerodynamic drag force (opposes motion)."""
    return 0.5 * drag_coefficient * frontal_area_m2 * air_density_kg_m3 * speed_mps * abs(speed_mps)


def rolling_resistance_force_n(
    mass_kg: float,
    rolling_resistance_coefficient: float,
    gradient_rad: float = 0.0,
    gravity_mps2: float = GRAVITY_MPS2,
) -> float:
    """Rolling resistance force (opposes motion)."""
    return rolling_resistance_coefficient * mass_kg * gravity_mps2 * abs(math.cos(gradient_rad))


def gradient_force_n(
    mass_kg: float,
    gradient_rad: float,
    gravity_mps2: float = GRAVITY_MPS2,
) -> float:
    """Force component from road gradient (positive = uphill resists forward motion)."""
    return mass_kg * gravity_mps2 * math.sin(gradient_rad)
