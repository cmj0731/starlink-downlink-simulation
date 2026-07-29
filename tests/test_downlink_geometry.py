from dataclasses import replace

import numpy as np
import pytest

from starlink_isl.downlink_geometry import (
    downlink_geometry,
    visibility_window,
)
from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    ground_station_state,
    satellite_state,
)


CONFIG = IdealOrbitConfig()


def test_overhead_geometry_at_initial_time():
    geometry = downlink_geometry(0.0, CONFIG)

    assert geometry.slant_range_km == pytest.approx(CONFIG.altitude_km)
    assert geometry.central_angle_rad == pytest.approx(0.0, abs=1e-12)
    assert geometry.surface_distance_km == pytest.approx(0.0, abs=1e-8)
    assert geometry.elevation_deg == pytest.approx(90.0)
    assert np.isnan(geometry.azimuth_deg)
    assert bool(geometry.visible)


def test_slant_range_matches_spherical_cosine_rule():
    times = np.linspace(-500.0, 500.0, 51)
    geometry = downlink_geometry(times, CONFIG)
    expected = np.sqrt(
        CONFIG.orbital_radius_km**2
        + CONFIG.earth_radius_km**2
        - 2.0
        * CONFIG.orbital_radius_km
        * CONFIG.earth_radius_km
        * np.cos(geometry.central_angle_rad)
    )

    assert geometry.slant_range_km == pytest.approx(expected)


def test_central_angle_matches_position_vectors():
    times = np.array([-300.0, 0.0, 400.0])
    station = ground_station_state(times, CONFIG)
    satellite = satellite_state(times, CONFIG)
    cosine = np.sum(
        station.position_km * satellite.position_km,
        axis=1,
    ) / (CONFIG.earth_radius_km * CONFIG.orbital_radius_km)

    geometry = downlink_geometry(times, CONFIG)

    assert np.cos(geometry.central_angle_rad) == pytest.approx(cosine)


def test_minimum_elevation_controls_visibility():
    times = np.array([0.0, 300.0, 1_000.0])
    geometry = downlink_geometry(
        times,
        CONFIG,
        minimum_elevation_deg=10.0,
    )

    assert geometry.visible.dtype == np.bool_
    assert geometry.visible[0]
    assert not geometry.visible[-1]
    assert geometry.visible == pytest.approx(geometry.elevation_deg >= 10.0)


def test_static_earth_reproduces_analytic_horizon_window():
    static_config = replace(CONFIG, earth_rotation_rate_rad_s=0.0)
    window = visibility_window(static_config)
    horizon_angle = np.arccos(
        static_config.earth_radius_km / static_config.orbital_radius_km
    )
    expected_duration = (
        2.0 * horizon_angle / static_config.orbital_rate_rad_s
    )
    horizon_geometry = downlink_geometry(window.start_s, static_config)
    expected_horizon_range = np.sqrt(
        static_config.orbital_radius_km**2
        - static_config.earth_radius_km**2
    )

    assert window.start_s == pytest.approx(-expected_duration / 2.0)
    assert window.end_s == pytest.approx(expected_duration / 2.0)
    assert window.duration_s == pytest.approx(expected_duration)
    assert window.duration_s == pytest.approx(749.9, abs=0.2)
    assert horizon_geometry.slant_range_km == pytest.approx(
        expected_horizon_range
    )
    assert horizon_geometry.elevation_deg == pytest.approx(0.0, abs=1e-10)


def test_rotating_earth_window_contains_overhead_time():
    window = visibility_window(CONFIG)

    assert window.start_s < 0.0 < window.end_s
    assert window.duration_s > 0.0
    assert window.closest_approach_s == 0.0
    assert window.minimum_slant_range_km == pytest.approx(CONFIG.altitude_km)
    assert window.maximum_elevation_deg == pytest.approx(90.0)


def test_higher_minimum_elevation_shortens_window():
    horizon_window = visibility_window(CONFIG, minimum_elevation_deg=0.0)
    ten_degree_window = visibility_window(
        CONFIG,
        minimum_elevation_deg=10.0,
    )

    assert ten_degree_window.duration_s < horizon_window.duration_s
    assert ten_degree_window.minimum_elevation_deg == 10.0


@pytest.mark.parametrize("minimum", [-91.0, 91.0])
def test_invalid_geometry_minimum_elevation_is_rejected(minimum):
    with pytest.raises(ValueError, match="minimum_elevation_deg"):
        downlink_geometry(0.0, CONFIG, minimum_elevation_deg=minimum)


def test_invalid_visibility_search_arguments_are_rejected():
    with pytest.raises(ValueError, match="minimum_elevation_deg"):
        visibility_window(CONFIG, minimum_elevation_deg=90.0)
    with pytest.raises(ValueError, match="search_step_s"):
        visibility_window(CONFIG, search_step_s=0.0)
    with pytest.raises(ValueError, match="maximum_search_s"):
        visibility_window(CONFIG, maximum_search_s=0.0)

