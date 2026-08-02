"""Waveform-independent carrier-frequency and phase compensation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.satellite_channel import SISOChannelResult

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]


def _finite(value: float, name: str) -> float:
    converted = float(value)
    if not np.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def _siso_signal(signal: ArrayLike) -> ComplexArray:
    samples = np.asarray(signal, dtype=np.complex128)
    if samples.ndim != 2 or samples.shape[0] != 1 or samples.shape[1] == 0:
        raise ValueError("received_signal must have shape (1, sample_count)")
    if not np.all(np.isfinite(samples.real)) or not np.all(
        np.isfinite(samples.imag)
    ):
        raise ValueError("received_signal must contain only finite samples")
    return samples


@dataclass(frozen=True, slots=True)
class CFOCompensationResult:
    """Compensated SISO waveform and optional ground-truth residuals.

    Residual CFO is defined as ``true_cfo_hz - estimated_cfo_hz``. A positive
    residual therefore leaves a positive phase slope after compensation.
    """

    compensated_signal: ComplexArray
    correction_phase_rad: FloatArray
    sample_rate_hz: float
    estimated_cfo_hz: float
    estimated_initial_phase_rad: float
    true_cfo_hz: float | None
    true_initial_phase_rad: float | None
    residual_cfo_hz: float | None
    residual_initial_phase_rad: float | None
    input_average_power_w: float
    output_average_power_w: float


def compensate_cfo(
    received_signal: ArrayLike,
    sample_rate_hz: float,
    estimated_cfo_hz: float,
    *,
    estimated_initial_phase_rad: float = 0.0,
    true_cfo_hz: float | None = None,
    true_initial_phase_rad: float | None = None,
) -> CFOCompensationResult:
    """Remove an estimated constant CFO and initial phase from one block.

    Only phase is changed; propagation attenuation and AWGN remain in the
    compensated signal. Truth arguments are optional metadata used to report
    residual errors and do not affect the correction itself.
    """

    samples = _siso_signal(received_signal)
    rate = _finite(sample_rate_hz, "sample_rate_hz")
    if rate <= 0.0:
        raise ValueError("sample_rate_hz must be positive")
    estimate = _finite(estimated_cfo_hz, "estimated_cfo_hz")
    phase_estimate = _finite(
        estimated_initial_phase_rad,
        "estimated_initial_phase_rad",
    )
    true_frequency = (
        None if true_cfo_hz is None else _finite(true_cfo_hz, "true_cfo_hz")
    )
    true_phase = (
        None
        if true_initial_phase_rad is None
        else _finite(true_initial_phase_rad, "true_initial_phase_rad")
    )

    sample_index = np.arange(samples.shape[1], dtype=np.float64)
    correction_phase = (
        phase_estimate + 2.0 * np.pi * estimate * sample_index / rate
    )
    compensated = samples * np.exp(-1j * correction_phase)[None, :]
    residual_frequency = (
        None if true_frequency is None else true_frequency - estimate
    )
    residual_phase = None if true_phase is None else true_phase - phase_estimate

    return CFOCompensationResult(
        compensated_signal=compensated,
        correction_phase_rad=correction_phase,
        sample_rate_hz=rate,
        estimated_cfo_hz=estimate,
        estimated_initial_phase_rad=phase_estimate,
        true_cfo_hz=true_frequency,
        true_initial_phase_rad=true_phase,
        residual_cfo_hz=residual_frequency,
        residual_initial_phase_rad=residual_phase,
        input_average_power_w=float(np.mean(np.abs(samples) ** 2)),
        output_average_power_w=float(np.mean(np.abs(compensated) ** 2)),
    )


def compensate_siso_channel_doppler(
    channel: SISOChannelResult,
    *,
    estimated_doppler_hz: float | None = None,
    estimated_initial_phase_rad: float | None = None,
) -> CFOCompensationResult:
    """Compensate a SISO channel result with perfect or estimated parameters.

    Omitting both estimates selects the perfect-knowledge reference branch.
    Supplying imperfect estimates leaves explicitly reported residual CFO and
    phase errors.
    """

    true_frequency = float(channel.doppler_shift_hz)
    true_phase = float(channel.doppler_phase_rad[0])
    frequency_estimate = (
        true_frequency
        if estimated_doppler_hz is None
        else estimated_doppler_hz
    )
    phase_estimate = (
        true_phase
        if estimated_initial_phase_rad is None
        else estimated_initial_phase_rad
    )
    return compensate_cfo(
        channel.received_signal,
        channel.sample_rate_hz,
        frequency_estimate,
        estimated_initial_phase_rad=phase_estimate,
        true_cfo_hz=true_frequency,
        true_initial_phase_rad=true_phase,
    )
