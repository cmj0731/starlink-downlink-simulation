"""Evaluate QPSK/AWGN/Doppler performance from an SGP4 pass result."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from starlink_isl.qpsk import (
    QPSKSnapshot,
    simulate_qpsk_snapshot,
    theoretical_qpsk_ber_awgn,
)

DEFAULT_GEOMETRY_RESULTS = Path("outputs/sgp4_downlink/results.csv")
DEFAULT_GEOMETRY_SUMMARY = Path("outputs/sgp4_downlink/summary.json")
DEFAULT_WAVEFORM_OUTPUT = Path("outputs/qpsk_downlink")


@dataclass(frozen=True, slots=True)
class WaveformArtifacts:
    """Files produced by the QPSK downlink evaluation."""

    results_csv: Path
    summary_json: Path
    ber_evm_png: Path
    constellation_png: Path


def _selected_visible_rows(
    frame: pd.DataFrame,
    snapshot_count: int,
) -> pd.DataFrame:
    visible = frame.loc[frame["visible"]].copy()
    if visible.empty:
        raise ValueError("geometry results contain no visible samples")
    count = min(snapshot_count, len(visible))
    indices = np.linspace(0, len(visible) - 1, count).round().astype(int)
    selected = visible.iloc[np.unique(indices)]
    event_rows = visible.loc[visible["event"].fillna("") != ""]
    return (
        pd.concat((selected, event_rows))
        .drop_duplicates(subset="utc")
        .sort_values("time_s")
        .reset_index(drop=True)
    )


def _metrics_frame(
    geometry: pd.DataFrame,
    *,
    symbol_count: int,
    symbol_rate_hz: float,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, QPSKSnapshot]]:
    records: list[dict[str, Any]] = []
    event_snapshots: dict[str, QPSKSnapshot] = {}
    for index, row in geometry.iterrows():
        es_n0_db = float(row["carrier_to_noise_density_db_hz"]) - (
            10.0 * np.log10(symbol_rate_hz)
        )
        snapshot = simulate_qpsk_snapshot(
            symbol_count=symbol_count,
            symbol_rate_hz=symbol_rate_hz,
            snr_db=es_n0_db,
            doppler_hz=float(row["doppler_shift_hz"]),
            seed=seed + index,
        )
        event = str(row["event"]) if pd.notna(row["event"]) else ""
        if event:
            event_snapshots[event] = snapshot
        records.append(
            {
                "utc": row["utc"],
                "time_s": row["time_s"],
                "event": event,
                "elevation_deg": row["elevation_deg"],
                "slant_range_km": row["slant_range_km"],
                "propagation_delay_ms": row["propagation_delay_ms"],
                "doppler_shift_hz": row["doppler_shift_hz"],
                "snr_db": row["snr_db"],
                "carrier_to_noise_density_db_hz": row[
                    "carrier_to_noise_density_db_hz"
                ],
                "es_n0_db": es_n0_db,
                "eb_n0_db": es_n0_db - 10.0 * np.log10(2.0),
                "symbol_rate_hz": symbol_rate_hz,
                "symbol_count": symbol_count,
                "normalized_doppler": (
                    float(row["doppler_shift_hz"]) / symbol_rate_hz
                ),
                "ber_uncompensated": snapshot.ber_uncompensated,
                "ber_compensated": snapshot.ber_compensated,
                "ber_theoretical_awgn": float(
                    theoretical_qpsk_ber_awgn(es_n0_db)
                ),
                "evm_uncompensated_percent": (
                    snapshot.evm_uncompensated_percent
                ),
                "evm_compensated_percent": (
                    snapshot.evm_compensated_percent
                ),
            }
        )
    return pd.DataFrame(records), event_snapshots


def _save_ber_evm(frame: pd.DataFrame, path: Path) -> None:
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(9.0, 7.2),
        sharex=True,
        constrained_layout=True,
    )
    time = frame["time_s"]
    axes[0].plot(
        time,
        frame["ber_uncompensated"],
        label="Without Doppler compensation",
        color="tab:red",
    )
    axes[0].plot(
        time,
        frame["ber_compensated"],
        label="Perfect Doppler compensation",
        color="tab:blue",
    )
    axes[0].plot(
        time,
        frame["ber_theoretical_awgn"],
        label="QPSK AWGN theory",
        color="0.3",
        linestyle="--",
    )
    axes[0].set(ylabel="Bit error rate", ylim=(-0.02, 0.55))
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    axes[1].plot(
        time,
        frame["evm_uncompensated_percent"],
        label="Without Doppler compensation",
        color="tab:red",
    )
    axes[1].plot(
        time,
        frame["evm_compensated_percent"],
        label="Perfect Doppler compensation",
        color="tab:blue",
    )
    axes[1].set(
        xlabel="Time from closest approach (s)",
        ylabel="RMS EVM (%)",
    )
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    figure.suptitle("QPSK performance over the selected SGP4 pass")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _save_constellation(
    snapshots: dict[str, QPSKSnapshot],
    path: Path,
) -> None:
    event = (
        "visibility_end"
        if "visibility_end" in snapshots
        else next(iter(snapshots))
    )
    snapshot = snapshots[event]
    limit = 2.0
    figure, axes = plt.subplots(
        1,
        2,
        figsize=(9.0, 4.5),
        constrained_layout=True,
    )
    for axis, samples, title in (
        (
            axes[0],
            snapshot.received_uncompensated[:800],
            "Without Doppler compensation",
        ),
        (
            axes[1],
            snapshot.received_compensated[:800],
            "Perfect Doppler compensation",
        ),
    ):
        axis.scatter(
            samples.real,
            samples.imag,
            s=9,
            alpha=0.45,
            color="tab:blue",
        )
        axis.axhline(0.0, color="0.7", linewidth=0.7)
        axis.axvline(0.0, color="0.7", linewidth=0.7)
        axis.set(
            xlim=(-limit, limit),
            ylim=(-limit, limit),
            xlabel="In-phase",
            ylabel="Quadrature",
            title=title,
            aspect="equal",
        )
        axis.grid(True, alpha=0.2)
    figure.suptitle(f"QPSK constellation at {event.replace('_', ' ')}")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def run_waveform_simulation(
    output_directory: Path,
    *,
    geometry_results_csv: Path = DEFAULT_GEOMETRY_RESULTS,
    geometry_summary_json: Path = DEFAULT_GEOMETRY_SUMMARY,
    symbol_count: int = 8_192,
    symbol_rate_hz: float = 1.0e6,
    snapshot_count: int = 81,
    seed: int = 52_285,
) -> WaveformArtifacts:
    """Generate deterministic QPSK link-performance artifacts."""
    if snapshot_count < 2:
        raise ValueError("snapshot_count must be at least 2")
    geometry_frame = pd.read_csv(geometry_results_csv)
    geometry_summary = json.loads(
        geometry_summary_json.read_text(encoding="utf-8")
    )
    selected = _selected_visible_rows(geometry_frame, snapshot_count)
    metrics, event_snapshots = _metrics_frame(
        selected,
        symbol_count=symbol_count,
        symbol_rate_hz=symbol_rate_hz,
        seed=seed,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = WaveformArtifacts(
        results_csv=output_directory / "results.csv",
        summary_json=output_directory / "summary.json",
        ber_evm_png=output_directory / "ber_evm.png",
        constellation_png=output_directory / "constellation.png",
    )
    metrics.to_csv(artifacts.results_csv, index=False)
    summary = {
        "model": "QPSK snapshot waveform over SGP4 downlink geometry",
        "source_geometry_results": str(geometry_results_csv),
        "source_object_name": geometry_summary.get("object_name"),
        "symbol_rate_hz": symbol_rate_hz,
        "symbol_count_per_snapshot": symbol_count,
        "snapshot_count": len(metrics),
        "random_seed": seed,
        "assumptions": [
            "unit-energy Gray-coded QPSK",
            "one complex sample per symbol after ideal matched filtering",
            "Es/N0 derived from C/N0 and the configured symbol rate",
            "locally constant Doppler within each snapshot",
            "complex white Gaussian receiver noise",
            "ideal timing synchronization and automatic gain control",
            "perfect Doppler knowledge in the compensated reference branch",
            "no coding, pulse shaping, multipath, fading, or oscillator error",
        ],
        "extrema": {
            "maximum_absolute_doppler_hz": float(
                metrics["doppler_shift_hz"].abs().max()
            ),
            "minimum_snr_db": float(metrics["snr_db"].min()),
            "maximum_snr_db": float(metrics["snr_db"].max()),
            "minimum_es_n0_db": float(metrics["es_n0_db"].min()),
            "maximum_es_n0_db": float(metrics["es_n0_db"].max()),
            "maximum_uncompensated_ber": float(
                metrics["ber_uncompensated"].max()
            ),
            "maximum_compensated_ber": float(
                metrics["ber_compensated"].max()
            ),
            "maximum_uncompensated_evm_percent": float(
                metrics["evm_uncompensated_percent"].max()
            ),
            "maximum_compensated_evm_percent": float(
                metrics["evm_compensated_percent"].max()
            ),
        },
    }
    artifacts.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _save_ber_evm(metrics, artifacts.ber_evm_png)
    _save_constellation(event_snapshots, artifacts.constellation_png)
    return artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--geometry-results",
        type=Path,
        default=DEFAULT_GEOMETRY_RESULTS,
    )
    parser.add_argument(
        "--geometry-summary",
        type=Path,
        default=DEFAULT_GEOMETRY_SUMMARY,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_WAVEFORM_OUTPUT)
    parser.add_argument("--symbol-count", type=int, default=8_192)
    parser.add_argument("--symbol-rate-msps", type=float, default=1.0)
    parser.add_argument("--snapshot-count", type=int, default=81)
    parser.add_argument("--seed", type=int, default=52_285)
    return parser


def main() -> None:
    """Run the QPSK waveform analysis CLI."""
    args = _parser().parse_args()
    artifacts = run_waveform_simulation(
        args.output,
        geometry_results_csv=args.geometry_results,
        geometry_summary_json=args.geometry_summary,
        symbol_count=args.symbol_count,
        symbol_rate_hz=args.symbol_rate_msps * 1e6,
        snapshot_count=args.snapshot_count,
        seed=args.seed,
    )
    print(f"Waveform artifacts written to: {args.output}")
    for path in asdict(artifacts).values():
        print(f"- {path}")


if __name__ == "__main__":
    main()
