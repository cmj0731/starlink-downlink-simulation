import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from starlink_isl.actual_downlink import (
    VISIBILITY_ELEVATION_TOLERANCE_DEG,
    dynamics_from_ecef_states,
    find_visibility_passes,
    geometry_from_ecef_states,
)
from starlink_isl.sgp4_orbit import (
    GroundStation,
    ground_station_ecef_state,
    propagate_ecef,
    satrec_from_omm,
)


FIXTURE = Path(__file__).parent / "fixtures" / "starlink_5285_omm.json"
RECORD = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
SATELLITE = satrec_from_omm(RECORD)
STATION = GroundStation()


def test_actual_pass_boundaries_and_closest_approach():
    search_start = datetime(2026, 7, 29, 7, 0, tzinfo=timezone.utc)
    passes = find_visibility_passes(
        SATELLITE,
        STATION,
        search_start,
        search_start + timedelta(hours=2),
        minimum_elevation_deg=10.0,
    )

    assert len(passes) == 1
    selected = passes[0]
    assert selected.duration_s == pytest.approx(505.914, abs=0.01)
    assert selected.maximum_elevation_deg == pytest.approx(85.164, abs=0.01)
    assert selected.minimum_slant_range_km == pytest.approx(579.705, abs=0.01)

    event_times = [
        selected.start_utc,
        selected.closest_approach_utc,
        selected.maximum_elevation_utc,
        selected.end_utc,
    ]
    satellite_state = propagate_ecef(SATELLITE, event_times)
    ground_state = ground_station_ecef_state(STATION, 4)
    geometry = geometry_from_ecef_states(
        satellite_state,
        ground_state,
        STATION,
        minimum_elevation_deg=10.0,
    )
    dynamics = dynamics_from_ecef_states(
        geometry,
        satellite_state,
        ground_state,
        10.0e9,
        phase_reference_range_km=selected.minimum_slant_range_km,
    )

    assert geometry.elevation_deg[[0, 3]] == pytest.approx(
        [10.0, 10.0],
        abs=VISIBILITY_ELEVATION_TOLERANCE_DEG,
    )
    assert geometry.visible[[0, 3]].tolist() == [True, True]
    assert geometry.elevation_deg[2] == pytest.approx(
        selected.maximum_elevation_deg
    )
    assert geometry.elevation_deg[2] >= geometry.elevation_deg[1]
    assert geometry.slant_range_km[1] <= geometry.slant_range_km[2]
    assert (
        selected.start_utc
        <= selected.maximum_elevation_utc
        <= selected.end_utc
    )
    assert dynamics.radial_velocity_km_s[1] == pytest.approx(
        0.0,
        abs=1e-7,
    )
    assert dynamics.doppler_shift_hz[1] == pytest.approx(0.0, abs=0.01)


def test_range_rate_matches_nonuniform_distance_derivative():
    center = datetime(
        2026,
        7,
        29,
        7,
        46,
        50,
        952_536,
        tzinfo=timezone.utc,
    )
    offsets = np.array([-2.0, -0.7, 0.0, 0.4, 1.8])
    datetimes = [
        center + timedelta(seconds=float(offset)) for offset in offsets
    ]
    satellite_state = propagate_ecef(SATELLITE, datetimes)
    ground_state = ground_station_ecef_state(STATION, len(datetimes))
    geometry = geometry_from_ecef_states(
        satellite_state,
        ground_state,
        STATION,
    )
    dynamics = dynamics_from_ecef_states(
        geometry,
        satellite_state,
        ground_state,
        10.0e9,
        phase_reference_range_km=float(geometry.slant_range_km[2]),
    )
    numerical = np.gradient(geometry.slant_range_km, offsets)

    assert dynamics.radial_velocity_km_s[1:-1] == pytest.approx(
        numerical[1:-1],
        abs=2e-4,
    )
