from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from starlink_isl import (
    build_ofdm_channel_grid_axes,
    evaluate_siso_ofdm_channel_grid,
    ideal_downlink_state_si,
    load_research_baseline,
    predict_block_start_delay_and_doppler_phase,
    save_siso_channel_grid_npz,
    save_synchronized_siso_channel_grid_npz,
    synchronize_siso_ofdm_channel_grid,
    synchronize_siso_ofdm_channel_grid_from_block_start,
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


def test_perfect_phase_synchronization_retains_only_path_gain(baseline):
    grid = _ideal_grid(baseline)
    synchronized = synchronize_siso_ofdm_channel_grid(
        grid,
        grid.propagation_delay_s,
        grid.carrier_doppler_phase_rad,
        prediction_label="perfect_truth_prediction",
    )

    assert synchronized.shape == grid.shape
    assert synchronized.channel_response == pytest.approx(
        grid.path_amplitude_gain.astype(np.complex128),
        abs=0.0,
    )
    assert synchronized.residual_propagation_delay_s == pytest.approx(0.0)
    assert synchronized.residual_carrier_doppler_phase_rad == pytest.approx(
        0.0
    )
    assert synchronized.residual_total_phase_rad == pytest.approx(0.0)
    assert np.abs(synchronized.channel_response) == pytest.approx(
        np.abs(grid.channel_response)
    )
    assert synchronized.channel_response.flags.writeable is False


def test_synchronization_exposes_known_delay_and_carrier_phase_errors(baseline):
    grid = _ideal_grid(baseline)
    delay_error_s = 12.0e-9
    carrier_phase_error_rad = 0.35
    synchronized = synchronize_siso_ofdm_channel_grid(
        grid,
        grid.propagation_delay_s - delay_error_s,
        grid.carrier_doppler_phase_rad - carrier_phase_error_rad,
    )
    expected_phase_rad = (
        carrier_phase_error_rad
        - 2.0
        * np.pi
        * delay_error_s
        * grid.axes.frequency.baseband_frequency_hz[None, :]
    )
    expected_response = grid.path_amplitude_gain * np.exp(
        1j * expected_phase_rad
    )

    assert synchronized.residual_propagation_delay_s == pytest.approx(
        delay_error_s
    )
    assert synchronized.residual_carrier_doppler_phase_rad == pytest.approx(
        carrier_phase_error_rad
    )
    assert synchronized.channel_response == pytest.approx(
        expected_response,
        abs=1.0e-18,
    )


def test_block_start_prediction_holds_delay_and_integrates_constant_doppler():
    time_s = np.array([2.0, 2.1, 2.2])
    delay_s = np.array([1.0e-3, 1.1e-3, 1.2e-3])
    doppler_hz = np.array([5.0, 6.0, 7.0])
    phase_rad = np.array([0.25, 4.0, 9.0])

    predicted_delay_s, predicted_phase_rad = (
        predict_block_start_delay_and_doppler_phase(
            time_s,
            delay_s,
            doppler_hz,
            phase_rad,
        )
    )

    assert predicted_delay_s == pytest.approx(delay_s[0])
    assert predicted_phase_rad == pytest.approx(
        phase_rad[0] + 2.0 * np.pi * doppler_hz[0] * (time_s - time_s[0])
    )
    assert predicted_delay_s.flags.writeable is False
    assert predicted_phase_rad.flags.writeable is False


def test_block_start_synchronization_uses_no_later_truth_updates(baseline):
    grid = _ideal_grid(baseline)
    synchronized = synchronize_siso_ofdm_channel_grid_from_block_start(grid)

    expected_delay_s, expected_phase_rad = (
        predict_block_start_delay_and_doppler_phase(
            grid.axes.time.time_s,
            grid.propagation_delay_s,
            grid.doppler_shift_hz,
            grid.carrier_doppler_phase_rad,
        )
    )
    assert synchronized.predicted_propagation_delay_s == pytest.approx(
        expected_delay_s
    )
    assert synchronized.predicted_carrier_doppler_phase_rad == pytest.approx(
        expected_phase_rad
    )
    assert synchronized.residual_propagation_delay_s[0] == 0.0
    assert synchronized.residual_carrier_doppler_phase_rad[0] == 0.0
    assert synchronized.residual_total_phase_rad[0] == pytest.approx(0.0)
    assert np.abs(synchronized.channel_response) == pytest.approx(
        np.abs(grid.channel_response)
    )
    assert synchronized.prediction_label.startswith("block_start")


def test_block_start_prediction_rejects_invalid_reference_index():
    values = np.array([1.0, 2.0])

    with pytest.raises(ValueError, match="outside"):
        predict_block_start_delay_and_doppler_phase(
            values,
            values,
            values,
            values,
            block_start_index=2,
        )


def test_synchronization_rejects_prediction_with_wrong_shape(baseline):
    grid = _ideal_grid(baseline)

    with pytest.raises(ValueError, match="predicted_propagation_delay_s"):
        synchronize_siso_ofdm_channel_grid(
            grid,
            grid.propagation_delay_s[:-1],
            grid.carrier_doppler_phase_rad,
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


def test_synchronized_grid_npz_contains_raw_and_residual_channels(
    baseline,
    tmp_path,
):
    grid = _ideal_grid(baseline, symbol_count=3)
    synchronized = synchronize_siso_ofdm_channel_grid(
        grid,
        grid.propagation_delay_s,
        grid.carrier_doppler_phase_rad,
        prediction_label="perfect_truth_prediction",
    )
    path = save_synchronized_siso_channel_grid_npz(
        synchronized,
        tmp_path / "synchronized_channel_grid.npz",
    )

    with np.load(path, allow_pickle=False) as saved:
        assert saved["channel_response"].shape == (3, 223)
        assert np.array_equal(
            saved["raw_channel_response"],
            grid.channel_response,
        )
        assert np.array_equal(
            saved["channel_response"],
            synchronized.channel_response,
        )
        assert saved["prediction_label"].item() == "perfect_truth_prediction"
