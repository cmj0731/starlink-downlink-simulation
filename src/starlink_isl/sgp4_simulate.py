"""Run a real STARLINK downlink pass from CelesTrak OMM and SGP4."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sgp4.api import Satrec

from starlink_isl.actual_downlink import (
    ActualPass,
    dynamics_from_ecef_states,
    find_visibility_passes,
    geometry_from_ecef_states,
    link_budget_from_geometry,
)
from starlink_isl.ideal_orbit import KinematicState
from starlink_isl.link_budget import LinkBudgetConfig
from starlink_isl.sgp4_orbit import (
    GroundStation,
    ecef_to_geodetic,
    ground_station_ecef_state,
    parse_omm_epoch,
    propagate_ecef,
    satrec_from_omm,
)
from starlink_isl.simulate import (
    _break_longitude_wrap,
    _mark_pass_events,
    _save_delay_doppler,
    _save_geometry,
    _save_link_budget,
    build_time_samples,
)

DEFAULT_SGP4_OUTPUT_DIRECTORY = Path("outputs/sgp4_downlink")


@dataclass(frozen=True, slots=True)
class SGP4SimulationArtifacts:
    """Paths written by a real-orbit simulation."""

    source_omm_json: Path
    passes_csv: Path
    results_csv: Path
    summary_json: Path
    orbit_3d_png: Path
    ground_track_png: Path
    geometry_png: Path
    delay_doppler_png: Path
    link_budget_png: Path


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit timezone."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC timestamp must include Z or a timezone offset")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _datetime_samples(
    selected_pass: ActualPass,
    time_step_s: float,
    padding_s: float,
) -> list[datetime]:
    start = selected_pass.start_utc - timedelta(seconds=padding_s)
    end = selected_pass.end_utc + timedelta(seconds=padding_s)
    timestamps = build_time_samples(
        start.timestamp(),
        end.timestamp(),
        time_step_s,
        event_times_s=(
            selected_pass.start_utc.timestamp(),
            selected_pass.closest_approach_utc.timestamp(),
            selected_pass.maximum_elevation_utc.timestamp(),
            selected_pass.end_utc.timestamp(),
        ),
    )
    return [
        datetime.fromtimestamp(float(timestamp), timezone.utc)
        for timestamp in timestamps
    ]


def _actual_frame(
    datetimes: list[datetime],
    satellite: Satrec,
    station: GroundStation,
    radio: LinkBudgetConfig,
    minimum_elevation_deg: float,
    selected_pass: ActualPass,
) -> pd.DataFrame:
    satellite_state = propagate_ecef(satellite, datetimes)
    ground_state = ground_station_ecef_state(station, len(datetimes))
    geometry = geometry_from_ecef_states(
        satellite_state,
        ground_state,
        station,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    reference_state = propagate_ecef(
        satellite,
        [selected_pass.closest_approach_utc],
    )
    reference_ground = ground_station_ecef_state(station, 1)
    reference_geometry = geometry_from_ecef_states(
        reference_state,
        reference_ground,
        station,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    dynamics = dynamics_from_ecef_states(
        geometry,
        satellite_state,
        ground_state,
        radio.carrier_frequency_hz,
        phase_reference_range_km=float(
            reference_geometry.slant_range_km.item()
        ),
    )
    budget = link_budget_from_geometry(geometry, radio)
    longitude, latitude, altitude = ecef_to_geodetic(
        satellite_state.position_km
    )
    radius = np.linalg.norm(satellite_state.position_km, axis=-1)
    relative_time = np.array(
        [
            (value - selected_pass.closest_approach_utc).total_seconds()
            for value in datetimes
        ]
    )

    frame = pd.DataFrame(
        {
            "utc": [_iso(value) for value in datetimes],
            "time_s": relative_time,
            "satellite_x_ecef_km": satellite_state.position_km[:, 0],
            "satellite_y_ecef_km": satellite_state.position_km[:, 1],
            "satellite_z_ecef_km": satellite_state.position_km[:, 2],
            "satellite_vx_ecef_km_s": satellite_state.velocity_km_s[:, 0],
            "satellite_vy_ecef_km_s": satellite_state.velocity_km_s[:, 1],
            "satellite_vz_ecef_km_s": satellite_state.velocity_km_s[:, 2],
            "satellite_geodetic_longitude_deg": longitude,
            "satellite_geodetic_latitude_deg": latitude,
            "satellite_geodetic_altitude_km": altitude,
            # Backward-compatible aliases; both now use WGS-84 geodetic axes.
            "satellite_longitude_deg": longitude,
            "satellite_latitude_deg": latitude,
            "satellite_radius_km": radius,
            "ground_station_geodetic_longitude_deg": (
                station.longitude_deg
            ),
            "ground_station_geodetic_latitude_deg": station.latitude_deg,
            "ground_station_geodetic_altitude_m": station.altitude_m,
            "slant_range_km": geometry.slant_range_km,
            "surface_distance_km": geometry.surface_distance_km,
            "azimuth_deg": geometry.azimuth_deg,
            "elevation_deg": geometry.elevation_deg,
            "visible": geometry.visible,
            "propagation_delay_ms": dynamics.propagation_delay_s * 1e3,
            "radial_velocity_km_s": dynamics.radial_velocity_km_s,
            "doppler_shift_hz": dynamics.doppler_shift_hz,
            "doppler_phase_rad": dynamics.doppler_phase_rad,
            "free_space_path_loss_db": budget.free_space_path_loss_db,
            "received_power_dbw": budget.received_power_dbw,
            "thermal_noise_power_dbw": budget.thermal_noise_power_dbw,
            "carrier_to_noise_density_db_hz": (
                budget.carrier_to_noise_density_db_hz
            ),
            "snr_db": budget.snr_db,
        }
    )
    frame["event"] = ""
    events = (
        (selected_pass.start_utc.timestamp(), "visibility_start"),
        (
            selected_pass.maximum_elevation_utc.timestamp(),
            "maximum_elevation",
        ),
        (
            selected_pass.closest_approach_utc.timestamp(),
            "closest_approach",
        ),
        (selected_pass.end_utc.timestamp(), "visibility_end"),
    )
    timestamps = np.array([value.timestamp() for value in datetimes])
    for timestamp, label in events:
        matches = timestamps == timestamp
        if not np.any(matches):
            raise RuntimeError(f"missing event timestamp: {label}")
        existing = frame.loc[matches, "event"]
        frame.loc[matches, "event"] = existing.map(
            lambda value: f"{value};{label}" if value else label
        )
    return frame


def _full_orbit_states(
    satellite: Satrec,
    selected_pass: ActualPass,
) -> tuple[list[datetime], KinematicState]:
    period_s = 2.0 * np.pi / satellite.no_kozai * 60.0
    offsets = np.linspace(-0.5 * period_s, 0.5 * period_s, 1_441)
    datetimes = [
        selected_pass.closest_approach_utc
        + timedelta(seconds=float(offset))
        for offset in offsets
    ]
    return datetimes, propagate_ecef(satellite, datetimes)


def _save_actual_orbit_3d(
    frame: pd.DataFrame,
    satellite: Satrec,
    station: GroundStation,
    selected_pass: ActualPass,
    path: Path,
) -> None:
    _, full_state = _full_orbit_states(satellite, selected_pass)
    figure = plt.figure(figsize=(8.0, 7.0), constrained_layout=True)
    axis = figure.add_subplot(111, projection="3d")

    longitude = np.linspace(0.0, 2.0 * np.pi, 40)
    latitude = np.linspace(-0.5 * np.pi, 0.5 * np.pi, 20)
    radius = 6_378.137
    earth_x = radius * np.outer(np.cos(latitude), np.cos(longitude))
    earth_y = radius * np.outer(np.cos(latitude), np.sin(longitude))
    earth_z = radius * np.outer(np.sin(latitude), np.ones_like(longitude))
    axis.plot_wireframe(
        earth_x,
        earth_y,
        earth_z,
        rstride=3,
        cstride=4,
        color="0.75",
        linewidth=0.35,
    )
    axis.plot(
        full_state.position_km[:, 0],
        full_state.position_km[:, 1],
        full_state.position_km[:, 2],
        color="0.55",
        linewidth=0.8,
        label="One-orbit ECEF reference",
    )
    analysis = frame[
        [
            "satellite_x_ecef_km",
            "satellite_y_ecef_km",
            "satellite_z_ecef_km",
        ]
    ].to_numpy()
    axis.plot(
        analysis[:, 0],
        analysis[:, 1],
        analysis[:, 2],
        color="tab:blue",
        linewidth=1.5,
        label="Analysis interval",
    )
    visible = analysis.copy()
    visible[~frame["visible"].to_numpy()] = np.nan
    axis.plot(
        visible[:, 0],
        visible[:, 1],
        visible[:, 2],
        color="tab:blue",
        linewidth=3.2,
        label="Visible interval",
    )
    ground = ground_station_ecef_state(station, 1).position_km[0]
    axis.scatter(
        [ground[0]],
        [ground[1]],
        [ground[2]],
        color="tab:orange",
        marker="^",
        s=55,
        label="Ground station",
    )
    closest = frame.loc[frame["event"] == "closest_approach"].iloc[0]
    axis.scatter(
        [closest["satellite_x_ecef_km"]],
        [closest["satellite_y_ecef_km"]],
        [closest["satellite_z_ecef_km"]],
        color="tab:blue",
        marker="o",
        label="Closest approach",
    )
    limit = 7_300.0
    axis.set(
        xlim=(-limit, limit),
        ylim=(-limit, limit),
        zlim=(-limit, limit),
        xlabel="ECEF x (km)",
        ylabel="ECEF y (km)",
        zlabel="ECEF z (km)",
        title="SGP4 orbit reference and selected SKKU pass",
    )
    axis.set_box_aspect((1.0, 1.0, 1.0))
    axis.legend(loc="upper left")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _save_actual_ground_track(
    frame: pd.DataFrame,
    satellite: Satrec,
    station: GroundStation,
    selected_pass: ActualPass,
    path: Path,
) -> None:
    _, full_state = _full_orbit_states(satellite, selected_pass)
    full_longitude, full_latitude, _ = ecef_to_geodetic(
        full_state.position_km
    )
    full_longitude, full_latitude = _break_longitude_wrap(
        full_longitude,
        full_latitude,
    )
    analysis_longitude, analysis_latitude = _break_longitude_wrap(
        frame["satellite_geodetic_longitude_deg"],
        frame["satellite_geodetic_latitude_deg"],
    )
    visible_longitude = frame[
        "satellite_geodetic_longitude_deg"
    ].to_numpy(copy=True)
    visible_latitude = frame[
        "satellite_geodetic_latitude_deg"
    ].to_numpy(copy=True)
    invisible = ~frame["visible"].to_numpy()
    visible_longitude[invisible] = np.nan
    visible_latitude[invisible] = np.nan
    visible_longitude, visible_latitude = _break_longitude_wrap(
        visible_longitude,
        visible_latitude,
    )

    figure, axis = plt.subplots(
        figsize=(9.0, 4.8),
        constrained_layout=True,
    )
    axis.plot(
        full_longitude,
        full_latitude,
        color="0.6",
        linewidth=0.8,
        label="One-orbit ground track",
    )
    axis.plot(
        analysis_longitude,
        analysis_latitude,
        color="tab:blue",
        linewidth=1.5,
        label="Analysis interval",
    )
    axis.plot(
        visible_longitude,
        visible_latitude,
        color="tab:blue",
        linewidth=3.2,
        label="Visible interval",
    )
    axis.scatter(
        [station.longitude_deg],
        [station.latitude_deg],
        color="tab:orange",
        marker="^",
        s=65,
        label="SKKU ground station",
    )
    axis.set(
        xlim=(-180.0, 180.0),
        ylim=(-90.0, 90.0),
        xticks=np.arange(-180.0, 181.0, 60.0),
        yticks=np.arange(-90.0, 91.0, 30.0),
        xlabel="Longitude (deg)",
        ylabel="Geodetic latitude (deg)",
        title="SGP4 ground track and selected visible pass",
    )
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _passes_frame(passes: list[ActualPass]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "start_utc": _iso(item.start_utc),
                "closest_approach_utc": _iso(item.closest_approach_utc),
                "maximum_elevation_utc": _iso(
                    item.maximum_elevation_utc
                ),
                "end_utc": _iso(item.end_utc),
                "duration_s": item.duration_s,
                "maximum_elevation_deg": item.maximum_elevation_deg,
                "minimum_slant_range_km": item.minimum_slant_range_km,
            }
            for item in passes
        ]
    )


def _summary(
    record: dict[str, Any],
    station: GroundStation,
    radio: LinkBudgetConfig,
    search_start: datetime,
    search_end: datetime,
    passes: list[ActualPass],
    selected_pass: ActualPass,
    frame: pd.DataFrame,
    minimum_elevation_deg: float,
) -> dict[str, Any]:
    visible = frame.loc[frame["visible"]]
    return {
        "model": "CelesTrak OMM / SGP4 downlink",
        "object_name": record["OBJECT_NAME"],
        "norad_catalog_id": int(record["NORAD_CAT_ID"]),
        "omm_epoch_utc": _iso(parse_omm_epoch(record)),
        "search_start_utc": _iso(search_start),
        "search_end_utc": _iso(search_end),
        "station": asdict(station),
        "radio": asdict(radio),
        "radio_parameters_are_illustrative": True,
        "minimum_elevation_deg": minimum_elevation_deg,
        "pass_count": len(passes),
        "selected_pass": {
            **asdict(selected_pass),
            "start_utc": _iso(selected_pass.start_utc),
            "closest_approach_utc": _iso(
                selected_pass.closest_approach_utc
            ),
            "maximum_elevation_utc": _iso(
                selected_pass.maximum_elevation_utc
            ),
            "end_utc": _iso(selected_pass.end_utc),
        },
        "sample_count": len(frame),
        "visible_extrema": {
            "minimum_slant_range_km": float(visible["slant_range_km"].min()),
            "maximum_slant_range_km": float(visible["slant_range_km"].max()),
            "minimum_delay_ms": float(visible["propagation_delay_ms"].min()),
            "maximum_delay_ms": float(visible["propagation_delay_ms"].max()),
            "maximum_absolute_doppler_hz": float(
                visible["doppler_shift_hz"].abs().max()
            ),
            "minimum_received_power_dbw": float(
                visible["received_power_dbw"].min()
            ),
            "maximum_received_power_dbw": float(
                visible["received_power_dbw"].max()
            ),
            "minimum_snr_db": float(visible["snr_db"].min()),
            "maximum_snr_db": float(visible["snr_db"].max()),
        },
        "coordinate_transform": {
            "source_frame": "TEME",
            "target_frame": "ECEF",
            "earth_rotation": "Vallado GMST with UTC used as UT1 proxy",
            "omitted": ["polar motion", "UT1-UTC correction"],
            "ground_track_coordinates": (
                "WGS-84 geodetic longitude, latitude, and altitude"
            ),
            "surface_distance_km": (
                "spherical central-angle approximation using a "
                "6371.0088 km mean Earth radius; not a WGS-84 geodesic"
            ),
        },
    }


def run_sgp4_simulation(
    output_directory: Path,
    *,
    omm_record: dict[str, Any],
    search_start_utc: datetime,
    search_hours: float,
    station: GroundStation,
    radio: LinkBudgetConfig,
    minimum_elevation_deg: float = 10.0,
    coarse_step_s: float = 30.0,
    time_step_s: float = 1.0,
    plot_padding_s: float = 60.0,
) -> SGP4SimulationArtifacts:
    """Find real passes and save the highest-elevation pass analysis."""
    if not np.isfinite(search_hours) or search_hours <= 0.0:
        raise ValueError("search_hours must be finite and positive")
    search_start = search_start_utc.astimezone(timezone.utc)
    search_end = search_start + timedelta(hours=search_hours)
    satellite = satrec_from_omm(omm_record)
    passes = find_visibility_passes(
        satellite,
        station,
        search_start,
        search_end,
        minimum_elevation_deg=minimum_elevation_deg,
        coarse_step_s=coarse_step_s,
    )
    if not passes:
        raise ValueError("no visibility pass found in the search interval")
    selected_pass = max(passes, key=lambda item: item.maximum_elevation_deg)
    datetimes = _datetime_samples(
        selected_pass,
        time_step_s,
        plot_padding_s,
    )
    frame = _actual_frame(
        datetimes,
        satellite,
        station,
        radio,
        minimum_elevation_deg,
        selected_pass,
    )
    start_relative = (
        selected_pass.start_utc - selected_pass.closest_approach_utc
    ).total_seconds()
    end_relative = (
        selected_pass.end_utc - selected_pass.closest_approach_utc
    ).total_seconds()

    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = SGP4SimulationArtifacts(
        source_omm_json=output_directory / "source_omm.json",
        passes_csv=output_directory / "passes.csv",
        results_csv=output_directory / "results.csv",
        summary_json=output_directory / "summary.json",
        orbit_3d_png=output_directory / "orbit_3d.png",
        ground_track_png=output_directory / "ground_track.png",
        geometry_png=output_directory / "geometry.png",
        delay_doppler_png=output_directory / "delay_doppler.png",
        link_budget_png=output_directory / "link_budget.png",
    )
    artifacts.source_omm_json.write_text(
        json.dumps([omm_record], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _passes_frame(passes).to_csv(artifacts.passes_csv, index=False)
    frame.to_csv(artifacts.results_csv, index=False)
    artifacts.summary_json.write_text(
        json.dumps(
            _summary(
                omm_record,
                station,
                radio,
                search_start,
                search_end,
                passes,
                selected_pass,
                frame,
                minimum_elevation_deg,
            ),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    _save_actual_orbit_3d(
        frame,
        satellite,
        station,
        selected_pass,
        artifacts.orbit_3d_png,
    )
    _save_actual_ground_track(
        frame,
        satellite,
        station,
        selected_pass,
        artifacts.ground_track_png,
    )
    _save_geometry(
        frame,
        start_relative,
        end_relative,
        minimum_elevation_deg,
        artifacts.geometry_png,
        time_label="Time from closest approach (s)",
    )
    _save_delay_doppler(
        frame,
        start_relative,
        end_relative,
        artifacts.delay_doppler_png,
        time_label="Time from closest approach (s)",
    )
    _save_link_budget(
        frame,
        start_relative,
        end_relative,
        artifacts.link_budget_png,
        time_label="Time from closest approach (s)",
    )
    return artifacts
