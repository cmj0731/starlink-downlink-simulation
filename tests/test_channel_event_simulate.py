import json
from dataclasses import astuple
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from starlink_isl import GroundStation, load_research_baseline
from starlink_isl.channel_event_simulate import (
    EVENT_ORDER,
    run_channel_event_comparison,
)
from starlink_isl.channel_state_io import load_channel_state_csv


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "configs" / "ofdm_baseline.yaml"
OMM_FIXTURE = ROOT / "tests" / "fixtures" / "starlink_5285_omm.json"


def test_three_event_channel_comparison_writes_ordered_metrics(tmp_path):
    config = load_research_baseline(BASELINE_PATH)
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
    references = {
        "visibility_start": datetime(
            2026,
            7,
            29,
            7,
            42,
            36,
            760_675,
            tzinfo=timezone.utc,
        ),
        "closest_approach": datetime(
            2026,
            7,
            29,
            7,
            46,
            50,
            953_295,
            tzinfo=timezone.utc,
        ),
        "visibility_end": datetime(
            2026,
            7,
            29,
            7,
            51,
            2,
            674_438,
            tzinfo=timezone.utc,
        ),
    }
    artifacts = run_channel_event_comparison(
        tmp_path,
        config=config,
        omm_record=record,
        event_references_utc=references,
        station=GroundStation(
            latitude_deg=37.2934,
            longitude_deg=126.9747,
        ),
        symbol_count=16,
        magnitude_observation_step_s=30.0,
    )

    for path in astuple(artifacts):
        assert path.exists()
        assert path.stat().st_size > 0
    for event in EVENT_ORDER:
        event_directory = tmp_path / event
        assert (event_directory / "channel_grid.npz").exists()
        assert (event_directory / "synchronized_channel_grid.npz").exists()
        assert (event_directory / "synchronization_comparison.png").exists()

    metrics = pd.read_csv(artifacts.metrics_csv)
    assert metrics["reference_event"].tolist() == list(EVENT_ORDER)
    start, closest, end = metrics.to_dict(orient="records")
    assert start["reference_slant_range_km"] > closest[
        "reference_slant_range_km"
    ]
    assert end["reference_slant_range_km"] > closest[
        "reference_slant_range_km"
    ]
    assert start["reference_doppler_shift_khz"] * end[
        "reference_doppler_shift_khz"
    ] < 0.0
    assert abs(closest["reference_doppler_shift_khz"]) < abs(
        start["reference_doppler_shift_khz"]
    )
    assert abs(closest["reference_doppler_shift_khz"]) < abs(
        end["reference_doppler_shift_khz"]
    )
    assert set(metrics["reference_value_method"]) == {
        "linear interpolation to relative t=0"
    }
    assert metrics["maximum_absolute_residual_delay_s"].max() == 0.0
    assert metrics["maximum_absolute_residual_phase_rad"].max() == 0.0

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["event_order"] == list(EVENT_ORDER)
    assert summary["shape_per_event"] == [16, 223]
    assert summary["interpretation_limits"][2].startswith("large raw Doppler")
    magnitude_summary = summary["long_duration_magnitude_observation"]
    assert magnitude_summary["time_axis_kind"].startswith("coarse observation")
    assert magnitude_summary["event_times_included_exactly"] is True
    assert magnitude_summary["near_dc_magnitude_time_span_db"] > 9.0
    assert (
        magnitude_summary["near_dc_magnitude_time_span_db"]
        > 100.0
        * magnitude_summary[
            "maximum_frequency_magnitude_span_at_one_time_db"
        ]
    )

    magnitude_frame = pd.read_csv(artifacts.magnitude_evolution_csv)
    event_rows = magnitude_frame.loc[
        magnitude_frame["event"].notna(),
        "event",
    ]
    assert set(event_rows) == set(EVENT_ORDER)
    compact_state = load_channel_state_csv(artifacts.channel_state_csv)
    assert compact_state.sample_count == len(magnitude_frame)
    assert set(compact_state.event_labels) >= set(EVENT_ORDER)
    assert magnitude_summary["compact_channel_state"][
        "frequency_axis_repeated"
    ] is False
    with np.load(artifacts.magnitude_evolution_npz, allow_pickle=False) as saved:
        magnitude = saved["channel_magnitude_db"]
        time_s = saved["time_from_closest_approach_s"]
        frequency_hz = saved["baseband_frequency_hz"]
        assert magnitude.shape == (time_s.size, frequency_hz.size)
        assert np.count_nonzero(time_s == 0.0) == 1
        near_dc = int(np.argmin(np.abs(frequency_hz)))
        closest_index = int(np.flatnonzero(time_s == 0.0)[0])
        assert magnitude[closest_index, near_dc] == np.max(
            magnitude[:, near_dc]
        )
