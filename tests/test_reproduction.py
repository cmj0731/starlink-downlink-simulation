import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

from starlink_isl.channel_event_simulate import EVENT_ORDER
from starlink_isl.channel_grid_simulate import run_channel_grid_simulation
from starlink_isl.reproduction import (
    REQUIRED_FIGURES,
    load_reproduction_scenario,
    load_scenario_omm,
    run_reproduction,
)
from starlink_isl.sgp4_simulate import parse_utc
from starlink_isl.waveform_simulate import run_waveform_simulation


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "configs" / "starlink_5285_reproduction.yaml"


@pytest.fixture(scope="module")
def reproduced(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("starlink-reproduction")
    manifest_path = run_reproduction(
        SCENARIO_PATH,
        output_root=output_root,
        progress=lambda _message: None,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return output_root, manifest


def test_fixed_omm_reproduction_does_not_request_network(monkeypatch):
    scenario = load_reproduction_scenario(SCENARIO_PATH)

    def fail_network(*_args, **_kwargs):
        raise AssertionError("network request attempted")

    monkeypatch.setattr(requests.Session, "get", fail_network)
    record, source_path, source_kind = load_scenario_omm(scenario)

    assert record["OBJECT_NAME"] == "STARLINK-5285"
    assert int(record["NORAD_CAT_ID"]) == 55296
    assert source_path == scenario.fixed_omm_path
    assert source_kind == "fixed_offline"


def test_reproduction_generates_required_and_nested_figures(reproduced):
    output_root, _manifest = reproduced
    for relative_path in REQUIRED_FIGURES:
        path = output_root / relative_path
        assert path.is_file(), relative_path
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    for parent in (
        "channel_events",
        "channel_blocks",
        "channel_prediction_errors",
    ):
        for event in EVENT_ORDER:
            event_directory = output_root / parent / event
            for filename in (
                "channel_grid_heatmap.png",
                "channel_grid_slices.png",
                "synchronization_comparison.png",
            ):
                assert (event_directory / filename).is_file()


def test_reproduction_manifest_has_provenance_hashes_and_physics(reproduced):
    _output_root, manifest = reproduced
    assert manifest["schema_version"] == 1
    assert len(manifest["git"]["commit_hash"]) == 40
    assert manifest["python"]["version"]
    assert set(manifest["package_versions"]) >= {
        "matplotlib",
        "numpy",
        "pandas",
        "PyYAML",
        "scipy",
        "sgp4",
    }
    assert manifest["execution"]["random_seed"] == 55285
    assert manifest["orbit_input"]["source_kind"] == "fixed_offline"
    assert len(manifest["orbit_input"]["sha256"]) == 64
    assert manifest["orbit_input"]["omm_epoch_utc"] == (
        "2026-07-27T11:53:54.484800Z"
    )
    assert len(manifest["generated_files"]) > 100
    assert len(manifest["numerical_file_sha256"]) > 50
    assert all(
        len(digest) == 64
        for digest in manifest["numerical_file_sha256"].values()
    )
    validation = manifest["physical_validation"]
    assert validation["all_passed"] is True
    assert all(check["passed"] for check in validation["checks"].values())
    assert validation["checks"]["channel_grid_shape_time_frequency"][
        "actual"
    ] == [256, 223]


def test_same_scenario_and_seed_reproduce_identical_numeric_outputs(
    reproduced,
    tmp_path,
):
    output_root, _manifest = reproduced
    scenario = load_reproduction_scenario(SCENARIO_PATH)
    record, _source_path, _source_kind = load_scenario_omm(scenario)
    geometry_summary = json.loads(
        (output_root / "sgp4_downlink" / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    closest_utc = parse_utc(
        geometry_summary["selected_pass"]["closest_approach_utc"]
    )

    grid_paths = []
    for name in ("first", "second"):
        artifacts = run_channel_grid_simulation(
            tmp_path / name / "grid",
            config=scenario.baseline,
            omm_record=record,
            reference_utc=closest_utc,
            station=scenario.station,
            minimum_elevation_deg=scenario.minimum_elevation_deg,
            symbol_count=16,
            other_losses_db=scenario.channel_other_losses_db,
        )
        grid_paths.append(artifacts.channel_grid_npz)

    with np.load(grid_paths[0], allow_pickle=False) as first, np.load(
        grid_paths[1], allow_pickle=False
    ) as second:
        assert set(first.files) == set(second.files)
        for key in first.files:
            np.testing.assert_array_equal(first[key], second[key])

    waveform_results = []
    for name in ("first", "second"):
        artifacts = run_waveform_simulation(
            tmp_path / name / "waveform",
            geometry_results_csv=output_root
            / "sgp4_downlink"
            / "results.csv",
            geometry_summary_json=output_root
            / "sgp4_downlink"
            / "summary.json",
            symbol_count=512,
            pilot_symbol_count=32,
            symbol_rate_hz=scenario.qpsk_symbol_rate_hz,
            snapshot_count=5,
            seed=scenario.random_seed,
        )
        waveform_results.append(pd.read_csv(artifacts.results_csv))
    pd.testing.assert_frame_equal(
        waveform_results[0],
        waveform_results[1],
        check_exact=True,
    )
