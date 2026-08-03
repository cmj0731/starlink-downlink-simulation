from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from starlink_isl import (
    build_ofdm_channel_grid_axes,
    evaluate_siso_ofdm_channel_grid,
    ideal_downlink_state_si,
    load_research_baseline,
    save_siso_channel_grid_npz,
)
from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S


BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "ofdm_baseline.yaml"
)
SPEED_OF_LIGHT_M_S = 1_000.0 * SPEED_OF_LIGHT_KM_S


@pytest.fixture
def baseline():
    return load_research_baseline(BASELINE_PATH)


def _ideal_grid(baseline, *, symbol_count=8, other_losses_db=0.0):
    axes = build_ofdm_channel_grid_axes(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
        symbol_count,
        symbol_time_reference=baseline.channel_grid.symbol_time_reference,
    )
    state = ideal_downlink_state_si(
        axes.time.time_s,
        baseline.radio.carrier_frequency_hz,
        phase_reference_time_s=0.0,
    )
    return evaluate_siso_ofdm_channel_grid(
        state,
        axes,
        other_losses_db=other_losses_db,
    )


def test_siso_grid_has_expected_shape_and_finite_complex_values(baseline):
    grid = _ideal_grid(baseline)

    assert grid.shape == (8, 223)
    assert grid.channel_response.shape == grid.shape
    assert grid.free_space_path_loss_db.shape == grid.shape
    assert np.all(np.isfinite(grid.channel_response.real))
    assert np.all(np.isfinite(grid.channel_response.imag))
    assert grid.channel_response.flags.writeable is False


def test_grid_magnitude_matches_frequency_dependent_free_space_loss(baseline):
    other_losses_db = 2.0
    grid = _ideal_grid(baseline, other_losses_db=other_losses_db)
    row = 3
    column = 25
    distance_m = grid.slant_range_m[row]
    frequency_hz = grid.axes.frequency.rf_frequency_hz[column]
    expected_fspl_db = 20.0 * np.log10(
        4.0 * np.pi * distance_m * frequency_hz / SPEED_OF_LIGHT_M_S
    )
    expected_gain = 10.0 ** (
        -(expected_fspl_db + other_losses_db) / 20.0
    )

    assert grid.free_space_path_loss_db[row, column] == pytest.approx(
        expected_fspl_db
    )
    assert abs(grid.channel_response[row, column]) == pytest.approx(
        expected_gain
    )


def test_adjacent_subcarrier_ratio_has_delay_phase_slope(baseline):
    grid = _ideal_grid(baseline)
    row = 4
    left = 20
    right = 21
    frequency_difference_hz = (
        grid.axes.frequency.baseband_frequency_hz[right]
        - grid.axes.frequency.baseband_frequency_hz[left]
    )
    measured_ratio = (
        grid.channel_response[row, right]
        / grid.path_amplitude_gain[row, right]
        * grid.path_amplitude_gain[row, left]
        / grid.channel_response[row, left]
    )
    expected_ratio = np.exp(
        -1j
        * 2.0
        * np.pi
        * frequency_difference_hz
        * grid.propagation_delay_s[row]
    )

    assert measured_ratio == pytest.approx(expected_ratio, abs=1.0e-11)


def test_dc_channel_phase_matches_carrier_doppler_phase(baseline):
    dc_numerology = replace(
        baseline.ofdm,
        active_subcarrier_count=1,
        dc_subcarrier_null=False,
        active_subcarrier_layout="centered_dc_active_provisional",
    )
    axes = build_ofdm_channel_grid_axes(
        dc_numerology,
        baseline.radio.carrier_frequency_hz,
        4,
    )
    state = ideal_downlink_state_si(
        axes.time.time_s,
        baseline.radio.carrier_frequency_hz,
    )
    grid = evaluate_siso_ofdm_channel_grid(state, axes)

    normalized = grid.channel_response[:, 0] / grid.path_amplitude_gain[:, 0]
    assert normalized == pytest.approx(
        np.exp(1j * state.doppler_phase_rad),
        abs=1.0e-12,
    )


def test_grid_rejects_state_with_different_times(baseline):
    axes = build_ofdm_channel_grid_axes(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
        4,
    )
    state = ideal_downlink_state_si(
        axes.time.time_s + 1.0e-3,
        baseline.radio.carrier_frequency_hz,
    )

    with pytest.raises(ValueError, match="evaluation times"):
        evaluate_siso_ofdm_channel_grid(state, axes)


def test_grid_rejects_carrier_inconsistent_with_state_doppler(baseline):
    axes = build_ofdm_channel_grid_axes(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
        4,
    )
    state = ideal_downlink_state_si(
        axes.time.time_s,
        10.0e9,
    )

    with pytest.raises(ValueError, match="carrier frequency"):
        evaluate_siso_ofdm_channel_grid(state, axes)


def test_grid_npz_contains_complex_response_and_coordinates(baseline, tmp_path):
    grid = _ideal_grid(baseline, symbol_count=3)
    path = save_siso_channel_grid_npz(grid, tmp_path / "channel_grid.npz")

    with np.load(path, allow_pickle=False) as saved:
        assert saved["channel_response"].shape == (3, 223)
        assert np.iscomplexobj(saved["channel_response"])
        assert np.array_equal(saved["time_s"], grid.axes.time.time_s)
        assert np.array_equal(
            saved["signed_subcarrier_indices"],
            grid.axes.frequency.signed_subcarrier_indices,
        )
        assert np.array_equal(
            saved["fftshift_bin_indices"],
            grid.axes.frequency.fftshift_bin_indices,
        )
        assert saved["model"].item().startswith("LOS SISO")
