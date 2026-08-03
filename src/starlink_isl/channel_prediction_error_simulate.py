"""Sweep block-start orbit and Doppler prediction errors for a LOS channel."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from starlink_isl.channel_event_simulate import (
    EVENT_LABELS,
    EVENT_ORDER,
    EVENT_SUMMARY_KEYS,
)
from starlink_isl.channel_grid_simulate import (
    DEFAULT_GEOMETRY_SUMMARY_PATH,
    DEFAULT_SOURCE_OMM_PATH,
    run_channel_grid_simulation,
)
from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S
from starlink_isl.ofdm_channel import (
    predict_block_start_delay_and_doppler_phase,
)
from starlink_isl.research_config import (
    DEFAULT_BASELINE_PATH,
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.sgp4_orbit import GroundStation

DEFAULT_CHANNEL_PREDICTION_ERROR_OUTPUT_DIRECTORY = Path(
    "outputs/channel_prediction_errors"
)
DEFAULT_SOURCE_SYMBOL_COUNT = 1200
DEFAULT_ANALYSIS_SYMBOL_COUNT = 256
DEFAULT_RANGE_ERRORS_M = (-10.0, -1.0, -0.1, 0.0, 0.1, 1.0, 10.0)
DEFAULT_RADIAL_VELOCITY_ERRORS_M_S = (
    -10.0,
    -1.0,
    -0.1,
    0.0,
    0.1,
    1.0,
    10.0,
)
DEFAULT_TIMING_ERRORS_MS = (-1.0, -0.1, -0.01, 0.0, 0.01, 0.1, 1.0)
DEFAULT_DOPPLER_ERRORS_HZ = (
    -1200.0,
    -600.0,
    -120.0,
    0.0,
    120.0,
    600.0,
    1200.0,
)
ERROR_ORDER = (
    "los_range",
    "los_radial_velocity",
    "state_time",
    "doppler_frequency",
)
ERROR_LABELS = {
    "los_range": "LOS range prediction error",
    "los_radial_velocity": "LOS radial-velocity prediction error",
    "state_time": "State timestamp error",
    "doppler_frequency": "Direct Doppler prediction error",
}
ERROR_UNITS = {
    "los_range": "m",
    "los_radial_velocity": "m/s",
    "state_time": "ms",
    "doppler_frequency": "Hz",
}
SPEED_OF_LIGHT_M_S = 1_000.0 * SPEED_OF_LIGHT_KM_S


@dataclass(frozen=True, slots=True)
class ChannelPredictionErrorArtifacts:
    """Files produced by one-factor-at-a-time prediction-error sweeps."""

    metrics_csv: Path
    summary_json: Path
    residual_cfo_png: Path
    residual_phase_png: Path


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
    if set(values) != set(EVENT_ORDER):
        raise ValueError(
            "event_references_utc must contain exactly: "
            + ", ".join(EVENT_ORDER)
        )
    return {
        event: _utc(values[event], f"event_references_utc[{event}]")
        for event in EVENT_ORDER
    }


def _finite_sweep(values: Sequence[float], name: str) -> tuple[float, ...]:
    converted = tuple(float(value) for value in values)
    if not converted or not np.all(np.isfinite(converted)):
        raise ValueError(f"{name} must contain finite values")
    if len(set(converted)) != len(converted):
        raise ValueError(f"{name} must contain unique values")
    if 0.0 not in converted:
        raise ValueError(f"{name} must include zero")
    return tuple(sorted(converted))


def _symbol_counts(source_count: int, analysis_count: int) -> tuple[int, int]:
    counts: list[int] = []
    for value, name in (
        (source_count, "source_symbol_count"),
        (analysis_count, "analysis_symbol_count"),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value,
            (int, np.integer),
        ):
            raise TypeError(f"{name} must be an integer")
        converted = int(value)
        if converted < 2:
            raise ValueError(f"{name} must be at least two")
        counts.append(converted)
    source, analysis = counts
    if source < analysis:
        raise ValueError("source_symbol_count must cover analysis_symbol_count")
    if source % 2 != analysis % 2:
        raise ValueError("source and analysis symbol counts must have same parity")
    return source, analysis


def _prediction_biases(
    *,
    error_type: str,
    error_value: float,
    full_time_s: np.ndarray,
    full_delay_s: np.ndarray,
    full_doppler_hz: np.ndarray,
    full_carrier_phase_rad: np.ndarray,
    block_start_time_s: float,
    block_start_delay_s: float,
    block_start_doppler_hz: float,
    block_start_carrier_phase_rad: float,
    carrier_frequency_hz: float,
) -> tuple[float, float, float]:
    """Return delay, Doppler, and initial phase biases as prediction-truth."""

    if error_type == "los_range":
        delay_bias_s = error_value / SPEED_OF_LIGHT_M_S
        phase_bias_rad = (
            -2.0
            * np.pi
            * carrier_frequency_hz
            * error_value
            / SPEED_OF_LIGHT_M_S
        )
        return delay_bias_s, 0.0, phase_bias_rad
    if error_type == "los_radial_velocity":
        doppler_bias_hz = (
            -error_value / SPEED_OF_LIGHT_M_S * carrier_frequency_hz
        )
        return 0.0, doppler_bias_hz, 0.0
    if error_type == "doppler_frequency":
        return 0.0, error_value, 0.0
    if error_type != "state_time":
        raise ValueError("unsupported prediction error type")

    estimated_state_time_s = block_start_time_s + error_value * 1.0e-3
    if not full_time_s[0] <= estimated_state_time_s <= full_time_s[-1]:
        raise ValueError("state timestamp error lies outside source grid")
    estimated_delay_s = float(
        np.interp(estimated_state_time_s, full_time_s, full_delay_s)
    )
    estimated_doppler_hz = float(
        np.interp(estimated_state_time_s, full_time_s, full_doppler_hz)
    )
    estimated_phase_rad = float(
        np.interp(
            estimated_state_time_s,
            full_time_s,
            full_carrier_phase_rad,
        )
    )
    return (
        estimated_delay_s - block_start_delay_s,
        estimated_doppler_hz - block_start_doppler_hz,
        estimated_phase_rad - block_start_carrier_phase_rad,
    )


def _evaluate_case(
    *,
    event: str,
    reference_utc: datetime,
    error_type: str,
    error_value: float,
    full_time_s: np.ndarray,
    full_delay_s: np.ndarray,
    full_doppler_hz: np.ndarray,
    full_carrier_phase_rad: np.ndarray,
    block_slice: slice,
    path_gain: np.ndarray,
    baseband_frequency_hz: np.ndarray,
    carrier_frequency_hz: float,
    subcarrier_spacing_hz: float,
    symbol_duration_s: float,
) -> dict[str, Any]:
    block_time_s = full_time_s[block_slice]
    block_delay_s = full_delay_s[block_slice]
    block_doppler_hz = full_doppler_hz[block_slice]
    block_carrier_phase_rad = full_carrier_phase_rad[block_slice]
    block_gain = path_gain[block_slice]
    delay_bias_s, doppler_bias_hz, phase_bias_rad = _prediction_biases(
        error_type=error_type,
        error_value=error_value,
        full_time_s=full_time_s,
        full_delay_s=full_delay_s,
        full_doppler_hz=full_doppler_hz,
        full_carrier_phase_rad=full_carrier_phase_rad,
        block_start_time_s=float(block_time_s[0]),
        block_start_delay_s=float(block_delay_s[0]),
        block_start_doppler_hz=float(block_doppler_hz[0]),
        block_start_carrier_phase_rad=float(block_carrier_phase_rad[0]),
        carrier_frequency_hz=carrier_frequency_hz,
    )
    predicted_delay_s, predicted_phase_rad = (
        predict_block_start_delay_and_doppler_phase(
            block_time_s,
            block_delay_s,
            block_doppler_hz,
            block_carrier_phase_rad,
            delay_prediction_bias_s=delay_bias_s,
            doppler_prediction_bias_hz=doppler_bias_hz,
            initial_carrier_phase_prediction_bias_rad=phase_bias_rad,
        )
    )
    predicted_doppler_hz = block_doppler_hz[0] + doppler_bias_hz
    residual_delay_s = block_delay_s - predicted_delay_s
    residual_cfo_hz = block_doppler_hz - predicted_doppler_hz
    residual_carrier_phase_rad = block_carrier_phase_rad - predicted_phase_rad
    residual_delay_phase_rad = (
        -2.0
        * np.pi
        * residual_delay_s[:, None]
        * baseband_frequency_hz[None, :]
    )
    residual_total_phase_rad = (
        residual_carrier_phase_rad[:, None] + residual_delay_phase_rad
    )
    compensated_response = block_gain * np.exp(1j * residual_total_phase_rad)
    reference_response = compensated_response[0]
    normalized_complex_error = (
        np.linalg.norm(
            compensated_response - reference_response[None, :],
            axis=1,
        )
        / np.linalg.norm(reference_response)
    )
    maximum_residual_cfo_hz = float(np.max(np.abs(residual_cfo_hz)))
    wrapped_residual_total_phase_rad = np.angle(
        np.exp(1j * residual_total_phase_rad)
    )
    return {
        "reference_event": event,
        "reference_utc": _iso(reference_utc),
        "error_type": error_type,
        "error_label": ERROR_LABELS[error_type],
        "error_value": float(error_value),
        "error_unit": ERROR_UNITS[error_type],
        "analysis_symbol_count": int(block_time_s.size),
        "nominal_block_duration_ms": float(
            block_time_s.size * symbol_duration_s * 1.0e3
        ),
        "channel_evaluation_span_ms": float(
            (block_time_s[-1] - block_time_s[0]) * 1.0e3
        ),
        "delay_prediction_bias_ns": float(delay_bias_s * 1.0e9),
        "doppler_prediction_bias_hz": float(doppler_bias_hz),
        "normalized_doppler_prediction_bias": float(
            doppler_bias_hz / subcarrier_spacing_hz
        ),
        "doppler_bias_equivalent_radial_velocity_error_m_s": float(
            -doppler_bias_hz
            * SPEED_OF_LIGHT_M_S
            / carrier_frequency_hz
        ),
        "initial_carrier_phase_prediction_bias_cycles": float(
            phase_bias_rad / (2.0 * np.pi)
        ),
        "initial_residual_delay_ns": float(residual_delay_s[0] * 1.0e9),
        "initial_residual_cfo_hz": float(residual_cfo_hz[0]),
        "initial_residual_carrier_phase_cycles": float(
            residual_carrier_phase_rad[0] / (2.0 * np.pi)
        ),
        "maximum_absolute_residual_delay_ns": float(
            np.max(np.abs(residual_delay_s)) * 1.0e9
        ),
        "maximum_absolute_residual_cfo_hz": maximum_residual_cfo_hz,
        "maximum_absolute_normalized_residual_cfo": float(
            maximum_residual_cfo_hz / subcarrier_spacing_hz
        ),
        "maximum_absolute_residual_carrier_phase_cycles": float(
            np.max(np.abs(residual_carrier_phase_rad)) / (2.0 * np.pi)
        ),
        "maximum_absolute_residual_delay_phase_cycles": float(
            np.max(np.abs(residual_delay_phase_rad)) / (2.0 * np.pi)
        ),
        "maximum_absolute_residual_total_phase_cycles": float(
            np.max(np.abs(residual_total_phase_rad)) / (2.0 * np.pi)
        ),
        "maximum_absolute_wrapped_residual_total_phase_cycles": float(
            np.max(np.abs(wrapped_residual_total_phase_rad))
            / (2.0 * np.pi)
        ),
        "rms_residual_total_phase_rad": float(
            np.sqrt(np.mean(residual_total_phase_rad**2))
        ),
        "maximum_normalized_complex_channel_error": float(
            np.max(normalized_complex_error)
        ),
    }


def _save_sweep_plot(
    metrics: pd.DataFrame,
    path: Path,
    *,
    y_column: str,
    y_label: str,
    title: str,
) -> None:
    figure, axes = plt.subplots(
        2,
        2,
        figsize=(11.5, 8.2),
        constrained_layout=True,
    )
    colors = ("tab:blue", "tab:green", "tab:orange")
    markers = ("o", "s", "^")
    for axis, error_type in zip(axes.flat, ERROR_ORDER, strict=True):
        error_metrics = metrics.loc[metrics["error_type"] == error_type]
        for event, color, marker in zip(
            EVENT_ORDER,
            colors,
            markers,
            strict=True,
        ):
            event_metrics = error_metrics.loc[
                error_metrics["reference_event"] == event
            ].sort_values("error_value")
            axis.plot(
                event_metrics["error_value"],
                event_metrics[y_column],
                color=color,
                marker=marker,
                label=EVENT_LABELS[event],
            )
        axis.axvline(0.0, color="0.4", linewidth=0.8, alpha=0.7)
        axis.set(
            xlabel=f"{ERROR_LABELS[error_type]} ({ERROR_UNITS[error_type]})",
            ylabel=y_label,
        )
        axis.set_yscale("log")
        axis.grid(True, which="both", alpha=0.3)
    axes[0, 0].legend(loc="best")
    figure.suptitle(title)
    figure.savefig(path, dpi=170)
    plt.close(figure)


def run_channel_prediction_error_comparison(
    output_directory: Path,
    *,
    config: ResearchBaselineConfig,
    omm_record: Mapping[str, Any],
    event_references_utc: Mapping[str, datetime],
    station: GroundStation,
    minimum_elevation_deg: float = 10.0,
    source_symbol_count: int = DEFAULT_SOURCE_SYMBOL_COUNT,
    analysis_symbol_count: int = DEFAULT_ANALYSIS_SYMBOL_COUNT,
    range_errors_m: Sequence[float] = DEFAULT_RANGE_ERRORS_M,
    radial_velocity_errors_m_s: Sequence[float] = (
        DEFAULT_RADIAL_VELOCITY_ERRORS_M_S
    ),
    timing_errors_ms: Sequence[float] = DEFAULT_TIMING_ERRORS_MS,
    doppler_errors_hz: Sequence[float] = DEFAULT_DOPPLER_ERRORS_HZ,
    other_losses_db: float = 0.0,
) -> ChannelPredictionErrorArtifacts:
    """Run independent error sweeps around a block-start predictor."""

    references = _event_references(event_references_utc)
    source_count, analysis_count = _symbol_counts(
        source_symbol_count,
        analysis_symbol_count,
    )
    sweeps = {
        "los_range": _finite_sweep(range_errors_m, "range_errors_m"),
        "los_radial_velocity": _finite_sweep(
            radial_velocity_errors_m_s,
            "radial_velocity_errors_m_s",
        ),
        "state_time": _finite_sweep(timing_errors_ms, "timing_errors_ms"),
        "doppler_frequency": _finite_sweep(
            doppler_errors_hz,
            "doppler_errors_hz",
        ),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    block_start = (source_count - analysis_count) // 2
    block_slice = slice(block_start, block_start + analysis_count)
    for event in EVENT_ORDER:
        event_artifacts = run_channel_grid_simulation(
            output_directory / event,
            config=config,
            omm_record=omm_record,
            reference_utc=references[event],
            station=station,
            minimum_elevation_deg=minimum_elevation_deg,
            symbol_count=source_count,
            other_losses_db=other_losses_db,
            reference_event=event,
        )
        with np.load(event_artifacts.channel_grid_npz, allow_pickle=False) as raw:
            full_time_s = np.array(raw["time_s"], copy=True)
            full_delay_s = np.array(raw["propagation_delay_s"], copy=True)
            full_doppler_hz = np.array(raw["doppler_shift_hz"], copy=True)
            full_carrier_phase_rad = np.array(
                raw["carrier_doppler_phase_rad"],
                copy=True,
            )
            path_gain = np.array(raw["path_amplitude_gain"], copy=True)
            baseband_frequency_hz = np.array(
                raw["baseband_frequency_hz"],
                copy=True,
            )
        for error_type in ERROR_ORDER:
            for error_value in sweeps[error_type]:
                records.append(
                    _evaluate_case(
                        event=event,
                        reference_utc=references[event],
                        error_type=error_type,
                        error_value=error_value,
                        full_time_s=full_time_s,
                        full_delay_s=full_delay_s,
                        full_doppler_hz=full_doppler_hz,
                        full_carrier_phase_rad=full_carrier_phase_rad,
                        block_slice=block_slice,
                        path_gain=path_gain,
                        baseband_frequency_hz=baseband_frequency_hz,
                        carrier_frequency_hz=config.radio.carrier_frequency_hz,
                        subcarrier_spacing_hz=(
                            config.ofdm.subcarrier_spacing_hz
                        ),
                        symbol_duration_s=(
                            config.ofdm.total_symbol_duration_s
                        ),
                    )
                )

    metrics = pd.DataFrame.from_records(records)
    symbol_duration_s = config.ofdm.total_symbol_duration_s
    metrics["nominal_block_duration_ms"] = (
        analysis_count * symbol_duration_s * 1.0e3
    )
    artifacts = ChannelPredictionErrorArtifacts(
        metrics_csv=output_directory / "prediction_error_metrics.csv",
        summary_json=output_directory / "prediction_error_summary.json",
        residual_cfo_png=output_directory / "prediction_error_residual_cfo.png",
        residual_phase_png=(
            output_directory / "prediction_error_residual_phase.png"
        ),
    )
    metrics.to_csv(artifacts.metrics_csv, index=False)
    summary = {
        "model": "one-factor-at-a-time block-start prediction-error sweep",
        "event_order": list(EVENT_ORDER),
        "error_order": list(ERROR_ORDER),
        "error_sweeps": {
            error_type: {
                "values": list(sweeps[error_type]),
                "unit": ERROR_UNITS[error_type],
            }
            for error_type in ERROR_ORDER
        },
        "source_symbol_count": source_count,
        "analysis_symbol_count": analysis_count,
        "nominal_block_duration_ms": (
            analysis_count * symbol_duration_s * 1.0e3
        ),
        "channel_evaluation_span_ms": (
            (analysis_count - 1) * symbol_duration_s * 1.0e3
        ),
        "carrier_frequency_hz": config.radio.carrier_frequency_hz,
        "subcarrier_spacing_hz": config.ofdm.subcarrier_spacing_hz,
        "error_sign_convention": {
            "range": "predicted LOS range minus true LOS range",
            "radial_velocity": (
                "predicted LOS radial velocity minus true radial velocity"
            ),
            "state_time": (
                "state at actual block start plus error is assigned to start"
            ),
            "doppler_frequency": (
                "predicted Doppler frequency minus true Doppler frequency"
            ),
            "residual": "truth minus prediction",
        },
        "conversion_formulas": {
            "range_to_delay": "delta_tau=delta_R/c",
            "range_to_carrier_phase": (
                "delta_phi_prediction=-2*pi*fc*delta_R/c"
            ),
            "velocity_to_doppler": "delta_fD=-delta_v*fc/c",
            "normalized_cfo": "epsilon=residual_CFO/subcarrier_spacing",
        },
        "metrics": records,
        "interpretation_limits": [
            "only one error source is changed at a time",
            "the block-start state is otherwise exact",
            "range error is LOS-projected position error",
            "transverse position and antenna-pointing errors are excluded",
            "no OFDM detector, BER, EVM, pilot estimator, AWGN, or ICI model",
        ],
    }
    artifacts.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _save_sweep_plot(
        metrics,
        artifacts.residual_cfo_png,
        y_column="maximum_absolute_residual_cfo_hz",
        y_label="Maximum residual CFO (Hz)",
        title="Residual CFO from block-start prediction errors",
    )
    _save_sweep_plot(
        metrics,
        artifacts.residual_phase_png,
        y_column="maximum_absolute_residual_total_phase_cycles",
        y_label="Maximum unwrapped residual total phase (cycles)",
        title=(
            "Unwrapped residual channel phase from block-start prediction errors"
        ),
    )
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
        default=DEFAULT_CHANNEL_PREDICTION_ERROR_OUTPUT_DIRECTORY,
    )
    parser.add_argument(
        "--source-symbol-count",
        type=int,
        default=DEFAULT_SOURCE_SYMBOL_COUNT,
    )
    parser.add_argument(
        "--analysis-symbol-count",
        type=int,
        default=DEFAULT_ANALYSIS_SYMBOL_COUNT,
    )
    parser.add_argument(
        "--range-errors-m",
        type=float,
        nargs="+",
        default=list(DEFAULT_RANGE_ERRORS_M),
    )
    parser.add_argument(
        "--radial-velocity-errors-m-s",
        type=float,
        nargs="+",
        default=list(DEFAULT_RADIAL_VELOCITY_ERRORS_M_S),
    )
    parser.add_argument(
        "--timing-errors-ms",
        type=float,
        nargs="+",
        default=list(DEFAULT_TIMING_ERRORS_MS),
    )
    parser.add_argument(
        "--doppler-errors-hz",
        type=float,
        nargs="+",
        default=list(DEFAULT_DOPPLER_ERRORS_HZ),
    )
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
    artifacts = run_channel_prediction_error_comparison(
        args.output,
        config=config,
        omm_record=matching_records[0],
        event_references_utc=event_references,
        station=station,
        minimum_elevation_deg=float(
            geometry_summary["minimum_elevation_deg"]
        ),
        source_symbol_count=args.source_symbol_count,
        analysis_symbol_count=args.analysis_symbol_count,
        range_errors_m=args.range_errors_m,
        radial_velocity_errors_m_s=args.radial_velocity_errors_m_s,
        timing_errors_ms=args.timing_errors_ms,
        doppler_errors_hz=args.doppler_errors_hz,
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
