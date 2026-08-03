"""Machine-readable v1 contract for team OFDM/channel integration."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from starlink_isl.channel_io import CHANNEL_CSV_SCHEMA_VERSION
from starlink_isl.channel_grid import build_ofdm_frequency_axis
from starlink_isl.research_config import (
    DEFAULT_BASELINE_PATH,
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.state_vector_io import STATE_VECTOR_CSV_SCHEMA_VERSION

TEAM_INTERFACE_SCHEMA_VERSION = 1
TEAM_INTERFACE_STATUS = "team_integration_v1"
DEFAULT_TEAM_INTERFACE_OUTPUT_DIRECTORY = Path("outputs/team_interface")


@dataclass(frozen=True, slots=True)
class TeamInterfaceArtifacts:
    """Files that define the shared channel-grid boundary."""

    manifest_json: Path
    frequency_mapping_csv: Path


def _validate_frozen_contract(config: ResearchBaselineConfig) -> None:
    if config.scenario.status != TEAM_INTERFACE_STATUS:
        raise ValueError(
            f"scenario.status must be {TEAM_INTERFACE_STATUS}"
        )
    if config.team_confirmation.required_before_final_integration or (
        config.team_confirmation.fields
    ):
        raise ValueError("team integration contract still has pending fields")


def build_team_frequency_mapping(
    config: ResearchBaselineConfig,
) -> pd.DataFrame:
    """Map each active channel column to FFT bins and pilot/data roles."""

    _validate_frozen_contract(config)
    axis = build_ofdm_frequency_axis(
        config.ofdm,
        config.radio.carrier_frequency_hz,
    )
    pilot_bins = np.asarray(
        config.pilot.fftshift_bin_indices,
        dtype=np.int64,
    )
    pilot_mask = np.isin(axis.fftshift_bin_indices, pilot_bins)
    if int(np.count_nonzero(pilot_mask)) != config.pilot.pilot_subcarrier_count:
        raise ValueError("pilot bins do not map one-to-one onto channel columns")
    return pd.DataFrame(
        {
            "channel_column_index": np.arange(
                axis.subcarrier_count,
                dtype=np.int64,
            ),
            "role": np.where(pilot_mask, "pilot", "data"),
            "signed_subcarrier_index": axis.signed_subcarrier_indices,
            "fft_bin_index": axis.fft_bin_indices,
            "fftshift_bin_index": axis.fftshift_bin_indices,
            "baseband_frequency_hz": axis.baseband_frequency_hz,
            "rf_frequency_hz": axis.rf_frequency_hz,
        }
    )


def build_team_interface_manifest(
    config: ResearchBaselineConfig,
) -> dict[str, Any]:
    """Return the complete v1 integration contract as JSON-ready data."""

    mapping = build_team_frequency_mapping(config)
    pilot_columns = mapping.loc[
        mapping["role"] == "pilot",
        "channel_column_index",
    ].astype(int)
    data_columns = mapping.loc[
        mapping["role"] == "data",
        "channel_column_index",
    ].astype(int)
    normalization = config.waveform_normalization
    return {
        "interface_schema_version": TEAM_INTERFACE_SCHEMA_VERSION,
        "contract_name": "starlink_isl_siso_ofdm_channel_v1",
        "status": "frozen_for_team_integration",
        "claim_boundary": (
            "research baseline; not a claim about the proprietary Starlink "
            "waveform"
        ),
        "ofdm": {
            "carrier_frequency_hz": config.radio.carrier_frequency_hz,
            "fft_size": config.ofdm.fft_size,
            "subcarrier_spacing_hz": config.ofdm.subcarrier_spacing_hz,
            "sample_rate_hz": config.ofdm.sample_rate_hz,
            "sample_period_s": config.ofdm.sample_period_s,
            "active_subcarrier_count": config.ofdm.active_subcarrier_count,
            "cyclic_prefix_samples": config.ofdm.cyclic_prefix_samples,
            "total_symbol_duration_s": (
                config.ofdm.total_symbol_duration_s
            ),
            "modulation": config.ofdm.modulation,
            "dc_subcarrier_null": config.ofdm.dc_subcarrier_null,
            "active_subcarrier_layout": (
                config.ofdm.active_subcarrier_layout
            ),
        },
        "waveform_normalization": {
            "data_symbol_average_energy": (
                normalization.data_symbol_average_energy
            ),
            "pilot_symbol_magnitude": normalization.pilot_symbol_magnitude,
            "ifft_convention": normalization.ifft_convention,
            "time_domain_scale": normalization.time_domain_scale,
            "time_domain_scale_value": normalization.ifft_scale(config.ofdm),
            "channel_input_average_power": (
                normalization.channel_input_average_power
            ),
            "formula": (
                "x_time=(NFFT/sqrt(K_active))*"
                "ifft(ifftshift(X_fftshift))"
            ),
            "physical_power_rule": (
                "the channel multiplies the unit-average-power complex "
                "envelope by sqrt(transmit_power_w)"
            ),
        },
        "channel_tensor": {
            "field_name": "channel_response",
            "symbol": "H[m,k]",
            "dtype": "complex128",
            "shape": ["ofdm_symbol_count", "active_subcarrier_count"],
            "axis_order": ["time", "frequency"],
            "channel_column_order": (
                "strictly increasing signed subcarrier index"
            ),
            "frequency_mapping_file": "frequency_mapping.csv",
            "input_output_relation": "Y_active[m,k]=H[m,k]*X_active[m,k]",
            "coefficient_unit": "dimensionless complex voltage ratio",
            "inactive_subcarrier_policy": (
                "guard and null-DC bins are omitted, not physical zero-gain "
                "channel samples"
            ),
            "raw_variant": (
                "includes FSPL, carrier Doppler phase, and delay phase slope"
            ),
            "synchronized_variant": (
                "retains FSPL and residual truth-minus-prediction phase"
            ),
            "exchange_files": {
                "canonical": "channel_grid.npz",
                "portable": "channel_grid.csv",
                "portable_schema_version": CHANNEL_CSV_SCHEMA_VERSION,
                "portable_layout": "time-major long format",
                "complex_encoding": ["h_real", "h_imag"],
            },
        },
        "external_state_vector_input": {
            "schema_version": STATE_VECTOR_CSV_SCHEMA_VERSION,
            "time_column": "utc",
            "time_rule": "timezone-aware, strictly increasing, unique",
            "coordinate_frame_column": "coordinate_frame",
            "supported_coordinate_frames": ["TEME", "ECEF"],
            "position_columns_m": [
                "satellite_x_m",
                "satellite_y_m",
                "satellite_z_m",
            ],
            "velocity_columns_m_s": [
                "satellite_vx_m_s",
                "satellite_vy_m_s",
                "satellite_vz_m_s",
            ],
            "normalization_frame": "ECEF",
            "teme_velocity_transform": "v_ecef=R*v_teme-omega_E_cross_r_ecef",
        },
        "time_axis": {
            "unit": "s",
            "origin": "frame-relative simulation time",
            "sample_location": config.channel_grid.symbol_time_reference,
            "sample_interval_s": config.ofdm.total_symbol_duration_s,
            "state_source_step_s": (
                config.channel_state.geometry_source_step_s
            ),
            "state_update_interval_s": (
                config.channel_state.update_interval_s
            ),
            "state_resampling": config.channel_state.resampling_method,
        },
        "frequency_axis": {
            "active_order": "frequency_ascending",
            "signed_index_formula": "f_baseband[k]=k*subcarrier_spacing_hz",
            "rf_formula": "f_rf[k]=carrier_frequency_hz+f_baseband[k]",
            "waveform_bin_order": config.channel_grid.waveform_bin_order,
            "first_signed_index": int(
                mapping["signed_subcarrier_index"].iloc[0]
            ),
            "last_signed_index": int(
                mapping["signed_subcarrier_index"].iloc[-1]
            ),
        },
        "pilot": {
            "placement": config.pilot.placement,
            "spacing_active_subcarriers": (
                config.pilot.spacing_active_subcarriers
            ),
            "pilot_subcarrier_count": config.pilot.pilot_subcarrier_count,
            "data_subcarrier_count": int(data_columns.size),
            "fftshift_bin_indices": list(
                config.pilot.fftshift_bin_indices
            ),
            "channel_column_indices": pilot_columns.tolist(),
            "data_channel_column_indices": data_columns.tolist(),
        },
        "si_state_fields": {
            "time_s": {"unit": "s", "shape": ["sample"]},
            "satellite_position_m": {
                "unit": "m",
                "shape": ["sample", 3],
            },
            "satellite_velocity_m_s": {
                "unit": "m/s",
                "shape": ["sample", 3],
            },
            "ue_position_m": {"unit": "m", "shape": ["sample", 3]},
            "ue_velocity_m_s": {
                "unit": "m/s",
                "shape": ["sample", 3],
            },
            "los_satellite_to_ue_unit": {
                "unit": "1",
                "shape": ["sample", 3],
                "direction": "satellite_to_ue",
            },
            "slant_range_m": {"unit": "m", "shape": ["sample"]},
            "radial_velocity_m_s": {
                "unit": "m/s",
                "shape": ["sample"],
                "sign": "positive_when_range_increases",
            },
            "propagation_delay_s": {
                "unit": "s",
                "shape": ["sample"],
            },
            "doppler_shift_hz": {
                "unit": "Hz",
                "shape": ["sample"],
                "formula": "-radial_velocity_m_s*carrier_frequency_hz/c",
            },
            "doppler_phase_rad": {
                "unit": "rad",
                "shape": ["sample"],
            },
        },
        "phase_and_error_signs": {
            "raw_channel": (
                "H=a*exp(+j*phi_D)*exp(-j*2*pi*f_baseband*tau)"
            ),
            "prediction_bias": "prediction_minus_truth_at_block_start",
            "synchronization_residual": "truth_minus_prediction",
            "normalized_cfo": "residual_cfo_hz/subcarrier_spacing_hz",
        },
        "responsibility_boundary": {
            "channel_team": [
                "H[m,k] and its time/frequency coordinates",
                "range, delay, radial velocity, Doppler, and path gain",
                "raw and explicitly labelled synchronized channel variants",
            ],
            "ofdm_team": [
                "bit mapping, QPSK symbols, pilots, FFT/IFFT, and decisions",
                "selecting matching fftshift bins from frequency_mapping.csv",
                "BER, EVM, ICI, and pilot-estimator evaluation",
            ],
            "excluded_until_later": [
                "beamforming or antenna-array dimensions",
                "multipath taps",
                "actual proprietary Starlink waveform claims",
            ],
        },
    }


def write_team_interface_artifacts(
    output_directory: str | Path,
    config: ResearchBaselineConfig,
) -> TeamInterfaceArtifacts:
    """Write the v1 manifest and the 223-column frequency mapping."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = TeamInterfaceArtifacts(
        manifest_json=output / "interface_manifest.json",
        frequency_mapping_csv=output / "frequency_mapping.csv",
    )
    manifest = build_team_interface_manifest(config)
    artifacts.manifest_json.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    build_team_frequency_mapping(config).to_csv(
        artifacts.frequency_mapping_csv,
        index=False,
    )
    return artifacts


def main() -> None:
    """Validate and export the frozen team integration contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TEAM_INTERFACE_OUTPUT_DIRECTORY,
    )
    args = parser.parse_args()
    config = load_research_baseline(args.config)
    artifacts = write_team_interface_artifacts(args.output, config)
    print(json.dumps(asdict(artifacts), default=str, indent=2))


if __name__ == "__main__":
    main()
