"""Downlink geometry derived from ideal ECI kinematic states."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import brentq

from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    ground_station_state,
    satellite_state,
)

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class DownlinkGeometry:
    """Sampled geometric quantities as observed from the ground station."""

    relative_position_km: FloatArray
    slant_range_km: FloatArray
    central_angle_rad: FloatArray
    surface_distance_km: FloatArray
    azimuth_deg: FloatArray
    elevation_deg: FloatArray
    visible: BoolArray


@dataclass(frozen=True, slots=True)
class VisibilityWindow:
    """The visibility interval surrounding the ideal overhead pass."""

    start_s: float
    end_s: float
    duration_s: float
    closest_approach_s: float
    minimum_slant_range_km: float
    maximum_elevation_deg: float
    minimum_elevation_deg: float


def downlink_geometry(
    times_s: ArrayLike,
    config: IdealOrbitConfig = IdealOrbitConfig(),
    *,
    minimum_elevation_deg: float = 0.0,
) -> DownlinkGeometry:
    """Calculate ideal downlink geometry for one or more times.

    Azimuth is measured clockwise from local north. It is returned as NaN at
    exact zenith because every horizontal direction is equivalent there.
    """
    if not -90.0 <= minimum_elevation_deg <= 90.0:
        raise ValueError("minimum_elevation_deg must be in [-90, 90]")

    station = ground_station_state(times_s, config)
    satellite = satellite_state(times_s, config)
    relative = satellite.position_km - station.position_km
    slant_range = np.linalg.norm(relative, axis=-1)

    position_dot_product = np.sum(
        satellite.position_km * station.position_km,
        axis=-1,
    )
    position_cross_norm = np.linalg.norm(
        np.cross(station.position_km, satellite.position_km),
        axis=-1,
    )
    central_angle = np.arctan2(position_cross_norm, position_dot_product)
    surface_distance = config.earth_radius_km * central_angle

    up = station.position_km / config.earth_radius_km
    longitude = np.arctan2(station.position_km[..., 1], station.position_km[..., 0])
    latitude = np.deg2rad(config.station_latitude_deg)
    east = np.stack(
        (
            -np.sin(longitude),
            np.cos(longitude),
            np.zeros_like(longitude),
        ),
        axis=-1,
    )
    north = np.stack(
        (
            -np.sin(latitude) * np.cos(longitude),
            -np.sin(latitude) * np.sin(longitude),
            np.full_like(longitude, np.cos(latitude)),
        ),
        axis=-1,
    )

    east_component = np.sum(relative * east, axis=-1)
    north_component = np.sum(relative * north, axis=-1)
    up_component = np.sum(relative * up, axis=-1)
    horizontal_range = np.hypot(east_component, north_component)

    elevation = np.rad2deg(np.arctan2(up_component, horizontal_range))
    azimuth = np.mod(
        np.rad2deg(np.arctan2(east_component, north_component)),
        360.0,
    )
    azimuth = np.where(horizontal_range > 1e-10, azimuth, np.nan)
    visible = elevation >= minimum_elevation_deg

    return DownlinkGeometry(
        relative_position_km=relative,
        slant_range_km=slant_range,
        central_angle_rad=central_angle,
        surface_distance_km=surface_distance,
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        visible=visible,
    )


def _elevation_margin(
    time_s: float,
    config: IdealOrbitConfig,
    minimum_elevation_deg: float,
) -> float:
    geometry = downlink_geometry(
        time_s,
        config,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    return float(geometry.elevation_deg - minimum_elevation_deg)


def _find_boundary(
    direction: float,
    config: IdealOrbitConfig,
    minimum_elevation_deg: float,
    search_step_s: float,
    maximum_search_s: float,
) -> float:
    inner_time = 0.0
    inner_margin = _elevation_margin(
        inner_time,
        config,
        minimum_elevation_deg,
    )

    elapsed = search_step_s
    while elapsed <= maximum_search_s:
        outer_time = direction * elapsed
        outer_margin = _elevation_margin(
            outer_time,
            config,
            minimum_elevation_deg,
        )
        if outer_margin <= 0.0:
            lower, upper = sorted((inner_time, outer_time))
            return float(
                brentq(
                    lambda time: _elevation_margin(
                        time,
                        config,
                        minimum_elevation_deg,
                    ),
                    lower,
                    upper,
                )
            )
        inner_time = outer_time
        inner_margin = outer_margin
        elapsed += search_step_s

    raise ValueError(
        "no visibility boundary found; increase maximum_search_s"
    )


def visibility_window(
    config: IdealOrbitConfig = IdealOrbitConfig(),
    *,
    minimum_elevation_deg: float = 0.0,
    search_step_s: float = 10.0,
    maximum_search_s: float | None = None,
) -> VisibilityWindow:
    """Find the visibility window surrounding the overhead pass at ``t=0``."""
    if not 0.0 <= minimum_elevation_deg < 90.0:
        raise ValueError("minimum_elevation_deg must be in [0, 90)")
    if search_step_s <= 0.0:
        raise ValueError("search_step_s must be positive")

    search_limit = (
        config.orbital_period_s / 2.0
        if maximum_search_s is None
        else maximum_search_s
    )
    if search_limit <= 0.0:
        raise ValueError("maximum_search_s must be positive")

    start = _find_boundary(
        -1.0,
        config,
        minimum_elevation_deg,
        search_step_s,
        search_limit,
    )
    end = _find_boundary(
        1.0,
        config,
        minimum_elevation_deg,
        search_step_s,
        search_limit,
    )
    closest = downlink_geometry(0.0, config)

    return VisibilityWindow(
        start_s=start,
        end_s=end,
        duration_s=end - start,
        closest_approach_s=0.0,
        minimum_slant_range_km=float(closest.slant_range_km),
        maximum_elevation_deg=float(closest.elevation_deg),
        minimum_elevation_deg=minimum_elevation_deg,
    )
