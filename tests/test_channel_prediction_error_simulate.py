import json
from dataclasses import astuple
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from starlink_isl import GroundStation, load_research_baseline
from starlink_isl.channel_prediction_error_simulate import (
    ERROR_ORDER,
    EVENT_ORDER,
    SPEED_OF_LIGHT_M_S,
    run_channel_prediction_error_comparison,
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


def test_prediction_error_sweeps_write_physical_mappings(tmp_path):
    config = load_research_baseline(BASELINE_PATH)
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]
    artifacts = run_channel_prediction_error_comparison(
        tmp_path,
        config=config,
        omm_record=record,
        event_references_utc=_references(),
        station=GroundStation(
            latitude_deg=37.2934,
            longitude_deg=126.9747,
        ),
        source_symbol_count=32,
        analysis_symbol_count=16,
        range_errors_m=(-1.0, 0.0, 1.0),
        radial_velocity_errors_m_s=(-1.0, 0.0, 1.0),
        timing_errors_ms=(-0.01, 0.0, 0.01),
        doppler_errors_hz=(-120.0, 0.0, 120.0),
    )

    for path in astuple(artifacts):
        assert path.exists()
        assert path.stat().st_size > 0
    metrics = pd.read_csv(artifacts.metrics_csv)
    assert len(metrics) == len(EVENT_ORDER) * len(ERROR_ORDER) * 3
    assert metrics["reference_event"].drop_duplicates().tolist() == list(
        EVENT_ORDER
    )
    assert metrics["error_type"].drop_duplicates().tolist() == list(
        ERROR_ORDER
    )

    start = metrics.loc[metrics["reference_event"] == "visibility_start"]
    range_plus = start.loc[
        (start["error_type"] == "los_range")
        & (start["error_value"] == 1.0)
    ].iloc[0]
    assert range_plus["delay_prediction_bias_ns"] == pytest.approx(
        1.0e9 / SPEED_OF_LIGHT_M_S
    )
    velocity_plus = start.loc[
        (start["error_type"] == "los_radial_velocity")
        & (start["error_value"] == 1.0)
    ].iloc[0]
    assert velocity_plus["doppler_prediction_bias_hz"] == pytest.approx(
        -config.radio.carrier_frequency_hz / SPEED_OF_LIGHT_M_S
    )
    doppler_plus = start.loc[
        (start["error_type"] == "doppler_frequency")
        & (start["error_value"] == 120.0)
    ].iloc[0]
    assert doppler_plus["doppler_prediction_bias_hz"] == 120.0
    assert doppler_plus[
        "doppler_bias_equivalent_radial_velocity_error_m_s"
    ] == pytest.approx(
        -120.0
        * SPEED_OF_LIGHT_M_S
        / config.radio.carrier_frequency_hz
    )
    assert doppler_plus[
        "maximum_absolute_normalized_residual_cfo"
    ] >= (120.0 / config.ofdm.subcarrier_spacing_hz)

    baseline = start.loc[start["error_value"] == 0.0]
    assert baseline["maximum_absolute_residual_cfo_hz"].nunique() == 1
    assert baseline[
        "maximum_absolute_residual_total_phase_cycles"
    ].nunique() == 1

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["event_order"] == list(EVENT_ORDER)
    assert summary["error_order"] == list(ERROR_ORDER)
    assert summary["analysis_symbol_count"] == 16
    assert summary["error_sign_convention"]["residual"] == (
        "truth minus prediction"
    )


def test_prediction_error_sweep_requires_zero(tmp_path):
    config = load_research_baseline(BASELINE_PATH)
    record = json.loads(OMM_FIXTURE.read_text(encoding="utf-8"))[0]

    with pytest.raises(ValueError, match="include zero"):
        run_channel_prediction_error_comparison(
            tmp_path,
            config=config,
            omm_record=record,
            event_references_utc=_references(),
            station=GroundStation(
                latitude_deg=37.2934,
                longitude_deg=126.9747,
            ),
            range_errors_m=(-1.0, 1.0),
        )
