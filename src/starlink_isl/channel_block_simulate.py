"""Compare LOS SISO channel variation across several OFDM block lengths."""

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
from starlink_isl.research_config import (
    DEFAULT_BASELINE_PATH,
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.sgp4_orbit import GroundStation

DEFAULT_CHANNEL_BLOCK_OUTPUT_DIRECTORY = Path("outputs/channel_blocks")
DEFAULT_BLOCK_SYMBOL_COUNTS = (120, 256, 600, 1200)


@dataclass(frozen=True, slots=True)
class ChannelBlockComparisonArtifacts:
    """Aggregate files produced by a block-length comparison."""

    metrics_csv: Path
    summary_json: Path
    comparison_png: Path


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


def _block_counts(values: Sequence[int]) -> tuple[int, ...]:
    counts: list[int] = []
    for value in values:
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value,
            (int, np.integer),
        ):
            raise TypeError("block symbol counts must be integers")
        count = int(value)
        if count < 2:
            raise ValueError("block symbol counts must be at least two")
        counts.append(count)
    if not counts:
        raise ValueError("at least one block symbol count is required")
    if len(set(counts)) != len(counts):
        raise ValueError("block symbol counts must be unique")
    ordered = tuple(sorted(counts))
    maximum_parity = ordered[-1] % 2
    if any(count % 2 != maximum_parity for count in ordered):
        raise ValueError(
            "all block symbol counts must have the same parity for centring"
        )
    return ordered


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


def _at_reference(time_s: np.ndarray, values: np.ndarray) -> float:
    if not time_s[0] < 0.0 < time_s[-1]:
        raise ValueError("channel block must bracket relative time zero")
    return float(np.interp(0.0, time_s, values))


def _frequency_vector_correlation(
    response: np.ndarray,
    reference: np.ndarray,
) -> np.ndarray:
    numerator = np.abs(
        np.sum(np.conj(reference)[None, :] * response, axis=1)
    )
    denominator = np.linalg.norm(reference) * np.linalg.norm(
        response,
        axis=1,
    )
    return np.asarray(numerator / denominator, dtype=np.float64)


def _block_metrics(
    event: str,
    reference_utc: datetime,
    raw_npz: Path,
    synchronized_npz: Path,
    block_symbol_counts: tuple[int, ...],
    symbol_duration_s: float,
) -> list[dict[str, Any]]:
    with np.load(raw_npz, allow_pickle=False) as raw:
        response = np.array(raw["channel_response"], copy=True)
        time_s = np.array(raw["time_s"], copy=True)
        frequency_hz = np.array(raw["baseband_frequency_hz"], copy=True)
        path_gain = np.array(raw["path_amplitude_gain"], copy=True)
        slant_range_m = np.array(raw["slant_range_m"], copy=True)
        delay_s = np.array(raw["propagation_delay_s"], copy=True)
        doppler_hz = np.array(raw["doppler_shift_hz"], copy=True)
        carrier_phase_rad = np.array(
            raw["carrier_doppler_phase_rad"],
            copy=True,
        )
    with np.load(synchronized_npz, allow_pickle=False) as synchronized:
        synchronized_response = np.array(
            synchronized["channel_response"],
            copy=True,
        )

    maximum_count = block_symbol_counts[-1]
    if response.shape != (maximum_count, frequency_hz.size):
        raise ValueError("saved channel grid does not match maximum block size")
    near_dc = int(np.argmin(np.abs(frequency_hz)))
    records: list[dict[str, Any]] = []
    for count in block_symbol_counts:
        start = (maximum_count - count) // 2
        stop = start + count
        block_time_s = time_s[start:stop]
        block_response = response[start:stop]
        block_synchronized = synchronized_response[start:stop]
        block_gain = path_gain[start:stop]
        block_range_m = slant_range_m[start:stop]
        block_delay_s = delay_s[start:stop]
        block_doppler_hz = doppler_hz[start:stop]
        block_carrier_phase_rad = carrier_phase_rad[start:stop]

        reference_delay_s = _at_reference(block_time_s, block_delay_s)
        reference_carrier_phase_rad = _at_reference(
            block_time_s,
            block_carrier_phase_rad,
        )
        reference_gain = np.asarray(
            [
                np.interp(0.0, block_time_s, block_gain[:, column])
                for column in range(frequency_hz.size)
            ],
            dtype=np.float64,
        )
        reference_response = reference_gain * np.exp(
            1j
            * (
                reference_carrier_phase_rad
                - 2.0 * np.pi * frequency_hz * reference_delay_s
            )
        )
        reference_synchronized = reference_gain.astype(np.complex128)
        raw_correlation = _frequency_vector_correlation(
            block_response,
            reference_response,
        )
        synchronized_correlation = _frequency_vector_correlation(
            block_synchronized,
            reference_synchronized,
        )
        near_dc_magnitude_db = 20.0 * np.log10(
            np.abs(block_response[:, near_dc])
        )
        reference_magnitude_db = _at_reference(
            block_time_s,
            near_dc_magnitude_db,
        )
        carrier_phase_excursion_cycles = (
            block_carrier_phase_rad - reference_carrier_phase_rad
        ) / (2.0 * np.pi)
        delay_excursion_s = block_delay_s - reference_delay_s
        maximum_baseband_frequency_hz = float(
            np.max(np.abs(frequency_hz))
        )
        records.append(
            {
                "reference_event": event,
                "reference_utc": _iso(reference_utc),
                "symbol_count": count,
                "nominal_block_duration_ms": (
                    count * symbol_duration_s * 1.0e3
                ),
                "channel_evaluation_span_ms": float(
                    (block_time_s[-1] - block_time_s[0]) * 1.0e3
                ),
                "first_evaluation_time_ms": float(
                    block_time_s[0] * 1.0e3
                ),
                "last_evaluation_time_ms": float(
                    block_time_s[-1] * 1.0e3
                ),
                "reference_slant_range_km": (
                    _at_reference(block_time_s, block_range_m) / 1.0e3
                ),
                "slant_range_span_m": float(np.ptp(block_range_m)),
                "maximum_absolute_range_change_from_reference_m": float(
                    np.max(
                        np.abs(
                            block_range_m
                            - _at_reference(block_time_s, block_range_m)
                        )
                    )
                ),
                "propagation_delay_span_ns": float(
                    np.ptp(block_delay_s) * 1.0e9
                ),
                "maximum_absolute_delay_change_ns": float(
                    np.max(np.abs(delay_excursion_s)) * 1.0e9
                ),
                "reference_doppler_shift_khz": (
                    _at_reference(block_time_s, block_doppler_hz) / 1.0e3
                ),
                "doppler_span_hz": float(np.ptp(block_doppler_hz)),
                "maximum_absolute_doppler_change_hz": float(
                    np.max(
                        np.abs(
                            block_doppler_hz
                            - _at_reference(block_time_s, block_doppler_hz)
                        )
                    )
                ),
                "near_dc_reference_magnitude_db": reference_magnitude_db,
                "near_dc_magnitude_span_db": float(
                    np.ptp(near_dc_magnitude_db)
                ),
                "maximum_absolute_magnitude_change_db": float(
                    np.max(
                        np.abs(
                            near_dc_magnitude_db - reference_magnitude_db
                        )
                    )
                ),
                "carrier_phase_peak_to_peak_cycles": float(
                    np.ptp(block_carrier_phase_rad) / (2.0 * np.pi)
                ),
                "maximum_absolute_carrier_phase_excursion_cycles": float(
                    np.max(np.abs(carrier_phase_excursion_cycles))
                ),
                "maximum_absolute_band_edge_delay_phase_cycles": float(
                    np.max(np.abs(delay_excursion_s))
                    * maximum_baseband_frequency_hz
                ),
                "minimum_raw_frequency_vector_correlation_magnitude": float(
                    np.min(raw_correlation)
                ),
                "minimum_synchronized_frequency_vector_correlation_magnitude": (
                    float(np.min(synchronized_correlation))
                ),
                "magnitude_change_below_0p01_db": bool(
                    np.max(
                        np.abs(
                            near_dc_magnitude_db - reference_magnitude_db
                        )
                    )
                    <= 0.01
                ),
            }
        )
    return records


def _save_comparison_plot(metrics: pd.DataFrame, path: Path) -> None:
    figure, axes = plt.subplots(
        2,
        2,
        figsize=(11.5, 8.2),
        constrained_layout=True,
    )
    columns = (
        (
            "near_dc_magnitude_span_db",
            "Near-DC magnitude span (dB)",
            True,
        ),
        ("doppler_span_hz", "Doppler span (Hz)", True),
        (
            "maximum_absolute_carrier_phase_excursion_cycles",
            "Max carrier-phase excursion (cycles)",
            True,
        ),
        (
            "minimum_raw_frequency_vector_correlation_magnitude",
            "Minimum frequency-vector correlation |rho|",
            False,
        ),
    )
    colors = ("tab:blue", "tab:green", "tab:orange")
    markers = ("o", "s", "^")
    for axis, (column, ylabel, logarithmic) in zip(
        axes.flat,
        columns,
        strict=True,
    ):
        for event, color, marker in zip(
            EVENT_ORDER,
            colors,
            markers,
            strict=True,
        ):
            event_metrics = metrics.loc[
                metrics["reference_event"] == event
            ]
            axis.plot(
                event_metrics["nominal_block_duration_ms"],
                event_metrics[column],
                color=color,
                marker=marker,
                label=EVENT_LABELS[event],
            )
        axis.set(
            xlabel="Nominal OFDM block duration (ms)",
            ylabel=ylabel,
        )
        if logarithmic:
            axis.set_yscale("log")
        else:
            axis.set_ylim(-0.02, 1.02)
        axis.grid(True, which="both", alpha=0.3)
    axes[0, 0].legend(loc="best")
    figure.suptitle(
        "STARLINK-5285 LOS channel variation versus OFDM block length"
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def run_channel_block_comparison(
    output_directory: Path,
    *,
    config: ResearchBaselineConfig,
    omm_record: Mapping[str, Any],
    event_references_utc: Mapping[str, datetime],
    station: GroundStation,
    minimum_elevation_deg: float = 10.0,
    block_symbol_counts: Sequence[int] = DEFAULT_BLOCK_SYMBOL_COUNTS,
    other_losses_db: float = 0.0,
) -> ChannelBlockComparisonArtifacts:
    """Compare nested, event-centred channel blocks on the OFDM symbol grid."""

    references = _event_references(event_references_utc)
    counts = _block_counts(block_symbol_counts)
    output_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for event in EVENT_ORDER:
        event_artifacts = run_channel_grid_simulation(
            output_directory / event,
            config=config,
            omm_record=omm_record,
            reference_utc=references[event],
            station=station,
            minimum_elevation_deg=minimum_elevation_deg,
            symbol_count=counts[-1],
            other_losses_db=other_losses_db,
            reference_event=event,
        )
        records.extend(
            _block_metrics(
                event,
                references[event],
                event_artifacts.channel_grid_npz,
                event_artifacts.synchronized_channel_grid_npz,
                counts,
                config.ofdm.total_symbol_duration_s,
            )
        )

    metrics = pd.DataFrame.from_records(records)
    artifacts = ChannelBlockComparisonArtifacts(
        metrics_csv=output_directory / "block_metrics.csv",
        summary_json=output_directory / "block_summary.json",
        comparison_png=output_directory / "block_length_comparison.png",
    )
    metrics.to_csv(artifacts.metrics_csv, index=False)
    current_rows = metrics.loc[metrics["symbol_count"] == 256]
    summary = {
        "model": "LOS SISO OFDM channel block-length comparison",
        "event_order": list(EVENT_ORDER),
        "block_symbol_counts": list(counts),
        "symbol_duration_s": config.ofdm.total_symbol_duration_s,
        "block_definition": {
            "nominal_duration": "N times OFDM symbol duration",
            "channel_evaluation_span": "(N-1) times OFDM symbol duration",
            "centering": "relative t=0 lies between the two centre symbols",
        },
        "metrics": records,
        "current_256_symbol_block": (
            current_rows.to_dict(orient="records")
            if not current_rows.empty
            else []
        ),
        "interpretation_limits": [
            "raw phase includes deterministic carrier Doppler and delay phase",
            (
                "frequency-vector correlation magnitude removes common "
                "carrier phase but retains delay-slope decorrelation"
            ),
            "perfect synchronized channel retains path amplitude only",
            "magnitude threshold 0.01 dB is an explicit reporting criterion",
            "no multipath, AWGN, pilot estimator, beamforming, or ICI model",
        ],
    }
    artifacts.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _save_comparison_plot(metrics, artifacts.comparison_png)
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
        default=DEFAULT_CHANNEL_BLOCK_OUTPUT_DIRECTORY,
    )
    parser.add_argument(
        "--symbol-counts",
        type=int,
        nargs="+",
        default=list(DEFAULT_BLOCK_SYMBOL_COUNTS),
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
    artifacts = run_channel_block_comparison(
        args.output,
        config=config,
        omm_record=matching_records[0],
        event_references_utc=event_references,
        station=station,
        minimum_elevation_deg=float(
            geometry_summary["minimum_elevation_deg"]
        ),
        block_symbol_counts=args.symbol_counts,
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
