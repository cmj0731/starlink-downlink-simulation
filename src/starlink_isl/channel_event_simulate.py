"""Compare frame-sized SISO channel grids at three visibility-pass events."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from starlink_isl.channel_grid import build_ofdm_channel_grid_axes
from starlink_isl.channel_grid_simulate import (
    DEFAULT_GEOMETRY_SUMMARY_PATH,
    DEFAULT_SOURCE_OMM_PATH,
    run_channel_grid_simulation,
)
from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S
from starlink_isl.research_config import (
    DEFAULT_BASELINE_PATH,
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.sgp4_orbit import GroundStation, satrec_from_omm
from starlink_isl.si_interface import sgp4_downlink_state_si
from starlink_isl.state_resampling import resample_downlink_state_si

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
SPEED_OF_LIGHT_M_S = 1_000.0 * SPEED_OF_LIGHT_KM_S


@dataclass(frozen=True, slots=True)
class ChannelEventComparisonArtifacts:
    """Aggregate files produced after the three per-event grid directories."""

    metrics_csv: Path
    summary_json: Path
    phase_comparison_png: Path
    metrics_png: Path
    magnitude_evolution_csv: Path
    magnitude_evolution_npz: Path
    magnitude_evolution_png: Path


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


def _positive_finite(value: float, name: str) -> float:
    converted = float(value)
    if not np.isfinite(converted) or converted <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return converted


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
        "near_dc_magnitude_span_over_frame_db": float(
            np.ptp(magnitude_db[:, near_dc])
        ),
        "frequency_magnitude_span_at_nearest_symbol_db": float(
            np.ptp(magnitude_db[nearest])
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


def _observation_time_axis(
    start_s: float,
    end_s: float,
    nominal_step_s: float,
    event_offsets_s: Mapping[str, float],
) -> np.ndarray:
    """Return a long observation axis with all event offsets included exactly."""

    step_s = _positive_finite(nominal_step_s, "magnitude_observation_step_s")
    if not np.isfinite(start_s) or not np.isfinite(end_s) or start_s >= end_s:
        raise ValueError("magnitude observation start must precede end")
    base = np.arange(start_s, end_s, step_s, dtype=np.float64)
    combined = np.concatenate(
        (
            base,
            np.asarray([end_s, *event_offsets_s.values()], dtype=np.float64),
        )
    )
    return np.unique(combined)


def _save_magnitude_evolution_plot(
    *,
    time_s: np.ndarray,
    frequency_hz: np.ndarray,
    magnitude_db: np.ndarray,
    event_offsets_s: Mapping[str, float],
    path: Path,
    nominal_step_s: float,
) -> None:
    frequency_mhz = frequency_hz / 1.0e6
    near_dc = int(np.argmin(np.abs(frequency_hz)))
    near_dc_magnitude_db = magnitude_db[:, near_dc]
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(11.0, 8.0),
        sharex=True,
        constrained_layout=True,
    )
    magnitude_map = axes[0].pcolormesh(
        time_s,
        frequency_mhz,
        magnitude_db.T,
        shading="nearest",
        cmap="viridis",
    )
    colorbar = figure.colorbar(
        magnitude_map,
        ax=axes[0],
        label="20 log10 |H| (dB)",
    )
    colorbar.formatter.set_useOffset(False)
    colorbar.update_ticks()
    axes[0].set(
        ylabel="Baseband subcarrier frequency (MHz)",
        title="Long-duration LOS channel magnitude across time and frequency",
    )
    axes[1].plot(
        time_s,
        near_dc_magnitude_db,
        color="tab:blue",
        label="Near-DC active subcarrier",
    )
    for event in EVENT_ORDER:
        event_time_s = float(event_offsets_s[event])
        event_index = int(np.flatnonzero(time_s == event_time_s)[0])
        for axis in axes:
            axis.axvline(
                event_time_s,
                color="tab:orange",
                linewidth=1.0,
                alpha=0.75,
            )
        axes[1].scatter(
            [event_time_s],
            [near_dc_magnitude_db[event_index]],
            color="tab:orange",
            zorder=3,
        )
        axes[1].annotate(
            EVENT_LABELS[event],
            (event_time_s, near_dc_magnitude_db[event_index]),
            xytext=(0, -18 if event == "closest_approach" else 8),
            textcoords="offset points",
            ha="center",
            va="top" if event == "closest_approach" else "bottom",
            fontsize=8,
        )
    axes[1].set(
        xlabel="Time from closest approach (s)",
        ylabel="20 log10 |H| (dB)",
        title="Time evolution at the active subcarrier nearest DC",
    )
    axes[1].ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="lower center")
    figure.suptitle(
        "STARLINK-5285 visible-pass magnitude envelope "
        f"(plot sampling {nominal_step_s:g} s; not the OFDM-symbol grid)"
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _save_long_duration_magnitude(
    output_directory: Path,
    *,
    config: ResearchBaselineConfig,
    omm_record: Mapping[str, Any],
    references: Mapping[str, datetime],
    station: GroundStation,
    minimum_elevation_deg: float,
    other_losses_db: float,
    nominal_step_s: float,
) -> tuple[dict[str, Any], Path, Path, Path]:
    """Sample the LOS amplitude over the full visible pass for display."""

    reference_utc = references["closest_approach"]
    event_offsets_s = {
        event: (references[event] - reference_utc).total_seconds()
        for event in EVENT_ORDER
    }
    time_s = _observation_time_axis(
        event_offsets_s["visibility_start"],
        event_offsets_s["visibility_end"],
        nominal_step_s,
        event_offsets_s,
    )
    source_step_s = config.channel_state.geometry_source_step_s
    first_anchor_s = np.floor(time_s[0] / source_step_s) * source_step_s
    first_anchor_s -= source_step_s
    last_anchor_s = np.ceil(time_s[-1] / source_step_s) * source_step_s
    last_anchor_s += source_step_s
    anchor_count = int(np.rint((last_anchor_s - first_anchor_s) / source_step_s))
    anchor_offsets_s = np.linspace(
        first_anchor_s,
        last_anchor_s,
        anchor_count + 1,
        dtype=np.float64,
    )
    satellite = satrec_from_omm(omm_record)
    anchor_datetimes = [
        reference_utc + timedelta(seconds=float(offset))
        for offset in anchor_offsets_s
    ]
    minimum_elevation_rad = np.deg2rad(minimum_elevation_deg)
    source_state = sgp4_downlink_state_si(
        anchor_datetimes,
        satellite,
        config.radio.carrier_frequency_hz,
        station,
        minimum_elevation_rad=minimum_elevation_rad,
        time_origin_utc=reference_utc,
        phase_reference_utc=reference_utc,
    )
    state = resample_downlink_state_si(
        source_state,
        time_s,
        config.radio.carrier_frequency_hz,
        minimum_elevation_rad=minimum_elevation_rad,
    )
    frequency_axis = build_ofdm_channel_grid_axes(
        config.ofdm,
        config.radio.carrier_frequency_hz,
        1,
        symbol_time_reference=config.channel_grid.symbol_time_reference,
    ).frequency
    rf_frequency_hz = np.asarray(frequency_axis.rf_frequency_hz)
    baseband_frequency_hz = np.asarray(frequency_axis.baseband_frequency_hz)
    free_space_path_loss_db = 20.0 * np.log10(
        4.0
        * np.pi
        * state.slant_range_m[:, None]
        * rf_frequency_hz[None, :]
        / SPEED_OF_LIGHT_M_S
    )
    magnitude_db = -(free_space_path_loss_db + float(other_losses_db))
    near_dc = int(np.argmin(np.abs(baseband_frequency_hz)))
    near_dc_magnitude_db = magnitude_db[:, near_dc]
    event_labels = np.full(time_s.shape, "", dtype=object)
    event_records: dict[str, dict[str, float]] = {}
    for event in EVENT_ORDER:
        index = int(np.flatnonzero(time_s == event_offsets_s[event])[0])
        event_labels[index] = event
        event_records[event] = {
            "time_from_closest_approach_s": float(time_s[index]),
            "slant_range_km": float(state.slant_range_m[index] / 1.0e3),
            "near_dc_channel_magnitude_db": float(
                near_dc_magnitude_db[index]
            ),
        }

    csv_path = output_directory / "magnitude_evolution.csv"
    npz_path = output_directory / "magnitude_evolution.npz"
    png_path = output_directory / "magnitude_evolution.png"
    utc_values = [
        _iso(reference_utc + timedelta(seconds=float(offset)))
        for offset in time_s
    ]
    pd.DataFrame(
        {
            "time_from_closest_approach_s": time_s,
            "utc": utc_values,
            "event": event_labels,
            "slant_range_km": state.slant_range_m / 1.0e3,
            "elevation_deg": np.rad2deg(state.elevation_rad),
            "propagation_delay_ms": state.propagation_delay_s * 1.0e3,
            "radial_velocity_km_s": state.radial_velocity_m_s / 1.0e3,
            "doppler_shift_hz": state.doppler_shift_hz,
            "near_dc_channel_magnitude_db": near_dc_magnitude_db,
            "minimum_frequency_channel_magnitude_db": np.min(
                magnitude_db,
                axis=1,
            ),
            "maximum_frequency_channel_magnitude_db": np.max(
                magnitude_db,
                axis=1,
            ),
        }
    ).to_csv(csv_path, index=False)
    np.savez_compressed(
        npz_path,
        channel_magnitude_db=magnitude_db,
        time_from_closest_approach_s=time_s,
        baseband_frequency_hz=baseband_frequency_hz,
        rf_frequency_hz=rf_frequency_hz,
        slant_range_m=state.slant_range_m,
        propagation_delay_s=state.propagation_delay_s,
        radial_velocity_m_s=state.radial_velocity_m_s,
        doppler_shift_hz=state.doppler_shift_hz,
        event_labels=np.asarray(event_labels, dtype="U32"),
        nominal_observation_step_s=np.asarray(nominal_step_s),
        model=np.asarray(
            "long-duration LOS magnitude envelope; not an OFDM-symbol grid"
        ),
    )
    _save_magnitude_evolution_plot(
        time_s=time_s,
        frequency_hz=baseband_frequency_hz,
        magnitude_db=magnitude_db,
        event_offsets_s=event_offsets_s,
        path=png_path,
        nominal_step_s=nominal_step_s,
    )
    frequency_span_per_time_db = np.ptp(magnitude_db, axis=1)
    summary = {
        "purpose": "long-duration visualization of the LOS magnitude envelope",
        "time_axis_kind": "coarse observation axis, not OFDM-symbol samples",
        "nominal_observation_step_s": float(nominal_step_s),
        "time_range_from_closest_approach_s": [
            float(time_s[0]),
            float(time_s[-1]),
        ],
        "sample_count": int(time_s.size),
        "shape": [int(time_s.size), int(baseband_frequency_hz.size)],
        "event_times_included_exactly": True,
        "near_dc_signed_subcarrier_index": int(
            frequency_axis.signed_subcarrier_indices[near_dc]
        ),
        "near_dc_magnitude_time_span_db": float(
            np.ptp(near_dc_magnitude_db)
        ),
        "maximum_frequency_magnitude_span_at_one_time_db": float(
            np.max(frequency_span_per_time_db)
        ),
        "events": event_records,
        "interpretation": (
            "distance-dependent amplitude changes slowly, so a full-pass "
            "time axis reveals variation hidden inside a millisecond frame"
        ),
    }
    return summary, csv_path, npz_path, png_path


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
    magnitude_observation_step_s: float = 0.1,
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
            export_channel_csv=False,
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
    (
        magnitude_summary,
        magnitude_csv,
        magnitude_npz,
        magnitude_png,
    ) = _save_long_duration_magnitude(
        output_directory,
        config=config,
        omm_record=omm_record,
        references=references,
        station=station,
        minimum_elevation_deg=minimum_elevation_deg,
        other_losses_db=other_losses_db,
        nominal_step_s=magnitude_observation_step_s,
    )
    artifacts = ChannelEventComparisonArtifacts(
        metrics_csv=output_directory / "event_comparison.csv",
        summary_json=output_directory / "event_comparison.json",
        phase_comparison_png=(
            output_directory / "event_phase_comparison.png"
        ),
        metrics_png=output_directory / "event_metrics.png",
        magnitude_evolution_csv=magnitude_csv,
        magnitude_evolution_npz=magnitude_npz,
        magnitude_evolution_png=magnitude_png,
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
        "long_duration_magnitude_observation": magnitude_summary,
        "interpretation_limits": [
            "each event is an independent frame centred on its own UTC",
            "wrapped phase is sampled once per OFDM symbol",
            "large raw Doppler can alias in the phase heatmap",
            "carrier_phase_change_cycles uses the unwrapped physical phase",
            "synchronized grids use perfect same-state phase prediction",
            "no OFDM transmitter, receiver, pilot estimator, or ICI model",
            (
                "magnitude_evolution uses a coarse display axis; "
                "it does not replace the per-symbol channel grid"
            ),
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
    parser.add_argument(
        "--magnitude-step-s",
        type=float,
        default=0.1,
        help="nominal full-pass magnitude visualization interval",
    )
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
        magnitude_observation_step_s=args.magnitude_step_s,
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
