"""Elevation fetching for track import."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from gokart.track.geometry import XYPoint

OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
BATCH_SIZE = 100


def fetch_elevations_m(latitudes: list[float], longitudes: list[float]) -> list[float] | None:
    """Fetch per-point elevations from Open-Meteo. Returns None if unavailable."""
    if len(latitudes) != len(longitudes):
        raise ValueError("latitudes and longitudes must have the same length")
    if not latitudes:
        return []

    elevations: list[float] = []
    for start in range(0, len(latitudes), BATCH_SIZE):
        batch_lats = latitudes[start : start + BATCH_SIZE]
        batch_lons = longitudes[start : start + BATCH_SIZE]
        params = urllib.parse.urlencode(
            {
                "latitude": ",".join(f"{lat:.6f}" for lat in batch_lats),
                "longitude": ",".join(f"{lon:.6f}" for lon in batch_lons),
            }
        )
        url = f"{OPEN_METEO_ELEVATION_URL}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None
        batch_elevations = payload.get("elevation")
        if not isinstance(batch_elevations, list) or len(batch_elevations) != len(batch_lats):
            return None
        elevations.extend(float(value) for value in batch_elevations)
    return elevations


def apply_elevations(
    points: list[XYPoint],
    elevations_m: list[float],
    *,
    scale: float,
) -> list[XYPoint]:
    """Attach scaled elevations relative to the first point."""
    if len(points) != len(elevations_m):
        raise ValueError("points and elevations_m must have the same length")
    if not points:
        return []
    base = elevations_m[0]
    return [
        XYPoint(
            point.x,
            point.y,
            (elevation - base) * scale,
        )
        for point, elevation in zip(points, elevations_m, strict=True)
    ]


def flat_elevations(points: list[XYPoint]) -> list[XYPoint]:
    return [XYPoint(point.x, point.y, 0.0) for point in points]
