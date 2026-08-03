from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from starlink_isl import (
    build_ofdm_channel_grid_axes,
    build_ofdm_frequency_axis,
    build_ofdm_time_axis,
    centered_active_subcarrier_indices,
    fftshift_guard_active_subcarrier_indices,
    load_research_baseline,
)


BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "ofdm_baseline.yaml"
)


@pytest.fixture
def baseline():
    return load_research_baseline(BASELINE_PATH)


def test_baseline_frequency_axis_matches_team_fftshift_layout(baseline):
    axis = build_ofdm_frequency_axis(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
    )

    expected_indices = np.concatenate((np.arange(-112, 0), np.arange(1, 112)))
    assert np.array_equal(axis.signed_subcarrier_indices, expected_indices)
    assert axis.subcarrier_count == 223
    assert 0 not in axis.signed_subcarrier_indices
    assert axis.fft_bin_indices[0] == 144
    assert axis.fft_bin_indices[111] == 255
    assert axis.fft_bin_indices[112] == 1
    assert axis.fft_bin_indices[-1] == 111
    assert axis.fftshift_bin_indices[0] == 16
    assert axis.fftshift_bin_indices[111] == 127
    assert axis.fftshift_bin_indices[112] == 129
    assert axis.fftshift_bin_indices[-1] == 239
    assert axis.baseband_frequency_hz[[0, -1]] == pytest.approx(
        [-13.44e6, 13.32e6]
    )
    assert axis.rf_frequency_hz[[0, -1]] == pytest.approx(
        [11.68656e9, 11.71332e9]
    )


def test_time_axis_uses_fft_window_center_and_total_symbol_spacing(baseline):
    axis = build_ofdm_time_axis(
        baseline.ofdm,
        3,
        frame_start_time_s=10.0,
        symbol_time_reference=baseline.channel_grid.symbol_time_reference,
    )

    expected_offset_s = (
        baseline.ofdm.cyclic_prefix_duration_s
        + 0.5 * baseline.ofdm.useful_symbol_duration_s
    )
    assert np.array_equal(axis.symbol_indices, [0, 1, 2])
    assert axis.symbol_start_time_s == pytest.approx(
        10.0 + np.arange(3) / 120.0e3
    )
    assert axis.reference_offset_s == pytest.approx(expected_offset_s)
    assert axis.time_s == pytest.approx(
        axis.symbol_start_time_s + expected_offset_s
    )
    assert np.diff(axis.time_s) == pytest.approx([1 / 120.0e3] * 2)


@pytest.mark.parametrize(
    ("reference", "expected_offset_property"),
    [
        ("symbol_start", 0.0),
        ("fft_window_start", "cyclic_prefix_duration_s"),
        ("fft_window_center", "center"),
    ],
)
def test_time_reference_conventions_are_explicit(
    baseline,
    reference,
    expected_offset_property,
):
    axis = build_ofdm_time_axis(
        baseline.ofdm,
        1,
        symbol_time_reference=reference,
    )

    if expected_offset_property == 0.0:
        expected_offset_s = 0.0
    elif expected_offset_property == "center":
        expected_offset_s = (
            baseline.ofdm.cyclic_prefix_duration_s
            + 0.5 * baseline.ofdm.useful_symbol_duration_s
        )
    else:
        expected_offset_s = getattr(
            baseline.ofdm,
            expected_offset_property,
        )
    assert axis.reference_offset_s == pytest.approx(expected_offset_s)


def test_combined_grid_shape_is_symbol_by_active_subcarrier(baseline):
    axes = build_ofdm_channel_grid_axes(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
        8,
        symbol_time_reference=baseline.channel_grid.symbol_time_reference,
    )

    assert axes.shape == (8, 223)
    assert axes.time.symbol_count == 8
    assert axes.frequency.subcarrier_count == 223


def test_explicit_signed_indices_override_named_layout(baseline):
    explicit = fftshift_guard_active_subcarrier_indices(
        baseline.ofdm.fft_size,
        left_guard_bins=16,
        right_guard_bins=16,
        dc_subcarrier_null=True,
    )
    axis = build_ofdm_frequency_axis(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
        active_subcarrier_indices=explicit,
    )

    assert np.array_equal(axis.signed_subcarrier_indices, explicit)


def test_pending_layout_cannot_silently_create_a_frequency_axis(baseline):
    pending = replace(
        baseline.ofdm,
        active_subcarrier_layout="pending_team_confirmation",
    )

    with pytest.raises(ValueError, match="not executable"):
        build_ofdm_frequency_axis(
            pending,
            baseline.radio.carrier_frequency_hz,
        )


@pytest.mark.parametrize(
    ("indices", "error_type", "match"),
    [
        (np.arange(223, dtype=float), TypeError, "integers"),
        (np.arange(-111, 112), ValueError, "DC subcarrier"),
        (
            np.concatenate((np.arange(-112, 0), np.arange(1, 111))),
            ValueError,
            "size",
        ),
        (
            np.concatenate((np.arange(-111, 0), [1, 1], np.arange(2, 112))),
            ValueError,
            "strictly increasing",
        ),
    ],
)
def test_frequency_axis_rejects_ambiguous_explicit_indices(
    baseline,
    indices,
    error_type,
    match,
):
    with pytest.raises(error_type, match=match):
        build_ofdm_frequency_axis(
            baseline.ofdm,
            baseline.radio.carrier_frequency_hz,
            active_subcarrier_indices=indices,
        )


def test_grid_axes_arrays_are_read_only(baseline):
    axes = build_ofdm_channel_grid_axes(
        baseline.ofdm,
        baseline.radio.carrier_frequency_hz,
        2,
    )

    assert axes.time.time_s.flags.writeable is False
    assert axes.frequency.signed_subcarrier_indices.flags.writeable is False
    assert axes.frequency.fftshift_bin_indices.flags.writeable is False


def test_legacy_centered_layout_helper_remains_available():
    indices = centered_active_subcarrier_indices(
        256,
        200,
        dc_subcarrier_null=True,
    )

    assert indices[[0, -1]].tolist() == [-100, 100]
