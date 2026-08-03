from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from starlink_isl import load_research_baseline
from starlink_isl.research_config import TeamConfirmation
from starlink_isl.team_interface import (
    build_team_frequency_mapping,
    build_team_interface_manifest,
    write_team_interface_artifacts,
)


BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "ofdm_baseline.yaml"
)


@pytest.fixture
def baseline():
    return load_research_baseline(BASELINE_PATH)


def test_frozen_contract_has_no_pending_team_fields(baseline):
    assert baseline.scenario.status == "team_integration_v1"
    assert baseline.team_confirmation.required_before_final_integration is False
    assert baseline.team_confirmation.fields == ()


def test_frequency_mapping_matches_waveform_and_pilot_layout(baseline):
    mapping = build_team_frequency_mapping(baseline)

    assert mapping.shape == (223, 7)
    assert mapping["channel_column_index"].tolist() == list(range(223))
    assert mapping["signed_subcarrier_index"].iloc[0] == -112
    assert mapping["signed_subcarrier_index"].iloc[111] == -1
    assert mapping["signed_subcarrier_index"].iloc[112] == 1
    assert mapping["signed_subcarrier_index"].iloc[-1] == 111
    assert mapping["fftshift_bin_index"].iloc[0] == 16
    assert mapping["fftshift_bin_index"].iloc[-1] == 239
    assert int((mapping["role"] == "pilot").sum()) == 15
    assert int((mapping["role"] == "data").sum()) == 208
    assert mapping.loc[
        mapping["role"] == "pilot",
        "fftshift_bin_index",
    ].tolist() == list(baseline.pilot.fftshift_bin_indices)


def test_normalization_produces_unit_mean_time_domain_power(baseline):
    mapping = build_team_frequency_mapping(baseline)
    shifted = np.zeros(baseline.ofdm.fft_size, dtype=np.complex128)
    qpsk = np.exp(
        1j
        * (np.pi / 4.0 + np.arange(mapping.shape[0]) * np.pi / 2.0)
    )
    shifted[mapping["fftshift_bin_index"].to_numpy()] = qpsk
    waveform = np.fft.ifft(np.fft.ifftshift(shifted))
    waveform *= baseline.waveform_normalization.ifft_scale(baseline.ofdm)

    assert np.mean(np.abs(qpsk) ** 2) == pytest.approx(1.0)
    assert np.mean(np.abs(waveform) ** 2) == pytest.approx(1.0)


def test_manifest_freezes_tensor_units_signs_and_responsibilities(baseline):
    manifest = build_team_interface_manifest(baseline)

    assert manifest["interface_schema_version"] == 1
    assert manifest["status"] == "frozen_for_team_integration"
    assert manifest["channel_tensor"]["shape"] == [
        "ofdm_symbol_count",
        "active_subcarrier_count",
    ]
    assert manifest["channel_tensor"]["axis_order"] == ["time", "frequency"]
    exchange = manifest["channel_tensor"]["exchange_files"]
    assert exchange["canonical"] == "channel_grid.npz"
    assert exchange["portable"] == "channel_grid.csv"
    assert exchange["complex_encoding"] == ["h_real", "h_imag"]
    state_input = manifest["external_state_vector_input"]
    assert state_input["supported_coordinate_frames"] == ["TEME", "ECEF"]
    assert state_input["normalization_frame"] == "ECEF"
    assert manifest["time_axis"]["sample_location"] == "fft_window_center"
    assert manifest["si_state_fields"]["slant_range_m"]["unit"] == "m"
    assert (
        manifest["si_state_fields"]["radial_velocity_m_s"]["sign"]
        == "positive_when_range_increases"
    )
    assert manifest["pilot"]["pilot_subcarrier_count"] == 15
    assert manifest["pilot"]["data_subcarrier_count"] == 208
    assert manifest["responsibility_boundary"]["channel_team"]
    assert manifest["responsibility_boundary"]["ofdm_team"]


def test_artifact_writer_creates_json_and_csv(baseline, tmp_path):
    artifacts = write_team_interface_artifacts(tmp_path, baseline)

    assert artifacts.manifest_json.is_file()
    assert artifacts.frequency_mapping_csv.is_file()
    saved = pd.read_csv(artifacts.frequency_mapping_csv)
    assert saved.shape == (223, 7)


def test_manifest_rejects_pending_team_decisions(baseline):
    pending = replace(
        baseline,
        team_confirmation=TeamConfirmation(
            required_before_final_integration=True,
            fields=("ofdm.waveform_normalization",),
        ),
    )

    with pytest.raises(ValueError, match="pending fields"):
        build_team_interface_manifest(pending)
