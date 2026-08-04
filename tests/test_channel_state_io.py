import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from starlink_isl import GroundStation
from starlink_isl.channel_state_io import (
    CHANNEL_STATE_CSV_SCHEMA_VERSION,
    CHANNEL_STATE_REPRESENTATION,
    load_channel_state_csv,
    save_channel_state_csv,
)
from starlink_isl.sgp4_orbit import satrec_from_omm
from starlink_isl.si_interface import sgp4_downlink_state_si


ROOT = Path(__file__).resolve().parents[1]
OMM_FIXTURE = ROOT / "tests" / "fixtures" / "starlink_5285_omm.json"
REFERENCE_UTC = datetime(
    2026,
    7,
    29,
    7,
    46,
    50,
    953_295,
    tzinfo=timezone.utc,
)
CARRIER_FREQUENCY_HZ = 11.7e9


def _three_sample_state():
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
    satellite = satrec_from_omm(record)
    datetimes = [
        REFERENCE_UTC + timedelta(seconds=offset)
        for offset in (-1.0, 0.0, 1.0)
    ]
    station = GroundStation(
        latitude_deg=37.2934,
        longitude_deg=126.9747,
        altitude_m=25.0,
    )
    state = sgp4_downlink_state_si(
        datetimes,
        satellite,
        CARRIER_FREQUENCY_HZ,
        station,
        minimum_elevation_rad=np.deg2rad(10.0),
        time_origin_utc=REFERENCE_UTC,
        phase_reference_utc=REFERENCE_UTC,
    )
    return state, station


def test_compact_channel_state_csv_round_trip(tmp_path):
    state, station = _three_sample_state()
    path = save_channel_state_csv(
        state,
        tmp_path / "channel_state.csv",
        reference_utc=REFERENCE_UTC,
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        station=station,
        other_losses_db=2.0,
        event_labels=("visibility_start", "closest_approach", "visibility_end"),
    )

    raw = pd.read_csv(path)
    assert len(raw) == state.sample_count
    assert set(raw["schema_version"]) == {CHANNEL_STATE_CSV_SCHEMA_VERSION}
    assert set(raw["state_representation"]) == {
        CHANNEL_STATE_REPRESENTATION
    }
    assert "grid_column" not in raw
    assert "baseband_frequency_hz" not in raw
    assert "h_real" not in raw

    loaded = load_channel_state_csv(path)
    assert loaded.sample_count == state.sample_count
    assert loaded.reference_utc == REFERENCE_UTC
    assert loaded.carrier_frequency_hz == CARRIER_FREQUENCY_HZ
    assert loaded.other_losses_db == 2.0
    assert loaded.station == station
    assert loaded.event_labels == (
        "visibility_start",
        "closest_approach",
        "visibility_end",
    )
    for field_name in (
        "time_s",
        "satellite_position_m",
        "satellite_velocity_m_s",
        "ue_position_m",
        "ue_velocity_m_s",
        "los_satellite_to_ue_unit",
        "slant_range_m",
        "surface_distance_m",
        "azimuth_rad",
        "elevation_rad",
        "radial_velocity_m_s",
        "propagation_delay_s",
        "doppler_shift_hz",
        "doppler_phase_rad",
    ):
        np.testing.assert_allclose(
            getattr(loaded.state, field_name),
            getattr(state, field_name),
            rtol=2.0e-15,
            atol=1.0e-12,
        )
    np.testing.assert_array_equal(loaded.state.visible, state.visible)


def test_channel_state_loader_rejects_inconsistent_delay(tmp_path):
    state, station = _three_sample_state()
    path = save_channel_state_csv(
        state,
        tmp_path / "channel_state.csv",
        reference_utc=REFERENCE_UTC,
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        station=station,
    )
    frame = pd.read_csv(path)
    frame.loc[1, "propagation_delay_s"] *= 1.01
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="delay is inconsistent"):
        load_channel_state_csv(path)
