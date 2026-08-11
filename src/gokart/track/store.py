"""Track file storage."""

from __future__ import annotations

import json
from pathlib import Path

from gokart.config.store import ConfigStoreError, data_root
from gokart.track.model import Track


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
