import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from starlink_isl import (
    compare_downlink_states,
    ideal_downlink_state_si,
    resample_downlink_state_si,
    sgp4_downlink_state_si,
)
from starlink_isl.sgp4_orbit import satrec_from_omm


FIXTURE = Path(__file__).parent / "fixtures" / "starlink_5285_omm.json"
CARRIER_FREQUENCY_HZ = 11.7e9
MINIMUM_ELEVATION_RAD = np.deg2rad(10.0)


def _satellite():
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    return satrec_from_omm(record)


def _epochs(start, offsets_s):
    return [
        start + timedelta(seconds=float(offset_s))
        for offset_s in offsets_s
    ]


def _sgp4_state(offsets_s):
    start = datetime(2026, 7, 29, 7, 46, 49, tzinfo=timezone.utc)
    return sgp4_downlink_state_si(
        _epochs(start, offsets_s),
        _satellite(),
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        minimum_elevation_rad=MINIMUM_ELEVATION_RAD,
        time_origin_utc=start,
        phase_reference_utc=start,
    )


def test_hermite_resampling_preserves_every_sgp4_anchor_state():
    source = _sgp4_state([0.0, 1.0, 2.0])

    result = resample_downlink_state_si(
        source,
        source.time_s,
        CARRIER_FREQUENCY_HZ,
        minimum_elevation_rad=MINIMUM_ELEVATION_RAD,
    )

    assert result.satellite_position_m == pytest.approx(
        source.satellite_position_m,
        abs=1e-8,
    )
    assert result.satellite_velocity_m_s == pytest.approx(
        source.satellite_velocity_m_s,
        abs=1e-9,
    )
    assert result.slant_range_m == pytest.approx(source.slant_range_m, abs=1e-8)
    assert result.radial_velocity_m_s == pytest.approx(
        source.radial_velocity_m_s,
        abs=1e-9,
    )
    assert result.doppler_shift_hz == pytest.approx(
        source.doppler_shift_hz,
        abs=1e-8,
    )
    assert result.doppler_phase_rad == pytest.approx(
        source.doppler_phase_rad,
        abs=1e-7,
    )


def test_one_second_anchors_match_direct_sgp4_on_one_ms_grid():
    source = _sgp4_state([0.0, 1.0, 2.0])
    target_time_s = np.linspace(0.0, 2.0, 2_001)
    direct = _sgp4_state(target_time_s)

    interpolated = resample_downlink_state_si(
        source,
        target_time_s,
        CARRIER_FREQUENCY_HZ,
        minimum_elevation_rad=MINIMUM_ELEVATION_RAD,
    )
    error = compare_downlink_states(direct, interpolated)

    assert error.satellite_position_m < 0.02
    assert error.satellite_velocity_m_s < 0.02
    assert error.slant_range_m < 0.002
    assert error.radial_velocity_m_s < 0.001
    assert error.propagation_delay_s < 1.0e-10
    assert error.doppler_shift_hz < 0.05
    assert error.doppler_phase_rad < 0.5
    assert error.los_angle_rad < 1.0e-7


def test_resampled_phase_derivative_matches_resampled_doppler():
    source = _sgp4_state([0.0, 1.0, 2.0])
    target_time_s = np.linspace(0.0, 2.0, 2_001)
    result = resample_downlink_state_si(
        source,
        target_time_s,
        CARRIER_FREQUENCY_HZ,
        minimum_elevation_rad=MINIMUM_ELEVATION_RAD,
    )

    phase_derived_doppler_hz = np.gradient(
        result.doppler_phase_rad,
        result.time_s,
    ) / (2.0 * np.pi)

    assert phase_derived_doppler_hz[1:-1] == pytest.approx(
        result.doppler_shift_hz[1:-1],
        abs=0.01,
    )


def test_resampler_supports_ideal_eci_state():
    source = ideal_downlink_state_si(
        [-1.0, 0.0, 1.0],
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
    )
    target_time_s = np.linspace(-1.0, 1.0, 2_001)
    direct = ideal_downlink_state_si(
        target_time_s,
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
    )

    interpolated = resample_downlink_state_si(
        source,
        target_time_s,
        CARRIER_FREQUENCY_HZ,
    )
    error = compare_downlink_states(direct, interpolated)

    assert interpolated.coordinate_frame == "ECI"
    assert error.satellite_position_m < 0.01
    assert error.slant_range_m < 0.01


def test_resampler_rejects_extrapolation():
    source = _sgp4_state([0.0, 1.0])

    with pytest.raises(ValueError, match="inside"):
        resample_downlink_state_si(
            source,
            [-0.001, 0.0, 1.0],
            CARRIER_FREQUENCY_HZ,
        )


def test_resampler_rejects_carrier_inconsistent_with_source_state():
    source = _sgp4_state([0.0, 1.0])

    with pytest.raises(ValueError, match="Doppler shift"):
        resample_downlink_state_si(
            source,
            [0.0, 0.5, 1.0],
            10.0e9,
        )


@pytest.mark.parametrize(
    "target_time_s",
    [[], [0.0, 0.5, 0.5], [0.0, np.nan, 1.0]],
)
def test_resampler_rejects_invalid_target_times(target_time_s):
    source = _sgp4_state([0.0, 1.0])

    with pytest.raises(ValueError, match="target_time_s"):
        resample_downlink_state_si(
            source,
            target_time_s,
            CARRIER_FREQUENCY_HZ,
        )


def test_state_comparison_rejects_different_time_grids():
    first = _sgp4_state([0.0, 1.0])
    second = _sgp4_state([0.0, 0.5])

    with pytest.raises(ValueError, match="identical sample times"):
        compare_downlink_states(first, second)
