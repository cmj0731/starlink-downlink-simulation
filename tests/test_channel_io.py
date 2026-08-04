import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import starlink_isl.channel_grid_simulate as channel_grid_module
from starlink_isl import GroundStation, load_research_baseline
from starlink_isl.channel_grid_simulate import run_channel_grid_simulation
from starlink_isl.channel_io import (
    CHANNEL_CSV_SCHEMA_VERSION,
    load_channel_grid_csv,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "configs" / "ofdm_baseline.yaml"
OMM_FIXTURE = ROOT / "tests" / "fixtures" / "starlink_5285_omm.json"


def test_channel_csv_round_trip_preserves_complex_grid(tmp_path, monkeypatch):
    monkeypatch.setattr(channel_grid_module, "_save_heatmap", lambda *args: None)
    monkeypatch.setattr(
        channel_grid_module,
        "_save_synchronization_comparison",
        lambda *args: None,
    )
    monkeypatch.setattr(channel_grid_module, "_save_slices", lambda *args: None)
    config = load_research_baseline(BASELINE_PATH)
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
    artifacts = run_channel_grid_simulation(
        tmp_path,
        config=config,
        omm_record=record,
        reference_utc=datetime(
            2026,
            7,
            29,
            7,
            46,
            50,
            953_295,
            tzinfo=timezone.utc,
        ),
        station=GroundStation(),
        symbol_count=8,
    )

    assert artifacts.channel_grid_csv is not None
    assert artifacts.channel_grid_csv.is_file()
    raw_csv = pd.read_csv(artifacts.channel_grid_csv)
    assert len(raw_csv) == 8 * 223
    assert set(raw_csv["schema_version"]) == {CHANNEL_CSV_SCHEMA_VERSION}
    assert set(raw_csv["channel_variant"]) == {"raw"}
    assert set(raw_csv["delay_compensation"]) == {"none"}
    assert set(raw_csv["doppler_compensation"]) == {"none"}
    assert raw_csv[["h_real", "h_imag"]].notna().all().all()

    loaded = load_channel_grid_csv(artifacts.channel_grid_csv)
    assert loaded.channel_variant == "raw"
    assert loaded.delay_compensation == "none"
    assert loaded.doppler_compensation == "none"
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["channel_artifacts"]["channel_grid.csv"] == {
        "generated": True,
        "channel_variant": "raw",
        "delay_compensation": "none",
        "doppler_compensation": "none",
    }
    with np.load(artifacts.channel_grid_npz, allow_pickle=False) as expected:
        assert loaded.shape == (8, 223)
        assert expected["channel_variant"].item() == "raw"
        np.testing.assert_allclose(
            loaded.channel_response,
            expected["channel_response"],
            rtol=2.0e-15,
            atol=0.0,
        )
        np.testing.assert_array_equal(loaded.time_s, expected["time_s"])
        np.testing.assert_array_equal(
            loaded.baseband_frequency_hz,
            expected["baseband_frequency_hz"],
        )
        np.testing.assert_allclose(
            loaded.radial_velocity_m_s,
            expected["radial_velocity_m_s"],
            rtol=2.0e-15,
            atol=0.0,
        )
        np.testing.assert_allclose(
            loaded.doppler_shift_hz,
            expected["doppler_shift_hz"],
            rtol=2.0e-15,
            atol=0.0,
        )

    mixed_path = tmp_path / "mixed-channel-variant.csv"
    raw_csv.loc[0, "channel_variant"] = "perfectly_compensated"
    raw_csv.to_csv(mixed_path, index=False)
    with pytest.raises(ValueError, match="channel_variant must be one"):
        load_channel_grid_csv(mixed_path)


def test_channel_csv_loader_rejects_missing_complex_component(tmp_path):
    path = tmp_path / "broken.csv"
    pd.DataFrame(
        {
            "schema_version": [CHANNEL_CSV_SCHEMA_VERSION],
            "symbol_index": [0],
        }
    ).to_csv(path, index=False)

    with pytest.raises(ValueError, match="missing required columns"):
        load_channel_grid_csv(path)
