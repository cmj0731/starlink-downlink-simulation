"""Downlink geometry, pass search, and channel metrics for SGP4 states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq, minimize_scalar
from sgp4.api import Satrec

from starlink_isl.downlink_dynamics import (
    SPEED_OF_LIGHT_KM_S,
    DownlinkDynamics,
)
from starlink_isl.downlink_geometry import DownlinkGeometry
from starlink_isl.ideal_orbit import KinematicState
from starlink_isl.link_budget import (
    BOLTZMANN_J_K,
    LinkBudgetConfig,
    LinkBudgetResult,
    free_space_path_loss_db,
    thermal_noise_power_dbw,
)
from starlink_isl.sgp4_orbit import (
    GroundStation,
    ground_station_ecef_state,
    propagate_ecef,
)

FloatArray = NDArray[np.float64]
MEAN_EARTH_RADIUS_KM = 6_371.0088
# Numerical guard only: 1e-7 degree is about 1 cm along Earth's surface.
VISIBILITY_ELEVATION_TOLERANCE_DEG = 1e-7


@dataclass(frozen=True, slots=True)
class ActualPass:
    """One ground-station visibility pass."""

    start_utc: datetime
    closest_approach_utc: datetime
    maximum_elevation_utc: datetime
    end_utc: datetime
    duration_s: float
    maximum_elevation_deg: float
    minimum_slant_range_km: float


def geometry_from_ecef_states(
    satellite: KinematicState,
    ground: KinematicState,
    station: GroundStation,
    *,
    minimum_elevation_deg: float = 0.0,
) -> DownlinkGeometry:
    """Calculate topocentric downlink geometry from matching ECEF states."""
    if satellite.position_km.shape != ground.position_km.shape:
        raise ValueError("satellite and ground position shapes must match")
    if satellite.position_km.shape[-1] != 3:
        raise ValueError("positions must end with an xyz axis")
    if not -90.0 <= minimum_elevation_deg <= 90.0:
        raise ValueError("minimum_elevation_deg must be in [-90, 90]")

    relative = satellite.position_km - ground.position_km
    slant_range = np.linalg.norm(relative, axis=-1)
    satellite_radius = np.linalg.norm(satellite.position_km, axis=-1)
    ground_radius = np.linalg.norm(ground.position_km, axis=-1)
    dot_product = np.sum(
        satellite.position_km * ground.position_km,
        axis=-1,
    )
    cross_norm = np.linalg.norm(
        np.cross(ground.position_km, satellite.position_km),
        axis=-1,
    )
    central_angle = np.arctan2(cross_norm, dot_product)

    latitude = np.deg2rad(station.latitude_deg)
    longitude = np.deg2rad(station.longitude_deg)
    east = np.array([-np.sin(longitude), np.cos(longitude), 0.0])
    north = np.array(
        [
            -np.sin(latitude) * np.cos(longitude),
            -np.sin(latitude) * np.sin(longitude),
            np.cos(latitude),
        ]
    )
    up = np.array(
        [
            np.cos(latitude) * np.cos(longitude),
            np.cos(latitude) * np.sin(longitude),
            np.sin(latitude),
        ]
    )
    east_component = relative @ east
    north_component = relative @ north
    up_component = relative @ up
    horizontal_range = np.hypot(east_component, north_component)
    elevation = np.rad2deg(np.arctan2(up_component, horizontal_range))
    azimuth = np.mod(
        np.rad2deg(np.arctan2(east_component, north_component)),
        360.0,
    )
    azimuth = np.where(horizontal_range > 1e-10, azimuth, np.nan)

    return DownlinkGeometry(
        relative_position_km=relative,
        slant_range_km=slant_range,
        central_angle_rad=central_angle,
        surface_distance_km=MEAN_EARTH_RADIUS_KM * central_angle,
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        visible=(
            elevation
            >= minimum_elevation_deg - VISIBILITY_ELEVATION_TOLERANCE_DEG
        ),
    )


def dynamics_from_ecef_states(
    geometry: DownlinkGeometry,
    satellite: KinematicState,
    ground: KinematicState,
    carrier_frequency_hz: float,
    *,
    phase_reference_range_km: float,
) -> DownlinkDynamics:
    """Calculate delay, range rate, Doppler shift, and relative phase."""
    if not np.isfinite(carrier_frequency_hz) or carrier_frequency_hz <= 0.0:
        raise ValueError("carrier_frequency_hz must be finite and positive")
    if (
        not np.isfinite(phase_reference_range_km)
        or phase_reference_range_km <= 0.0
    ):
        raise ValueError("phase_reference_range_km must be positive")

    relative_velocity = satellite.velocity_km_s - ground.velocity_km_s
    radial_velocity = np.sum(
        geometry.relative_position_km * relative_velocity,
        axis=-1,
    ) / geometry.slant_range_km
    delay = geometry.slant_range_km / SPEED_OF_LIGHT_KM_S
    doppler = (
        -radial_velocity / SPEED_OF_LIGHT_KM_S * carrier_frequency_hz
    )
    phase = (
        -2.0
        * np.pi
        * carrier_frequency_hz
        / SPEED_OF_LIGHT_KM_S
        * (geometry.slant_range_km - phase_reference_range_km)
    )
    return DownlinkDynamics(delay, radial_velocity, doppler, phase)


def link_budget_from_geometry(
    geometry: DownlinkGeometry,
    radio: LinkBudgetConfig,
) -> LinkBudgetResult:
    """Apply the existing free-space and thermal-noise model to geometry."""
    path_loss = free_space_path_loss_db(
        geometry.slant_range_km,
        radio.carrier_frequency_hz,
    )
    received_power = (
        radio.transmit_power_dbw
        + radio.transmit_antenna_gain_dbi
        + radio.receive_antenna_gain_dbi
        - path_loss
        - radio.other_losses_db
    )
    noise_power = thermal_noise_power_dbw(
        radio.bandwidth_hz,
        radio.system_noise_temperature_k,
    )
    noise_density = 10.0 * np.log10(
        BOLTZMANN_J_K * radio.system_noise_temperature_k
    )
    return LinkBudgetResult(
        free_space_path_loss_db=path_loss,
        received_power_dbw=received_power,
        thermal_noise_power_dbw=noise_power,
        carrier_to_noise_density_db_hz=received_power - noise_density,
        snr_db=received_power - noise_power,
        visible=geometry.visible,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _datetimes(
    start_utc: datetime,
    end_utc: datetime,
    step_s: float,
) -> list[datetime]:
    start = _utc(start_utc)
    end = _utc(end_utc)
    if end <= start:
        raise ValueError("end_utc must be after start_utc")
    if not np.isfinite(step_s) or step_s <= 0.0:
        raise ValueError("step_s must be finite and positive")
    duration = (end - start).total_seconds()
    offsets = np.arange(0.0, duration, step_s)
    values = [start + timedelta(seconds=float(offset)) for offset in offsets]
    if not values or values[-1] != end:
        values.append(end)
    return values


def _geometry_at_offset(
    offset_s: float,
    search_start: datetime,
    satellite: Satrec,
    station: GroundStation,
    minimum_elevation_deg: float,
) -> DownlinkGeometry:
    epoch = search_start + timedelta(seconds=float(offset_s))
    satellite_state = propagate_ecef(satellite, [epoch])
    ground_state = ground_station_ecef_state(station, 1)
    return geometry_from_ecef_states(
        satellite_state,
        ground_state,
        station,
        minimum_elevation_deg=minimum_elevation_deg,
    )


def _range_rate_at_offset(
    offset_s: float,
    search_start: datetime,
    satellite: Satrec,
    station: GroundStation,
) -> float:
    epoch = search_start + timedelta(seconds=float(offset_s))
    satellite_state = propagate_ecef(satellite, [epoch])
    ground_state = ground_station_ecef_state(station, 1)
    geometry = geometry_from_ecef_states(
        satellite_state,
        ground_state,
        station,
    )
    relative_velocity = (
        satellite_state.velocity_km_s - ground_state.velocity_km_s
    )
    return float(
        (
            np.sum(
                geometry.relative_position_km * relative_velocity,
                axis=-1,
            )
            / geometry.slant_range_km
        ).item()
    )


def find_visibility_passes(
    satellite: Satrec,
    station: GroundStation,
    start_utc: datetime,
    end_utc: datetime,
    *,
    minimum_elevation_deg: float = 10.0,
    coarse_step_s: float = 30.0,
) -> list[ActualPass]:
    """Find and refine every visibility pass in a UTC search interval."""
    if not 0.0 <= minimum_elevation_deg < 90.0:
        raise ValueError("minimum_elevation_deg must be in [0, 90)")
    search_start = _utc(start_utc)
    search_end = _utc(end_utc)
    coarse_times = _datetimes(search_start, search_end, coarse_step_s)
    satellite_states = propagate_ecef(satellite, coarse_times)
    ground_states = ground_station_ecef_state(station, len(coarse_times))
    coarse_geometry = geometry_from_ecef_states(
        satellite_states,
        ground_states,
        station,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    offsets = np.array(
        [(value - search_start).total_seconds() for value in coarse_times]
    )
    margins = coarse_geometry.elevation_deg - minimum_elevation_deg
    visible = margins >= 0.0

    boundary_offsets: list[tuple[str, float]] = []
    if visible[0]:
        boundary_offsets.append(("start", 0.0))
    for index in range(len(offsets) - 1):
        if visible[index] == visible[index + 1]:
            continue
        boundary = brentq(
            lambda offset: float(
                _geometry_at_offset(
                    offset,
                    search_start,
                    satellite,
                    station,
                    minimum_elevation_deg,
                ).elevation_deg.item()
                - minimum_elevation_deg
            ),
            offsets[index],
            offsets[index + 1],
        )
        boundary_offsets.append(
            ("start" if not visible[index] else "end", float(boundary))
        )
    if visible[-1]:
        boundary_offsets.append(
            ("end", (search_end - search_start).total_seconds())
        )

    passes: list[ActualPass] = []
    open_start: float | None = None
    for kind, offset in boundary_offsets:
        if kind == "start":
            open_start = offset
            continue
        if open_start is None or offset <= open_start:
            continue
        end_offset = offset
        start_rate = _range_rate_at_offset(
            open_start,
            search_start,
            satellite,
            station,
        )
        end_rate = _range_rate_at_offset(
            end_offset,
            search_start,
            satellite,
            station,
        )
        if start_rate <= 0.0 <= end_rate:
            closest_offset = float(
                brentq(
                    lambda candidate: _range_rate_at_offset(
                        candidate,
                        search_start,
                        satellite,
                        station,
                    ),
                    open_start,
                    end_offset,
                    xtol=1e-6,
                )
            )
        else:
            optimum = minimize_scalar(
                lambda candidate: float(
                    _geometry_at_offset(
                        candidate,
                        search_start,
                        satellite,
                        station,
                        minimum_elevation_deg,
                    ).slant_range_km.item()
                ),
                bounds=(open_start, end_offset),
                method="bounded",
                options={"xatol": 1e-6},
            )
            closest_offset = float(optimum.x)
        closest_geometry = _geometry_at_offset(
            closest_offset,
            search_start,
            satellite,
            station,
            minimum_elevation_deg,
        )
        maximum_elevation_result = minimize_scalar(
            lambda candidate: -float(
                _geometry_at_offset(
                    candidate,
                    search_start,
                    satellite,
                    station,
                    minimum_elevation_deg,
                ).elevation_deg.item()
            ),
            bounds=(open_start, end_offset),
            method="bounded",
            options={"xatol": 1e-6},
        )
        maximum_elevation_offset = float(maximum_elevation_result.x)
        maximum_elevation_geometry = _geometry_at_offset(
            maximum_elevation_offset,
            search_start,
            satellite,
            station,
            minimum_elevation_deg,
        )
        passes.append(
            ActualPass(
                start_utc=search_start + timedelta(seconds=open_start),
                closest_approach_utc=(
                    search_start + timedelta(seconds=closest_offset)
                ),
                maximum_elevation_utc=(
                    search_start
                    + timedelta(seconds=maximum_elevation_offset)
                ),
                end_utc=search_start + timedelta(seconds=end_offset),
                duration_s=end_offset - open_start,
                maximum_elevation_deg=float(
                    maximum_elevation_geometry.elevation_deg.item()
                ),
                minimum_slant_range_km=float(
                    closest_geometry.slant_range_km.item()
                ),
            )
        )
        open_start = None
    return passes
