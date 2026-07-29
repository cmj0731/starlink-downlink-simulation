import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from starlink_isl.ideal_orbit import IdealOrbitConfig, satellite_state
from starlink_isl.link_budget import LinkBudgetConfig
from starlink_isl.simulate import (
    build_time_samples,
    eci_to_spherical_ground_track,
    run_simulation,
)


RADIO = LinkBudgetConfig(
    carrier_frequency_hz=10.0e9,
    bandwidth_hz=100.0e6,
    transmit_power_dbw=10.0,
    transmit_antenna_gain_dbi=30.0,
    receive_antenna_gain_dbi=40.0,
    system_noise_temperature_k=290.0,
    other_losses_db=2.0,
)


def test_time_samples_include_requested_end():
    samples = build_time_samples(-1.0, 1.0, 0.6)

    assert samples[0] == -1.0
    assert samples[-1] == 1.0
    assert np.all(np.diff(samples) > 0.0)


def test_ground_track_starts_above_station():
    orbit = IdealOrbitConfig()
    satellite = satellite_state(np.array([0.0]), orbit)
    longitude, latitude, radius = eci_to_spherical_ground_track(
        satellite.position_km,
        np.array([0.0]),
        orbit.earth_rotation_rate_rad_s,
    )

    assert longitude[0] == pytest.approx(orbit.station_initial_longitude_deg)
    assert latitude[0] == pytest.approx(orbit.station_latitude_deg)
    assert radius[0] == pytest.approx(orbit.orbital_radius_km)


def test_simulation_writes_complete_artifact_set(tmp_path: Path):
    artifacts = run_simulation(
        tmp_path,
        radio=RADIO,
        minimum_elevation_deg=10.0,
        time_step_s=10.0,
    )

    for path in (
        artifacts.results_csv,
        artifacts.summary_json,
        artifacts.orbit_3d_png,
        artifacts.ground_track_png,
        artifacts.geometry_png,
        artifacts.delay_doppler_png,
        artifacts.link_budget_png,
    ):
        assert path.is_file()
        assert path.stat().st_size > 100

    frame = pd.read_csv(artifacts.results_csv)
    assert {
        "time_s",
        "slant_range_km",
        "elevation_deg",
        "propagation_delay_ms",
        "doppler_shift_hz",
        "received_power_dbw",
        "snr_db",
        "visible",
    }.issubset(frame.columns)
    assert frame["visible"].any()
    assert (~frame["visible"]).any()

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["model"] == "ideal STARLINK-5285 overhead downlink"
    assert summary["radio_parameters_are_illustrative"]
    assert summary["minimum_elevation_deg"] == 10.0
    assert summary["sample_count"] == len(frame)

    for path in (
        artifacts.orbit_3d_png,
        artifacts.ground_track_png,
        artifacts.geometry_png,
        artifacts.delay_doppler_png,
        artifacts.link_budget_png,
    ):
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    ("start", "end", "step"),
    [
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (0.0, 1.0, 0.0),
        (np.nan, 1.0, 1.0),
    ],
)
def test_invalid_time_samples_are_rejected(start, end, step):
    with pytest.raises(ValueError):
        build_time_samples(start, end, step)


def test_ground_track_shape_mismatch_is_rejected():
    with pytest.raises(ValueError, match="shapes must match"):
        eci_to_spherical_ground_track(
            np.zeros((2, 3)),
            np.zeros(3),
            0.0,
        )

