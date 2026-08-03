"""Resample sparse orbital states onto a faster channel-update timeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import CubicHermiteSpline

from starlink_isl.actual_downlink import VISIBILITY_ELEVATION_TOLERANCE_DEG
from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S
from starlink_isl.si_interface import DownlinkStateSI

FloatArray = NDArray[np.float64]
SPEED_OF_LIGHT_M_S = 1_000.0 * SPEED_OF_LIGHT_KM_S


def _time_vector(values: ArrayLike, name: str) -> FloatArray:
    times = np.asarray(values, dtype=np.float64)
    if times.ndim == 0:
        times = times.reshape(1)
    if times.ndim != 1 or times.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(times)):
        raise ValueError(f"{name} must contain only finite values")
    if times.size > 1 and np.any(np.diff(times) <= 0.0):
        raise ValueError(f"{name} must be strictly increasing")
    return times


def _finite_positive(value: float, name: str) -> float:
    converted = float(value)
    if not np.isfinite(converted) or converted <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return converted


def _linear_resample(
    source_time_s: FloatArray,
    values: ArrayLike,
    target_time_s: FloatArray,
) -> FloatArray:
    source_values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(source_values)
    if not np.any(finite):
        return np.full(target_time_s.shape, np.nan, dtype=np.float64)
    if np.count_nonzero(finite) == 1:
        return np.full(
            target_time_s.shape,
            float(source_values[finite][0]),
            dtype=np.float64,
        )
    return np.interp(
        target_time_s,
        source_time_s[finite],
        source_values[finite],
    )


def _azimuth_resample(
    source_time_s: FloatArray,
    azimuth_rad: ArrayLike,
    target_time_s: FloatArray,
) -> FloatArray:
    values = np.asarray(azimuth_rad, dtype=np.float64)
    finite = np.isfinite(values)
    if not np.any(finite):
        return np.full(target_time_s.shape, np.nan, dtype=np.float64)
    unwrapped = np.unwrap(values[finite])
    if unwrapped.size == 1:
        interpolated = np.full(target_time_s.shape, unwrapped[0])
    else:
        interpolated = np.interp(
            target_time_s,
            source_time_s[finite],
            unwrapped,
        )
    return np.mod(interpolated, 2.0 * np.pi)


def _phase_reference_range_m(
    source: DownlinkStateSI,
    carrier_frequency_hz: float,
    supplied_reference_m: float | None,
) -> float:
    if supplied_reference_m is not None:
        return _finite_positive(
            supplied_reference_m,
            "phase_reference_range_m",
        )
    phase_per_metre = 2.0 * np.pi * carrier_frequency_hz / SPEED_OF_LIGHT_M_S
    candidates = source.slant_range_m + source.doppler_phase_rad / phase_per_metre
    reference = float(np.mean(candidates))
    reconstructed_phase = -phase_per_metre * (
        source.slant_range_m - reference
    )
    if not np.allclose(
        reconstructed_phase,
        source.doppler_phase_rad,
        rtol=0.0,
        atol=1.0e-4,
    ):
        raise ValueError(
            "source Doppler phase is inconsistent with carrier_frequency_hz"
        )
    return _finite_positive(reference, "inferred phase reference range")


def resample_downlink_state_si(
    source: DownlinkStateSI,
    target_time_s: ArrayLike,
    carrier_frequency_hz: float,
    *,
    minimum_elevation_rad: float = 0.0,
    phase_reference_range_m: float | None = None,
) -> DownlinkStateSI:
    """Cubic-Hermite resample a sparse SI state without extrapolation.

    Position and velocity in the source coordinate frame define the Hermite
    polynomials. Range, LOS, range rate, delay, Doppler, and phase are then
    recomputed from the interpolated vectors. SGP4 remains the reference orbit
    model; this function only fills times between its anchor states.
    """

    source_time_s = _time_vector(source.time_s, "source.time_s")
    if source_time_s.size < 2:
        raise ValueError("source must contain at least two anchor states")
    target_times = _time_vector(target_time_s, "target_time_s")
    if target_times[0] < source_time_s[0] or target_times[-1] > source_time_s[-1]:
        raise ValueError("target_time_s must lie inside the source time interval")
    carrier_hz = _finite_positive(
        carrier_frequency_hz,
        "carrier_frequency_hz",
    )
    minimum_elevation = float(minimum_elevation_rad)
    if not np.isfinite(minimum_elevation) or not (
        -0.5 * np.pi <= minimum_elevation <= 0.5 * np.pi
    ):
        raise ValueError("minimum_elevation_rad must be in [-pi/2, pi/2]")

    expected_source_doppler_hz = (
        -source.radial_velocity_m_s / SPEED_OF_LIGHT_M_S * carrier_hz
    )
    if not np.allclose(
        expected_source_doppler_hz,
        source.doppler_shift_hz,
        rtol=1.0e-10,
        atol=1.0e-6,
    ):
        raise ValueError(
            "source Doppler shift is inconsistent with carrier_frequency_hz"
        )
    reference_range_m = _phase_reference_range_m(
        source,
        carrier_hz,
        phase_reference_range_m,
    )

    satellite_spline = CubicHermiteSpline(
        source_time_s,
        source.satellite_position_m,
        source.satellite_velocity_m_s,
        axis=0,
        extrapolate=False,
    )
    ue_spline = CubicHermiteSpline(
        source_time_s,
        source.ue_position_m,
        source.ue_velocity_m_s,
        axis=0,
        extrapolate=False,
    )
    satellite_position_m = np.asarray(
        satellite_spline(target_times),
        dtype=np.float64,
    )
    satellite_velocity_m_s = np.asarray(
        satellite_spline(target_times, 1),
        dtype=np.float64,
    )
    ue_position_m = np.asarray(ue_spline(target_times), dtype=np.float64)
    ue_velocity_m_s = np.asarray(ue_spline(target_times, 1), dtype=np.float64)

    satellite_to_ue_m = ue_position_m - satellite_position_m
    slant_range_m = np.linalg.norm(satellite_to_ue_m, axis=1)
    if np.any(slant_range_m <= 0.0):
        raise ValueError("interpolated satellite and UE positions must be distinct")
    los_satellite_to_ue = satellite_to_ue_m / slant_range_m[:, None]
    relative_velocity_m_s = ue_velocity_m_s - satellite_velocity_m_s
    radial_velocity_m_s = np.sum(
        relative_velocity_m_s * los_satellite_to_ue,
        axis=1,
    )
    propagation_delay_s = slant_range_m / SPEED_OF_LIGHT_M_S
    doppler_shift_hz = (
        -radial_velocity_m_s / SPEED_OF_LIGHT_M_S * carrier_hz
    )
    phase_per_metre = 2.0 * np.pi * carrier_hz / SPEED_OF_LIGHT_M_S
    doppler_phase_rad = -phase_per_metre * (
        slant_range_m - reference_range_m
    )

    elevation_rad = _linear_resample(
        source_time_s,
        source.elevation_rad,
        target_times,
    )
    visibility_tolerance_rad = np.deg2rad(
        VISIBILITY_ELEVATION_TOLERANCE_DEG
    )
    return DownlinkStateSI(
        coordinate_frame=source.coordinate_frame,
        time_s=target_times,
        satellite_position_m=satellite_position_m,
        satellite_velocity_m_s=satellite_velocity_m_s,
        ue_position_m=ue_position_m,
        ue_velocity_m_s=ue_velocity_m_s,
        los_satellite_to_ue_unit=los_satellite_to_ue,
        slant_range_m=slant_range_m,
        surface_distance_m=_linear_resample(
            source_time_s,
            source.surface_distance_m,
            target_times,
        ),
        azimuth_rad=_azimuth_resample(
            source_time_s,
            source.azimuth_rad,
            target_times,
        ),
        elevation_rad=elevation_rad,
        radial_velocity_m_s=radial_velocity_m_s,
        propagation_delay_s=propagation_delay_s,
        doppler_shift_hz=doppler_shift_hz,
        doppler_phase_rad=doppler_phase_rad,
        visible=elevation_rad >= minimum_elevation - visibility_tolerance_rad,
    )


@dataclass(frozen=True, slots=True)
class StateResamplingError:
    """Maximum absolute errors against a direct reference state."""

    satellite_position_m: float
    satellite_velocity_m_s: float
    slant_range_m: float
    radial_velocity_m_s: float
    propagation_delay_s: float
    doppler_shift_hz: float
    doppler_phase_rad: float
    los_angle_rad: float


def compare_downlink_states(
    reference: DownlinkStateSI,
    approximation: DownlinkStateSI,
) -> StateResamplingError:
    """Return maximum errors for states sampled at identical times."""

    if reference.coordinate_frame != approximation.coordinate_frame:
        raise ValueError("states must use the same coordinate frame")
    if reference.sample_count != approximation.sample_count or not np.allclose(
        reference.time_s,
        approximation.time_s,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise ValueError("states must contain identical sample times")
    los_dot = np.sum(
        reference.los_satellite_to_ue_unit
        * approximation.los_satellite_to_ue_unit,
        axis=1,
    )
    los_angle_rad = np.arccos(np.clip(los_dot, -1.0, 1.0))
    return StateResamplingError(
        satellite_position_m=float(
            np.max(
                np.linalg.norm(
                    reference.satellite_position_m
                    - approximation.satellite_position_m,
                    axis=1,
                )
            )
        ),
        satellite_velocity_m_s=float(
            np.max(
                np.linalg.norm(
                    reference.satellite_velocity_m_s
                    - approximation.satellite_velocity_m_s,
                    axis=1,
                )
            )
        ),
        slant_range_m=float(
            np.max(np.abs(reference.slant_range_m - approximation.slant_range_m))
        ),
        radial_velocity_m_s=float(
            np.max(
                np.abs(
                    reference.radial_velocity_m_s
                    - approximation.radial_velocity_m_s
                )
            )
        ),
        propagation_delay_s=float(
            np.max(
                np.abs(
                    reference.propagation_delay_s
                    - approximation.propagation_delay_s
                )
            )
        ),
        doppler_shift_hz=float(
            np.max(
                np.abs(
                    reference.doppler_shift_hz
                    - approximation.doppler_shift_hz
                )
            )
        ),
        doppler_phase_rad=float(
            np.max(
                np.abs(
                    reference.doppler_phase_rad
                    - approximation.doppler_phase_rad
                )
            )
        ),
        los_angle_rad=float(np.max(los_angle_rad)),
    )
