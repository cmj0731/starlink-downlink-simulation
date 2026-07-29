from dataclasses import replace

import numpy as np
import pytest

from starlink_isl.downlink_dynamics import (
    SPEED_OF_LIGHT_KM_S,
    downlink_dynamics,
)
from starlink_isl.downlink_geometry import (
    downlink_geometry,
    visibility_window,
)
from starlink_isl.ideal_orbit import IdealOrbitConfig


CONFIG = IdealOrbitConfig()
ONE_GHZ = 1.0e9


def test_overhead_delay_and_zero_doppler():
    dynamics = downlink_dynamics(0.0, ONE_GHZ, CONFIG)

    assert dynamics.propagation_delay_s == pytest.approx(
        CONFIG.altitude_km / SPEED_OF_LIGHT_KM_S
    )
    assert dynamics.propagation_delay_s * 1e3 == pytest.approx(1.908, abs=0.001)
    assert dynamics.radial_velocity_km_s == pytest.approx(0.0, abs=1e-12)
    assert dynamics.doppler_shift_hz == pytest.approx(0.0, abs=1e-7)
    assert dynamics.doppler_phase_rad == pytest.approx(0.0)


def test_range_rate_matches_numerical_slant_range_derivative():
    times = np.linspace(-300.0, 300.0, 6_001)
    geometry = downlink_geometry(times, CONFIG)
    dynamics = downlink_dynamics(times, ONE_GHZ, CONFIG)
    numerical_range_rate = np.gradient(geometry.slant_range_km, times)

    assert dynamics.radial_velocity_km_s[1:-1] == pytest.approx(
        numerical_range_rate[1:-1],
        abs=2e-6,
    )


def test_doppler_sign_reverses_at_closest_approach():
    dynamics = downlink_dynamics(
        np.array([-100.0, 0.0, 100.0]),
        ONE_GHZ,
        CONFIG,
    )

    assert dynamics.radial_velocity_km_s[0] < 0.0
    assert dynamics.doppler_shift_hz[0] > 0.0
    assert dynamics.doppler_shift_hz[1] == pytest.approx(0.0, abs=1e-7)
    assert dynamics.radial_velocity_km_s[2] > 0.0
    assert dynamics.doppler_shift_hz[2] < 0.0


def test_static_earth_horizon_reproduces_reference_values():
    static_config = replace(CONFIG, earth_rotation_rate_rad_s=0.0)
    window = visibility_window(static_config)
    start = downlink_dynamics(window.start_s, ONE_GHZ, static_config)
    end = downlink_dynamics(window.end_s, ONE_GHZ, static_config)
    horizon_range = downlink_geometry(
        window.start_s,
        static_config,
    ).slant_range_km

    expected_speed = (
        static_config.earth_radius_km
        * static_config.orbital_rate_rad_s
    )
    expected_fraction = expected_speed / SPEED_OF_LIGHT_KM_S

    assert horizon_range == pytest.approx(2_761.0, abs=1.0)
    assert horizon_range / SPEED_OF_LIGHT_KM_S * 1e3 == pytest.approx(
        9.21, abs=0.01
    )
    assert start.radial_velocity_km_s == pytest.approx(-expected_speed)
    assert end.radial_velocity_km_s == pytest.approx(expected_speed)
    assert abs(start.doppler_shift_hz) == pytest.approx(
        expected_fraction * ONE_GHZ
    )
    assert abs(start.doppler_shift_hz) == pytest.approx(23_180.0, abs=30.0)


def test_doppler_scales_linearly_with_carrier_frequency():
    time = -200.0
    one_ghz = downlink_dynamics(time, 1.0e9, CONFIG)
    ten_ghz = downlink_dynamics(time, 10.0e9, CONFIG)
    twenty_ghz = downlink_dynamics(time, 20.0e9, CONFIG)

    assert ten_ghz.doppler_shift_hz == pytest.approx(
        10.0 * one_ghz.doppler_shift_hz
    )
    assert twenty_ghz.doppler_shift_hz == pytest.approx(
        20.0 * one_ghz.doppler_shift_hz
    )


def test_doppler_phase_derivative_matches_frequency_shift():
    times = np.linspace(-300.0, 300.0, 6_001)
    dynamics = downlink_dynamics(times, 10.0e9, CONFIG)
    phase_rate = np.gradient(dynamics.doppler_phase_rad, times)

    assert phase_rate[1:-1] == pytest.approx(
        2.0 * np.pi * dynamics.doppler_shift_hz[1:-1],
        abs=0.5,
    )


def test_phase_reference_sets_zero_phase():
    reference_time = 123.0
    dynamics = downlink_dynamics(
        np.array([0.0, reference_time, 200.0]),
        ONE_GHZ,
        CONFIG,
        phase_reference_time_s=reference_time,
    )

    assert dynamics.doppler_phase_rad[1] == pytest.approx(0.0)


@pytest.mark.parametrize("frequency", [0.0, -1.0, np.inf, np.nan])
def test_invalid_carrier_frequency_is_rejected(frequency):
    with pytest.raises(ValueError, match="carrier_frequency_hz"):
        downlink_dynamics(0.0, frequency, CONFIG)


def test_invalid_phase_reference_is_rejected():
    with pytest.raises(ValueError, match="phase_reference_time_s"):
        downlink_dynamics(
            0.0,
            ONE_GHZ,
            CONFIG,
            phase_reference_time_s=np.nan,
        )
