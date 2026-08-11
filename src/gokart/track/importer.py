"""GeoJSON track import."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from gokart.track.elevation import apply_elevations, fetch_elevations_m, flat_elevations
from gokart.track.geometry import (
    DEFAULT_RESAMPLE_SPACING_M,
    XYPoint,
    build_track_points,
    close_polyline,
    compute_bbox,
    compute_target_length_m,
    offset_boundaries,
    polyline_length,
    resample_polyline,
    scale_polyline,
)
from gokart.track.model import StartFinish, Track
from gokart.track.projection import latlon_to_local_m, local_m_to_latlon


class TrackImportError(Exception):
    """Raised when a GeoJSON track cannot be imported."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "track"


def _extract_linestring_coordinates(
    geojson: dict[str, Any],
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features") or []
        if not features:
            raise TrackImportError("GeoJSON FeatureCollection has no features")
        feature = features[0]
    elif geojson.get("type") == "Feature":
        feature = geojson
    else:
        raise TrackImportError("GeoJSON must be a Feature or FeatureCollection")

    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "LineString":
        raise TrackImportError(f"Unsupported geometry type: {geometry.get('type')}")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise TrackImportError("LineString must have at least two coordinates")

    props = feature.get("properties") or {}
    latlon_coords: list[tuple[float, float]] = []
    for coord in coordinates:
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            raise TrackImportError("Each coordinate must be [lon, lat]")
        lon, lat = float(coord[0]), float(coord[1])
        latlon_coords.append((lat, lon))
    return latlon_coords, props


def _project_latlon_points(
    latlon_coords: list[tuple[float, float]],
) -> tuple[list[XYPoint], float, float]:
    lats = [lat for lat, _ in latlon_coords]
    lons = [lon for _, lon in latlon_coords]
    ref_lat = sum(lats) / len(lats)
    ref_lon = sum(lons) / len(lons)
    points = [
        XYPoint(*latlon_to_local_m(lat, lon, ref_lat=ref_lat, ref_lon=ref_lon))
        for lat, lon in latlon_coords
    ]
    return points, ref_lat, ref_lon


def _source_length_m(properties: dict[str, Any], points: list[XYPoint]) -> float:
    length = properties.get("length")
    if isinstance(length, (int, float)) and length > 0:
        return float(length)
    return polyline_length(points)


def import_geojson_track(
    geojson_path: Path,
    *,
    track_id: str | None = None,
    target_length_m: float | None = None,
    width_m: float = 10.0,
    direction: Literal["clockwise", "counterclockwise"] = "clockwise",
    resample_spacing_m: float = DEFAULT_RESAMPLE_SPACING_M,
    fetch_elevation: bool = True,
) -> Track:
    """Import an F1-style GeoJSON circuit into a kart-scale track model."""
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    latlon_coords, properties = _extract_linestring_coordinates(data)
    raw_points, ref_lat, ref_lon = _project_latlon_points(latlon_coords)
    raw_length_m = polyline_length(raw_points)
    source_length_m = _source_length_m(properties, raw_points)

    if target_length_m is None:
        target_length_m = compute_target_length_m(source_length_m)
    if target_length_m <= 0:
        raise TrackImportError("target_length_m must be positive")

    scale = target_length_m / raw_length_m
    scaled_points = scale_polyline(raw_points, scale)
    closed_points = close_polyline(scaled_points)
    resampled = resample_polyline(closed_points, resample_spacing_m)

    if fetch_elevation:
        lats: list[float] = []
        lons: list[float] = []
        for point in resampled:
            lat, lon = local_m_to_latlon(point.x, point.y, ref_lat=ref_lat, ref_lon=ref_lon)
            lats.append(lat)
            lons.append(lon)
        elevations = fetch_elevations_m(lats, lons)
        if elevations is None:
            elevated = flat_elevations(resampled)
        else:
            elevated = apply_elevations(resampled, elevations, scale=scale)
    else:
        elevated = flat_elevations(resampled)

    centerline = build_track_points(elevated)
    inner, outer = offset_boundaries(elevated, width_m)
    bbox = compute_bbox(elevated, inner, outer)

    name = str(properties.get("Name") or properties.get("name") or geojson_path.stem)
    resolved_id = track_id or _slugify(str(properties.get("id") or name))
    start_finish = StartFinish(s_m=0.0, width_m=width_m)

    return Track(
        id=resolved_id,
        name=name,
        source=str(geojson_path),
        source_length_m=source_length_m,
        target_length_m=target_length_m,
        scale=scale,
        width_m=width_m,
        direction=direction,
        start_finish=start_finish,
        bbox=bbox,
        centerline=centerline,
        inner_boundary=inner,
        outer_boundary=outer,
    )
