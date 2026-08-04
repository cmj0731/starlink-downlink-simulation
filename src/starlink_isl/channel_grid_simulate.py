"""Generate and visualize a frame-sized STARLINK OFDM channel grid."""

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

from starlink_isl.channel_grid import (
    OFDMChannelGridAxes,
    build_ofdm_channel_grid_axes,
    build_ofdm_time_axis,
)
from starlink_isl.channel_io import (
    MAX_CHANNEL_CSV_CELLS,
    save_channel_grid_csv,
    validate_channel_csv_size,
)
from starlink_isl.ofdm_channel import (
    SISOChannelGrid,
    SynchronizedSISOChannelGrid,
    evaluate_siso_ofdm_channel_grid,
    save_siso_channel_grid_npz,
    save_synchronized_siso_channel_grid_npz,
    synchronize_siso_ofdm_channel_grid,
    synchronize_siso_ofdm_channel_grid_from_block_start,
)
from starlink_isl.research_config import (
    DEFAULT_BASELINE_PATH,
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.sgp4_orbit import GroundStation, satrec_from_omm
from starlink_isl.si_interface import DownlinkStateSI, sgp4_downlink_state_si
from starlink_isl.state_vector_io import (
    external_state_downlink_si,
    load_satellite_state_csv,
)
from starlink_isl.state_resampling import resample_downlink_state_si

DEFAULT_SOURCE_OMM_PATH = Path("outputs/sgp4_downlink/source_omm.json")
DEFAULT_GEOMETRY_SUMMARY_PATH = Path("outputs/sgp4_downlink/summary.json")
DEFAULT_CHANNEL_GRID_OUTPUT_DIRECTORY = Path("outputs/channel_grid")
REFERENCE_EVENT_KEYS = {
    "visibility_start": "start_utc",
    "maximum_elevation": "maximum_elevation_utc",
    "closest_approach": "closest_approach_utc",
    "visibility_end": "end_utc",
}


@dataclass(frozen=True, slots=True)
class ChannelGridArtifacts:
    """Paths produced by one frame-sized channel-grid simulation."""

    channel_grid_npz: Path
    channel_grid_csv: Path | None
    synchronized_channel_grid_npz: Path
    block_start_synchronized_channel_grid_npz: Path
    time_axis_csv: Path
    frequency_axis_csv: Path
    summary_json: Path
    heatmap_png: Path
    synchronization_comparison_png: Path
    slices_png: Path


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, np.integer),
    ):
        raise TypeError(f"{name} must be an integer")
    converted = int(value)
    if converted <= 0:
        raise ValueError(f"{name} must be positive")
    return converted


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc(parsed, "UTC timestamp")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _centred_frame_axes(
    config: ResearchBaselineConfig,
    symbol_count: int,
) -> OFDMChannelGridAxes:
    count = _positive_integer(symbol_count, "symbol_count")
    reference = config.channel_grid.symbol_time_reference
    one_symbol = build_ofdm_time_axis(
        config.ofdm,
        1,
        symbol_time_reference=reference,
    )
    frame_start_time_s = -(
        one_symbol.reference_offset_s
        + 0.5 * (count - 1) * config.ofdm.total_symbol_duration_s
    )
    return build_ofdm_channel_grid_axes(
        config.ofdm,
        config.radio.carrier_frequency_hz,
        count,
        frame_start_time_s=frame_start_time_s,
        symbol_time_reference=reference,
    )


def _anchor_offsets_s(
    axes: OFDMChannelGridAxes,
    source_step_s: float,
) -> np.ndarray:
    first = (
        np.floor(float(axes.time.time_s[0]) / source_step_s) * source_step_s
        - source_step_s
    )
    last = (
        np.ceil(float(axes.time.time_s[-1]) / source_step_s) * source_step_s
        + source_step_s
    )
    interval_count = int(np.rint((last - first) / source_step_s))
    return np.linspace(first, last, interval_count + 1, dtype=np.float64)


def _save_axes_csv(
    axes: OFDMChannelGridAxes,
    reference_utc: datetime,
    time_path: Path,
    frequency_path: Path,
) -> None:
    utc_values = [
        _iso(reference_utc + timedelta(seconds=float(offset)))
        for offset in axes.time.time_s
    ]
    pd.DataFrame(
        {
            "symbol_index": axes.time.symbol_indices,
            "symbol_start_time_s": axes.time.symbol_start_time_s,
            "channel_evaluation_time_s": axes.time.time_s,
            "channel_evaluation_utc": utc_values,
            "symbol_time_reference": axes.time.symbol_time_reference,
        }
    ).to_csv(time_path, index=False)
    pd.DataFrame(
        {
            "grid_column": np.arange(
                axes.frequency.subcarrier_count,
                dtype=np.int64,
            ),
            "signed_subcarrier_index": (
                axes.frequency.signed_subcarrier_indices
            ),
            "fft_bin_index": axes.frequency.fft_bin_indices,
            "fftshift_bin_index": axes.frequency.fftshift_bin_indices,
            "baseband_frequency_hz": axes.frequency.baseband_frequency_hz,
            "rf_frequency_hz": axes.frequency.rf_frequency_hz,
        }
    ).to_csv(frequency_path, index=False)


def _save_heatmap(grid: SISOChannelGrid, path: Path) -> None:
    frequency_mhz = grid.axes.frequency.baseband_frequency_hz / 1.0e6
    time_ms = grid.axes.time.time_s * 1.0e3
    magnitude_db = 20.0 * np.log10(np.abs(grid.channel_response))
    phase_rad = np.angle(grid.channel_response)
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(10.0, 7.4),
        sharex=True,
        constrained_layout=True,
    )
    magnitude_map = axes[0].pcolormesh(
        time_ms,
        frequency_mhz,
        magnitude_db.T,
        shading="nearest",
        cmap="viridis",
    )
    magnitude_colorbar = figure.colorbar(
        magnitude_map,
        ax=axes[0],
        label="20 log10 |H| (dB)",
    )
    magnitude_colorbar.formatter.set_useOffset(False)
    magnitude_colorbar.update_ticks()
    axes[0].set(
        ylabel="Baseband subcarrier frequency (MHz)",
        title="SISO OFDM channel magnitude",
    )
    phase_map = axes[1].pcolormesh(
        time_ms,
        frequency_mhz,
        phase_rad.T,
        shading="nearest",
        cmap="twilight",
        vmin=-np.pi,
        vmax=np.pi,
    )
    figure.colorbar(phase_map, ax=axes[1], label="Wrapped phase (rad)")
    axes[1].set(
        xlabel="Time from reference event (ms)",
        ylabel="Baseband subcarrier frequency (MHz)",
        title="SISO OFDM channel phase",
    )
    figure.suptitle(
        "Time-frequency view of H[m,k]: x=time, y=frequency"
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _save_synchronization_comparison(
    synchronized: SynchronizedSISOChannelGrid,
    block_start_synchronized: SynchronizedSISOChannelGrid,
    path: Path,
) -> None:
    """Plot raw, block-start, and perfect residual phase on shared axes."""

    raw_grid = synchronized.raw_grid
    if block_start_synchronized.raw_grid is not raw_grid:
        raise ValueError("synchronization results must share one raw grid")
    frequency_mhz = raw_grid.axes.frequency.baseband_frequency_hz / 1.0e6
    time_ms = raw_grid.axes.time.time_s * 1.0e3
    raw_phase_rad = np.angle(raw_grid.channel_response)
    block_start_phase_rad = np.angle(
        block_start_synchronized.channel_response
    )
    synchronized_phase_rad = np.angle(synchronized.channel_response)
    figure, axes = plt.subplots(
        3,
        1,
        figsize=(10.0, 9.4),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    raw_map = axes[0].pcolormesh(
        time_ms,
        frequency_mhz,
        raw_phase_rad.T,
        shading="nearest",
        cmap="twilight",
        vmin=-np.pi,
        vmax=np.pi,
    )
    axes[0].set(
        ylabel="Baseband subcarrier frequency (MHz)",
        title="Raw channel: absolute delay and full Doppler phase",
    )
    axes[1].pcolormesh(
        time_ms,
        frequency_mhz,
        block_start_phase_rad.T,
        shading="nearest",
        cmap="twilight",
        vmin=-np.pi,
        vmax=np.pi,
    )
    axes[1].set(
        ylabel="Baseband subcarrier frequency (MHz)",
        title=(
            "Block-start prediction: held delay and constant Doppler"
        ),
    )
    axes[2].pcolormesh(
        time_ms,
        frequency_mhz,
        synchronized_phase_rad.T,
        shading="nearest",
        cmap="twilight",
        vmin=-np.pi,
        vmax=np.pi,
    )
    axes[2].set(
        xlabel="Time from reference event (ms)",
        ylabel="Baseband subcarrier frequency (MHz)",
        title="Perfect same-state prediction: zero residual phase",
    )
    figure.colorbar(
        raw_map,
        ax=axes,
        label="Wrapped phase (rad)",
    )
    figure.suptitle(
        "Raw versus phase-synchronized SISO channel "
        "(block-start versus perfect prediction)"
    )
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _combined_legend(primary, secondary, *, location: str) -> None:
    handles_a, labels_a = primary.get_legend_handles_labels()
    handles_b, labels_b = secondary.get_legend_handles_labels()
    primary.legend(handles_a + handles_b, labels_a + labels_b, loc=location)


def _save_slices(grid: SISOChannelGrid, path: Path) -> None:
    frequency_mhz = grid.axes.frequency.baseband_frequency_hz / 1.0e6
    time_ms = grid.axes.time.time_s * 1.0e3
    magnitude_db = 20.0 * np.log10(np.abs(grid.channel_response))
    phase_rad = np.angle(grid.channel_response)
    symbol_index = int(np.argmin(np.abs(grid.axes.time.time_s)))
    subcarrier_index = int(
        np.argmin(np.abs(grid.axes.frequency.baseband_frequency_hz))
    )

    figure, axes = plt.subplots(
        2,
        1,
        figsize=(9.5, 7.2),
        constrained_layout=True,
    )
    frequency_phase_axis = axes[0].twinx()
    axes[0].plot(
        frequency_mhz,
        magnitude_db[symbol_index],
        color="tab:blue",
        label="Magnitude",
    )
    frequency_phase_axis.plot(
        frequency_mhz,
        phase_rad[symbol_index],
        color="tab:orange",
        linewidth=1.0,
        label="Wrapped phase",
    )
    axes[0].set(
        xlabel="Baseband subcarrier frequency (MHz)",
        ylabel="20 log10 |H| (dB)",
        title=(
            "Frequency slice at t="
            f"{grid.axes.time.time_s[symbol_index] * 1e3:.6f} ms"
        ),
    )
    axes[0].ticklabel_format(axis="y", style="plain", useOffset=False)
    frequency_phase_axis.set_ylabel("Wrapped phase (rad)")
    axes[0].grid(True, alpha=0.3)
    _combined_legend(axes[0], frequency_phase_axis, location="best")

    time_phase_axis = axes[1].twinx()
    magnitude_change_nanodb = 1.0e9 * (
        magnitude_db[:, subcarrier_index]
        - magnitude_db[symbol_index, subcarrier_index]
    )
    axes[1].plot(
        time_ms,
        magnitude_change_nanodb,
        color="tab:blue",
        label="Magnitude change",
    )
    time_phase_axis.plot(
        time_ms,
        phase_rad[:, subcarrier_index],
        color="tab:orange",
        linewidth=1.0,
        label="Wrapped phase",
    )
    signed_index = int(
        grid.axes.frequency.signed_subcarrier_indices[subcarrier_index]
    )
    axes[1].set(
        xlabel="Time from reference event (ms)",
        ylabel="Magnitude change from center (nanodB)",
        title=f"Time slice at signed subcarrier k={signed_index}",
    )
    time_phase_axis.set_ylabel("Wrapped phase (rad)")
    axes[1].grid(True, alpha=0.3)
    _combined_legend(axes[1], time_phase_axis, location="best")
    figure.suptitle("Selected frequency and time slices of H[m,k]")
    figure.savefig(path, dpi=170)
    plt.close(figure)


def _summary(
    grid: SISOChannelGrid,
    synchronized: SynchronizedSISOChannelGrid,
    block_start_synchronized: SynchronizedSISOChannelGrid,
    config: ResearchBaselineConfig,
    omm_record: Mapping[str, Any] | None,
    reference_utc: datetime,
    reference_event: str,
    anchor_offsets_s: np.ndarray,
    station: GroundStation,
    export_channel_csv: bool,
    source_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    magnitude_db = 20.0 * np.log10(np.abs(grid.channel_response))
    synchronized_magnitude_db = 20.0 * np.log10(
        np.abs(synchronized.channel_response)
    )
    block_start_magnitude_db = 20.0 * np.log10(
        np.abs(block_start_synchronized.channel_response)
    )
    metadata = dict(source_metadata or {})
    if omm_record is not None:
        object_name = str(omm_record["OBJECT_NAME"])
        norad_catalog_id: int | None = int(omm_record["NORAD_CAT_ID"])
        reference_model = "CelesTrak OMM / SGP4"
        source_coordinate_frame = "TEME"
    else:
        object_name = str(metadata.get("object_name") or "external_state")
        raw_norad = metadata.get("norad_catalog_id")
        norad_catalog_id = None if raw_norad is None else int(raw_norad)
        reference_model = str(
            metadata.get("reference_model") or "external state-vector CSV"
        )
        source_coordinate_frame = str(
            metadata.get("source_coordinate_frame") or "unknown"
        )
    anchor_step_s = (
        config.channel_state.geometry_source_step_s
        if omm_record is not None
        else float(np.median(np.diff(anchor_offsets_s)))
    )
    return {
        "model": "LOS SISO OFDM time-frequency channel grid",
        "object_name": object_name,
        "norad_catalog_id": norad_catalog_id,
        "reference_event": reference_event,
        "reference_utc": _iso(reference_utc),
        "station": {
            "latitude_deg": station.latitude_deg,
            "longitude_deg": station.longitude_deg,
            "altitude_m": station.altitude_m,
            "coordinate_definition": "WGS-84 geodetic",
        },
        "scenario_status": config.scenario.status,
        "represents_actual_starlink_waveform": (
            config.scenario.represents_actual_starlink_waveform
        ),
        "shape_convention": ["ofdm_symbol", "active_subcarrier"],
        "shape": list(grid.shape),
        "heatmap_axis_convention": {
            "x": "time_from_reference_event_ms",
            "y": "baseband_subcarrier_frequency_mhz",
            "displayed_values": "transpose of H[m,k] for visualization only",
        },
        "carrier_frequency_hz": grid.axes.frequency.carrier_frequency_hz,
        "subcarrier_spacing_hz": (
            grid.axes.frequency.subcarrier_spacing_hz
        ),
        "active_subcarrier_layout": config.ofdm.active_subcarrier_layout,
        "waveform_bin_order": config.channel_grid.waveform_bin_order,
        "symbol_time_reference": grid.axes.time.symbol_time_reference,
        "symbol_duration_s": grid.axes.time.total_symbol_duration_s,
        "time_range_s": [
            float(grid.axes.time.time_s[0]),
            float(grid.axes.time.time_s[-1]),
        ],
        "signed_subcarrier_index_range": [
            int(grid.axes.frequency.signed_subcarrier_indices[0]),
            int(grid.axes.frequency.signed_subcarrier_indices[-1]),
        ],
        "baseband_frequency_range_hz": [
            float(grid.axes.frequency.baseband_frequency_hz[0]),
            float(grid.axes.frequency.baseband_frequency_hz[-1]),
        ],
        "rf_frequency_range_hz": [
            float(grid.axes.frequency.rf_frequency_hz[0]),
            float(grid.axes.frequency.rf_frequency_hz[-1]),
        ],
        "slant_range_m": {
            "minimum": float(np.min(grid.slant_range_m)),
            "maximum": float(np.max(grid.slant_range_m)),
        },
        "propagation_delay_s": {
            "minimum": float(np.min(grid.propagation_delay_s)),
            "maximum": float(np.max(grid.propagation_delay_s)),
        },
        "doppler_shift_hz": {
            "minimum": float(np.min(grid.doppler_shift_hz)),
            "maximum": float(np.max(grid.doppler_shift_hz)),
        },
        "free_space_path_loss_db": {
            "minimum": float(np.min(grid.free_space_path_loss_db)),
            "maximum": float(np.max(grid.free_space_path_loss_db)),
        },
        "channel_magnitude_db": {
            "minimum": float(np.min(magnitude_db)),
            "maximum": float(np.max(magnitude_db)),
        },
        "other_losses_db": grid.other_losses_db,
        "channel_artifacts": {
            "channel_grid.npz": {
                "channel_variant": "raw",
                "delay_compensation": "none",
                "doppler_compensation": "none",
            },
            "channel_grid.csv": {
                "generated": export_channel_csv,
                "channel_variant": "raw",
                "delay_compensation": "none",
                "doppler_compensation": "none",
                "maximum_allowed_cells": MAX_CHANNEL_CSV_CELLS,
            },
            "synchronized_channel_grid.npz": {
                "channel_variant": "perfectly_compensated",
                "delay_compensation": synchronized.prediction_label,
                "doppler_compensation": synchronized.prediction_label,
            },
            "block_start_synchronized_channel_grid.npz": {
                "channel_variant": "block_start_compensated",
                "delay_compensation": block_start_synchronized.prediction_label,
                "doppler_compensation": block_start_synchronized.prediction_label,
            },
        },
        "phase_synchronization": {
            "prediction_label": synchronized.prediction_label,
            "removed_terms": [
                "predicted carrier Doppler phase",
                "predicted absolute propagation-delay phase",
            ],
            "retained_terms": [
                "free-space path amplitude",
                "other scalar losses",
                "residual delay and carrier-phase errors",
            ],
            "maximum_absolute_residual_delay_s": float(
                np.max(np.abs(synchronized.residual_propagation_delay_s))
            ),
            "maximum_absolute_residual_carrier_phase_rad": float(
                np.max(
                    np.abs(
                        synchronized.residual_carrier_doppler_phase_rad
                    )
                )
            ),
            "maximum_absolute_residual_total_phase_rad": float(
                np.max(np.abs(synchronized.residual_total_phase_rad))
            ),
            "maximum_magnitude_change_db": float(
                np.max(np.abs(synchronized_magnitude_db - magnitude_db))
            ),
            "formula": (
                "H_sync=a exp(j(phi_D-phi_D_pred)) "
                "exp(-j 2 pi f_k (tau-tau_pred))"
            ),
            "scope": (
                "channel-side phase removal; not an OFDM receiver estimator"
            ),
        },
        "block_start_phase_synchronization": {
            "prediction_label": block_start_synchronized.prediction_label,
            "block_start_time_s": float(grid.axes.time.time_s[0]),
            "block_start_delay_s": float(grid.propagation_delay_s[0]),
            "block_start_doppler_shift_hz": float(grid.doppler_shift_hz[0]),
            "prediction": {
                "propagation_delay": "held at the block-start value",
                "carrier_phase": (
                    "block-start phase plus constant block-start Doppler"
                ),
            },
            "maximum_absolute_residual_delay_s": float(
                np.max(
                    np.abs(
                        block_start_synchronized.residual_propagation_delay_s
                    )
                )
            ),
            "maximum_absolute_residual_cfo_hz": float(
                np.max(
                    np.abs(
                        grid.doppler_shift_hz - grid.doppler_shift_hz[0]
                    )
                )
            ),
            "maximum_absolute_residual_carrier_phase_rad": float(
                np.max(
                    np.abs(
                        block_start_synchronized.residual_carrier_doppler_phase_rad
                    )
                )
            ),
            "maximum_absolute_residual_total_phase_rad": float(
                np.max(
                    np.abs(block_start_synchronized.residual_total_phase_rad)
                )
            ),
            "maximum_magnitude_change_db": float(
                np.max(np.abs(block_start_magnitude_db - magnitude_db))
            ),
            "scope": (
                "one exact state update at block start; no later truth updates"
            ),
        },
        "orbit_state": {
            "reference_model": reference_model,
            "source_coordinate_frame": source_coordinate_frame,
            "channel_coordinate_frame": "ECEF",
            "source_file": metadata.get("source_file"),
            "anchor_step_s": anchor_step_s,
            "anchor_time_range_s": [
                float(anchor_offsets_s[0]),
                float(anchor_offsets_s[-1]),
            ],
            "interpolation": config.channel_state.resampling_method,
            "position_velocity_consistency": metadata.get(
                "position_velocity_consistency"
            ),
            "physical_validation": metadata.get("physical_validation"),
        },
        "channel_formula": (
            "H[m,k]=a[m,k] exp(j phi_D[m]) "
            "exp(-j 2 pi f_k tau[m])"
        ),
        "phase_convention": {
            "carrier_phase": (
                "relative to the slant range at the reference event"
            ),
            "subcarrier_delay_phase": "uses absolute propagation delay",
            "constant_carrier_phase_at_reference": "omitted",
        },
        "scope_limitations": [
            "one channel sample per OFDM symbol",
            "within-symbol Doppler and ICI are not represented by H[m,k]",
            "absolute delay is a frequency-domain phase, not a sample shift",
            "no multipath, antenna gain, beamforming, or AWGN",
        ],
    }


def run_channel_grid_simulation(
    output_directory: Path,
    *,
    config: ResearchBaselineConfig,
    omm_record: Mapping[str, Any] | None = None,
    reference_utc: datetime,
    station: GroundStation,
    minimum_elevation_deg: float = 10.0,
    symbol_count: int = 256,
    other_losses_db: float = 0.0,
    reference_event: str = "closest_approach",
    source_state: DownlinkStateSI | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    export_channel_csv: bool = True,
) -> ChannelGridArtifacts:
    """Generate a small physical channel grid centred on a pass event."""

    reference = _utc(reference_utc, "reference_utc")
    if reference_event not in REFERENCE_EVENT_KEYS:
        raise ValueError("reference_event is not supported")
    if not np.isfinite(minimum_elevation_deg) or not (
        -90.0 <= minimum_elevation_deg <= 90.0
    ):
        raise ValueError("minimum_elevation_deg must be in [-90, 90]")
    if export_channel_csv:
        validate_channel_csv_size(
            symbol_count,
            config.ofdm.active_subcarrier_count,
        )

    if source_state is not None and omm_record is not None:
        raise ValueError("provide either omm_record or source_state, not both")
    axes = _centred_frame_axes(config, symbol_count)
    if source_state is None:
        if omm_record is None:
            raise ValueError("omm_record or source_state is required")
        anchor_offsets_s = _anchor_offsets_s(
            axes,
            config.channel_state.geometry_source_step_s,
        )
        anchor_datetimes = [
            reference + timedelta(seconds=float(offset))
            for offset in anchor_offsets_s
        ]
        satellite = satrec_from_omm(dict(omm_record))
        source_state = sgp4_downlink_state_si(
            anchor_datetimes,
            satellite,
            config.radio.carrier_frequency_hz,
            station,
            minimum_elevation_rad=np.deg2rad(minimum_elevation_deg),
            time_origin_utc=reference,
            phase_reference_utc=reference,
        )
    else:
        if source_state.coordinate_frame != "ECEF":
            raise ValueError("external source_state must be normalized to ECEF")
        anchor_offsets_s = np.asarray(source_state.time_s, dtype=np.float64)
    symbol_state = resample_downlink_state_si(
        source_state,
        axes.time.time_s,
        config.radio.carrier_frequency_hz,
        minimum_elevation_rad=np.deg2rad(minimum_elevation_deg),
    )
    grid = evaluate_siso_ofdm_channel_grid(
        symbol_state,
        axes,
        other_losses_db=other_losses_db,
    )
    synchronized = synchronize_siso_ofdm_channel_grid(
        grid,
        grid.propagation_delay_s,
        grid.carrier_doppler_phase_rad,
        prediction_label="perfect_same_state_prediction",
    )
    block_start_synchronized = (
        synchronize_siso_ofdm_channel_grid_from_block_start(grid)
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = ChannelGridArtifacts(
        channel_grid_npz=output_directory / "channel_grid.npz",
        channel_grid_csv=(
            output_directory / "channel_grid.csv"
            if export_channel_csv
            else None
        ),
        synchronized_channel_grid_npz=(
            output_directory / "synchronized_channel_grid.npz"
        ),
        block_start_synchronized_channel_grid_npz=(
            output_directory / "block_start_synchronized_channel_grid.npz"
        ),
        time_axis_csv=output_directory / "time_axis.csv",
        frequency_axis_csv=output_directory / "frequency_axis.csv",
        summary_json=output_directory / "summary.json",
        heatmap_png=output_directory / "channel_grid_heatmap.png",
        synchronization_comparison_png=(
            output_directory / "synchronization_comparison.png"
        ),
        slices_png=output_directory / "channel_grid_slices.png",
    )
    save_siso_channel_grid_npz(grid, artifacts.channel_grid_npz)
    if artifacts.channel_grid_csv is not None:
        save_channel_grid_csv(
            grid,
            artifacts.channel_grid_csv,
            reference_utc=reference,
        )
    save_synchronized_siso_channel_grid_npz(
        synchronized,
        artifacts.synchronized_channel_grid_npz,
        channel_variant="perfectly_compensated",
    )
    save_synchronized_siso_channel_grid_npz(
        block_start_synchronized,
        artifacts.block_start_synchronized_channel_grid_npz,
        channel_variant="block_start_compensated",
    )
    _save_axes_csv(
        axes,
        reference,
        artifacts.time_axis_csv,
        artifacts.frequency_axis_csv,
    )
    artifacts.summary_json.write_text(
        json.dumps(
            _summary(
                grid,
                synchronized,
                block_start_synchronized,
                config,
                omm_record,
                reference,
                reference_event,
                anchor_offsets_s,
                station,
                export_channel_csv,
                source_metadata,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _save_heatmap(grid, artifacts.heatmap_png)
    _save_synchronization_comparison(
        synchronized,
        block_start_synchronized,
        artifacts.synchronization_comparison_png,
    )
    _save_slices(grid, artifacts.slices_png)
    return artifacts


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """CLI entry point using the existing SGP4 pass artifacts."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument(
        "--source-omm",
        type=Path,
        default=DEFAULT_SOURCE_OMM_PATH,
    )
    parser.add_argument(
        "--state-csv",
        type=Path,
        help=(
            "external TEME/ECEF state-vector CSV; when supplied, OMM/SGP4 "
            "propagation is bypassed"
        ),
    )
    parser.add_argument(
        "--geometry-summary",
        type=Path,
        default=DEFAULT_GEOMETRY_SUMMARY_PATH,
    )
    parser.add_argument(
        "--reference-utc",
        help=(
            "explicit channel-grid centre UTC; permits --state-csv without "
            "an existing geometry summary"
        ),
    )
    parser.add_argument("--station-latitude-deg", type=float)
    parser.add_argument("--station-longitude-deg", type=float)
    parser.add_argument("--station-altitude-m", type=float)
    parser.add_argument("--minimum-elevation-deg", type=float)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CHANNEL_GRID_OUTPUT_DIRECTORY,
    )
    parser.add_argument("--symbol-count", type=int, default=256)
    parser.add_argument("--other-losses-db", type=float, default=0.0)
    parser.add_argument(
        "--no-channel-csv",
        action="store_true",
        help="skip the portable long-format H[m,k] CSV export",
    )
    parser.add_argument(
        "--reference-event",
        choices=tuple(REFERENCE_EVENT_KEYS),
        default="closest_approach",
    )
    args = parser.parse_args()

    config = load_research_baseline(args.config)
    geometry_summary = (
        _load_json(args.geometry_summary)
        if args.geometry_summary.is_file()
        else None
    )
    if args.reference_utc is not None:
        reference_utc = _parse_utc(args.reference_utc)
    elif geometry_summary is not None:
        selected_pass = geometry_summary["selected_pass"]
        reference_utc = _parse_utc(
            selected_pass[REFERENCE_EVENT_KEYS[args.reference_event]]
        )
    else:
        raise ValueError(
            "--reference-utc is required when geometry summary is unavailable"
        )
    station_values = (
        geometry_summary.get("station", {})
        if geometry_summary is not None
        else {}
    )
    if args.state_csv is not None:
        required_station_arguments = {
            "--station-latitude-deg": args.station_latitude_deg,
            "--station-longitude-deg": args.station_longitude_deg,
            "--station-altitude-m": args.station_altitude_m,
        }
        missing_station_arguments = [
            name
            for name, value in required_station_arguments.items()
            if value is None
        ]
        if missing_station_arguments:
            raise ValueError(
                "--state-csv requires explicit ground-station coordinates: "
                + ", ".join(missing_station_arguments)
            )
        station = GroundStation(
            latitude_deg=float(args.station_latitude_deg),
            longitude_deg=float(args.station_longitude_deg),
            altitude_m=float(args.station_altitude_m),
        )
    else:
        station = GroundStation(
            latitude_deg=(
                args.station_latitude_deg
                if args.station_latitude_deg is not None
                else float(station_values.get("latitude_deg", 37.2934))
            ),
            longitude_deg=(
                args.station_longitude_deg
                if args.station_longitude_deg is not None
                else float(station_values.get("longitude_deg", 126.9747))
            ),
            altitude_m=(
                args.station_altitude_m
                if args.station_altitude_m is not None
                else float(station_values.get("altitude_m", 0.0))
            ),
        )
    minimum_elevation_deg = (
        args.minimum_elevation_deg
        if args.minimum_elevation_deg is not None
        else float(
            geometry_summary.get("minimum_elevation_deg", 10.0)
            if geometry_summary is not None
            else 10.0
        )
    )
    omm_record = None
    source_state = None
    source_metadata = None
    if args.state_csv is not None:
        external = load_satellite_state_csv(args.state_csv)
        source_state = external_state_downlink_si(
            external,
            reference_utc,
            config.radio.carrier_frequency_hz,
            station,
            minimum_elevation_deg=minimum_elevation_deg,
        )
        source_metadata = {
            "reference_model": "external state-vector CSV",
            "source_coordinate_frame": external.source_coordinate_frame,
            "object_name": external.object_name,
            "norad_catalog_id": external.norad_catalog_id,
            "source_file": str(args.state_csv),
            "position_velocity_consistency": (
                external.position_velocity_consistency.as_metadata()
            ),
            "physical_validation": external.physical_validation.as_metadata(),
        }
    else:
        if geometry_summary is None:
            raise ValueError(
                "geometry summary is required when using an OMM source"
            )
        omm_data = _load_json(args.source_omm)
        if not isinstance(omm_data, list) or not omm_data:
            raise ValueError("source OMM JSON must be a non-empty list")
        norad_id = int(geometry_summary["norad_catalog_id"])
        matching_records = [
            record
            for record in omm_data
            if int(record["NORAD_CAT_ID"]) == norad_id
        ]
        if len(matching_records) != 1:
            raise ValueError(
                "source OMM must contain exactly one matching NORAD ID"
            )
        omm_record = matching_records[0]
    artifacts = run_channel_grid_simulation(
        args.output,
        config=config,
        omm_record=omm_record,
        reference_utc=reference_utc,
        station=station,
        minimum_elevation_deg=minimum_elevation_deg,
        symbol_count=args.symbol_count,
        other_losses_db=args.other_losses_db,
        reference_event=args.reference_event,
        source_state=source_state,
        source_metadata=source_metadata,
        export_channel_csv=not args.no_channel_csv,
    )
    print(
        json.dumps(
            {
                name: None if path is None else str(path)
                for name, path in asdict(artifacts).items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
