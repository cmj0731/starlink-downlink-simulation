import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import starlink_isl.channel_grid_simulate as channel_grid_module
from starlink_isl import GroundStation, load_research_baseline
from starlink_isl.channel_grid_simulate import (
    main as channel_grid_main,
    run_channel_grid_simulation,
)
from starlink_isl.sgp4_orbit import (
    propagate_ecef,
    propagate_teme,
    satrec_from_omm,
)
from starlink_isl.si_interface import sgp4_downlink_state_si
from starlink_isl.state_vector_io import (
    STATE_VECTOR_CSV_SCHEMA_VERSION,
    external_state_downlink_si,
    load_satellite_state_csv,
    save_satellite_state_csv,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "configs" / "ofdm_baseline.yaml"
OMM_FIXTURE = ROOT / "tests" / "fixtures" / "starlink_5285_omm.json"
RECORD = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
SATELLITE = satrec_from_omm(RECORD)
REFERENCE = datetime(
    2026,
    7,
    29,
    7,
    46,
    50,
    953_295,
    tzinfo=timezone.utc,
)
EPOCHS = tuple(
    REFERENCE + timedelta(seconds=offset) for offset in (-1.0, 0.0, 1.0)
)


@pytest.mark.parametrize("coordinate_frame", ["ECEF", "TEME"])
def test_state_vector_csv_normalizes_to_ecef(tmp_path, coordinate_frame):
    source_state = (
        propagate_ecef(SATELLITE, EPOCHS)
        if coordinate_frame == "ECEF"
        else propagate_teme(SATELLITE, EPOCHS)
    )
    path = save_satellite_state_csv(
        tmp_path / f"state-{coordinate_frame.lower()}.csv",
        EPOCHS,
        source_state,
        coordinate_frame=coordinate_frame,
        object_name="STARLINK-5285",
        norad_catalog_id=55296,
    )

    frame = pd.read_csv(path)
    assert set(frame["schema_version"]) == {STATE_VECTOR_CSV_SCHEMA_VERSION}
    assert set(frame["coordinate_frame"]) == {coordinate_frame}
    loaded = load_satellite_state_csv(path)
    expected_ecef = propagate_ecef(SATELLITE, EPOCHS)
    assert loaded.source_coordinate_frame == coordinate_frame
    assert loaded.position_velocity_consistency.interval_count == 2
    assert (
        loaded.position_velocity_consistency.maximum_relative_error
        < 1.0e-5
    )
    assert loaded.object_name == "STARLINK-5285"
    assert loaded.norad_catalog_id == 55296
    np.testing.assert_allclose(
        loaded.state_ecef.position_km,
        expected_ecef.position_km,
        rtol=2.0e-15,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        loaded.state_ecef.velocity_km_s,
        expected_ecef.velocity_km_s,
        rtol=2.0e-15,
        atol=1.0e-12,
    )


def test_external_velocity_vectors_reproduce_direct_sgp4_channel(tmp_path):
    config = load_research_baseline(BASELINE_PATH)
    ecef_state = propagate_ecef(SATELLITE, EPOCHS)
    state_path = save_satellite_state_csv(
        tmp_path / "provided-satellite-state.csv",
        EPOCHS,
        ecef_state,
        coordinate_frame="ECEF",
        object_name="STARLINK-5285",
        norad_catalog_id=55296,
    )
    external = load_satellite_state_csv(state_path)
    source_state = external_state_downlink_si(
        external,
        REFERENCE,
        config.radio.carrier_frequency_hz,
        GroundStation(),
        minimum_elevation_deg=10.0,
    )
    direct_source = sgp4_downlink_state_si(
        EPOCHS,
        SATELLITE,
        config.radio.carrier_frequency_hz,
        GroundStation(),
        minimum_elevation_rad=np.deg2rad(10.0),
        time_origin_utc=REFERENCE,
        phase_reference_utc=REFERENCE,
    )
    np.testing.assert_allclose(
        source_state.satellite_velocity_m_s,
        direct_source.satellite_velocity_m_s,
        rtol=2.0e-15,
        atol=1.0e-9,
    )
    np.testing.assert_allclose(
        source_state.radial_velocity_m_s,
        direct_source.radial_velocity_m_s,
        rtol=2.0e-15,
        atol=1.0e-9,
    )

    external_artifacts = run_channel_grid_simulation(
        tmp_path / "external",
        config=config,
        reference_utc=REFERENCE,
        station=GroundStation(),
        minimum_elevation_deg=10.0,
        symbol_count=16,
        source_state=source_state,
        source_metadata={
            "object_name": external.object_name,
            "norad_catalog_id": external.norad_catalog_id,
            "source_coordinate_frame": external.source_coordinate_frame,
        },
    )
    direct_artifacts = run_channel_grid_simulation(
        tmp_path / "direct",
        config=config,
        omm_record=RECORD,
        reference_utc=REFERENCE,
        station=GroundStation(),
        minimum_elevation_deg=10.0,
        symbol_count=16,
    )
    with np.load(
        external_artifacts.channel_grid_npz, allow_pickle=False
    ) as external_grid, np.load(
        direct_artifacts.channel_grid_npz, allow_pickle=False
    ) as direct_grid:
        np.testing.assert_allclose(
            external_grid["channel_response"],
            direct_grid["channel_response"],
            rtol=1.0e-9,
            atol=1.0e-12,
        )
        np.testing.assert_allclose(
            external_grid["doppler_shift_hz"],
            direct_grid["doppler_shift_hz"],
            rtol=1.0e-10,
            atol=1.0e-6,
        )
    external_summary = json.loads(
        external_artifacts.summary_json.read_text(encoding="utf-8")
    )
    assert external_summary["orbit_state"]["reference_model"] == (
        "external state-vector CSV"
    )
    assert external_summary["orbit_state"]["source_coordinate_frame"] == (
        "ECEF"
    )


def test_state_vector_loader_rejects_ambiguous_frames(tmp_path):
    state = propagate_ecef(SATELLITE, EPOCHS)
    path = save_satellite_state_csv(
        tmp_path / "ambiguous.csv",
        EPOCHS,
        state,
        coordinate_frame="ECEF",
    )
    frame = pd.read_csv(path)
    frame.loc[1, "coordinate_frame"] = "TEME"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="one constant value"):
        load_satellite_state_csv(path)


def test_state_vector_loader_rejects_inconsistent_velocity(tmp_path):
    path = save_satellite_state_csv(
        tmp_path / "inconsistent-velocity.csv",
        EPOCHS,
        propagate_ecef(SATELLITE, EPOCHS),
        coordinate_frame="ECEF",
    )
    frame = pd.read_csv(path)
    velocity_columns = [
        "satellite_vx_m_s",
        "satellite_vy_m_s",
        "satellite_vz_m_s",
    ]
    frame[velocity_columns] *= 1_000.0
    frame.to_csv(path, index=False)

    with pytest.raises(
        ValueError,
        match="positions and supplied velocities are inconsistent",
    ):
        load_satellite_state_csv(path)


def test_channel_grid_cli_accepts_external_state_without_sgp4_summary(
    tmp_path,
    monkeypatch,
):
    state_path = save_satellite_state_csv(
        tmp_path / "provided-state.csv",
        EPOCHS,
        propagate_ecef(SATELLITE, EPOCHS),
        coordinate_frame="ECEF",
        object_name="STARLINK-5285",
        norad_catalog_id=55296,
    )
    output = tmp_path / "cli-output"
    monkeypatch.setattr(channel_grid_module, "_save_heatmap", lambda *args: None)
    monkeypatch.setattr(
        channel_grid_module,
        "_save_synchronization_comparison",
        lambda *args: None,
    )
    monkeypatch.setattr(channel_grid_module, "_save_slices", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "starlink-channel-grid",
            "--config",
            str(BASELINE_PATH),
            "--state-csv",
            str(state_path),
            "--geometry-summary",
            str(tmp_path / "does-not-exist.json"),
            "--reference-utc",
            REFERENCE.isoformat(),
            "--station-latitude-deg",
            "37.2934",
            "--station-longitude-deg",
            "126.9747",
            "--station-altitude-m",
            "0",
            "--output",
            str(output),
            "--symbol-count",
            "8",
        ],
    )

    channel_grid_main()

    assert (output / "channel_grid.npz").is_file()
    assert (output / "channel_grid.csv").is_file()
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["object_name"] == "STARLINK-5285"
    assert summary["orbit_state"]["reference_model"] == (
        "external state-vector CSV"
    )
    assert summary["station"] == {
        "latitude_deg": 37.2934,
        "longitude_deg": 126.9747,
        "altitude_m": 0.0,
        "coordinate_definition": "WGS-84 geodetic",
    }
    consistency = summary["orbit_state"]["position_velocity_consistency"]
    assert consistency["passed"] is True
    assert consistency["interval_count"] == 2


def test_channel_grid_cli_requires_station_for_external_state(
    tmp_path,
    monkeypatch,
):
    state_path = save_satellite_state_csv(
        tmp_path / "provided-state.csv",
        EPOCHS,
        propagate_ecef(SATELLITE, EPOCHS),
        coordinate_frame="ECEF",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "starlink-channel-grid",
            "--config",
            str(BASELINE_PATH),
            "--state-csv",
            str(state_path),
            "--geometry-summary",
            str(tmp_path / "does-not-exist.json"),
            "--reference-utc",
            REFERENCE.isoformat(),
            "--output",
            str(tmp_path / "cli-output"),
        ],
    )

    with pytest.raises(
        ValueError,
        match="requires explicit ground-station coordinates",
    ):
        channel_grid_main()
