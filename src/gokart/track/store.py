"""Track file storage."""

from __future__ import annotations

import json
from pathlib import Path

from gokart.config.store import ConfigStoreError, data_root
from gokart.track.geometry import (
    build_track_points,
    compute_bbox,
    offset_boundaries,
    remap_start_finish_s,
    reverse_centerline_points,
)
from gokart.track.model import StartFinish, Track


def _track_path(root: Path, track_id: str) -> Path:
    safe_id = track_id.replace(" ", "_").lower()
    return root / "tracks" / f"{safe_id}.json"


def save_track(
    track: Track,
    *,
    root: Path | None = None,
    allow_overwrite: bool = False,
) -> Path:
    path = _track_path(data_root(root), track.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not allow_overwrite:
        raise ConfigStoreError(f"Refusing to overwrite existing track at {path}")
    path.write_text(
        json.dumps(track.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_track(track_id: str, *, root: Path | None = None) -> Track:
    path = _track_path(data_root(root), track_id)
    if not path.exists():
        raise ConfigStoreError(f"Track not found: {track_id}")
    return Track.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_tracks(*, root: Path | None = None) -> list[Path]:
    tracks_dir = data_root(root) / "tracks"
    if not tracks_dir.is_dir():
        return []
    return sorted(tracks_dir.glob("*.json"))


def update_track_start_finish(
    track_id: str,
    s_m: float,
    *,
    width_m: float | None = None,
    root: Path | None = None,
) -> Track:
    track = load_track(track_id, root=root)
    if s_m < 0 or s_m > track.length_m:
        raise ConfigStoreError(
            f"start/finish s_m must be between 0 and {track.length_m:.1f}, got {s_m:.1f}"
        )
    resolved_width = width_m if width_m is not None else track.start_finish.width_m or track.width_m
    updated = track.model_copy(
        update={
            "start_finish": StartFinish(s_m=s_m, width_m=resolved_width),
        }
    )
    save_track(updated, root=root, allow_overwrite=True)
    return updated


def update_track_direction(
    track_id: str,
    direction: str,
    *,
    root: Path | None = None,
) -> Track:
    if direction not in {"clockwise", "counterclockwise"}:
        raise ConfigStoreError(f"Unsupported track direction: {direction}")
    track = load_track(track_id, root=root)
    if track.direction == direction:
        return track

    reversed_points = reverse_centerline_points(track.centerline)
    centerline = build_track_points(reversed_points)
    inner, outer = offset_boundaries(reversed_points, track.width_m)
    bbox = compute_bbox(reversed_points, inner, outer)
    length_m = centerline[-1].s if centerline else 0.0
    start_finish = StartFinish(
        s_m=remap_start_finish_s(length_m, track.start_finish.s_m),
        width_m=track.start_finish.width_m or track.width_m,
    )
    updated = track.model_copy(
        update={
            "direction": direction,
            "centerline": centerline,
            "inner_boundary": inner,
            "outer_boundary": outer,
            "bbox": bbox,
            "start_finish": start_finish,
        }
    )
    save_track(updated, root=root, allow_overwrite=True)
    return updated
