"""Run the ideal STARLINK-5285 downlink simulation and save artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

from starlink_isl.downlink_dynamics import downlink_dynamics
from starlink_isl.downlink_geometry import (
    VisibilityWindow,
    downlink_geometry,
    visibility_window,
)
from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    ground_station_state,
    satellite_state,
)
from starlink_isl.link_budget import (
    LinkBudgetConfig,
    link_budget,
)

FloatArray = NDArray[np.float64]
DEFAULT_OUTPUT_DIRECTORY = Path("outputs/ideal_downlink")


@dataclass(frozen=True, slots=True)
class SimulationArtifacts:
    """Paths written by one simulation run."""

    results_csv: Path
    summary_json: Path
    orbit_3d_png: Path
    ground_track_png: Path
    geometry_png: Path
    delay_doppler_png: Path
    link_budget_png: Path


def _finite_positive(value: float, name: str) -> None:
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")


def build_time_samples(
    start_s: float,
    end_s: float,
    step_s: float,
    *,
    event_times_s: ArrayLike = (),
) -> FloatArray:
    """Build an inclusive time array containing exact event timestamps."""
    if not np.isfinite(start_s) or not np.isfinite(end_s):
        raise ValueError("start_s and end_s must be finite")
    if end_s <= start_s:
        raise ValueError("end_s must be greater than start_s")
    _finite_positive(step_s, "step_s")

    regular_times = np.arange(start_s, end_s, step_s, dtype=np.float64)
    if regular_times.size == 0 or not np.isclose(regular_times[-1], end_s):
        regular_times = np.append(regular_times, end_s)

    event_times = np.asarray(event_times_s, dtype=np.float64).reshape(-1)
    if not np.all(np.isfinite(event_times)):
        raise ValueError("event_times_s must contain only finite values")
    if event_times.size:
        # Prefer the exact event value when a regular sample is equal to it
        # within floating-point time resolution.
        separation = np.abs(regular_times[:, None] - event_times[None, :])
        regular_times = regular_times[np.all(separation > 1e-9, axis=1)]

    return np.unique(np.sort(np.concatenate((regular_times, event_times))))


def eci_to_spherical_ground_track(
    position_eci_km: ArrayLike,
    times_s: ArrayLike,
    earth_rotation_rate_rad_s: float,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Convert ideal ECI positions to Earth-fixed longitude, latitude, radius."""
    position = np.asarray(position_eci_km, dtype=np.float64)
    times = np.asarray(times_s, dtype=np.float64)
    if position.shape[-1] != 3:
        raise ValueError("position_eci_km must end with an xyz axis")
    if position.shape[:-1] != times.shape:
        raise ValueError("position and time sample shapes must match")

    inertial_longitude = np.arctan2(position[..., 1], position[..., 0])
    longitude = inertial_longitude - earth_rotation_rate_rad_s * times
    longitude = (longitude + np.pi) % (2.0 * np.pi) - np.pi
    radius = np.linalg.norm(position, axis=-1)
    latitude = np.arcsin(np.clip(position[..., 2] / radius, -1.0, 1.0))
    return np.rad2deg(longitude), np.rad2deg(latitude), radius


def _simulation_frame(
    times_s: FloatArray,
    orbit: IdealOrbitConfig,
    radio: LinkBudgetConfig,
    minimum_elevation_deg: float,
) -> pd.DataFrame:
    station = ground_station_state(times_s, orbit)
    satellite = satellite_state(times_s, orbit)
    geometry = downlink_geometry(
        times_s,
        orbit,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    dynamics = downlink_dynamics(
        times_s,
        radio.carrier_frequency_hz,
        orbit,
    )
    budget = link_budget(
        times_s,
        radio,
        orbit,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    satellite_longitude, satellite_latitude, satellite_radius = (
        eci_to_spherical_ground_track(
            satellite.position_km,
            times_s,
            orbit.earth_rotation_rate_rad_s,
        )
    )

    return pd.DataFrame(
        {
            "time_s": times_s,
            "satellite_x_eci_km": satellite.position_km[:, 0],
            "satellite_y_eci_km": satellite.position_km[:, 1],
            "satellite_z_eci_km": satellite.position_km[:, 2],
            "satellite_vx_eci_km_s": satellite.velocity_km_s[:, 0],
            "satellite_vy_eci_km_s": satellite.velocity_km_s[:, 1],
            "satellite_vz_eci_km_s": satellite.velocity_km_s[:, 2],
            "station_x_eci_km": station.position_km[:, 0],
            "station_y_eci_km": station.position_km[:, 1],
            "station_z_eci_km": station.position_km[:, 2],
            "satellite_longitude_deg": satellite_longitude,
            "satellite_latitude_deg": satellite_latitude,
            "satellite_radius_km": satellite_radius,
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


def _add_event_labels(
    frame: pd.DataFrame,
    *,
    visibility_start_s: float,
    visibility_end_s: float,
    closest_approach_s: float,
) -> None:
    labels: dict[float, list[str]] = {
        visibility_start_s: ["visibility_start"],
        visibility_end_s: ["visibility_end"],
        closest_approach_s: ["closest_approach"],
    }
    labels.setdefault(0.0, []).append("overhead")
    frame["event"] = ""
    for time_s, names in labels.items():
        matches = frame["time_s"] == time_s
        if not bool(matches.any()):
            raise RuntimeError(f"required event time is missing: {time_s}")
        frame.loc[matches, "event"] = "|".join(names)


def _break_longitude_wrap(
    longitude_deg: ArrayLike,
    latitude_deg: ArrayLike,
) -> tuple[FloatArray, FloatArray]:
    longitude = np.asarray(longitude_deg, dtype=np.float64).copy()
    latitude = np.asarray(latitude_deg, dtype=np.float64).copy()
    jumps = np.abs(np.diff(longitude)) > 180.0
    longitude[1:][jumps] = np.nan
    latitude[1:][jumps] = np.nan
    return longitude, latitude


def _mark_pass_events(
    axes: ArrayLike,
    start_s: float,
    end_s: float,
) -> None:
    for axis in np.asarray(axes, dtype=object).flat:
        axis.axvline(start_s, color="0.45", linestyle="--", linewidth=0.9)
        axis.axvline(0.0, color="0.2", linestyle=":", linewidth=1.0)
        axis.axvline(end_s, color="0.45", linestyle="--", linewidth=0.9)
        axis.grid(True, alpha=0.25)


def _save_orbit_3d(
    frame: pd.DataFrame,
    orbit: IdealOrbitConfig,
    path: Path,
) -> None:
    figure = plt.figure(figsize=(8.0, 7.0), constrained_layout=True)
    axis = figure.add_subplot(111, projection="3d")
    full_orbit_times = np.linspace(
        -0.5 * orbit.orbital_period_s,
        0.5 * orbit.orbital_period_s,
        1_441,
    )
    full_orbit = satellite_state(full_orbit_times, orbit)

    longitude = np.linspace(0.0, 2.0 * np.pi, 40)
    latitude = np.linspace(-0.5 * np.pi, 0.5 * np.pi, 20)
    earth_x = orbit.earth_radius_km * np.outer(
        np.cos(latitude),
        np.cos(longitude),
    )
    earth_y = orbit.earth_radius_km * np.outer(
        np.cos(latitude),
        np.sin(longitude),
    )
    earth_z = orbit.earth_radius_km * np.outer(
        np.sin(latitude),
        np.ones_like(longitude),
    )
    axis.plot_wireframe(
        earth_x,
        earth_y,
        earth_z,
        rstride=3,
        cstride=4,
        color="0.7",
        linewidth=0.35,
    )
    axis.plot(
        full_orbit.position_km[:, 0],
        full_orbit.position_km[:, 1],
        full_orbit.position_km[:, 2],
        color="0.55",
        linewidth=0.8,
        label="Full orbit reference",
    )
    axis.plot(
        frame["satellite_x_eci_km"],
        frame["satellite_y_eci_km"],
        frame["satellite_z_eci_km"],
        color="tab:blue",
        label="Analysis interval",
        linewidth=1.5,
    )
    visible = frame["visible"].to_numpy()
    visible_position = frame[
        [
            "satellite_x_eci_km",
            "satellite_y_eci_km",
            "satellite_z_eci_km",
        ]
    ].to_numpy(copy=True)
    visible_position[~visible] = np.nan
    axis.plot(
        visible_position[:, 0],
        visible_position[:, 1],
        visible_position[:, 2],
        color="tab:blue",
        label="Visible interval",
        linewidth=3.2,
    )
    axis.plot(
        frame["station_x_eci_km"],
        frame["station_y_eci_km"],
        frame["station_z_eci_km"],
        color="tab:orange",
        label="Ground-station rotation",
        linewidth=1.8,
    )
    overhead = frame.loc[frame["time_s"] == 0.0].iloc[0]
    axis.scatter(
        [overhead["satellite_x_eci_km"]],
        [overhead["satellite_y_eci_km"]],
        [overhead["satellite_z_eci_km"]],
        color="tab:blue",
        marker="o",
        label="Overhead at t=0",
    )
    limit = orbit.orbital_radius_km * 1.05
    axis.set(
        xlim=(-limit, limit),
        ylim=(-limit, limit),
        zlim=(-limit, limit),
        xlabel="ECI x (km)",
        ylabel="ECI y (km)",
        zlabel="ECI z (km)",
        title="Full ideal orbit, analysis interval, and visible pass",
    )
    axis.set_box_aspect((1.0, 1.0, 1.0))
    axis.legend(loc="upper left")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _save_ground_track(
    frame: pd.DataFrame,
    orbit: IdealOrbitConfig,
    path: Path,
) -> None:
    full_times = np.linspace(
        -0.5 * orbit.orbital_period_s,
        0.5 * orbit.orbital_period_s,
        1_441,
    )
    full_state = satellite_state(full_times, orbit)
    full_longitude, full_latitude, _ = eci_to_spherical_ground_track(
        full_state.position_km,
        full_times,
        orbit.earth_rotation_rate_rad_s,
    )
    full_longitude, full_latitude = _break_longitude_wrap(
        full_longitude,
        full_latitude,
    )
    analysis_longitude, analysis_latitude = _break_longitude_wrap(
        frame["satellite_longitude_deg"],
        frame["satellite_latitude_deg"],
    )
    visible = frame["visible"].to_numpy()
    visible_longitude = frame["satellite_longitude_deg"].to_numpy(copy=True)
    visible_latitude = frame["satellite_latitude_deg"].to_numpy(copy=True)
    visible_longitude[~visible] = np.nan
    visible_latitude[~visible] = np.nan
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
        label="Full-orbit ground track",
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
        [orbit.station_initial_longitude_deg],
        [orbit.station_latitude_deg],
        color="tab:orange",
        marker="^",
        s=65,
        label="Ground station at t=0",
    )
    axis.set(
        xlim=(-180.0, 180.0),
        ylim=(-90.0, 90.0),
        xticks=np.arange(-180.0, 181.0, 60.0),
        yticks=np.arange(-90.0, 91.0, 30.0),
        xlabel="Earth-fixed longitude (deg)",
        ylabel="Latitude (deg)",
        title="Full-orbit and visible-pass ground tracks",
    )
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _save_geometry(
    frame: pd.DataFrame,
    start_s: float,
    end_s: float,
    minimum_elevation_deg: float,
    path: Path,
    *,
    time_label: str = "Time from overhead (s)",
) -> None:
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(9.0, 7.0),
        sharex=True,
        constrained_layout=True,
    )
    axes[0].plot(frame["time_s"], frame["elevation_deg"])
    axes[0].axhline(
        minimum_elevation_deg,
        color="0.45",
        linestyle="-.",
        label=f"Minimum elevation: {minimum_elevation_deg:g} deg",
    )
    axes[0].set(ylabel="Elevation (deg)", title="Downlink geometry")
    axes[0].legend()
    axes[1].plot(frame["time_s"], frame["slant_range_km"])
    axes[1].set(xlabel=time_label, ylabel="Slant range (km)")
    _mark_pass_events(axes, start_s, end_s)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _save_delay_doppler(
    frame: pd.DataFrame,
    start_s: float,
    end_s: float,
    path: Path,
    *,
    time_label: str = "Time from overhead (s)",
) -> None:
    figure, axes = plt.subplots(
        3,
        1,
        figsize=(9.0, 8.5),
        sharex=True,
        constrained_layout=True,
    )
    axes[0].plot(frame["time_s"], frame["propagation_delay_ms"])
    axes[0].set(
        ylabel="Delay (ms)",
        title="Propagation delay and Doppler dynamics",
    )
    axes[1].plot(frame["time_s"], frame["radial_velocity_km_s"])
    axes[1].axhline(0.0, color="0.45", linewidth=0.8)
    axes[1].set(ylabel="Range rate (km/s)")
    axes[2].plot(frame["time_s"], frame["doppler_shift_hz"] / 1e3)
    axes[2].axhline(0.0, color="0.45", linewidth=0.8)
    axes[2].set(
        xlabel=time_label,
        ylabel="Doppler shift (kHz)",
    )
    _mark_pass_events(axes, start_s, end_s)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _save_link_budget(
    frame: pd.DataFrame,
    start_s: float,
    end_s: float,
    path: Path,
    *,
    time_label: str = "Time from overhead (s)",
) -> None:
    figure, axes = plt.subplots(
        3,
        1,
        figsize=(9.0, 8.5),
        sharex=True,
        constrained_layout=True,
    )
    axes[0].plot(frame["time_s"], frame["free_space_path_loss_db"])
    axes[0].set(ylabel="FSPL (dB)", title="Free-space link budget")
    axes[1].plot(
        frame["time_s"],
        frame["received_power_dbw"],
        label="Received power",
    )
    axes[1].axhline(
        frame["thermal_noise_power_dbw"].iloc[0],
        color="0.45",
        linestyle="--",
        label="Thermal noise",
    )
    axes[1].set(ylabel="Power (dBW)")
    axes[1].legend()
    axes[2].plot(frame["time_s"], frame["snr_db"])
    axes[2].set(xlabel=time_label, ylabel="SNR (dB)")
    _mark_pass_events(axes, start_s, end_s)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _summary(
    frame: pd.DataFrame,
    orbit: IdealOrbitConfig,
    radio: LinkBudgetConfig,
    minimum_elevation_deg: float,
    window: VisibilityWindow,
) -> dict[str, Any]:
    visible = frame.loc[frame["visible"]]
    return {
        "model": "ideal STARLINK-5285 overhead downlink",
        "radio_parameters_are_illustrative": True,
        "orbit": asdict(orbit),
        "radio": asdict(radio),
        "minimum_elevation_deg": minimum_elevation_deg,
        "visibility": asdict(window),
        "events_s": {
            "visibility_start": window.start_s,
            "overhead": 0.0,
            "closest_approach": window.closest_approach_s,
            "visibility_end": window.end_s,
        },
        "sample_count": len(frame),
        "visible_sample_count": len(visible),
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
    }


def run_simulation(
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    *,
    orbit: IdealOrbitConfig = IdealOrbitConfig(),
    radio: LinkBudgetConfig,
    minimum_elevation_deg: float = 10.0,
    time_step_s: float = 1.0,
    start_s: float | None = None,
    end_s: float | None = None,
    plot_padding_s: float = 60.0,
) -> SimulationArtifacts:
    """Run one simulation and write tabular, summary, and plot artifacts."""
    if plot_padding_s < 0.0 or not np.isfinite(plot_padding_s):
        raise ValueError("plot_padding_s must be finite and non-negative")
    window = visibility_window(
        orbit,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    simulation_start = (
        window.start_s - plot_padding_s if start_s is None else start_s
    )
    simulation_end = (
        window.end_s + plot_padding_s if end_s is None else end_s
    )
    times = build_time_samples(
        simulation_start,
        simulation_end,
        time_step_s,
        event_times_s=(
            window.start_s,
            0.0,
            window.closest_approach_s,
            window.end_s,
        ),
    )
    frame = _simulation_frame(
        times,
        orbit,
        radio,
        minimum_elevation_deg,
    )
    _add_event_labels(
        frame,
        visibility_start_s=window.start_s,
        visibility_end_s=window.end_s,
        closest_approach_s=window.closest_approach_s,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = SimulationArtifacts(
        results_csv=output_directory / "results.csv",
        summary_json=output_directory / "summary.json",
        orbit_3d_png=output_directory / "orbit_3d.png",
        ground_track_png=output_directory / "ground_track.png",
        geometry_png=output_directory / "geometry.png",
        delay_doppler_png=output_directory / "delay_doppler.png",
        link_budget_png=output_directory / "link_budget.png",
    )
    frame.to_csv(artifacts.results_csv, index=False)
    artifacts.summary_json.write_text(
        json.dumps(
            _summary(
                frame,
                orbit,
                radio,
                minimum_elevation_deg,
                window,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _save_orbit_3d(frame, orbit, artifacts.orbit_3d_png)
    _save_ground_track(frame, orbit, artifacts.ground_track_png)
    _save_geometry(
        frame,
        window.start_s,
        window.end_s,
        minimum_elevation_deg,
        artifacts.geometry_png,
    )
    _save_delay_doppler(
        frame,
        window.start_s,
        window.end_s,
        artifacts.delay_doppler_png,
    )
    _save_link_budget(
        frame,
        window.start_s,
        window.end_s,
        artifacts.link_budget_png,
    )
    return artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("ideal", "sgp4"), default="ideal")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--carrier-ghz", type=float, default=10.0)
    parser.add_argument("--bandwidth-mhz", type=float, default=100.0)
    parser.add_argument("--minimum-elevation-deg", type=float, default=10.0)
    parser.add_argument("--time-step-s", type=float, default=1.0)
    parser.add_argument("--transmit-power-dbw", type=float, default=10.0)
    parser.add_argument("--transmit-gain-dbi", type=float, default=30.0)
    parser.add_argument("--receive-gain-dbi", type=float, default=40.0)
    parser.add_argument("--system-noise-temperature-k", type=float, default=290.0)
    parser.add_argument("--other-losses-db", type=float, default=2.0)
    parser.add_argument("--norad-id", type=int, default=55_296)
    parser.add_argument("--start-utc")
    parser.add_argument("--search-hours", type=float, default=24.0)
    parser.add_argument("--station-altitude-m", type=float, default=0.0)
    parser.add_argument("--force-download", action="store_true")
    return parser


def main() -> None:
    """Run the selected ideal or CelesTrak/SGP4 downlink simulation."""
    args = _parser().parse_args()
    radio = LinkBudgetConfig(
        carrier_frequency_hz=args.carrier_ghz * 1e9,
        bandwidth_hz=args.bandwidth_mhz * 1e6,
        transmit_power_dbw=args.transmit_power_dbw,
        transmit_antenna_gain_dbi=args.transmit_gain_dbi,
        receive_antenna_gain_dbi=args.receive_gain_dbi,
        system_noise_temperature_k=args.system_noise_temperature_k,
        other_losses_db=args.other_losses_db,
    )
    if args.model == "ideal":
        output = args.output or DEFAULT_OUTPUT_DIRECTORY
        artifacts = run_simulation(
            output,
            radio=radio,
            minimum_elevation_deg=args.minimum_elevation_deg,
            time_step_s=args.time_step_s,
        )
    else:
        from starlink_isl.celestrak import fetch_catalog_omm
        from starlink_isl.sgp4_orbit import GroundStation
        from starlink_isl.sgp4_simulate import (
            DEFAULT_SGP4_OUTPUT_DIRECTORY,
            parse_utc,
            run_sgp4_simulation,
        )

        output = args.output or DEFAULT_SGP4_OUTPUT_DIRECTORY
        cache_path = Path(
            f"data/raw/starlink_{args.norad_id}_omm.json"
        )
        record = fetch_catalog_omm(
            args.norad_id,
            cache_path,
            force=args.force_download,
        )
        search_start = (
            parse_utc(args.start_utc)
            if args.start_utc
            else datetime.now(timezone.utc).replace(
                minute=0,
                second=0,
                microsecond=0,
            )
        )
        artifacts = run_sgp4_simulation(
            output,
            omm_record=record,
            search_start_utc=search_start,
            search_hours=args.search_hours,
            station=GroundStation(altitude_m=args.station_altitude_m),
            radio=radio,
            minimum_elevation_deg=args.minimum_elevation_deg,
            time_step_s=args.time_step_s,
        )

    print(f"Simulation artifacts written to: {output}")
    for path in asdict(artifacts).values():
        print(f"- {path}")


if __name__ == "__main__":
    main()
