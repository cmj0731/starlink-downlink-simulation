"""Deterministic, offline-first reproduction of the STARLINK-5285 study."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "DejaVu Sans"

from starlink_isl.actual_downlink import (  # noqa: E402
    dynamics_from_ecef_states,
    geometry_from_ecef_states,
)
from starlink_isl.celestrak import (  # noqa: E402
    fetch_catalog_omm,
    load_omm,
)
from starlink_isl.channel_block_simulate import (  # noqa: E402
    run_channel_block_comparison,
)
from starlink_isl.channel_event_simulate import (  # noqa: E402
    EVENT_ORDER,
    run_channel_event_comparison,
)
from starlink_isl.channel_grid_simulate import (  # noqa: E402
    run_channel_grid_simulation,
)
from starlink_isl.channel_prediction_error_simulate import (  # noqa: E402
    run_channel_prediction_error_comparison,
)
from starlink_isl.link_budget import LinkBudgetConfig  # noqa: E402
from starlink_isl.research_config import (  # noqa: E402
    ResearchBaselineConfig,
    load_research_baseline,
)
from starlink_isl.sgp4_orbit import (  # noqa: E402
    GroundStation,
    ground_station_ecef_state,
    parse_omm_epoch,
    propagate_ecef,
    satrec_from_omm,
)
from starlink_isl.sgp4_simulate import (  # noqa: E402
    parse_utc,
    run_sgp4_simulation,
)
from starlink_isl.simulate import run_simulation  # noqa: E402
from starlink_isl.waveform_simulate import (  # noqa: E402
    run_waveform_simulation,
)


DEFAULT_SCENARIO_PATH = Path("configs/starlink_5285_reproduction.yaml")
MANIFEST_NAME = "reproduction_manifest.json"

EXPECTED_PHYSICAL_RESULTS = {
    "selected_pass_duration_s": 505.914,
    "minimum_slant_range_km": 579.705,
    "maximum_elevation_deg": 85.164879,
    "closest_to_maximum_elevation_time_difference_s": 0.152,
    "sgp4_maximum_absolute_doppler_hz": 223_102.0,
    "channel_start_doppler_hz": 260_857.0,
    "channel_end_doppler_hz": -261_029.0,
}

# Absolute tolerances reflect numerical optimization/propagation sensitivity,
# not measurement uncertainty. Exact interface checks use zero tolerance.
PHYSICAL_TOLERANCES = {
    "selected_pass_duration_s": 0.05,
    "minimum_slant_range_km": 0.02,
    "maximum_elevation_deg": 0.02,
    "closest_to_maximum_elevation_time_difference_s": 0.02,
    "sgp4_maximum_absolute_doppler_hz": 5.0,
    "channel_start_doppler_hz": 5.0,
    "channel_end_doppler_hz": 5.0,
    "visibility_boundary_elevation_deg": 1.0e-6,
    "range_rate_consistency_km_s": 2.0e-4,
}

REQUIRED_FIGURES = (
    "sgp4_downlink/orbit_3d.png",
    "sgp4_downlink/ground_track.png",
    "sgp4_downlink/geometry.png",
    "sgp4_downlink/delay_doppler.png",
    "sgp4_downlink/link_budget.png",
    "channel_grid/channel_grid_heatmap.png",
    "channel_grid/channel_grid_slices.png",
    "channel_grid/synchronization_comparison.png",
    "channel_events/event_metrics.png",
    "channel_events/event_phase_comparison.png",
    "channel_events/magnitude_evolution.png",
    "channel_blocks/block_length_comparison.png",
    "channel_blocks/block_start_compensation.png",
    "channel_prediction_errors/prediction_error_residual_cfo.png",
    "channel_prediction_errors/prediction_error_residual_phase.png",
)

PACKAGE_DISTRIBUTIONS = {
    "matplotlib": "matplotlib",
    "networkx": "networkx",
    "numpy": "numpy",
    "pandas": "pandas",
    "PyYAML": "PyYAML",
    "requests": "requests",
    "scipy": "scipy",
    "sgp4": "sgp4",
}


class ReproductionError(RuntimeError):
    """Raised when one deterministic reproduction stage fails."""


@dataclass(frozen=True, slots=True)
class ReproductionScenario:
    """Validated SI-valued settings needed by the integrated runner."""

    scenario_path: Path
    repository_root: Path
    name: str
    random_seed: int
    baseline_path: Path
    fixed_omm_path: Path
    latest_cache_path: Path
    output_root: Path
    satellite_name: str
    norad_catalog_id: int
    station_name: str
    station: GroundStation
    search_start_utc: datetime
    search_duration_s: float
    minimum_elevation_deg: float
    coarse_step_s: float
    output_time_step_s: float
    plot_padding_s: float
    link_budget: LinkBudgetConfig
    channel_symbol_count: int
    channel_other_losses_db: float
    magnitude_observation_step_s: float
    block_symbol_counts: tuple[int, ...]
    prediction_source_symbol_count: int
    prediction_analysis_symbol_count: int
    range_errors_m: tuple[float, ...]
    radial_velocity_errors_m_s: tuple[float, ...]
    timing_errors_ms: tuple[float, ...]
    doppler_errors_hz: tuple[float, ...]
    ideal_enabled: bool
    ideal_time_step_s: float
    qpsk_enabled: bool
    qpsk_data_symbol_count: int
    qpsk_pilot_symbol_count: int
    qpsk_symbol_rate_hz: float
    qpsk_snapshot_count: int
    baseline: ResearchBaselineConfig


def _mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return value


def _required(parent: Mapping[str, Any], key: str, prefix: str) -> Any:
    if key not in parent:
        raise ValueError(f"missing required setting: {prefix}.{key}")
    return parent[key]


def _text(parent: Mapping[str, Any], key: str, prefix: str) -> str:
    value = _required(parent, key, prefix)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{prefix}.{key} must be a non-empty string")
    return value.strip()


def _number(parent: Mapping[str, Any], key: str, prefix: str) -> float:
    value = _required(parent, key, prefix)
    if isinstance(value, bool):
        raise TypeError(f"{prefix}.{key} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{prefix}.{key} must be numeric") from exc
    if not np.isfinite(result):
        raise ValueError(f"{prefix}.{key} must be finite")
    return result


def _positive_number(parent: Mapping[str, Any], key: str, prefix: str) -> float:
    result = _number(parent, key, prefix)
    if result <= 0.0:
        raise ValueError(f"{prefix}.{key} must be positive")
    return result


def _integer(parent: Mapping[str, Any], key: str, prefix: str) -> int:
    value = _required(parent, key, prefix)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{prefix}.{key} must be an integer")
    return int(value)


def _positive_integer(parent: Mapping[str, Any], key: str, prefix: str) -> int:
    result = _integer(parent, key, prefix)
    if result <= 0:
        raise ValueError(f"{prefix}.{key} must be positive")
    return result


def _boolean(parent: Mapping[str, Any], key: str, prefix: str) -> bool:
    value = _required(parent, key, prefix)
    if not isinstance(value, bool):
        raise TypeError(f"{prefix}.{key} must be a bool")
    return value


def _number_tuple(
    parent: Mapping[str, Any],
    key: str,
    prefix: str,
) -> tuple[float, ...]:
    values = _required(parent, key, prefix)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError(f"{prefix}.{key} must be a sequence")
    result: list[float] = []
    for index, value in enumerate(values):
        if isinstance(value, bool):
            raise TypeError(f"{prefix}.{key}[{index}] must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"{prefix}.{key}[{index}] must be numeric"
            ) from exc
        if not np.isfinite(number):
            raise ValueError(f"{prefix}.{key}[{index}] must be finite")
        result.append(number)
    if not result:
        raise ValueError(f"{prefix}.{key} must not be empty")
    return tuple(result)


def _integer_tuple(
    parent: Mapping[str, Any],
    key: str,
    prefix: str,
) -> tuple[int, ...]:
    values = _required(parent, key, prefix)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError(f"{prefix}.{key} must be a sequence")
    result: list[int] = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise TypeError(f"{prefix}.{key}[{index}] must be an integer")
        if int(value) <= 0:
            raise ValueError(f"{prefix}.{key}[{index}] must be positive")
        result.append(int(value))
    if not result:
        raise ValueError(f"{prefix}.{key} must not be empty")
    return tuple(result)


def _utc(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError(f"{name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include Z or a timezone offset")
    return parsed.astimezone(timezone.utc)


def _discover_repository_root(scenario_path: Path) -> Path:
    for candidate in (scenario_path.parent, *scenario_path.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "src" / "starlink_isl").is_dir()
        ):
            return candidate.resolve()
    return Path.cwd().resolve()


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_baseline_link(
    channel: Mapping[str, Any],
    baseline: ResearchBaselineConfig,
) -> None:
    expected = {
        "carrier_frequency_hz": baseline.radio.carrier_frequency_hz,
        "fft_size": baseline.ofdm.fft_size,
        "subcarrier_spacing_hz": baseline.ofdm.subcarrier_spacing_hz,
        "cyclic_prefix_samples": baseline.ofdm.cyclic_prefix_samples,
        "active_subcarrier_count": baseline.ofdm.active_subcarrier_count,
        "pilot_spacing_active_subcarriers": (
            baseline.pilot.spacing_active_subcarriers
        ),
    }
    mismatches: list[str] = []
    for key, actual in expected.items():
        configured = _required(channel, key, "channel")
        if isinstance(actual, int):
            matches = (
                not isinstance(configured, bool)
                and isinstance(configured, (int, np.integer))
                and int(configured) == actual
            )
        else:
            try:
                matches = bool(
                    np.isclose(float(configured), actual, rtol=0.0, atol=0.0)
                )
            except (TypeError, ValueError):
                matches = False
        if not matches:
            mismatches.append(f"{key}: scenario={configured!r}, baseline={actual!r}")
    if mismatches:
        raise ValueError(
            "reproduction channel settings drifted from the team baseline: "
            + "; ".join(mismatches)
        )


def load_reproduction_scenario(
    path: str | Path,
    *,
    repository_root: str | Path | None = None,
) -> ReproductionScenario:
    """Load one scenario and verify its explicit baseline contract."""

    scenario_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {scenario_path}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("reproduction scenario root must be a mapping")
    if _integer(raw, "schema_version", "root") != 1:
        raise ValueError("unsupported reproduction schema_version")

    root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else _discover_repository_root(scenario_path)
    )
    metadata = _mapping(raw, "scenario")
    paths = _mapping(raw, "paths")
    satellite = _mapping(raw, "satellite")
    station_raw = _mapping(raw, "ground_station")
    search = _mapping(raw, "pass_search")
    budget = _mapping(raw, "sgp4_link_budget")
    channel = _mapping(raw, "channel")
    prediction = _mapping(raw, "prediction_error_sweep")
    ideal = _mapping(raw, "ideal_reference")
    qpsk = _mapping(raw, "qpsk_reference")

    baseline_path = _resolve_path(
        root, _text(paths, "baseline_config", "paths")
    )
    fixed_omm_path = _resolve_path(root, _text(paths, "fixed_omm", "paths"))
    latest_cache_path = _resolve_path(
        root, _text(paths, "latest_celestrak_cache", "paths")
    )
    output_root = _resolve_path(root, _text(paths, "output_root", "paths"))
    baseline = load_research_baseline(baseline_path)
    _validate_baseline_link(channel, baseline)

    minimum_elevation_deg = _number(
        search, "minimum_elevation_deg", "pass_search"
    )
    if not 0.0 <= minimum_elevation_deg < 90.0:
        raise ValueError("pass_search.minimum_elevation_deg must be in [0, 90)")

    return ReproductionScenario(
        scenario_path=scenario_path,
        repository_root=root,
        name=_text(metadata, "name", "scenario"),
        random_seed=_integer(metadata, "random_seed", "scenario"),
        baseline_path=baseline_path,
        fixed_omm_path=fixed_omm_path,
        latest_cache_path=latest_cache_path,
        output_root=output_root,
        satellite_name=_text(satellite, "object_name", "satellite"),
        norad_catalog_id=_positive_integer(
            satellite, "norad_catalog_id", "satellite"
        ),
        station_name=_text(station_raw, "name", "ground_station"),
        station=GroundStation(
            latitude_deg=_number(
                station_raw, "latitude_deg", "ground_station"
            ),
            longitude_deg=_number(
                station_raw, "longitude_deg", "ground_station"
            ),
            altitude_m=_number(station_raw, "altitude_m", "ground_station"),
        ),
        search_start_utc=_utc(
            _required(search, "start_utc", "pass_search"),
            "pass_search.start_utc",
        ),
        search_duration_s=_positive_number(
            search, "duration_s", "pass_search"
        ),
        minimum_elevation_deg=minimum_elevation_deg,
        coarse_step_s=_positive_number(search, "coarse_step_s", "pass_search"),
        output_time_step_s=_positive_number(
            search, "output_time_step_s", "pass_search"
        ),
        plot_padding_s=_number(search, "plot_padding_s", "pass_search"),
        link_budget=LinkBudgetConfig(
            carrier_frequency_hz=_positive_number(
                budget, "carrier_frequency_hz", "sgp4_link_budget"
            ),
            bandwidth_hz=_positive_number(
                budget, "bandwidth_hz", "sgp4_link_budget"
            ),
            transmit_power_dbw=_number(
                budget, "transmit_power_dbw", "sgp4_link_budget"
            ),
            transmit_antenna_gain_dbi=_number(
                budget, "transmit_antenna_gain_dbi", "sgp4_link_budget"
            ),
            receive_antenna_gain_dbi=_number(
                budget, "receive_antenna_gain_dbi", "sgp4_link_budget"
            ),
            system_noise_temperature_k=_positive_number(
                budget, "system_noise_temperature_k", "sgp4_link_budget"
            ),
            other_losses_db=_number(
                budget, "other_losses_db", "sgp4_link_budget"
            ),
        ),
        channel_symbol_count=_positive_integer(
            channel, "symbol_count", "channel"
        ),
        channel_other_losses_db=_number(
            channel, "other_losses_db", "channel"
        ),
        magnitude_observation_step_s=_positive_number(
            channel, "magnitude_observation_step_s", "channel"
        ),
        block_symbol_counts=_integer_tuple(
            channel, "block_symbol_counts", "channel"
        ),
        prediction_source_symbol_count=_positive_integer(
            prediction, "source_symbol_count", "prediction_error_sweep"
        ),
        prediction_analysis_symbol_count=_positive_integer(
            prediction, "analysis_symbol_count", "prediction_error_sweep"
        ),
        range_errors_m=_number_tuple(
            prediction, "range_errors_m", "prediction_error_sweep"
        ),
        radial_velocity_errors_m_s=_number_tuple(
            prediction,
            "radial_velocity_errors_m_s",
            "prediction_error_sweep",
        ),
        timing_errors_ms=_number_tuple(
            prediction, "timing_errors_ms", "prediction_error_sweep"
        ),
        doppler_errors_hz=_number_tuple(
            prediction, "doppler_errors_hz", "prediction_error_sweep"
        ),
        ideal_enabled=_boolean(ideal, "enabled", "ideal_reference"),
        ideal_time_step_s=_positive_number(
            ideal, "output_time_step_s", "ideal_reference"
        ),
        qpsk_enabled=_boolean(qpsk, "enabled", "qpsk_reference"),
        qpsk_data_symbol_count=_positive_integer(
            qpsk, "data_symbol_count", "qpsk_reference"
        ),
        qpsk_pilot_symbol_count=_positive_integer(
            qpsk, "pilot_symbol_count", "qpsk_reference"
        ),
        qpsk_symbol_rate_hz=_positive_number(
            qpsk, "symbol_rate_hz", "qpsk_reference"
        ),
        qpsk_snapshot_count=_positive_integer(
            qpsk, "snapshot_count", "qpsk_reference"
        ),
        baseline=baseline,
    )


def load_scenario_omm(
    scenario: ReproductionScenario,
    *,
    latest_celestrak: bool = False,
    force_download: bool = False,
    session: Any | None = None,
) -> tuple[dict[str, Any], Path, str]:
    """Load the fixed record offline, or explicitly use CelesTrak/cache."""

    if force_download and not latest_celestrak:
        raise ValueError("--force-download requires --latest-celestrak")
    if latest_celestrak:
        record = fetch_catalog_omm(
            scenario.norad_catalog_id,
            scenario.latest_cache_path,
            force=force_download,
            session=session,
        )
        source_path = scenario.latest_cache_path
        source_kind = "latest_celestrak_or_cache"
    else:
        records = load_omm(scenario.fixed_omm_path)
        matching = [
            record
            for record in records
            if int(record["NORAD_CAT_ID"]) == scenario.norad_catalog_id
        ]
        if len(matching) != 1:
            raise ValueError(
                "fixed OMM must contain exactly one matching NORAD catalog ID"
            )
        record = matching[0]
        source_path = scenario.fixed_omm_path
        source_kind = "fixed_offline"
    if str(record["OBJECT_NAME"]) != scenario.satellite_name:
        raise ValueError(
            "OMM object name does not match the reproduction scenario: "
            f"{record['OBJECT_NAME']!r} != {scenario.satellite_name!r}"
        )
    return record, source_path, source_kind


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _event_references(summary: Mapping[str, Any]) -> dict[str, datetime]:
    selected = summary["selected_pass"]
    return {
        "visibility_start": parse_utc(selected["start_utc"]),
        "closest_approach": parse_utc(selected["closest_approach_utc"]),
        "visibility_end": parse_utc(selected["end_utc"]),
    }


def _range_rate_consistency(
    record: Mapping[str, Any],
    station: GroundStation,
    closest_utc: datetime,
    carrier_frequency_hz: float,
) -> float:
    offsets_s = np.array([-2.0, -0.7, 0.0, 0.4, 1.8])
    datetimes = [
        closest_utc + timedelta(seconds=float(offset))
        for offset in offsets_s
    ]
    satellite = satrec_from_omm(dict(record))
    satellite_state = propagate_ecef(satellite, datetimes)
    ground_state = ground_station_ecef_state(station, len(datetimes))
    geometry = geometry_from_ecef_states(
        satellite_state,
        ground_state,
        station,
    )
    dynamics = dynamics_from_ecef_states(
        geometry,
        satellite_state,
        ground_state,
        carrier_frequency_hz,
        phase_reference_range_km=float(geometry.slant_range_km[2]),
    )
    numerical = np.gradient(geometry.slant_range_km, offsets_s)
    return float(
        np.max(
            np.abs(
                numerical[1:-1] - dynamics.radial_velocity_km_s[1:-1]
            )
        )
    )


def _approximate_check(
    actual: float,
    expected: float,
    tolerance: float,
    unit: str,
) -> dict[str, Any]:
    return {
        "actual": actual,
        "expected": expected,
        "absolute_tolerance": tolerance,
        "unit": unit,
        "passed": bool(abs(actual - expected) <= tolerance),
    }


def validate_physical_results(
    *,
    scenario: ReproductionScenario,
    record: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Validate physical reference values and the frozen H[m,k] contract."""

    sgp4_summary = _json(output_root / "sgp4_downlink" / "summary.json")
    selected = sgp4_summary["selected_pass"]
    closest_utc = parse_utc(selected["closest_approach_utc"])
    maximum_elevation_utc = parse_utc(selected["maximum_elevation_utc"])
    time_difference_s = abs(
        (maximum_elevation_utc - closest_utc).total_seconds()
    )
    event_metrics = pd.read_csv(
        output_root / "channel_events" / "event_comparison.csv"
    ).set_index("reference_event")
    sgp4_frame = pd.read_csv(output_root / "sgp4_downlink" / "results.csv")
    event_labels = sgp4_frame["event"].fillna("").astype(str)
    start_row = sgp4_frame.loc[
        event_labels.str.contains("visibility_start", regex=False)
    ].iloc[0]
    end_row = sgp4_frame.loc[
        event_labels.str.contains("visibility_end", regex=False)
    ].iloc[0]
    range_rate_error = _range_rate_consistency(
        record,
        scenario.station,
        closest_utc,
        scenario.link_budget.carrier_frequency_hz,
    )
    with np.load(
        output_root / "channel_grid" / "channel_grid.npz",
        allow_pickle=False,
    ) as channel_grid:
        shape = tuple(int(value) for value in channel_grid["channel_response"].shape)

    checks: dict[str, dict[str, Any]] = {
        "selected_pass_duration_s": _approximate_check(
            float(selected["duration_s"]),
            EXPECTED_PHYSICAL_RESULTS["selected_pass_duration_s"],
            PHYSICAL_TOLERANCES["selected_pass_duration_s"],
            "s",
        ),
        "minimum_slant_range_km": _approximate_check(
            float(selected["minimum_slant_range_km"]),
            EXPECTED_PHYSICAL_RESULTS["minimum_slant_range_km"],
            PHYSICAL_TOLERANCES["minimum_slant_range_km"],
            "km",
        ),
        "maximum_elevation_deg": _approximate_check(
            float(selected["maximum_elevation_deg"]),
            EXPECTED_PHYSICAL_RESULTS["maximum_elevation_deg"],
            PHYSICAL_TOLERANCES["maximum_elevation_deg"],
            "deg",
        ),
        "closest_to_maximum_elevation_time_difference_s": _approximate_check(
            time_difference_s,
            EXPECTED_PHYSICAL_RESULTS[
                "closest_to_maximum_elevation_time_difference_s"
            ],
            PHYSICAL_TOLERANCES[
                "closest_to_maximum_elevation_time_difference_s"
            ],
            "s",
        ),
        "sgp4_maximum_absolute_doppler_hz": _approximate_check(
            float(
                sgp4_summary["visible_extrema"][
                    "maximum_absolute_doppler_hz"
                ]
            ),
            EXPECTED_PHYSICAL_RESULTS["sgp4_maximum_absolute_doppler_hz"],
            PHYSICAL_TOLERANCES["sgp4_maximum_absolute_doppler_hz"],
            "Hz",
        ),
        "channel_start_doppler_hz": _approximate_check(
            float(
                event_metrics.loc[
                    "visibility_start", "reference_doppler_shift_khz"
                ]
                * 1.0e3
            ),
            EXPECTED_PHYSICAL_RESULTS["channel_start_doppler_hz"],
            PHYSICAL_TOLERANCES["channel_start_doppler_hz"],
            "Hz",
        ),
        "channel_end_doppler_hz": _approximate_check(
            float(
                event_metrics.loc[
                    "visibility_end", "reference_doppler_shift_khz"
                ]
                * 1.0e3
            ),
            EXPECTED_PHYSICAL_RESULTS["channel_end_doppler_hz"],
            PHYSICAL_TOLERANCES["channel_end_doppler_hz"],
            "Hz",
        ),
        "visibility_start_elevation_deg": _approximate_check(
            float(start_row["elevation_deg"]),
            scenario.minimum_elevation_deg,
            PHYSICAL_TOLERANCES["visibility_boundary_elevation_deg"],
            "deg",
        ),
        "visibility_end_elevation_deg": _approximate_check(
            float(end_row["elevation_deg"]),
            scenario.minimum_elevation_deg,
            PHYSICAL_TOLERANCES["visibility_boundary_elevation_deg"],
            "deg",
        ),
        "range_rate_consistency_km_s": {
            "actual_maximum_absolute_error": range_rate_error,
            "maximum_allowed": PHYSICAL_TOLERANCES[
                "range_rate_consistency_km_s"
            ],
            "unit": "km/s",
            "passed": bool(
                range_rate_error
                <= PHYSICAL_TOLERANCES["range_rate_consistency_km_s"]
            ),
        },
        "visibility_boundaries_visible": {
            "actual": [bool(start_row["visible"]), bool(end_row["visible"])],
            "expected": [True, True],
            "passed": bool(start_row["visible"] and end_row["visible"]),
        },
        "closest_and_maximum_elevation_times_are_distinct": {
            "closest_approach_utc": closest_utc.isoformat(),
            "maximum_elevation_utc": maximum_elevation_utc.isoformat(),
            "passed": closest_utc != maximum_elevation_utc,
        },
        "channel_grid_shape_time_frequency": {
            "actual": list(shape),
            "expected": [
                scenario.channel_symbol_count,
                scenario.baseline.ofdm.active_subcarrier_count,
            ],
            "axis_order": ["time", "frequency"],
            "passed": shape
            == (
                scenario.channel_symbol_count,
                scenario.baseline.ofdm.active_subcarrier_count,
            ),
        },
        "active_subcarrier_count": {
            "actual": shape[1],
            "expected": 223,
            "passed": shape[1] == 223,
        },
    }
    failed = [name for name, check in checks.items() if not check["passed"]]
    if failed:
        raise ReproductionError(
            "physical validation failed: " + ", ".join(failed)
        )
    return {
        "all_passed": True,
        "tolerances_are_absolute": True,
        "checks": checks,
    }


def assert_required_figures(output_root: Path) -> list[str]:
    """Require all top-level figures promised by the reproduction contract."""

    missing = [
        relative
        for relative in REQUIRED_FIGURES
        if not (output_root / relative).is_file()
    ]
    if missing:
        raise ReproductionError(
            "required figures were not generated: " + ", ".join(missing)
        )
    return list(REQUIRED_FIGURES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _git_state(repository_root: Path) -> tuple[str, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit, bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        return "unknown", None


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for label, distribution in PACKAGE_DISTRIBUTIONS.items():
        try:
            versions[label] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[label] = "not-installed"
    return versions


def _generated_files(
    output_root: Path,
    generated_directories: Sequence[Path],
) -> list[Path]:
    files = {
        path.resolve()
        for directory in generated_directories
        if directory.is_dir()
        for path in directory.rglob("*")
        if path.is_file()
    }
    return sorted(files, key=lambda path: _display_path(path, output_root))


def write_reproduction_manifest(
    *,
    scenario: ReproductionScenario,
    output_root: Path,
    omm_path: Path,
    omm_source_kind: str,
    record: Mapping[str, Any],
    generated_directories: Sequence[Path],
    physical_validation: Mapping[str, Any],
    required_figures: Sequence[str],
    started_utc: datetime,
    finished_utc: datetime,
) -> Path:
    """Write provenance, checksums, outputs, and physical checks as JSON."""

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / MANIFEST_NAME
    files = _generated_files(output_root, generated_directories)
    numerical_files = [
        path for path in files if path.suffix.lower() in {".csv", ".npz", ".json"}
    ]
    commit, dirty = _git_state(scenario.repository_root)
    manifest = {
        "schema_version": 1,
        "scenario_name": scenario.name,
        "git": {"commit_hash": commit, "working_tree_dirty": dirty},
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "package_versions": _package_versions(),
        "execution": {
            "started_utc": started_utc.isoformat().replace("+00:00", "Z"),
            "finished_utc": finished_utc.isoformat().replace("+00:00", "Z"),
            "duration_s": (finished_utc - started_utc).total_seconds(),
            "random_seed": scenario.random_seed,
            "scenario_file": _display_path(
                scenario.scenario_path, scenario.repository_root
            ),
            "scenario_sha256": sha256_file(scenario.scenario_path),
            "baseline_file": _display_path(
                scenario.baseline_path, scenario.repository_root
            ),
            "baseline_sha256": sha256_file(scenario.baseline_path),
        },
        "orbit_input": {
            "source_kind": omm_source_kind,
            "file": _display_path(omm_path, scenario.repository_root),
            "sha256": sha256_file(omm_path),
            "object_name": str(record["OBJECT_NAME"]),
            "norad_catalog_id": int(record["NORAD_CAT_ID"]),
            "omm_epoch_utc": parse_omm_epoch(dict(record))
            .isoformat()
            .replace("+00:00", "Z"),
        },
        "generated_files": [
            *[
                _display_path(path, scenario.repository_root)
                for path in files
            ],
            _display_path(manifest_path, scenario.repository_root),
        ],
        "numerical_file_sha256": {
            _display_path(path, scenario.repository_root): sha256_file(path)
            for path in numerical_files
        },
        "required_figures": list(required_figures),
        "physical_validation": dict(physical_validation),
        "png_policy": (
            "PNG byte hashes are not pass/fail criteria; numerical arrays and "
            "physical results are validated because OS, font, and Matplotlib "
            "rendering can change PNG bytes."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _stage(
    index: int,
    total: int,
    label: str,
    operation: Callable[[], Any],
    progress: Callable[[str], None],
) -> Any:
    progress(f"[{index}/{total}] {label}")
    try:
        return operation()
    except ReproductionError:
        raise
    except Exception as exc:
        raise ReproductionError(f"stage '{label}' failed: {exc}") from exc


def run_reproduction(
    scenario_path: str | Path = DEFAULT_SCENARIO_PATH,
    *,
    latest_celestrak: bool = False,
    force_download: bool = False,
    output_root: str | Path | None = None,
    progress: Callable[[str], None] = print,
) -> Path:
    """Run every configured stage, validate it, and return the manifest path."""

    started_utc = datetime.now(timezone.utc)
    timer_start = perf_counter()
    scenario = load_reproduction_scenario(scenario_path)
    root = (
        Path(output_root).resolve()
        if output_root is not None
        else scenario.output_root
    )
    root.mkdir(parents=True, exist_ok=True)
    np.random.seed(scenario.random_seed)

    record, omm_path, omm_source_kind = _stage(
        1,
        10,
        "load fixed OMM input"
        if not latest_celestrak
        else "load explicit latest CelesTrak input",
        lambda: load_scenario_omm(
            scenario,
            latest_celestrak=latest_celestrak,
            force_download=force_download,
        ),
        progress,
    )
    sgp4_directory = root / "sgp4_downlink"
    sgp4_artifacts = _stage(
        2,
        10,
        "SGP4 pass, geometry, Doppler, and link budget",
        lambda: run_sgp4_simulation(
            sgp4_directory,
            omm_record=record,
            search_start_utc=scenario.search_start_utc,
            search_hours=scenario.search_duration_s / 3600.0,
            station=scenario.station,
            radio=scenario.link_budget,
            minimum_elevation_deg=scenario.minimum_elevation_deg,
            coarse_step_s=scenario.coarse_step_s,
            time_step_s=scenario.output_time_step_s,
            plot_padding_s=scenario.plot_padding_s,
        ),
        progress,
    )
    summary = _json(sgp4_artifacts.summary_json)
    event_references = _event_references(summary)

    channel_grid_directory = root / "channel_grid"
    _stage(
        3,
        10,
        "complex SISO channel grid H[m,k]",
        lambda: run_channel_grid_simulation(
            channel_grid_directory,
            config=scenario.baseline,
            omm_record=record,
            reference_utc=event_references["closest_approach"],
            station=scenario.station,
            minimum_elevation_deg=scenario.minimum_elevation_deg,
            symbol_count=scenario.channel_symbol_count,
            other_losses_db=scenario.channel_other_losses_db,
            reference_event="closest_approach",
        ),
        progress,
    )

    channel_events_directory = root / "channel_events"
    _stage(
        4,
        10,
        "visibility start, closest approach, and visibility end",
        lambda: run_channel_event_comparison(
            channel_events_directory,
            config=scenario.baseline,
            omm_record=record,
            event_references_utc=event_references,
            station=scenario.station,
            minimum_elevation_deg=scenario.minimum_elevation_deg,
            symbol_count=scenario.channel_symbol_count,
            other_losses_db=scenario.channel_other_losses_db,
            magnitude_observation_step_s=(
                scenario.magnitude_observation_step_s
            ),
        ),
        progress,
    )

    channel_blocks_directory = root / "channel_blocks"
    _stage(
        5,
        10,
        "block-length and block-start compensation analysis",
        lambda: run_channel_block_comparison(
            channel_blocks_directory,
            config=scenario.baseline,
            omm_record=record,
            event_references_utc=event_references,
            station=scenario.station,
            minimum_elevation_deg=scenario.minimum_elevation_deg,
            block_symbol_counts=scenario.block_symbol_counts,
            other_losses_db=scenario.channel_other_losses_db,
        ),
        progress,
    )

    prediction_directory = root / "channel_prediction_errors"
    _stage(
        6,
        10,
        "channel prediction-error sweeps",
        lambda: run_channel_prediction_error_comparison(
            prediction_directory,
            config=scenario.baseline,
            omm_record=record,
            event_references_utc=event_references,
            station=scenario.station,
            minimum_elevation_deg=scenario.minimum_elevation_deg,
            source_symbol_count=scenario.prediction_source_symbol_count,
            analysis_symbol_count=(
                scenario.prediction_analysis_symbol_count
            ),
            range_errors_m=scenario.range_errors_m,
            radial_velocity_errors_m_s=(
                scenario.radial_velocity_errors_m_s
            ),
            timing_errors_ms=scenario.timing_errors_ms,
            doppler_errors_hz=scenario.doppler_errors_hz,
            other_losses_db=scenario.channel_other_losses_db,
        ),
        progress,
    )

    generated_directories = [
        sgp4_directory,
        channel_grid_directory,
        channel_events_directory,
        channel_blocks_directory,
        prediction_directory,
    ]
    ideal_directory = root / "ideal_downlink"
    if scenario.ideal_enabled:
        _stage(
            7,
            10,
            "existing ideal downlink reference",
            lambda: run_simulation(
                ideal_directory,
                radio=scenario.link_budget,
                minimum_elevation_deg=scenario.minimum_elevation_deg,
                time_step_s=scenario.ideal_time_step_s,
            ),
            progress,
        )
        generated_directories.append(ideal_directory)
    else:
        progress("[7/10] existing ideal downlink reference (disabled)")

    qpsk_directory = root / "qpsk_downlink"
    if scenario.qpsk_enabled:
        _stage(
            8,
            10,
            "deterministic QPSK reference waveform",
            lambda: run_waveform_simulation(
                qpsk_directory,
                geometry_results_csv=sgp4_artifacts.results_csv,
                geometry_summary_json=sgp4_artifacts.summary_json,
                symbol_count=scenario.qpsk_data_symbol_count,
                pilot_symbol_count=scenario.qpsk_pilot_symbol_count,
                symbol_rate_hz=scenario.qpsk_symbol_rate_hz,
                snapshot_count=scenario.qpsk_snapshot_count,
                seed=scenario.random_seed,
            ),
            progress,
        )
        generated_directories.append(qpsk_directory)
    else:
        progress("[8/10] deterministic QPSK reference waveform (disabled)")

    physical_validation = _stage(
        9,
        10,
        "required figures and physical reference validation",
        lambda: validate_physical_results(
            scenario=scenario,
            record=record,
            output_root=root,
        ),
        progress,
    )
    required_figures = assert_required_figures(root)
    finished_utc = datetime.now(timezone.utc)
    manifest_path = _stage(
        10,
        10,
        "reproduction manifest",
        lambda: write_reproduction_manifest(
            scenario=scenario,
            output_root=root,
            omm_path=omm_path,
            omm_source_kind=omm_source_kind,
            record=record,
            generated_directories=generated_directories,
            physical_validation=physical_validation,
            required_figures=required_figures,
            started_utc=started_utc,
            finished_utc=finished_utc,
        ),
        progress,
    )
    progress(
        f"Reproduction complete in {perf_counter() - timer_start:.2f} s: "
        f"{manifest_path}"
    )
    return manifest_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=DEFAULT_SCENARIO_PATH,
        help="repository-root-relative reproduction scenario YAML",
    )
    parser.add_argument(
        "--latest-celestrak",
        action="store_true",
        help=(
            "explicitly use the existing CelesTrak/cache interface instead "
            "of the offline fixed OMM"
        ),
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="refresh CelesTrak data; requires --latest-celestrak",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="override paths.output_root (useful for isolated verification)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point with fail-fast, stage-specific diagnostics."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        run_reproduction(
            args.scenario,
            latest_celestrak=args.latest_celestrak,
            force_download=args.force_download,
            output_root=args.output_root,
        )
    except (OSError, ValueError, TypeError, ReproductionError) as exc:
        parser.exit(1, f"reproduction failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
