"""Centrifugal clutch engagement and slip model."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import Clutch

# Engine and axle are rigidly coupled only when shoes are fully out AND slip is small.
SLIP_LOCK_RPM = 120.0

# Slip torque rises with rpm delta — shoes bite harder as slip grows, capped by capacity.
SLIP_TORQUE_NM_PER_RPM = 0.012


@dataclass(frozen=True)
class ClutchParams:
    engagement_rpm: float
    lock_rpm: float
    max_torque_nm: float

    @classmethod
    def from_component(cls, clutch: Clutch) -> ClutchParams:
        return cls(
            engagement_rpm=clutch.engagement_rpm,
            lock_rpm=clutch.lock_rpm,
            max_torque_nm=clutch.max_torque_nm,
        )


@dataclass(frozen=True)
class ClutchOutputs:
    engagement_fraction: float
    locked: bool
    transmitted_torque_nm: float
    slip_rpm: float = 0.0


def engagement_fraction(engine_rpm: float, params: ClutchParams) -> float:
    """Return 0 below engagement, 1 at/above lock, linear between."""
    if engine_rpm <= params.engagement_rpm:
        return 0.0
    if engine_rpm >= params.lock_rpm:
        return 1.0
    span = params.lock_rpm - params.engagement_rpm
    if span <= 0:
        return 1.0
    return (engine_rpm - params.engagement_rpm) / span


def slip_rpm(engine_rpm: float, coupled_rpm: float) -> float:
    """Positive slip when the engine leads the axle."""
    return max(0.0, engine_rpm - coupled_rpm)


def is_axle_locked(
    engine_rpm: float,
    coupled_rpm: float,
    params: ClutchParams,
    *,
    slip_lock_rpm: float = SLIP_LOCK_RPM,
) -> bool:
    """True when clutch shoes are out and engine speed matches the axle."""
    return engagement_fraction(engine_rpm, params) >= 1.0 and slip_rpm(
        engine_rpm,
        coupled_rpm,
    ) < slip_lock_rpm


def transmitted_drive_torque_nm(
    engine_torque_nm: float,
    engine_rpm: float,
    coupled_rpm: float,
    params: ClutchParams,
) -> float:
    """Torque passed to the axle while the clutch slips or is locked."""
    engage_frac = engagement_fraction(engine_rpm, params)
    if engage_frac <= 0.0 or engine_torque_nm <= 0.0:
        return 0.0

    capacity = params.max_torque_nm * engage_frac
    slip = slip_rpm(engine_rpm, coupled_rpm)
    if is_axle_locked(engine_rpm, coupled_rpm, params):
        return min(engine_torque_nm, capacity)

    # Shoes fully out — friction capacity is the limit, not slip speed.
    if engage_frac >= 1.0:
        return min(engine_torque_nm, capacity)

    slip_torque = min(capacity, slip * SLIP_TORQUE_NM_PER_RPM * engage_frac)
    return min(engine_torque_nm, max(slip_torque, capacity * 0.08))


def step_clutch(
    engine_torque_nm: float,
    engine_rpm: float,
    params: ClutchParams,
    *,
    coupled_rpm: float = 0.0,
) -> ClutchOutputs:
    """Compute clutch torque and lock state for one physics tick."""
    engage_frac = engagement_fraction(engine_rpm, params)
    slip = slip_rpm(engine_rpm, coupled_rpm)
    locked = is_axle_locked(engine_rpm, coupled_rpm, params)
    transmitted = transmitted_drive_torque_nm(
        engine_torque_nm,
        engine_rpm,
        coupled_rpm,
        params,
    )
    return ClutchOutputs(
        engagement_fraction=engage_frac,
        locked=locked,
        transmitted_torque_nm=transmitted,
        slip_rpm=slip,
    )
