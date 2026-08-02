"""Waveform-independent carrier-frequency and phase compensation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.satellite_channel import (
    SISOChannelResult,
    SISOChannelSequenceResult,
)

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


@dataclass(frozen=True, slots=True)
class CFOSequenceCompensationResult:
    """Phase-continuous compensation result for a multi-block sequence.

    Doppler estimates and residuals have shape ``(block_count,)``. Residual
    CFO follows ``true_doppler_hz - estimated_doppler_hz``. The initial-phase
    residual is reported at every block start, including accumulated frequency
    estimation error from all preceding blocks.
    """

    compensated_signal: ComplexArray
    correction_phase_rad: FloatArray
    sample_rate_hz: float
    block_boundaries: NDArray[np.int64]
    estimated_doppler_hz: FloatArray
    estimated_block_initial_phase_rad: FloatArray
    true_doppler_hz: FloatArray
    true_block_initial_phase_rad: FloatArray
    residual_cfo_hz: FloatArray
    residual_block_initial_phase_rad: FloatArray
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


def _block_estimates(values: ArrayLike, block_count: int) -> FloatArray:
    estimates = np.asarray(values, dtype=np.float64)
    if estimates.ndim == 0:
        estimates = np.full(block_count, float(estimates), dtype=np.float64)
    if estimates.shape != (block_count,):
        raise ValueError(
            f"estimated_doppler_hz must have shape ({block_count},)"
        )
    if not np.all(np.isfinite(estimates)):
        raise ValueError("estimated_doppler_hz must contain only finite values")
    return estimates


def compensate_siso_channel_sequence_doppler(
    channel: SISOChannelSequenceResult,
    *,
    estimated_doppler_hz: ArrayLike | None = None,
    estimated_initial_phase_rad: float | None = None,
) -> CFOSequenceCompensationResult:
    """Compensate a multi-block channel with continuous correction phase.

    Omitting estimates selects the perfect-knowledge reference branch. A
    scalar Doppler estimate is broadcast to every block; an array supplies one
    estimate per block. The correction oscillator is never reset at a block
    boundary, so any frequency-estimation error accumulates naturally.
    """

    block_count = channel.block_count
    true_doppler_hz = np.asarray(channel.doppler_shift_hz, dtype=np.float64)
    estimates = (
        true_doppler_hz.copy()
        if estimated_doppler_hz is None
        else _block_estimates(estimated_doppler_hz, block_count)
    )
    first_phase_estimate = (
        float(channel.block_initial_phase_rad[0])
        if estimated_initial_phase_rad is None
        else _finite(
            estimated_initial_phase_rad,
            "estimated_initial_phase_rad",
        )
    )

    correction_phase = np.empty(channel.sample_count, dtype=np.float64)
    estimated_block_phase = np.empty(block_count, dtype=np.float64)
    current_phase_rad = first_phase_estimate
    for block_index, frequency_hz in enumerate(estimates):
        start = int(channel.block_boundaries[block_index])
        stop = int(channel.block_boundaries[block_index + 1])
        block_length = stop - start
        local_sample_index = np.arange(block_length, dtype=np.float64)
        estimated_block_phase[block_index] = current_phase_rad
        correction_phase[start:stop] = (
            current_phase_rad
            + 2.0
            * np.pi
            * frequency_hz
            * local_sample_index
            / channel.sample_rate_hz
        )
        current_phase_rad += (
            2.0
            * np.pi
            * frequency_hz
            * block_length
            / channel.sample_rate_hz
        )

    compensated = channel.received_signal * np.exp(-1j * correction_phase)[
        None, :
    ]
    true_block_phase = np.asarray(
        channel.block_initial_phase_rad,
        dtype=np.float64,
    )
    return CFOSequenceCompensationResult(
        compensated_signal=compensated,
        correction_phase_rad=correction_phase,
        sample_rate_hz=channel.sample_rate_hz,
        block_boundaries=channel.block_boundaries.copy(),
        estimated_doppler_hz=estimates,
        estimated_block_initial_phase_rad=estimated_block_phase,
        true_doppler_hz=true_doppler_hz,
        true_block_initial_phase_rad=true_block_phase,
        residual_cfo_hz=true_doppler_hz - estimates,
        residual_block_initial_phase_rad=(
            true_block_phase - estimated_block_phase
        ),
        input_average_power_w=float(
            np.mean(np.abs(channel.received_signal) ** 2)
        ),
        output_average_power_w=float(np.mean(np.abs(compensated) ** 2)),
    )
