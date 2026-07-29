import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from starlink_isl.link_budget import LinkBudgetConfig
from starlink_isl.sgp4_orbit import GroundStation
from starlink_isl.sgp4_simulate import (
    parse_utc,
    run_sgp4_simulation,
)


FIXTURE = Path(__file__).parent / "fixtures" / "starlink_5285_omm.json"
RECORD = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
RADIO = LinkBudgetConfig(
    carrier_frequency_hz=10.0e9,
    bandwidth_hz=100.0e6,
    transmit_power_dbw=10.0,
    transmit_antenna_gain_dbi=30.0,
    receive_antenna_gain_dbi=40.0,
    system_noise_temperature_k=290.0,
    other_losses_db=2.0,
)


def test_parse_utc_requires_timezone():
    assert parse_utc("2026-07-29T00:00:00Z") == datetime(
        2026,
        7,
        29,
        tzinfo=timezone.utc,
    )
    with pytest.raises(ValueError, match="timezone"):
        parse_utc("2026-07-29T00:00:00")


def test_sgp4_simulation_writes_separate_complete_outputs(tmp_path: Path):
    artifacts = run_sgp4_simulation(
        tmp_path,
        omm_record=RECORD,
        search_start_utc=datetime(
            2026,
            7,
            29,
            7,
            0,
            tzinfo=timezone.utc,
        ),
        search_hours=2.0,
        station=GroundStation(),
        radio=RADIO,
        minimum_elevation_deg=10.0,
        time_step_s=1.0,
    )

    for path in (
        artifacts.source_omm_json,
        artifacts.passes_csv,
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
    events = frame.loc[frame["event"].notna()].set_index("event")
    assert set(events.index) == {
        "visibility_start",
        "closest_approach",
        "visibility_end",
    }
    assert events.loc["visibility_start", "elevation_deg"] == pytest.approx(
        10.0,
        abs=1e-7,
    )
    assert events.loc["visibility_end", "elevation_deg"] == pytest.approx(
        10.0,
        abs=1e-7,
    )
    assert events.loc[
        "closest_approach", "radial_velocity_km_s"
    ] == pytest.approx(0.0, abs=1e-7)

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["model"] == "CelesTrak OMM / SGP4 downlink"
    assert summary["norad_catalog_id"] == 55296
    assert summary["pass_count"] == 1
    assert summary["selected_pass"]["maximum_elevation_deg"] == pytest.approx(
        85.164,
        abs=0.01,
    )

    for path in (
        artifacts.orbit_3d_png,
        artifacts.ground_track_png,
        artifacts.geometry_png,
        artifacts.delay_doppler_png,
        artifacts.link_budget_png,
    ):
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
