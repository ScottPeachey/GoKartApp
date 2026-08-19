"""Longitudinal tyre grip and force saturation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gokart.physics.constants import GRAVITY_MPS2
from gokart.physics.load_transfer import AxleLoads, WheelLoads


@dataclass(frozen=True)
class TyreParams:
    grip_coefficient: float
    wheel_radius_m: float


@dataclass(frozen=True)
class TyreOutputs:
    traction_force_n: float
    traction_force_requested_n: float
    normal_load_n: float
    lateral_force_n: float = 0.0
    longitudinal_grip_limit_n: float = 0.0
    front_normal_n: float = 0.0
    rear_normal_n: float = 0.0
    front_longitudinal_n: float = 0.0
    rear_longitudinal_n: float = 0.0
    front_lateral_n: float = 0.0
    rear_lateral_n: float = 0.0


@dataclass(frozen=True)
class WheelTyreOutputs:
    wheel_loads: WheelLoads
    fl_longitudinal_n: float
    fl_lateral_n: float
    fr_longitudinal_n: float
    fr_lateral_n: float
    rl_longitudinal_n: float
    rl_lateral_n: float
    rr_longitudinal_n: float
    rr_lateral_n: float
    traction_force_n: float
    traction_force_requested_n: float
    normal_load_n: float
    lateral_force_n: float
    longitudinal_grip_limit_n: float
    front_normal_n: float
    rear_normal_n: float
    front_longitudinal_n: float
    rear_longitudinal_n: float
    front_lateral_n: float
    rear_lateral_n: float

    def as_axle_outputs(self) -> TyreOutputs:
        return TyreOutputs(
            traction_force_n=self.traction_force_n,
            traction_force_requested_n=self.traction_force_requested_n,
            normal_load_n=self.normal_load_n,
            lateral_force_n=self.lateral_force_n,
            longitudinal_grip_limit_n=self.longitudinal_grip_limit_n,
            front_normal_n=self.front_normal_n,
            rear_normal_n=self.rear_normal_n,
            front_longitudinal_n=self.front_longitudinal_n,
            rear_longitudinal_n=self.rear_longitudinal_n,
            front_lateral_n=self.front_lateral_n,
            rear_lateral_n=self.rear_lateral_n,
        )


def clip_friction_circle(
    long_requested_n: float,
    lat_requested_n: float,
    max_force_n: float,
) -> tuple[float, float]:
    """Clip longitudinal and lateral requests to a circular friction limit."""
    if max_force_n <= 0.0:
        return 0.0, 0.0
    lat = max(-max_force_n, min(lat_requested_n, max_force_n))
    lat_mag = abs(lat)
    long_available = math.sqrt(max(0.0, max_force_n * max_force_n - lat_mag * lat_mag))
    long_force = max(-long_available, min(long_requested_n, long_available))
    return long_force, lat


def max_traction_force_at_rear(
    axle_loads: AxleLoads,
    rear_grip_coefficient: float,
    *,
    lateral_force_n: float = 0.0,
) -> float:
    """Available rear-axle longitudinal force after lateral demand on the front axle."""
    rear_max = axle_loads.rear_normal_n * rear_grip_coefficient
    long_available, _ = clip_friction_circle(rear_max, 0.0, rear_max)
    return long_available


def saturate_wheel_forces(
    drive_force_requested_n: float,
    brake_force_n: float,
    lateral_force_n: float,
    wheel_loads: WheelLoads,
    front_grip_fl: float,
    front_grip_fr: float,
    rear_grip_rl: float,
    rear_grip_rr: float,
    *,
    front_brake_bias: float = 0.55,
) -> WheelTyreOutputs:
    """Resolve per-wheel friction circles for drive, brake, and steering."""
    front_brake = max(0.0, brake_force_n) * front_brake_bias
    rear_brake = max(0.0, brake_force_n) * (1.0 - front_brake_bias)
    front_lat_each = lateral_force_n * 0.5
    rear_drive_each = drive_force_requested_n * 0.5

    fl_long, fl_lat = clip_friction_circle(
        -front_brake * 0.5,
        front_lat_each,
        wheel_loads.fl_normal_n * front_grip_fl,
    )
    fr_long, fr_lat = clip_friction_circle(
        -front_brake * 0.5,
        front_lat_each,
        wheel_loads.fr_normal_n * front_grip_fr,
    )
    rl_long, rl_lat = clip_friction_circle(
        rear_drive_each - rear_brake * 0.5,
        0.0,
        wheel_loads.rl_normal_n * rear_grip_rl,
    )
    rr_long, rr_lat = clip_friction_circle(
        rear_drive_each - rear_brake * 0.5,
        0.0,
        wheel_loads.rr_normal_n * rear_grip_rr,
    )

    front_long = fl_long + fr_long
    front_lat = fl_lat + fr_lat
    rear_long = rl_long + rr_long
    rear_lat = rl_lat + rr_lat
    rear_max = (
        wheel_loads.rl_normal_n * rear_grip_rl + wheel_loads.rr_normal_n * rear_grip_rr
    )
    total_normal = wheel_loads.front_normal_n + wheel_loads.rear_normal_n

    return WheelTyreOutputs(
        wheel_loads=wheel_loads,
        fl_longitudinal_n=fl_long,
        fl_lateral_n=fl_lat,
        fr_longitudinal_n=fr_long,
        fr_lateral_n=fr_lat,
        rl_longitudinal_n=rl_long,
        rl_lateral_n=rl_lat,
        rr_longitudinal_n=rr_long,
        rr_lateral_n=rr_lat,
        traction_force_n=rear_long,
        traction_force_requested_n=drive_force_requested_n,
        normal_load_n=total_normal,
        lateral_force_n=lateral_force_n,
        longitudinal_grip_limit_n=rear_max,
        front_normal_n=wheel_loads.front_normal_n,
        rear_normal_n=wheel_loads.rear_normal_n,
        front_longitudinal_n=front_long,
        rear_longitudinal_n=rear_long,
        front_lateral_n=front_lat,
        rear_lateral_n=rear_lat,
    )


def saturate_axle_forces(
    drive_force_requested_n: float,
    brake_force_n: float,
    lateral_force_n: float,
    axle_loads: AxleLoads,
    front_grip_coefficient: float,
    rear_grip_coefficient: float,
    *,
    front_brake_bias: float = 0.55,
) -> TyreOutputs:
    """Resolve per-axle friction circles for rear drive/brake and front steer/brake."""
    front_brake = max(0.0, brake_force_n) * front_brake_bias
    rear_brake = max(0.0, brake_force_n) * (1.0 - front_brake_bias)

    front_max = axle_loads.front_normal_n * front_grip_coefficient
    rear_max = axle_loads.rear_normal_n * rear_grip_coefficient

    front_long, front_lat = clip_friction_circle(-front_brake, lateral_force_n, front_max)
    rear_long, rear_lat = clip_friction_circle(
        drive_force_requested_n - rear_brake,
        0.0,
        rear_max,
    )

    total_normal = axle_loads.front_normal_n + axle_loads.rear_normal_n
    return TyreOutputs(
        traction_force_n=rear_long,
        traction_force_requested_n=drive_force_requested_n,
        normal_load_n=total_normal,
        lateral_force_n=lateral_force_n,
        longitudinal_grip_limit_n=rear_max,
        front_normal_n=axle_loads.front_normal_n,
        rear_normal_n=axle_loads.rear_normal_n,
        front_longitudinal_n=front_long,
        rear_longitudinal_n=rear_long,
        front_lateral_n=front_lat,
        rear_lateral_n=rear_lat,
    )


def normal_load_n(mass_kg: float, gradient_rad: float = 0.0) -> float:
    return mass_kg * GRAVITY_MPS2 * math.cos(gradient_rad)


def max_traction_force_n(
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> float:
    return normal_load_n(mass_kg, gradient_rad) * grip_coefficient


def saturate_traction_force(
    requested_force_n: float,
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> TyreOutputs:
    """Clip requested longitudinal force to tyre friction limit."""
    limit = max_traction_force_n(mass_kg, grip_coefficient, gradient_rad)
    traction = max(-limit, min(requested_force_n, limit))
    return TyreOutputs(
        traction_force_n=traction,
        traction_force_requested_n=requested_force_n,
        normal_load_n=normal_load_n(mass_kg, gradient_rad),
        longitudinal_grip_limit_n=limit,
    )


def lateral_accel_from_bicycle_mps2(
    speed_mps: float,
    steer_rad: float,
    wheelbase_m: float,
) -> float:
    if wheelbase_m <= 0.0 or abs(steer_rad) < 1e-6:
        return 0.0
    return speed_mps * speed_mps * math.tan(steer_rad) / wheelbase_m


def lateral_force_from_steering_n(
    speed_mps: float,
    steer_rad: float,
    wheelbase_m: float,
    mass_kg: float,
) -> float:
    """Lateral force demand from bicycle-model cornering at the given speed."""
    return mass_kg * lateral_accel_from_bicycle_mps2(speed_mps, steer_rad, wheelbase_m)


def max_lateral_accel_mps2(
    grip_coefficient: float,
    gradient_rad: float = 0.0,
    *,
    normal_load_n: float | None = None,
    mass_kg: float | None = None,
) -> float:
    if normal_load_n is not None and mass_kg is not None and mass_kg > 0.0:
        return normal_load_n * grip_coefficient / mass_kg
    return grip_coefficient * GRAVITY_MPS2 * math.cos(gradient_rad)


# Bicycle-model tan(steer) is only defined below 90°. Off-line driver
# corrections can request more than that; clamp before taking sqrt.
_MAX_BICYCLE_STEER_RAD = math.radians(80.0)


def cornering_speed_limit_mps(
    steer_rad: float,
    wheelbase_m: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> float | None:
    """Maximum speed before lateral grip is exceeded for a given steer angle."""
    if wheelbase_m <= 0.0:
        return None
    steer_mag = min(abs(steer_rad), _MAX_BICYCLE_STEER_RAD)
    if steer_mag < 1e-6:
        return None
    max_lat = max_lateral_accel_mps2(grip_coefficient, gradient_rad)
    if max_lat <= 0.0:
        return 0.0
    denom = math.tan(steer_mag)
    if denom <= 1e-9:
        return None
    return math.sqrt(max(0.0, max_lat * wheelbase_m / denom))


def apply_cornering_speed_bleed(
    speed_mps: float,
    steer_rad: float,
    wheelbase_m: float,
    grip_coefficient: float,
    gradient_rad: float,
    dt: float,
    *,
    mass_kg: float | None = None,
    front_normal_n: float | None = None,
) -> float:
    """Reduce scalar speed when cornering demand exceeds available lateral grip."""
    lat_accel = abs(lateral_accel_from_bicycle_mps2(speed_mps, steer_rad, wheelbase_m))
    if lat_accel <= 1e-6:
        return speed_mps

    max_lat = max_lateral_accel_mps2(
        grip_coefficient,
        gradient_rad,
        normal_load_n=front_normal_n,
        mass_kg=mass_kg,
    )
    demand_ratio = lat_accel / max(max_lat, 1e-6)
    speed_cap = cornering_speed_limit_mps(steer_rad, wheelbase_m, grip_coefficient, gradient_rad)
    incoming = speed_mps
    new_speed = min(speed_mps, speed_cap) if speed_cap is not None else speed_mps

    if demand_ratio > 1.0:
        bleed = min(1.0, (demand_ratio - 1.0) * 8.0 * dt)
        new_speed *= 1.0 - bleed
        if speed_cap is not None:
            new_speed = min(new_speed, speed_cap)
    elif demand_ratio > 0.88:
        # Only bleed speed when cornering load is near the friction limit.
        scrub_fraction = (demand_ratio - 0.88) / 0.12
        scrub_accel = (scrub_fraction * scrub_fraction) * max_lat * 0.35
        new_speed = max(0.0, new_speed - scrub_accel * dt)

    # Cornering bleed must never add speed (a bad max() floor caused runaway on gentle steer).
    return min(max(0.0, new_speed), incoming)


def cornering_scrub_force_n(
    lateral_force_n: float,
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
    *,
    scrub_gain: float = 0.4,
) -> float:
    """Longitudinal drag from cornering load — makes steering bleed speed even when coasting."""
    normal = normal_load_n(mass_kg, gradient_rad)
    max_total = normal * grip_coefficient
    if max_total <= 0.0:
        return 0.0
    lat_ratio = min(abs(lateral_force_n) / max_total, 1.5)
    return scrub_gain * lat_ratio * lat_ratio * normal


def saturate_traction_friction_circle(
    requested_force_n: float,
    lateral_force_n: float,
    mass_kg: float,
    grip_coefficient: float,
    gradient_rad: float = 0.0,
) -> TyreOutputs:
    """Limit longitudinal force using a 2-D friction circle with lateral demand."""
    normal = normal_load_n(mass_kg, gradient_rad)
    max_total = normal * grip_coefficient
    lat = min(abs(lateral_force_n), max_total)
    long_available = math.sqrt(max(0.0, max_total * max_total - lat * lat))
    traction = max(-long_available, min(requested_force_n, long_available))
    return TyreOutputs(
        traction_force_n=traction,
        traction_force_requested_n=requested_force_n,
        normal_load_n=normal,
        lateral_force_n=lateral_force_n,
        longitudinal_grip_limit_n=long_available,
    )
