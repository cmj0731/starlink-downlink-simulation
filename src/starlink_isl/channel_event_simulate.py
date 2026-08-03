"""Compare frame-sized SISO channel grids at three visibility-pass events."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from starlink_isl.channel_grid_simulate import (
    DEFAULT_GEOMETRY_SUMMARY_PATH,
    DEFAULT_SOURCE_OMM_PATH,
    run_channel_grid_simulation,
)
from starlink_isl.research_config import (
    DEFAULT_BASELINE_PATH,
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.sgp4_orbit import GroundStation

DEFAULT_CHANNEL_EVENT_OUTPUT_DIRECTORY = Path("outputs/channel_events")
EVENT_ORDER = (
    "visibility_start",
    "closest_approach",
    "visibility_end",
)
EVENT_SUMMARY_KEYS = {
    "visibility_start": "start_utc",
    "closest_approach": "closest_approach_utc",
    "visibility_end": "end_utc",
}
EVENT_LABELS = {
    "visibility_start": "Visibility start",
    "closest_approach": "Closest approach",
    "visibility_end": "Visibility end",
}


@dataclass(frozen=True, slots=True)
class ChannelEventComparisonArtifacts:
    """Aggregate files produced after the three per-event grid directories."""

    metrics_csv: Path
    summary_json: Path
    phase_comparison_png: Path
    metrics_png: Path


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    return _utc(
        datetime.fromisoformat(value.replace("Z", "+00:00")),
        "UTC timestamp",
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_references(
    values: Mapping[str, datetime],
) -> dict[str, datetime]:
    missing = [event for event in EVENT_ORDER if event not in values]
    extras = [event for event in values if event not in EVENT_ORDER]
    if missing or extras:
        raise ValueError(
            "event_references_utc must contain exactly: "
            + ", ".join(EVENT_ORDER)
        )
    return {
        event: _utc(values[event], f"event_references_utc[{event}]")
        for event in EVENT_ORDER
    }


def _event_metrics(
    event: str,
    reference_utc: datetime,
    raw_npz: Path,
    synchronized_npz: Path,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    with np.load(raw_npz, allow_pickle=False) as raw:
        channel_response = np.array(raw["channel_response"], copy=True)
        time_s = np.array(raw["time_s"], copy=True)
        frequency_hz = np.array(raw["baseband_frequency_hz"], copy=True)
        slant_range_m = np.array(raw["slant_range_m"], copy=True)
        delay_s = np.array(raw["propagation_delay_s"], copy=True)
        radial_velocity_m_s = np.array(
            raw["radial_velocity_m_s"],
            copy=True,
        )
        doppler_hz = np.array(raw["doppler_shift_hz"], copy=True)
        fspl_db = np.array(raw["free_space_path_loss_db"], copy=True)
        carrier_phase_rad = np.array(
            raw["carrier_doppler_phase_rad"],
            copy=True,
        )
    with np.load(synchronized_npz, allow_pickle=False) as synchronized:
        residual_delay_s = np.array(
            synchronized["residual_propagation_delay_s"],
            copy=True,
        )
        residual_phase_rad = np.array(
            synchronized["residual_total_phase_rad"],
            copy=True,
        )

    if not time_s[0] < 0.0 < time_s[-1]:
        raise ValueError("event channel grid must bracket relative time zero")
    nearest = int(np.argmin(np.abs(time_s)))
    near_dc = int(np.argmin(np.abs(frequency_hz)))
    magnitude_db = 20.0 * np.log10(np.abs(channel_response))

    def at_reference(values: np.ndarray) -> float:
        return float(np.interp(0.0, time_s, values))

    metrics = {
        "reference_event": event,
        "reference_utc": _iso(reference_utc),
        "reference_value_method": "linear interpolation to relative t=0",
        "nearest_symbol_index": nearest,
        "nearest_symbol_time_us": float(time_s[nearest] * 1.0e6),
        "channel_evaluation_span_ms": float(
            (time_s[-1] - time_s[0]) * 1.0e3
        ),
        "reference_slant_range_km": at_reference(slant_range_m) / 1.0e3,
        "reference_propagation_delay_ms": at_reference(delay_s) * 1.0e3,
        "reference_radial_velocity_km_s": (
            at_reference(radial_velocity_m_s) / 1.0e3
        ),
        "reference_doppler_shift_khz": at_reference(doppler_hz) / 1.0e3,
        "carrier_phase_change_cycles_over_frame": float(
            (carrier_phase_rad[-1] - carrier_phase_rad[0])
            / (2.0 * np.pi)
        ),
        "minimum_fspl_db": float(np.min(fspl_db)),
        "maximum_fspl_db": float(np.max(fspl_db)),
        "near_dc_signed_frequency_khz": float(
            frequency_hz[near_dc] / 1.0e3
        ),
        "reference_near_dc_channel_magnitude_db": at_reference(
            magnitude_db[:, near_dc]
        ),
        "maximum_absolute_residual_delay_s": float(
            np.max(np.abs(residual_delay_s))
        ),
        "maximum_absolute_residual_phase_rad": float(
            np.max(np.abs(residual_phase_rad))
        ),
    }
    plot_values = {
        "time_s": time_s,
        "frequency_hz": frequency_hz,
        "raw_phase_rad": np.angle(channel_response),
    }
    return metrics, plot_values


def _save_phase_comparison(
    event_plot_values: Mapping[str, Mapping[str, np.ndarray]],
    path: Path,
) -> None:
    figure, axes = plt.subplots(
        len(EVENT_ORDER),
        1,
        figsize=(10.2, 9.0),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    phase_map = None
    for axis, event in zip(axes, EVENT_ORDER, strict=True):
        values = event_plot_values[event]
        phase_map = axis.pcolormesh(
            values["time_s"] * 1.0e3,
            values["frequency_hz"] / 1.0e6,
            values["raw_phase_rad"].T,
            shading="nearest",
            cmap="twilight",
            vmin=-np.pi,
            vmax=np.pi,
        )
        axis.set(
            ylabel="Baseband frequency (MHz)",
            title=f"{EVENT_LABELS[event]}: raw wrapped phase",
        )
    axes[-1].set_xlabel("Time from each reference event (ms)")
    if phase_map is None:
        raise RuntimeError("no event phase data were plotted")
    figure.colorbar(
        phase_map,
        ax=axes,
        label="Wrapped phase (rad)",
    )
    figure.suptitle(
        "STARLINK-5285 raw SISO channel phase at three pass events"
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _save_metrics_plot(metrics: pd.DataFrame, path: Path) -> None:
    labels = [EVENT_LABELS[event] for event in metrics["reference_event"]]
    colors = ["tab:blue", "tab:green", "tab:orange"]
    figure, axes = plt.subplots(
        2,
        2,
        figsize=(11.0, 8.2),
        constrained_layout=True,
    )
    values_and_labels = (
        ("reference_slant_range_km", "Slant range (km)"),
        ("reference_propagation_delay_ms", "Propagation delay (ms)"),
        ("reference_doppler_shift_khz", "Carrier Doppler shift (kHz)"),
        (
            "carrier_phase_change_cycles_over_frame",
            "Carrier phase change over frame (cycles)",
        ),
    )
    for axis, (column, ylabel) in zip(
        axes.flat,
        values_and_labels,
        strict=True,
    ):
        bars = axis.bar(labels, metrics[column], color=colors)
        axis.set_ylabel(ylabel)
        axis.grid(True, axis="y", alpha=0.3)
        axis.tick_params(axis="x", rotation=12)
        axis.margins(y=0.18)
        axis.bar_label(bars, fmt="%.3f", padding=3)
    figure.suptitle("Channel metrics at visibility start, closest, and end")
    figure.savefig(path, dpi=170)
    plt.close(figure)


def run_channel_event_comparison(
    output_directory: Path,
    *,
    config: ResearchBaselineConfig,
    omm_record: Mapping[str, Any],
    event_references_utc: Mapping[str, datetime],
    station: GroundStation,
    minimum_elevation_deg: float = 10.0,
    symbol_count: int = 256,
    other_losses_db: float = 0.0,
) -> ChannelEventComparisonArtifacts:
    """Generate independent grids and aggregate metrics for three events."""

    references = _event_references(event_references_utc)
    output_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    plot_values: dict[str, dict[str, np.ndarray]] = {}
    for event in EVENT_ORDER:
        event_artifacts = run_channel_grid_simulation(
            output_directory / event,
            config=config,
            omm_record=omm_record,
            reference_utc=references[event],
            station=station,
            minimum_elevation_deg=minimum_elevation_deg,
            symbol_count=symbol_count,
            other_losses_db=other_losses_db,
            reference_event=event,
        )
        metrics, event_plot = _event_metrics(
            event,
            references[event],
            event_artifacts.channel_grid_npz,
            event_artifacts.synchronized_channel_grid_npz,
        )
        records.append(metrics)
        plot_values[event] = event_plot

    metrics_frame = pd.DataFrame.from_records(records)
    artifacts = ChannelEventComparisonArtifacts(
        metrics_csv=output_directory / "event_comparison.csv",
        summary_json=output_directory / "event_comparison.json",
        phase_comparison_png=(
            output_directory / "event_phase_comparison.png"
        ),
        metrics_png=output_directory / "event_metrics.png",
    )
    metrics_frame.to_csv(artifacts.metrics_csv, index=False)
    summary = {
        "model": "three-event LOS SISO channel-grid comparison",
        "event_order": list(EVENT_ORDER),
        "symbol_count_per_event": int(symbol_count),
        "shape_per_event": [
            int(symbol_count),
            int(config.ofdm.active_subcarrier_count),
        ],
        "subcarrier_spacing_hz": config.ofdm.subcarrier_spacing_hz,
        "minimum_elevation_deg": float(minimum_elevation_deg),
        "events": records,
        "interpretation_limits": [
            "each event is an independent frame centred on its own UTC",
            "wrapped phase is sampled once per OFDM symbol",
            "large raw Doppler can alias in the phase heatmap",
            "carrier_phase_change_cycles uses the unwrapped physical phase",
            "synchronized grids use perfect same-state phase prediction",
            "no OFDM transmitter, receiver, pilot estimator, or ICI model",
        ],
    }
    artifacts.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _save_phase_comparison(plot_values, artifacts.phase_comparison_png)
    _save_metrics_plot(metrics_frame, artifacts.metrics_png)
    return artifacts


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """CLI entry point using the existing selected SGP4 pass."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument(
        "--source-omm",
        type=Path,
        default=DEFAULT_SOURCE_OMM_PATH,
    )
    parser.add_argument(
        "--geometry-summary",
        type=Path,
        default=DEFAULT_GEOMETRY_SUMMARY_PATH,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CHANNEL_EVENT_OUTPUT_DIRECTORY,
    )
    parser.add_argument("--symbol-count", type=int, default=256)
    parser.add_argument("--other-losses-db", type=float, default=0.0)
    args = parser.parse_args()

    config = load_research_baseline(args.config)
    omm_data = _load_json(args.source_omm)
    if not isinstance(omm_data, list) or not omm_data:
        raise ValueError("source OMM JSON must be a non-empty list")
    geometry_summary = _load_json(args.geometry_summary)
    selected_pass = geometry_summary["selected_pass"]
    event_references = {
        event: _parse_utc(selected_pass[EVENT_SUMMARY_KEYS[event]])
        for event in EVENT_ORDER
    }
    station = GroundStation(**geometry_summary["station"])
    norad_id = int(geometry_summary["norad_catalog_id"])
    matching_records = [
        record
        for record in omm_data
        if int(record["NORAD_CAT_ID"]) == norad_id
    ]
    if len(matching_records) != 1:
        raise ValueError("source OMM must contain exactly one matching NORAD ID")
    artifacts = run_channel_event_comparison(
        args.output,
        config=config,
        omm_record=matching_records[0],
        event_references_utc=event_references,
        station=station,
        minimum_elevation_deg=float(
            geometry_summary["minimum_elevation_deg"]
        ),
        symbol_count=args.symbol_count,
        other_losses_db=args.other_losses_db,
    )
    print(
        json.dumps(
            {
                name: str(path)
                for name, path in asdict(artifacts).items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
