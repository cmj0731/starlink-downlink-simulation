import json
from dataclasses import astuple
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from starlink_isl import GroundStation, load_research_baseline
from starlink_isl.channel_grid_simulate import run_channel_grid_simulation
from starlink_isl.channel_io import MAX_CHANNEL_CSV_CELLS


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "configs" / "ofdm_baseline.yaml"
OMM_FIXTURE = ROOT / "tests" / "fixtures" / "starlink_5285_omm.json"


def test_channel_grid_simulation_writes_viewable_artifacts(tmp_path):
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
        station=GroundStation(
            latitude_deg=37.2934,
            longitude_deg=126.9747,
        ),
        symbol_count=16,
    )

    for path in astuple(artifacts):
        assert path.exists()
        assert path.stat().st_size > 0

    with np.load(artifacts.channel_grid_npz, allow_pickle=False) as saved:
        assert saved["channel_response"].shape == (16, 223)
        assert saved["channel_variant"].item() == "raw"
        assert saved["delay_compensation"].item() == "none"
        assert saved["doppler_compensation"].item() == "none"
        assert saved["time_s"][0] < 0.0 < saved["time_s"][-1]
    with np.load(
        artifacts.synchronized_channel_grid_npz,
        allow_pickle=False,
    ) as saved:
        synchronized_response = saved["channel_response"]
        assert synchronized_response.shape == (16, 223)
        assert np.max(np.abs(np.angle(synchronized_response))) == 0.0
        assert saved["prediction_label"].item() == (
            "perfect_same_state_prediction"
        )
        assert saved["channel_variant"].item() == "perfectly_compensated"
    with np.load(
        artifacts.block_start_synchronized_channel_grid_npz,
        allow_pickle=False,
    ) as saved:
        assert saved["channel_response"].shape == (16, 223)
        assert saved["prediction_label"].item().startswith("block_start")
        assert saved["channel_variant"].item() == "block_start_compensated"
        assert saved["residual_propagation_delay_s"][0] == 0.0
        assert saved["residual_carrier_doppler_phase_rad"][0] == 0.0
    time_axis = pd.read_csv(artifacts.time_axis_csv)
    frequency_axis = pd.read_csv(artifacts.frequency_axis_csv)
    assert len(time_axis) == 16
    assert len(frequency_axis) == 223
    shifted_endpoints = (
        frequency_axis["fftshift_bin_index"].iloc[[0, -1]].tolist()
    )
    assert shifted_endpoints == [16, 239]
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["shape"] == [16, 223]
    assert summary["heatmap_axis_convention"] == {
        "x": "time_from_reference_event_ms",
        "y": "baseband_subcarrier_frequency_mhz",
        "displayed_values": "transpose of H[m,k] for visualization only",
    }
    assert summary["waveform_bin_order"] == "fftshifted"
    assert summary["channel_artifacts"]["channel_grid.csv"] == {
        "generated": True,
        "channel_variant": "raw",
        "delay_compensation": "none",
        "doppler_compensation": "none",
        "maximum_allowed_cells": MAX_CHANNEL_CSV_CELLS,
    }
    synchronization = summary["phase_synchronization"]
    assert synchronization["prediction_label"] == (
        "perfect_same_state_prediction"
    )
    assert synchronization["maximum_absolute_residual_delay_s"] == 0.0
    assert synchronization["maximum_absolute_residual_total_phase_rad"] == 0.0
    assert synchronization["maximum_magnitude_change_db"] == 0.0
    block_start = summary["block_start_phase_synchronization"]
    assert block_start["prediction_label"].startswith("block_start")
    assert block_start["maximum_absolute_residual_delay_s"] > 0.0
    assert block_start["maximum_absolute_residual_cfo_hz"] > 0.0
    assert block_start["maximum_magnitude_change_db"] == 0.0
    assert summary["norad_catalog_id"] == 55296
    assert summary["scope_limitations"][1].startswith("within-symbol Doppler")
