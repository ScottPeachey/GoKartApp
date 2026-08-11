"""Track API response helpers."""

from __future__ import annotations

from typing import Any

from gokart.track.model import Track
from gokart.track.queries import start_finish_segment


def track_summary(track: Track) -> dict[str, Any]:
    return {
        "id": track.id,
        "name": track.name,
        "length_m": track.length_m,
        "width_m": track.width_m,
        "direction": track.direction,
        "start_finish_s_m": track.start_finish.s_m,
    }


def track_detail(track: Track) -> dict[str, Any]:
    width = track.start_finish.width_m or track.width_m
    payload = track.model_dump(mode="json")
    payload["length_m"] = track.length_m
    payload["start_finish_line"] = start_finish_segment(
        track.centerline,
        track.start_finish.s_m,
        width,
    )
    return payload
