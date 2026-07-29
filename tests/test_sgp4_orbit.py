import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from starlink_isl.sgp4_orbit import (
    GroundStation,
    geodetic_to_ecef,
    parse_omm_epoch,
    propagate_ecef,
    propagate_teme,
    satrec_from_omm,
)


FIXTURE = Path(__file__).parent / "fixtures" / "starlink_5285_omm.json"


@pytest.fixture
def omm_record():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))[0]


def test_omm_epoch_is_aware_utc(omm_record):
    epoch = parse_omm_epoch(omm_record)

    assert epoch == datetime(
        2026,
        7,
        27,
        11,
        53,
        54,
        484_800,
        tzinfo=timezone.utc,
    )


def test_sgp4_epoch_state_matches_fixed_reference(omm_record):
    satellite = satrec_from_omm(omm_record)
    epoch = parse_omm_epoch(omm_record)
    state = propagate_teme(satellite, [epoch])

    assert state.position_km[0] == pytest.approx(
        [5906.58810, 3667.66107, -0.01007042],
        abs=1e-5,
    )
    assert state.velocity_km_s[0] == pytest.approx(
        [-1.37034243, 2.19642798, 7.11761638],
        abs=1e-8,
    )


def test_teme_to_ecef_preserves_position_radius(omm_record):
    satellite = satrec_from_omm(omm_record)
    epoch = parse_omm_epoch(omm_record)
    teme = propagate_teme(satellite, [epoch])
    ecef = propagate_ecef(satellite, [epoch])

    assert np.linalg.norm(ecef.position_km[0]) == pytest.approx(
        np.linalg.norm(teme.position_km[0])
    )
    assert ecef.position_km[0] == pytest.approx(
        [-220.519247, -6949.16484, -0.01007042],
        abs=1e-5,
    )


def test_wgs84_equator_and_skku_coordinates():
    equator = geodetic_to_ecef(
        GroundStation(latitude_deg=0.0, longitude_deg=0.0)
    )
    skku = geodetic_to_ecef(GroundStation())

    assert equator == pytest.approx([6378.137, 0.0, 0.0])
    assert skku == pytest.approx(
        [-3055.627349, 4058.682029, 3843.347761],
        abs=1e-6,
    )


def test_naive_datetime_is_rejected(omm_record):
    satellite = satrec_from_omm(omm_record)
    with pytest.raises(ValueError, match="timezone-aware"):
        propagate_teme(satellite, [datetime(2026, 7, 29)])

