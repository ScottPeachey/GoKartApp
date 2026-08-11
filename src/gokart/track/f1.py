"""Batch import of F1 circuits from bacinger/f1-circuits."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gokart.track.importer import TrackImportError, import_geojson_track
from gokart.track.store import save_track

F1_CIRCUITS_API = (
    "https://api.github.com/repos/bacinger/f1-circuits/contents/circuits?ref=master"
)
F1_CIRCUITS_RAW_BASE = (
    "https://raw.githubusercontent.com/bacinger/f1-circuits/master/circuits"
)


@dataclass(frozen=True)
class F1ImportResult:
    filename: str
    track_id: str | None
    ok: bool
    message: str


def list_f1_circuit_filenames() -> list[str]:
    try:
        with urllib.request.urlopen(F1_CIRCUITS_API, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TrackImportError(f"Could not list F1 circuits: {exc}") from exc
    names = [
        str(item["name"])
        for item in payload
        if isinstance(item, dict) and str(item.get("name", "")).endswith(".geojson")
    ]
    if not names:
        raise TrackImportError("No F1 circuit GeoJSON files found")
    return sorted(names)


def download_f1_geojson(filename: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    url = f"{F1_CIRCUITS_RAW_BASE}/{filename}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            dest.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TrackImportError(f"Could not download {filename}: {exc}") from exc
    return dest


def import_f1_circuits(
    *,
    width_m: float = 10.0,
    direction: Literal["clockwise", "counterclockwise"] = "clockwise",
    fetch_elevation: bool = True,
    allow_overwrite: bool = False,
    cache_dir: Path | None = None,
    root: Path | None = None,
) -> list[F1ImportResult]:
    """Download and import every circuit from bacinger/f1-circuits."""
    cache = cache_dir or Path(".cache/f1-circuits")
    results: list[F1ImportResult] = []
    for filename in list_f1_circuit_filenames():
        try:
            geojson_path = download_f1_geojson(filename, cache)
            track = import_geojson_track(
                geojson_path,
                width_m=width_m,
                direction=direction,
                fetch_elevation=fetch_elevation,
            )
            save_track(track, root=root, allow_overwrite=allow_overwrite)
            results.append(
                F1ImportResult(
                    filename=filename,
                    track_id=track.id,
                    ok=True,
                    message=f"{track.name} ({track.length_m:.0f} m)",
                )
            )
        except (TrackImportError, OSError, ValueError) as exc:
            results.append(
                F1ImportResult(
                    filename=filename,
                    track_id=None,
                    ok=False,
                    message=str(exc),
                )
            )
    return results
