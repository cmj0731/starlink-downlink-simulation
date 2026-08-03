"""Inspect and plot outputs produced by beamforming_demo.py.

Examples:
    python view_results.py
    python view_results.py --no-show
    python view_results.py --npz output/simulation_outputs.npz
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View Ku-band OFDM simulation results")
    parser.add_argument(
        "--npz",
        type=Path,
        default=Path("output") / "simulation_outputs.npz",
        help="simulation NPZ file (default: output/simulation_outputs.npz)",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("output") / "outputs_metadata.json",
        help="metadata JSON file (default: output/outputs_metadata.json)",
    )
    parser.add_argument(
        "--save",
        type=Path,
        default=Path("output") / "results_overview.png",
        help="plot output path (default: output/results_overview.png)",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="save the plot without opening a GUI window",
    )
    return parser.parse_args()


def print_metadata(metadata_path: Path) -> None:
    if not metadata_path.exists():
        print(f"Metadata not found; skipping: {metadata_path}")
        return

    with metadata_path.open("r", encoding="utf-8") as file:
        metadata = json.load(file)

    config = metadata.get("config", {})
    derived = metadata.get("derived", {})
    orbit = metadata.get("orbit", {})
    validation = orbit.get("direct_provider_validation", {})

    print("\n=== Simulation configuration ===")
    print(f"Carrier: {config.get('carrier_hz', float('nan')) / 1e9:.3f} GHz")
    print(f"FFT size: {config.get('fft_size', 'N/A')}")
    print(f"Active subcarriers: {config.get('active_subcarriers', 'N/A')}")
    print(f"CP: {config.get('cp_samples', 'N/A')} samples")
    print(f"Sample rate: {derived.get('sample_rate_hz', float('nan')) / 1e6:.3f} MHz")
    print(
        "OFDM symbol duration: "
        f"{derived.get('ofdm_symbol_duration_s', float('nan')) * 1e6:.3f} us"
    )
    print(f"Orbit source: {orbit.get('source', 'N/A')}")
    if validation:
        print(
            "Hermite maximum errors: "
            f"position={validation.get('max_position_error_m', float('nan')):.6g} m, "
            f"velocity={validation.get('max_velocity_error_mps', float('nan')):.6g} m/s"
        )


def require_arrays(data: np.lib.npyio.NpzFile, names: tuple[str, ...]) -> None:
    missing = [name for name in names if name not in data.files]
    if missing:
        raise KeyError(f"NPZ file is missing required arrays: {', '.join(missing)}")


def print_array_summary(data: np.lib.npyio.NpzFile) -> None:
    print("\n=== Arrays in NPZ ===")
    for name in data.files:
        array = data[name]
        print(f"{name:34s} shape={str(array.shape):16s} dtype={array.dtype}")


def print_result_summary(data: np.lib.npyio.NpzFile) -> None:
    radial_velocity = data["radial_velocity_mps"]
    doppler = data["doppler_hz"]
    ranges = data["range_m"]
    los = data["los_satellite_to_ue"]
    antenna = data["antenna_signals_baseband"]

    print("\n=== Main result ranges ===")
    print(f"Range: {ranges.min() / 1e3:.3f} .. {ranges.max() / 1e3:.3f} km")
    print(
        "Radial velocity: "
        f"{radial_velocity.min():.3f} .. {radial_velocity.max():.3f} m/s"
    )
    print(f"Doppler: {doppler.min():.3f} .. {doppler.max():.3f} Hz")
    print(f"Maximum LOS norm error: {np.max(np.abs(np.linalg.norm(los, axis=1) - 1.0)):.3e}")
    print(f"Antenna waveform shape: {antenna.shape}")


def make_plot(data: np.lib.npyio.NpzFile, save_path: Path) -> plt.Figure:
    time_s = data["channel_times_s"]
    ranges_km = data["range_m"] / 1e3
    radial_velocity = data["radial_velocity_mps"]
    doppler = data["doppler_hz"]
    antenna = data["antenna_signals_baseband"]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    axes[0, 0].plot(time_s, ranges_km)
    axes[0, 0].set_title("Satellite-to-UE range")
    axes[0, 0].set_xlabel("Simulation time (s)")
    axes[0, 0].set_ylabel("Range (km)")

    axes[0, 1].plot(time_s, radial_velocity)
    axes[0, 1].axhline(0.0, color="black", linewidth=0.8)
    axes[0, 1].set_title("Radial velocity (+ means receding)")
    axes[0, 1].set_xlabel("Simulation time (s)")
    axes[0, 1].set_ylabel("Radial velocity (m/s)")

    axes[1, 0].plot(time_s, doppler)
    axes[1, 0].axhline(0.0, color="black", linewidth=0.8)
    axes[1, 0].set_title("Ku-band Doppler shift")
    axes[1, 0].set_xlabel("Simulation time (s)")
    axes[1, 0].set_ylabel("Doppler (Hz)")

    display_samples = min(500, antenna.shape[1])
    sample_index = np.arange(display_samples)
    axes[1, 1].plot(sample_index, antenna[0, :display_samples].real, label="I (real)")
    axes[1, 1].plot(sample_index, antenna[0, :display_samples].imag, label="Q (imag)", alpha=0.8)
    axes[1, 1].set_title("Antenna 0 complex baseband")
    axes[1, 1].set_xlabel("Sample index")
    axes[1, 1].set_ylabel("Amplitude")
    axes[1, 1].legend()

    for axis in axes.flat:
        axis.grid(True, alpha=0.35)

    fig.suptitle("Ku-band OFDM Beamforming Results")
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    return fig


def main() -> None:
    args = parse_args()
    if not args.npz.exists():
        raise FileNotFoundError(
            f"Result file not found: {args.npz}\n"
            "Run 'python beamforming_demo.py' first."
        )

    print(f"Loading: {args.npz.resolve()}")
    print_metadata(args.metadata)

    required = (
        "channel_times_s",
        "range_m",
        "radial_velocity_mps",
        "doppler_hz",
        "los_satellite_to_ue",
        "antenna_signals_baseband",
    )
    with np.load(args.npz) as data:
        require_arrays(data, required)
        print_array_summary(data)
        print_result_summary(data)
        figure = make_plot(data, args.save)

    print(f"\nPlot saved: {args.save.resolve()}")
    if args.no_show:
        plt.close(figure)
    else:
        plt.show()


if __name__ == "__main__":
    main()
