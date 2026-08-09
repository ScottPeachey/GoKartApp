"""Self-contained HTML analysis reports."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from gokart.analysis.metrics import SessionMetrics, compute_metrics
from gokart.telemetry.storage import SessionInfo, TelemetryStore


def _figure_to_base64(fig: plt.Figure) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _plot_series(
    samples: list[dict[str, Any]],
    *,
    channel: str,
    ylabel: str,
    title: str,
) -> str:
    fig, axis = plt.subplots(figsize=(8, 3))
    times = [float(sample.get("time_s", 0.0)) for sample in samples]
    values = [float(sample.get(channel, 0.0)) for sample in samples]
    axis.plot(times, values, linewidth=1.5)
    axis.set_xlabel("Time (s)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(True, alpha=0.3)
    return _figure_to_base64(fig)


def generate_report_html(
    session: SessionInfo,
    metrics: SessionMetrics,
    samples: list[dict[str, Any]],
    *,
    scenario_name: str | None = None,
) -> str:
    speed_plot = _plot_series(samples, channel="speed_mps", ylabel="Speed (m/s)", title="Speed")
    power_plot = _plot_series(samples, channel="power_w", ylabel="Power (W)", title="Power")
    soc_plot = _plot_series(samples, channel="soc", ylabel="SOC", title="State of Charge")

    metric_rows = "".join(
        f"<tr><td>{name}</td><td>{value}</td></tr>"
        for name, value in metrics.as_dict().items()
        if value is not None
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Go-Kart Session Report — {session.session_id}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
    table {{ border-collapse: collapse; margin: 1rem 0; }}
    td, th {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
    img {{ max-width: 100%; margin: 1rem 0; }}
    .meta {{ color: #555; }}
  </style>
</head>
<body>
  <h1>Session Report</h1>
  <p class="meta">
    Vehicle: {session.vehicle_name} {session.vehicle_version}<br />
    Config hash: {session.config_hash}<br />
    Scenario: {scenario_name or session.scenario_name or "—"}<br />
    Started: {session.started_at}<br />
  </p>
  <h2>Metrics</h2>
  <table>
    <thead><tr><th>Metric</th><th>Value</th></tr></thead>
    <tbody>{metric_rows}</tbody>
  </table>
  <h2>Plots</h2>
  <img alt="Speed" src="data:image/png;base64,{speed_plot}" />
  <img alt="Power" src="data:image/png;base64,{power_plot}" />
  <img alt="SOC" src="data:image/png;base64,{soc_plot}" />
</body>
</html>
"""


def write_session_report(
    session_id: str,
    path: Path,
    *,
    store: TelemetryStore | None = None,
) -> SessionMetrics:
    telemetry_store = store or TelemetryStore()
    session = telemetry_store.get_session(session_id)
    if session is None:
        raise KeyError(f"Session not found: {session_id}")
    samples = telemetry_store.load_samples(session_id)
    metrics = compute_metrics(samples)
    html = generate_report_html(session, metrics, samples, scenario_name=session.scenario_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return metrics
