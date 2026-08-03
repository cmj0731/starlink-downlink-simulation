import json
from dataclasses import astuple
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from starlink_isl import GroundStation, load_research_baseline
from starlink_isl.channel_block_simulate import (
    EVENT_ORDER,
    run_channel_block_comparison,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "configs" / "ofdm_baseline.yaml"
OMM_FIXTURE = ROOT / "tests" / "fixtures" / "starlink_5285_omm.json"


def _references():
    return {
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


def test_channel_block_comparison_writes_nested_metrics(tmp_path):
    config = load_research_baseline(BASELINE_PATH)
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
    artifacts = run_channel_block_comparison(
        tmp_path,
        config=config,
        omm_record=record,
        event_references_utc=_references(),
        station=GroundStation(
            latitude_deg=37.2934,
            longitude_deg=126.9747,
        ),
        block_symbol_counts=(8, 16),
    )

    for path in astuple(artifacts):
        assert path.exists()
        assert path.stat().st_size > 0
    for event in EVENT_ORDER:
        assert (tmp_path / event / "channel_grid.npz").exists()
        assert (tmp_path / event / "synchronized_channel_grid.npz").exists()
        for count in (8, 16):
            block_path = (
                tmp_path
                / event
                / f"block_start_compensation_{count}_symbols.npz"
            )
            assert block_path.exists()
            with np.load(block_path, allow_pickle=False) as saved:
                assert saved["channel_response"].shape == (count, 223)
                assert saved["residual_propagation_delay_s"][0] == 0.0
                assert saved["residual_cfo_hz"][0] == 0.0
                assert saved[
                    "residual_carrier_doppler_phase_rad"
                ][0] == 0.0

    metrics = pd.read_csv(artifacts.metrics_csv)
    assert len(metrics) == 2 * len(EVENT_ORDER)
    assert metrics["reference_event"].tolist() == [
        event
        for event in EVENT_ORDER
        for _ in range(2)
    ]
    expected_duration_ms = {
        count: count * config.ofdm.total_symbol_duration_s * 1.0e3
        for count in (8, 16)
    }
    expected_span_ms = {
        count: (count - 1) * config.ofdm.total_symbol_duration_s * 1.0e3
        for count in (8, 16)
    }
    for row in metrics.to_dict(orient="records"):
        count = row["symbol_count"]
        assert row["nominal_block_duration_ms"] == pytest.approx(
            expected_duration_ms[count]
        )
        assert row["channel_evaluation_span_ms"] == pytest.approx(
            expected_span_ms[count]
        )
        assert 0.0 <= row[
            "minimum_raw_frequency_vector_correlation_magnitude"
        ] <= 1.0 + 1.0e-12
        assert row[
            "minimum_synchronized_frequency_vector_correlation_magnitude"
        ] == pytest.approx(1.0, abs=1.0e-12)
        assert bool(row["magnitude_change_below_0p01_db"])
        assert row[
            "maximum_absolute_block_start_residual_delay_ns"
        ] >= 0.0
        assert row[
            "maximum_absolute_block_start_residual_cfo_hz"
        ] >= 0.0
        assert row[
            "maximum_absolute_block_start_residual_carrier_phase_cycles"
        ] >= 0.0
        assert row["maximum_perfect_normalized_complex_error"] < 1.0e-5

    for event in EVENT_ORDER:
        event_metrics = metrics.loc[metrics["reference_event"] == event]
        assert np.all(np.diff(event_metrics["slant_range_span_m"]) >= 0.0)
        assert np.all(
            np.diff(event_metrics["near_dc_magnitude_span_db"]) >= 0.0
        )
        assert np.all(
            np.diff(
                event_metrics[
                    "maximum_absolute_carrier_phase_excursion_cycles"
                ]
            )
            >= 0.0
        )

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["event_order"] == list(EVENT_ORDER)
    assert summary["block_symbol_counts"] == [8, 16]
    assert summary["block_definition"]["nominal_duration"].startswith("N times")
    assert summary["current_256_symbol_block"] == []
    compensation = summary["block_start_compensation_model"]
    assert compensation["update_count_per_block"] == 1
    assert compensation["uses_later_truth_samples"] is False


@pytest.mark.parametrize(
    "counts, error",
    [
        ((8, 8), "unique"),
        ((8, 15), "same parity"),
        ((1, 2), "at least two"),
    ],
)
def test_channel_block_comparison_rejects_invalid_counts(
    tmp_path,
    counts,
    error,
):
    config = load_research_baseline(BASELINE_PATH)
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
    with pytest.raises(ValueError, match=error):
        run_channel_block_comparison(
            tmp_path,
            config=config,
            omm_record=record,
            event_references_utc=_references(),
            station=GroundStation(
                latitude_deg=37.2934,
                longitude_deg=126.9747,
            ),
            block_symbol_counts=counts,
        )
