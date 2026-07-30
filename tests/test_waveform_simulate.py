import json
from pathlib import Path

import pandas as pd

from starlink_isl.waveform_simulate import run_waveform_simulation


def test_waveform_simulation_writes_deterministic_outputs(tmp_path: Path):
    geometry_csv = tmp_path / "geometry.csv"
    geometry_summary = tmp_path / "geometry-summary.json"
    pd.DataFrame(
        {
            "utc": [
                "2026-07-29T07:42:36Z",
                "2026-07-29T07:46:50Z",
                "2026-07-29T07:51:02Z",
            ],
            "time_s": [-254.0, 0.0, 252.0],
            "event": [
                "visibility_start",
                "closest_approach",
                "visibility_end",
            ],
            "visible": [True, True, True],
            "elevation_deg": [10.0, 85.0, 10.0],
            "slant_range_km": [1888.0, 580.0, 1873.0],
            "propagation_delay_ms": [6.30, 1.93, 6.25],
            "doppler_shift_hz": [222_954.0, 0.0, -223_102.0],
            "snr_db": [6.0, 12.0, 6.0],
            "carrier_to_noise_density_db_hz": [66.0, 72.0, 66.0],
        }
    ).to_csv(geometry_csv, index=False)
    geometry_summary.write_text(
        json.dumps({"object_name": "STARLINK-5285"}),
        encoding="utf-8",
    )

    artifacts = run_waveform_simulation(
        tmp_path / "waveform",
        geometry_results_csv=geometry_csv,
        geometry_summary_json=geometry_summary,
        symbol_count=20_000,
        snapshot_count=3,
        seed=7,
    )

    for path in (
        artifacts.results_csv,
        artifacts.summary_json,
        artifacts.ber_evm_png,
        artifacts.constellation_png,
    ):
        assert path.is_file()
        assert path.stat().st_size > 100

    results = pd.read_csv(artifacts.results_csv)
    assert set(results["event"]) == {
        "visibility_start",
        "closest_approach",
        "visibility_end",
    }
    closest = results.loc[results["event"] == "closest_approach"].iloc[0]
    assert closest["ber_uncompensated"] == closest["ber_compensated"]
    assert results["ber_compensated"].max() < 0.03
    assert results["ber_uncompensated"].max() > 0.4
    assert results["es_n0_db"].tolist() == [6.0, 12.0, 6.0]

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["source_object_name"] == "STARLINK-5285"
    assert summary["snapshot_count"] == 3
    assert summary["extrema"]["maximum_absolute_doppler_hz"] == 223_102.0
