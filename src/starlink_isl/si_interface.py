"""SI-unit bridge for team-level downlink integration.

The original analysis modules intentionally retain their kilometre/degree
interfaces for backward compatibility.  This module exposes the same physical
state with one stable integration convention:

* distance and position: metres
* velocity and range rate: metres per second
* time: seconds
* angles: radians
* LOS direction: satellite to user equipment (UE)
* sample vectors: ``(sample_count, 3)``
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sgp4.api import Satrec

from starlink_isl.actual_downlink import (
    dynamics_from_ecef_states,
    geometry_from_ecef_states,
)
from starlink_isl.downlink_dynamics import DownlinkDynamics, downlink_dynamics
from starlink_isl.downlink_geometry import DownlinkGeometry, downlink_geometry
from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    KinematicState,
    ground_station_state,
    satellite_state,
)
from starlink_isl.sgp4_orbit import (
    GroundStation,
    ground_station_ecef_state,
    propagate_ecef,
)

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
KM_TO_M = 1_000.0


@dataclass(frozen=True, slots=True)
class DownlinkStateSI:
    """Common per-sample geometry and Doppler state in SI units.

    Scalar time-series fields have shape ``(sample_count,)``. Position,
    velocity, and LOS fields have shape ``(sample_count, 3)``. The LOS unit
    vector always points from the satellite toward the UE. ``coordinate_frame``
    is ``"ECI"`` for the ideal constructor and ``"ECEF"`` for the SGP4
    constructor.
    """

    coordinate_frame: str
    time_s: FloatArray
    satellite_position_m: FloatArray
    satellite_velocity_m_s: FloatArray
    ue_position_m: FloatArray
    ue_velocity_m_s: FloatArray
    los_satellite_to_ue_unit: FloatArray
    slant_range_m: FloatArray
    surface_distance_m: FloatArray
    azimuth_rad: FloatArray
    elevation_rad: FloatArray
    radial_velocity_m_s: FloatArray
    propagation_delay_s: FloatArray
    doppler_shift_hz: FloatArray
    doppler_phase_rad: FloatArray
    visible: BoolArray

    @property
    def sample_count(self) -> int:
        """Number of time samples in the state."""

        return int(self.time_s.size)


def _time_samples(values: ArrayLike) -> FloatArray:
    samples = np.asarray(values, dtype=np.float64)
    if samples.ndim == 0:
        samples = samples.reshape(1)
    if samples.ndim != 1 or not np.all(np.isfinite(samples)):
        raise ValueError("time_s must be a finite scalar or one-dimensional array")
    if samples.size == 0:
        raise ValueError("time_s must contain at least one sample")
    return samples


def _sample_values(values: ArrayLike, sample_count: int, name: str) -> FloatArray:
    samples = np.asarray(values, dtype=np.float64)
    if samples.ndim == 0 and sample_count == 1:
        samples = samples.reshape(1)
    if samples.shape != (sample_count,):
        raise ValueError(f"{name} must have shape ({sample_count},)")
    return samples


def _state_vectors(
    state: KinematicState,
    sample_count: int,
    name: str,
) -> tuple[FloatArray, FloatArray]:
    position = np.asarray(state.position_km, dtype=np.float64)
    velocity = np.asarray(state.velocity_km_s, dtype=np.float64)
    if sample_count == 1 and position.shape == (3,):
        position = position.reshape(1, 3)
    if sample_count == 1 and velocity.shape == (3,):
        velocity = velocity.reshape(1, 3)
    expected = (sample_count, 3)
    if position.shape != expected or velocity.shape != expected:
        raise ValueError(f"{name} position and velocity must have shape {expected}")
    if not np.all(np.isfinite(position)) or not np.all(np.isfinite(velocity)):
        raise ValueError(f"{name} state must contain only finite values")
    return position, velocity


def _minimum_elevation_deg(minimum_elevation_rad: float) -> float:
    if not np.isfinite(minimum_elevation_rad):
        raise ValueError("minimum_elevation_rad must be finite")
    if not -0.5 * np.pi <= minimum_elevation_rad <= 0.5 * np.pi:
        raise ValueError("minimum_elevation_rad must be in [-pi/2, pi/2]")
    return float(np.rad2deg(minimum_elevation_rad))


def downlink_state_si(
    time_s: ArrayLike,
    satellite: KinematicState,
    ue: KinematicState,
    geometry: DownlinkGeometry,
    dynamics: DownlinkDynamics,
    *,
    coordinate_frame: str,
) -> DownlinkStateSI:
    """Convert matching legacy state objects to the common SI interface."""

    times = _time_samples(time_s)
    sample_count = times.size
    satellite_position_km, satellite_velocity_km_s = _state_vectors(
        satellite,
        sample_count,
        "satellite",
    )
    ue_position_km, ue_velocity_km_s = _state_vectors(
        ue,
        sample_count,
        "ue",
    )
    frame = coordinate_frame.upper()
    if frame not in {"ECI", "ECEF"}:
        raise ValueError("coordinate_frame must be 'ECI' or 'ECEF'")

    satellite_position_m = KM_TO_M * satellite_position_km
    satellite_velocity_m_s = KM_TO_M * satellite_velocity_km_s
    ue_position_m = KM_TO_M * ue_position_km
    ue_velocity_m_s = KM_TO_M * ue_velocity_km_s

    satellite_to_ue_m = ue_position_m - satellite_position_m
    slant_range_m = np.linalg.norm(satellite_to_ue_m, axis=1)
    if np.any(slant_range_m <= 0.0):
        raise ValueError("satellite and UE positions must be distinct")
    los_satellite_to_ue = satellite_to_ue_m / slant_range_m[:, None]
    radial_velocity_m_s = np.sum(
        (ue_velocity_m_s - satellite_velocity_m_s)
        * los_satellite_to_ue,
        axis=1,
    )

    legacy_range_m = KM_TO_M * _sample_values(
        geometry.slant_range_km,
        sample_count,
        "geometry.slant_range_km",
    )
    legacy_radial_velocity_m_s = KM_TO_M * _sample_values(
        dynamics.radial_velocity_km_s,
        sample_count,
        "dynamics.radial_velocity_km_s",
    )
    if not np.allclose(slant_range_m, legacy_range_m, rtol=1e-12, atol=1e-6):
        raise ValueError("geometry range does not match the supplied states")
    if not np.allclose(
        radial_velocity_m_s,
        legacy_radial_velocity_m_s,
        rtol=1e-12,
        atol=1e-6,
    ):
        raise ValueError("range rate does not match the supplied states")

    azimuth_deg = _sample_values(
        geometry.azimuth_deg,
        sample_count,
        "geometry.azimuth_deg",
    )
    elevation_deg = _sample_values(
        geometry.elevation_deg,
        sample_count,
        "geometry.elevation_deg",
    )

    return DownlinkStateSI(
        coordinate_frame=frame,
        time_s=times,
        satellite_position_m=satellite_position_m,
        satellite_velocity_m_s=satellite_velocity_m_s,
        ue_position_m=ue_position_m,
        ue_velocity_m_s=ue_velocity_m_s,
        los_satellite_to_ue_unit=los_satellite_to_ue,
        slant_range_m=slant_range_m,
        surface_distance_m=KM_TO_M
        * _sample_values(
            geometry.surface_distance_km,
            sample_count,
            "geometry.surface_distance_km",
        ),
        azimuth_rad=np.deg2rad(azimuth_deg),
        elevation_rad=np.deg2rad(elevation_deg),
        radial_velocity_m_s=radial_velocity_m_s,
        propagation_delay_s=_sample_values(
            dynamics.propagation_delay_s,
            sample_count,
            "dynamics.propagation_delay_s",
        ),
        doppler_shift_hz=_sample_values(
            dynamics.doppler_shift_hz,
            sample_count,
            "dynamics.doppler_shift_hz",
        ),
        doppler_phase_rad=_sample_values(
            dynamics.doppler_phase_rad,
            sample_count,
            "dynamics.doppler_phase_rad",
        ),
        visible=np.asarray(geometry.visible, dtype=np.bool_).reshape(sample_count),
    )


def ideal_downlink_state_si(
    time_s: ArrayLike,
    carrier_frequency_hz: float,
    config: IdealOrbitConfig = IdealOrbitConfig(),
    *,
    minimum_elevation_rad: float = 0.0,
    phase_reference_time_s: float = 0.0,
) -> DownlinkStateSI:
    """Return ideal-orbit downlink samples through the SI team interface."""

    times = _time_samples(time_s)
    minimum_elevation_deg = _minimum_elevation_deg(minimum_elevation_rad)
    satellite = satellite_state(times, config)
    ue = ground_station_state(times, config)
    geometry = downlink_geometry(
        times,
        config,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    dynamics = downlink_dynamics(
        times,
        carrier_frequency_hz,
        config,
        phase_reference_time_s=phase_reference_time_s,
    )
    return downlink_state_si(
        times,
        satellite,
        ue,
        geometry,
        dynamics,
        coordinate_frame="ECI",
    )


def sgp4_downlink_state_si(
    datetimes: Sequence[datetime],
    satellite: Satrec,
    carrier_frequency_hz: float,
    station: GroundStation = GroundStation(),
    *,
    minimum_elevation_rad: float = 0.0,
    time_origin_utc: datetime | None = None,
    phase_reference_utc: datetime | None = None,
) -> DownlinkStateSI:
    """Return SGP4/ECEF samples through the SI team interface.

    ``time_s`` is measured from ``time_origin_utc``. By default the first input
    epoch is the simulation origin, so the first output time is exactly zero.
    Doppler phase is likewise referenced to the first input epoch unless
    ``phase_reference_utc`` is supplied.
    """

    epochs = list(datetimes)
    if not epochs:
        raise ValueError("datetimes must contain at least one epoch")
    for epoch in epochs:
        if epoch.tzinfo is None:
            raise ValueError("all datetimes must be timezone-aware")
    origin = epochs[0] if time_origin_utc is None else time_origin_utc
    if origin.tzinfo is None:
        raise ValueError("time_origin_utc must be timezone-aware")
    origin_utc = origin.astimezone(timezone.utc)
    time_s = np.asarray(
        [
            (epoch.astimezone(timezone.utc) - origin_utc).total_seconds()
            for epoch in epochs
        ],
        dtype=np.float64,
    )

    minimum_elevation_deg = _minimum_elevation_deg(minimum_elevation_rad)
    satellite_state_ecef = propagate_ecef(satellite, epochs)
    ue_state_ecef = ground_station_ecef_state(station, len(epochs))
    geometry = geometry_from_ecef_states(
        satellite_state_ecef,
        ue_state_ecef,
        station,
        minimum_elevation_deg=minimum_elevation_deg,
    )

    if phase_reference_utc is None:
        phase_reference_range_km = float(geometry.slant_range_km[0])
    else:
        if phase_reference_utc.tzinfo is None:
            raise ValueError("phase_reference_utc must be timezone-aware")
        reference_satellite = propagate_ecef(satellite, [phase_reference_utc])
        reference_ue = ground_station_ecef_state(station, 1)
        reference_geometry = geometry_from_ecef_states(
            reference_satellite,
            reference_ue,
            station,
            minimum_elevation_deg=minimum_elevation_deg,
        )
        phase_reference_range_km = float(
            reference_geometry.slant_range_km.item()
        )

    dynamics = dynamics_from_ecef_states(
        geometry,
        satellite_state_ecef,
        ue_state_ecef,
        carrier_frequency_hz,
        phase_reference_range_km=phase_reference_range_km,
    )
    return downlink_state_si(
        time_s,
        satellite_state_ecef,
        ue_state_ecef,
        geometry,
        dynamics,
        coordinate_frame="ECEF",
    )
