"""SGP4 propagation and TEME-to-ECEF conversion for OMM records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray
from sgp4.api import SGP4_ERRORS, Satrec, jday
from sgp4.omm import initialize

from starlink_isl.ideal_orbit import KinematicState

FloatArray = NDArray[np.float64]
WGS84_SEMI_MAJOR_AXIS_KM = 6_378.137
WGS84_FLATTENING = 1.0 / 298.257_223_563
EARTH_ROTATION_RATE_RAD_S = 7.292_115_0e-5


class SGP4PropagationError(RuntimeError):
    """Raised when SGP4 cannot propagate one or more requested epochs."""


@dataclass(frozen=True, slots=True)
class GroundStation:
    """WGS-84 geodetic ground-station coordinates."""

    latitude_deg: float = 37.2934
    longitude_deg: float = 126.9747
    altitude_m: float = 0.0

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("latitude_deg must be in [-90, 90]")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("longitude_deg must be in [-180, 180]")
        if not np.isfinite(self.altitude_m):
            raise ValueError("altitude_m must be finite")


def parse_omm_epoch(record: dict[str, Any]) -> datetime:
    """Parse a CelesTrak OMM epoch as an aware UTC datetime."""
    value = str(record["EPOCH"])
    epoch = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)
    return epoch.astimezone(timezone.utc)


def satrec_from_omm(record: dict[str, Any]) -> Satrec:
    """Initialize an SGP4 satellite from one JSON OMM record."""
    fields = {key: str(value) for key, value in record.items()}
    satellite = Satrec()
    initialize(satellite, fields)
    return satellite


def _as_utc(datetimes: Sequence[datetime]) -> list[datetime]:
    values: list[datetime] = []
    for value in datetimes:
        if value.tzinfo is None:
            raise ValueError("all datetimes must be timezone-aware")
        values.append(value.astimezone(timezone.utc))
    if not values:
        raise ValueError("at least one datetime is required")
    return values


def datetime_julian_dates(
    datetimes: Sequence[datetime],
) -> tuple[FloatArray, FloatArray]:
    """Convert aware UTC datetimes to split Julian dates."""
    values = _as_utc(datetimes)
    whole: list[float] = []
    fraction: list[float] = []
    for value in values:
        jd, fr = jday(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second + value.microsecond / 1e6,
        )
        whole.append(jd)
        fraction.append(fr)
    return np.asarray(whole), np.asarray(fraction)


def propagate_teme(
    satellite: Satrec,
    datetimes: Sequence[datetime],
) -> KinematicState:
    """Propagate an SGP4 satellite to TEME position and velocity samples."""
    jd, fraction = datetime_julian_dates(datetimes)
    errors, position, velocity = satellite.sgp4_array(jd, fraction)
    if np.any(errors):
        details = sorted(
            {
                f"{int(code)}: {SGP4_ERRORS.get(int(code), 'unknown error')}"
                for code in errors
                if code
            }
        )
        raise SGP4PropagationError("; ".join(details))
    return KinematicState(
        np.asarray(position, dtype=np.float64),
        np.asarray(velocity, dtype=np.float64),
    )


def greenwich_mean_sidereal_time_rad(julian_date: FloatArray) -> FloatArray:
    """Vallado GMST approximation using UTC as the UT1 proxy."""
    centuries = (np.asarray(julian_date) - 2_451_545.0) / 36_525.0
    seconds = (
        67_310.548_41
        + (876_600.0 * 3_600.0 + 8_640_184.812_866) * centuries
        + 0.093_104 * centuries**2
        - 6.2e-6 * centuries**3
    )
    return np.mod(seconds, 86_400.0) * (2.0 * np.pi / 86_400.0)


def teme_to_ecef(
    teme: KinematicState,
    datetimes: Sequence[datetime],
) -> KinematicState:
    """Rotate TEME states into an Earth-fixed frame.

    This first-order transform applies GMST and the rotating-frame velocity
    correction. Polar motion and UT1-UTC corrections are intentionally omitted.
    """
    jd, fraction = datetime_julian_dates(datetimes)
    angle = greenwich_mean_sidereal_time_rad(jd + fraction)
    cosine = np.cos(angle)
    sine = np.sin(angle)

    x, y, z = np.moveaxis(teme.position_km, -1, 0)
    vx, vy, vz = np.moveaxis(teme.velocity_km_s, -1, 0)
    position = np.stack(
        (
            cosine * x + sine * y,
            -sine * x + cosine * y,
            z,
        ),
        axis=-1,
    )
    rotated_velocity = np.stack(
        (
            cosine * vx + sine * vy,
            -sine * vx + cosine * vy,
            vz,
        ),
        axis=-1,
    )
    omega_cross_position = np.stack(
        (
            -EARTH_ROTATION_RATE_RAD_S * position[..., 1],
            EARTH_ROTATION_RATE_RAD_S * position[..., 0],
            np.zeros_like(position[..., 0]),
        ),
        axis=-1,
    )
    velocity = rotated_velocity - omega_cross_position
    return KinematicState(position, velocity)


def propagate_ecef(
    satellite: Satrec,
    datetimes: Sequence[datetime],
) -> KinematicState:
    """Propagate an SGP4 satellite directly to Earth-fixed states."""
    teme = propagate_teme(satellite, datetimes)
    return teme_to_ecef(teme, datetimes)


def geodetic_to_ecef(station: GroundStation) -> FloatArray:
    """Convert a WGS-84 geodetic point to an ECEF position in kilometres."""
    latitude = np.deg2rad(station.latitude_deg)
    longitude = np.deg2rad(station.longitude_deg)
    altitude_km = station.altitude_m / 1_000.0
    eccentricity_squared = (
        WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    )
    prime_vertical = WGS84_SEMI_MAJOR_AXIS_KM / np.sqrt(
        1.0 - eccentricity_squared * np.sin(latitude) ** 2
    )
    return np.array(
        [
            (prime_vertical + altitude_km)
            * np.cos(latitude)
            * np.cos(longitude),
            (prime_vertical + altitude_km)
            * np.cos(latitude)
            * np.sin(longitude),
            (
                prime_vertical * (1.0 - eccentricity_squared)
                + altitude_km
            )
            * np.sin(latitude),
        ],
        dtype=np.float64,
    )


def ecef_to_geodetic(
    positions_km: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Convert ECEF positions to WGS-84 longitude, latitude, altitude.

    Longitude and latitude are returned in degrees and altitude in kilometres.
    """
    positions = np.asarray(positions_km, dtype=np.float64)
    if positions.shape[-1] != 3:
        raise ValueError("positions_km must end with an xyz axis")
    x, y, z = np.moveaxis(positions, -1, 0)
    longitude = np.arctan2(y, x)
    horizontal = np.hypot(x, y)
    eccentricity_squared = (
        WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    )
    latitude = np.arctan2(
        z,
        horizontal * (1.0 - eccentricity_squared),
    )
    altitude = np.zeros_like(latitude)
    for _ in range(8):
        sine = np.sin(latitude)
        prime_vertical = WGS84_SEMI_MAJOR_AXIS_KM / np.sqrt(
            1.0 - eccentricity_squared * sine**2
        )
        altitude = horizontal / np.cos(latitude) - prime_vertical
        latitude = np.arctan2(
            z,
            horizontal
            * (
                1.0
                - eccentricity_squared
                * prime_vertical
                / (prime_vertical + altitude)
            ),
        )
    return (
        np.rad2deg(longitude),
        np.rad2deg(latitude),
        altitude,
    )


def ground_station_ecef_state(
    station: GroundStation,
    sample_count: int,
) -> KinematicState:
    """Repeat one fixed ECEF ground-station state for a sample array."""
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    position = np.repeat(
        geodetic_to_ecef(station)[None, :],
        sample_count,
        axis=0,
    )
    return KinematicState(position, np.zeros_like(position))
