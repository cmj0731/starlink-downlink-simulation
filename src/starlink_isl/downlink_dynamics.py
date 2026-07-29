"""Propagation delay, range rate, Doppler shift, and Doppler phase."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.downlink_geometry import downlink_geometry
from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    ground_station_state,
    satellite_state,
)

SPEED_OF_LIGHT_KM_S = 299_792.458
FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class DownlinkDynamics:
    """Time-varying one-way downlink quantities."""

    propagation_delay_s: FloatArray
    radial_velocity_km_s: FloatArray
    doppler_shift_hz: FloatArray
    doppler_phase_rad: FloatArray


def downlink_dynamics(
    times_s: ArrayLike,
    carrier_frequency_hz: float,
    config: IdealOrbitConfig = IdealOrbitConfig(),
    *,
    phase_reference_time_s: float = 0.0,
) -> DownlinkDynamics:
    """Calculate one-way delay and first-order Doppler quantities.

    Radial velocity is positive while range is increasing. The project Doppler
    convention is ``f_D = -(v_r / c) f_c``, so an approaching satellite has a
    positive Doppler shift. Doppler phase is relative to
    ``phase_reference_time_s`` and its time derivative is ``2*pi*f_D``.
    """
    if not np.isfinite(carrier_frequency_hz) or carrier_frequency_hz <= 0.0:
        raise ValueError("carrier_frequency_hz must be finite and positive")
    if not np.isfinite(phase_reference_time_s):
        raise ValueError("phase_reference_time_s must be finite")

    geometry = downlink_geometry(times_s, config)
    station = ground_station_state(times_s, config)
    satellite = satellite_state(times_s, config)
    relative_velocity = satellite.velocity_km_s - station.velocity_km_s

    radial_velocity = np.sum(
        geometry.relative_position_km * relative_velocity,
        axis=-1,
    ) / geometry.slant_range_km
    propagation_delay = geometry.slant_range_km / SPEED_OF_LIGHT_KM_S
    doppler_shift = (
        -radial_velocity / SPEED_OF_LIGHT_KM_S * carrier_frequency_hz
    )

    reference_range = float(
        downlink_geometry(phase_reference_time_s, config).slant_range_km
    )
    doppler_phase = (
        -2.0
        * np.pi
        * carrier_frequency_hz
        / SPEED_OF_LIGHT_KM_S
        * (geometry.slant_range_km - reference_range)
    )

    return DownlinkDynamics(
        propagation_delay_s=propagation_delay,
        radial_velocity_km_s=radial_velocity,
        doppler_shift_hz=doppler_shift,
        doppler_phase_rad=doppler_phase,
    )

