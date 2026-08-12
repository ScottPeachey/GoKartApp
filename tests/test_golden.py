"""Phase 6 golden vector and C core tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "shared" / "golden"
CORE_TESTS = ROOT / "firmware" / "core_c" / "tests"


def test_generate_golden_writes_json() -> None:
    subprocess.run(
        ["uv", "run", "python", "tools/generate_golden.py"],
        cwd=ROOT,
        check=True,
    )
    for name in ("limits", "safety", "control"):
        path = GOLDEN_DIR / f"{name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["cases"]


def test_c_golden_runner_passes() -> None:
    subprocess.run(["make", "-C", str(CORE_TESTS), "test"], cwd=ROOT, check=True)


def test_hard_limits_generator() -> None:
    subprocess.run(
        ["uv", "run", "python", "tools/generate_hard_limits.py"],
        cwd=ROOT,
        check=True,
    )
    out_json = ROOT / "firmware" / "esp32" / "include" / "hard_limits.json"
    out_header = ROOT / "firmware" / "esp32" / "include" / "hard_limits.h"
    assert out_json.exists()
    assert out_header.exists()
