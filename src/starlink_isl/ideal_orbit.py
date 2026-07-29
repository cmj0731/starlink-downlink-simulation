"""Ideal circular-orbit and rotating-ground-station kinematics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class IdealOrbitConfig:
    """Parameters for the ideal STARLINK-5285 overhead-pass model.

    Angles supplied by callers are in degrees. Positions and velocities use
    kilometres and seconds throughout the model.
    """

    earth_radius_km: float = 6_378.0
    altitude_km: float = 572.0
    orbital_period_s: float = 5_766.6
    inclination_deg: float = 70.0
    station_latitude_deg: float = 37.2934
    station_initial_longitude_deg: float = 0.0
    earth_rotation_rate_rad_s: float = 7.2921159e-5

    def __post_init__(self) -> None:
        if self.earth_radius_km <= 0:
            raise ValueError("earth_radius_km must be positive")
        if self.altitude_km <= 0:
            raise ValueError("altitude_km must be positive")
        if self.orbital_period_s <= 0:
            raise ValueError("orbital_period_s must be positive")
        if not 0 < self.inclination_deg <= 90:
            raise ValueError("inclination_deg must be in (0, 90]")
        if abs(self.station_latitude_deg) > self.inclination_deg:
            raise ValueError(
                "an overhead pass requires |station latitude| <= inclination"
            )

    @property
    def orbital_radius_km(self) -> float:
        """Circular-orbit radius measured from Earth's centre."""
        return self.earth_radius_km + self.altitude_km

    @property
    def orbital_rate_rad_s(self) -> float:
        """Constant angular rate of the circular orbit."""
        return 2.0 * np.pi / self.orbital_period_s

    @property
    def orbital_speed_km_s(self) -> float:
        """Constant inertial speed of the satellite."""
        return self.orbital_radius_km * self.orbital_rate_rad_s

    @property
    def initial_argument_of_latitude_rad(self) -> float:
        """Argument of latitude giving an ascending overhead pass."""
        latitude = np.deg2rad(self.station_latitude_deg)
        inclination = np.deg2rad(self.inclination_deg)
        ratio = np.clip(np.sin(latitude) / np.sin(inclination), -1.0, 1.0)
        return float(np.arcsin(ratio))

    @property
    def raan_rad(self) -> float:
        """RAAN orienting the orbit through the initial station position."""
        argument = self.initial_argument_of_latitude_rad
        inclination = np.deg2rad(self.inclination_deg)
        longitude = np.deg2rad(self.station_initial_longitude_deg)
        relative_raan = np.arctan2(
            -np.sin(argument) * np.cos(inclination),
            np.cos(argument),
        )
        return float(longitude + relative_raan)


@dataclass(frozen=True, slots=True)
class KinematicState:
    """Position and velocity samples in the ECI frame."""

    position_km: FloatArray
    velocity_km_s: FloatArray


def _time_array(times_s: ArrayLike) -> FloatArray:
    times = np.asarray(times_s, dtype=np.float64)
    if not np.all(np.isfinite(times)):
        raise ValueError("times_s must contain only finite values")
    return times


def ground_station_state(
    times_s: ArrayLike,
    config: IdealOrbitConfig = IdealOrbitConfig(),
) -> KinematicState:
    """Return ECI position and velocity of the rotating ground station."""
    times = _time_array(times_s)
    latitude = np.deg2rad(config.station_latitude_deg)
    initial_longitude = np.deg2rad(config.station_initial_longitude_deg)
    longitude = initial_longitude + config.earth_rotation_rate_rad_s * times

    equatorial_radius = config.earth_radius_km * np.cos(latitude)
    z = np.full_like(longitude, config.earth_radius_km * np.sin(latitude))
    position = np.stack(
        (
            equatorial_radius * np.cos(longitude),
            equatorial_radius * np.sin(longitude),
            z,
        ),
        axis=-1,
    )
    velocity = np.stack(
        (
            -equatorial_radius
            * config.earth_rotation_rate_rad_s
            * np.sin(longitude),
            equatorial_radius
            * config.earth_rotation_rate_rad_s
            * np.cos(longitude),
            np.zeros_like(longitude),
        ),
        axis=-1,
    )
    return KinematicState(position, velocity)


def satellite_state(
    times_s: ArrayLike,
    config: IdealOrbitConfig = IdealOrbitConfig(),
) -> KinematicState:
    """Return ECI position and velocity of the ideal circular-orbit satellite."""
    times = _time_array(times_s)
    inclination = np.deg2rad(config.inclination_deg)
    raan = config.raan_rad
    argument = (
        config.initial_argument_of_latitude_rad
        + config.orbital_rate_rad_s * times
    )

    cos_raan = np.cos(raan)
    sin_raan = np.sin(raan)
    cos_argument = np.cos(argument)
    sin_argument = np.sin(argument)
    cos_inclination = np.cos(inclination)
    sin_inclination = np.sin(inclination)

    direction = np.stack(
        (
            cos_raan * cos_argument
            - sin_raan * sin_argument * cos_inclination,
            sin_raan * cos_argument
            + cos_raan * sin_argument * cos_inclination,
            sin_argument * sin_inclination,
        ),
        axis=-1,
    )
    tangent = np.stack(
        (
            -cos_raan * sin_argument
            - sin_raan * cos_argument * cos_inclination,
            -sin_raan * sin_argument
            + cos_raan * cos_argument * cos_inclination,
            cos_argument * sin_inclination,
        ),
        axis=-1,
    )

    position = config.orbital_radius_km * direction
    velocity = config.orbital_speed_km_s * tangent
    return KinematicState(position, velocity)

