"""Track data models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TrackPoint(BaseModel):
    x: float
    y: float
    z: float = 0.0
    s: float = 0.0
    curvature: float = 0.0
    gradient_rad: float = 0.0


class BoundaryPoint(BaseModel):
    x: float
    y: float


class StartFinish(BaseModel):
    s_m: float = 0.0
    width_m: float | None = None


class TrackBBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float


class Track(BaseModel):
    id: str
    name: str
    source: str
    source_length_m: float = Field(gt=0)
    target_length_m: float = Field(gt=0)
    scale: float = Field(gt=0)
    width_m: float = Field(gt=0)
    direction: Literal["clockwise", "counterclockwise"] = "clockwise"
    start_finish: StartFinish = Field(default_factory=StartFinish)
    bbox: TrackBBox
    centerline: list[TrackPoint]
    inner_boundary: list[BoundaryPoint]
    outer_boundary: list[BoundaryPoint]

    @property
    def length_m(self) -> float:
        if not self.centerline:
            return 0.0
        return self.centerline[-1].s
