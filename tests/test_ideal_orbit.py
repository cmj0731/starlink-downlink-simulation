from dataclasses import replace

import numpy as np
import pytest

from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    ground_station_state,
    satellite_state,
)


CONFIG = IdealOrbitConfig()


def test_default_derived_orbit_values():
    assert CONFIG.orbital_radius_km == pytest.approx(6_950.0)
    assert CONFIG.orbital_rate_rad_s == pytest.approx(1.08958e-3, rel=1e-4)
    assert CONFIG.orbital_speed_km_s == pytest.approx(7.57, rel=1e-3)


def test_position_radii_and_speed_are_constant():
    times = np.linspace(-1_000.0, 1_000.0, 101)
    station = ground_station_state(times, CONFIG)
    satellite = satellite_state(times, CONFIG)

    assert np.linalg.norm(station.position_km, axis=1) == pytest.approx(
        CONFIG.earth_radius_km
    )
    assert np.linalg.norm(satellite.position_km, axis=1) == pytest.approx(
        CONFIG.orbital_radius_km
    )
    assert np.linalg.norm(satellite.velocity_km_s, axis=1) == pytest.approx(
        CONFIG.orbital_speed_km_s
    )


def test_initial_state_is_northbound_overhead_pass():
    station = ground_station_state(0.0, CONFIG)
    satellite = satellite_state(0.0, CONFIG)

    station_direction = station.position_km / CONFIG.earth_radius_km
    satellite_direction = satellite.position_km / CONFIG.orbital_radius_km

    assert satellite_direction == pytest.approx(station_direction, abs=1e-14)
    assert np.linalg.norm(
        satellite.position_km - station.position_km
    ) == pytest.approx(CONFIG.altitude_km)
    assert satellite.velocity_km_s[2] > 0.0


def test_orbit_has_configured_inclination():
    state = satellite_state(0.0, CONFIG)
    angular_momentum = np.cross(state.position_km, state.velocity_km_s)
    normal = angular_momentum / np.linalg.norm(angular_momentum)
    inclination = np.rad2deg(np.arccos(np.clip(normal[2], -1.0, 1.0)))

    assert inclination == pytest.approx(CONFIG.inclination_deg)


def test_satellite_returns_after_one_period():
    initial = satellite_state(0.0, CONFIG)
    after_period = satellite_state(CONFIG.orbital_period_s, CONFIG)

    assert after_period.position_km == pytest.approx(
        initial.position_km, abs=1e-10
    )
    assert after_period.velocity_km_s == pytest.approx(
        initial.velocity_km_s, abs=1e-12
    )


def test_zero_earth_rotation_keeps_station_fixed():
    static_config = replace(CONFIG, earth_rotation_rate_rad_s=0.0)
    times = np.array([-1_000.0, 0.0, 1_000.0])
    station = ground_station_state(times, static_config)

    assert station.position_km[0] == pytest.approx(station.position_km[1])
    assert station.position_km[2] == pytest.approx(station.position_km[1])
    assert station.velocity_km_s == pytest.approx(np.zeros((3, 3)))


def test_scalar_and_vector_time_shapes():
    assert satellite_state(0.0, CONFIG).position_km.shape == (3,)
    assert satellite_state([0.0, 1.0], CONFIG).position_km.shape == (2, 3)
    assert ground_station_state(0.0, CONFIG).velocity_km_s.shape == (3,)
    assert ground_station_state([0.0, 1.0], CONFIG).velocity_km_s.shape == (
        2,
        3,
    )


def test_invalid_overhead_geometry_is_rejected():
    with pytest.raises(ValueError, match="overhead pass"):
        IdealOrbitConfig(inclination_deg=30.0, station_latitude_deg=37.2934)


def test_nonfinite_time_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        satellite_state([0.0, np.nan], CONFIG)

