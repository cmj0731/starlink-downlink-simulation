import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from starlink_isl import (
    downlink_dynamics,
    downlink_geometry,
    ideal_downlink_state_si,
    sgp4_downlink_state_si,
)
from starlink_isl.sgp4_orbit import satrec_from_omm


FIXTURE = Path(__file__).parent / "fixtures" / "starlink_5285_omm.json"


def test_ideal_si_interface_uses_team_units_shapes_and_los_direction():
    times = np.array([0.0, 1.0, 2.0])
    state = ideal_downlink_state_si(times, carrier_frequency_hz=10.0e9)
    legacy_geometry = downlink_geometry(times)
    legacy_dynamics = downlink_dynamics(times, carrier_frequency_hz=10.0e9)

    assert state.coordinate_frame == "ECI"
    assert state.sample_count == 3
    assert state.time_s.shape == (3,)
    assert state.satellite_position_m.shape == (3, 3)
    assert state.satellite_velocity_m_s.shape == (3, 3)
    assert state.ue_position_m.shape == (3, 3)
    assert state.ue_velocity_m_s.shape == (3, 3)
    assert state.los_satellite_to_ue_unit.shape == (3, 3)
    assert state.slant_range_m == pytest.approx(
        1_000.0 * legacy_geometry.slant_range_km
    )
    assert state.surface_distance_m == pytest.approx(
        1_000.0 * legacy_geometry.surface_distance_km
    )
    assert state.elevation_rad == pytest.approx(
        np.deg2rad(legacy_geometry.elevation_deg)
    )
    assert state.radial_velocity_m_s == pytest.approx(
        1_000.0 * legacy_dynamics.radial_velocity_km_s,
        rel=1e-12,
        abs=1e-8,
    )

    satellite_to_ue = state.ue_position_m - state.satellite_position_m
    expected_los = satellite_to_ue / np.linalg.norm(
        satellite_to_ue,
        axis=1,
        keepdims=True,
    )
    assert state.los_satellite_to_ue_unit == pytest.approx(expected_los)
    assert np.linalg.norm(
        state.los_satellite_to_ue_unit,
        axis=1,
    ) == pytest.approx(np.ones(3))


def test_ideal_si_interface_preserves_range_rate_and_doppler_signs():
    state = ideal_downlink_state_si(
        [-100.0, 0.0, 100.0],
        carrier_frequency_hz=10.0e9,
    )

    assert state.slant_range_m[1] == pytest.approx(572_000.0)
    assert state.elevation_rad[1] == pytest.approx(0.5 * np.pi)
    assert state.radial_velocity_m_s[0] < 0.0
    assert state.radial_velocity_m_s[1] == pytest.approx(0.0, abs=1e-9)
    assert state.radial_velocity_m_s[2] > 0.0
    assert state.doppler_shift_hz[0] > 0.0
    assert state.doppler_shift_hz[1] == pytest.approx(0.0, abs=1e-6)
    assert state.doppler_shift_hz[2] < 0.0


def test_ideal_si_interface_scalar_input_still_has_sample_axis():
    state = ideal_downlink_state_si(0.0, carrier_frequency_hz=10.0e9)

    assert state.time_s.shape == (1,)
    assert state.satellite_position_m.shape == (1, 3)
    assert state.los_satellite_to_ue_unit.shape == (1, 3)
    assert state.visible.shape == (1,)


def test_sgp4_si_interface_uses_ecef_and_simulation_elapsed_time():
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    satellite = satrec_from_omm(record)
    start = datetime(2026, 7, 29, 7, 46, 49, tzinfo=timezone.utc)
    epochs = [start, start + timedelta(seconds=2.5)]

    state = sgp4_downlink_state_si(
        epochs,
        satellite,
        carrier_frequency_hz=10.0e9,
        minimum_elevation_rad=np.deg2rad(10.0),
    )

    assert state.coordinate_frame == "ECEF"
    assert state.time_s == pytest.approx([0.0, 2.5])
    assert state.satellite_position_m.shape == (2, 3)
    assert state.ue_position_m[0] == pytest.approx(state.ue_position_m[1])
    assert state.ue_velocity_m_s == pytest.approx(np.zeros((2, 3)))
    assert state.doppler_phase_rad[0] == pytest.approx(0.0)

    satellite_to_ue = state.ue_position_m - state.satellite_position_m
    assert np.sum(
        satellite_to_ue * state.los_satellite_to_ue_unit,
        axis=1,
    ) == pytest.approx(state.slant_range_m)


@pytest.mark.parametrize(
    "minimum_elevation_rad",
    [-0.5 * np.pi - 1e-6, 0.5 * np.pi + 1e-6, np.nan],
)
def test_si_interface_rejects_invalid_minimum_elevation(
    minimum_elevation_rad,
):
    with pytest.raises(ValueError, match="minimum_elevation_rad"):
        ideal_downlink_state_si(
            0.0,
            carrier_frequency_hz=10.0e9,
            minimum_elevation_rad=minimum_elevation_rad,
        )


def test_sgp4_si_interface_rejects_naive_time_origin():
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    satellite = satrec_from_omm(record)
    epoch = datetime(2026, 7, 29, 7, 46, 49, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="time_origin_utc"):
        sgp4_downlink_state_si(
            [epoch],
            satellite,
            carrier_frequency_hz=10.0e9,
            time_origin_utc=datetime(2026, 7, 29),
        )
