"""Centrifugal clutch engagement model."""

from __future__ import annotations

from dataclasses import dataclass

from gokart.config.schemas.components import Clutch


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


def step_clutch(
    engine_torque_nm: float,
    engine_rpm: float,
    params: ClutchParams,
) -> ClutchOutputs:
    """Transmit engine torque through a centrifugal clutch."""
    fraction = engagement_fraction(engine_rpm, params)
    locked = fraction >= 1.0
    transmitted = max(0.0, engine_torque_nm) * fraction
    transmitted = min(transmitted, params.max_torque_nm)
    return ClutchOutputs(
        engagement_fraction=fraction,
        locked=locked,
        transmitted_torque_nm=transmitted,
    )
