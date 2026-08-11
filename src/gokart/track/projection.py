"""Geographic projection helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def latlon_to_local_m(
    lat: float,
    lon: float,
    *,
    ref_lat: float,
    ref_lon: float,
) -> tuple[float, float]:
    """Project WGS84 coordinates to local metres (equirectangular at ref)."""
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ref_lat_rad = math.radians(ref_lat)
    ref_lon_rad = math.radians(ref_lon)
    x = (lon_rad - ref_lon_rad) * math.cos(ref_lat_rad) * EARTH_RADIUS_M
    y = (lat_rad - ref_lat_rad) * EARTH_RADIUS_M
    return x, y


def local_m_to_latlon(
    x: float,
    y: float,
    *,
    ref_lat: float,
    ref_lon: float,
) -> tuple[float, float]:
    """Inverse of latlon_to_local_m."""
    ref_lat_rad = math.radians(ref_lat)
    ref_lon_rad = math.radians(ref_lon)
    lat_rad = ref_lat_rad + y / EARTH_RADIUS_M
    lon_rad = ref_lon_rad + x / (math.cos(ref_lat_rad) * EARTH_RADIUS_M)
    return math.degrees(lat_rad), math.degrees(lon_rad)
