"""Waveform-independent SISO satellite downlink channel.

This module deliberately does not generate or demodulate OFDM symbols. It
accepts an arbitrary complex-baseband waveform and applies only the propagation
effects owned by the channel model: free-space attenuation, locally constant
Doppler phase rotation, and optional receiver thermal noise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.link_budget import (
    BOLTZMANN_J_K,
    REFERENCE_NOISE_TEMPERATURE_K,
    free_space_path_loss_db,
)
from starlink_isl.si_interface import DownlinkStateSI

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]


def _positive_finite(value: float, name: str) -> None:
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class SISOChannelConfig:
    """Physical and sampling settings for one SISO channel block.

    The input waveform is dimensionless. ``transmit_power_w`` therefore scales
    a unit-average-power input to a physical complex envelope in ``sqrt(W)``.
    No antenna or beamforming gain is included in this SISO baseline.
    """

    carrier_frequency_hz: float
    sample_rate_hz: float
    transmit_power_w: float = 1.0
    noise_bandwidth_hz: float | None = None
    system_noise_temperature_k: float = REFERENCE_NOISE_TEMPERATURE_K
    other_losses_db: float = 0.0
    add_awgn: bool = True
    random_seed: int = 52_285

    def __post_init__(self) -> None:
        _positive_finite(self.carrier_frequency_hz, "carrier_frequency_hz")
        _positive_finite(self.sample_rate_hz, "sample_rate_hz")
        if not np.isfinite(self.transmit_power_w) or self.transmit_power_w < 0.0:
            raise ValueError("transmit_power_w must be finite and non-negative")
        _positive_finite(
            self.system_noise_temperature_k,
            "system_noise_temperature_k",
        )
        if self.noise_bandwidth_hz is not None:
            _positive_finite(self.noise_bandwidth_hz, "noise_bandwidth_hz")
            if self.noise_bandwidth_hz > self.sample_rate_hz:
                raise ValueError("noise_bandwidth_hz cannot exceed sample_rate_hz")
        if not np.isfinite(self.other_losses_db) or self.other_losses_db < 0.0:
            raise ValueError("other_losses_db must be finite and non-negative")
        if not isinstance(self.add_awgn, bool):
            raise TypeError("add_awgn must be a bool")
        if not isinstance(self.random_seed, (int, np.integer)):
            raise TypeError("random_seed must be an integer")
        if int(self.random_seed) < 0:
            raise ValueError("random_seed must be non-negative")

    @property
    def effective_noise_bandwidth_hz(self) -> float:
        """Configured receiver-noise bandwidth, defaulting to sample rate."""

        if self.noise_bandwidth_hz is None:
            return self.sample_rate_hz
        return self.noise_bandwidth_hz


@dataclass(frozen=True, slots=True)
class SISOChannelResult:
    """One timing-aligned SISO channel block and its ground-truth metadata.

    Signal arrays have shape ``(1, sample_count)``. Received and noise samples
    are physical complex envelopes in ``sqrt(W)``. Absolute propagation delay
    is reported but not applied as a sample shift in this first-stage model.
    """

    sample_time_s: FloatArray
    received_signal: ComplexArray
    noiseless_received_signal: ComplexArray
    noise_signal: ComplexArray
    doppler_phase_rad: FloatArray
    free_space_path_loss_db: float
    path_amplitude_gain: float
    propagation_delay_s: float
    doppler_shift_hz: float
    thermal_noise_power_w: float
    input_average_power: float
    expected_signal_power_w: float
    expected_snr_db: float
    state_index: int
    timing_aligned: bool = True


def _siso_signal(signal: ArrayLike) -> ComplexArray:
    samples = np.asarray(signal, dtype=np.complex128)
    if samples.ndim != 2 or samples.shape[0] != 1 or samples.shape[1] == 0:
        raise ValueError("tx_signal must have shape (1, sample_count)")
    if not np.all(np.isfinite(samples.real)) or not np.all(
        np.isfinite(samples.imag)
    ):
        raise ValueError("tx_signal must contain only finite samples")
    return samples


def _valid_state_index(state: DownlinkStateSI, state_index: int) -> int:
    if not isinstance(state_index, (int, np.integer)):
        raise TypeError("state_index must be an integer")
    index = int(state_index)
    if not 0 <= index < state.sample_count:
        raise IndexError("state_index is outside the downlink state")
    return index


def apply_siso_downlink_channel(
    tx_signal: ArrayLike,
    state: DownlinkStateSI,
    config: SISOChannelConfig,
    *,
    state_index: int = 0,
    random_seed: int | None = None,
) -> SISOChannelResult:
    """Apply one locally constant downlink state to a complex waveform.

    The selected geometry and Doppler values remain constant over this block,
    while Doppler phase advances for every waveform sample. Calling code can
    update ``state_index`` once per OFDM symbol without this function depending
    on any OFDM-specific framing or pilot convention.
    """

    samples = _siso_signal(tx_signal)
    index = _valid_state_index(state, state_index)
    sample_count = samples.shape[1]
    sample_offset_s = np.arange(sample_count, dtype=np.float64) / (
        config.sample_rate_hz
    )
    sample_time_s = float(state.time_s[index]) + sample_offset_s

    slant_range_m = float(state.slant_range_m[index])
    if not np.isfinite(slant_range_m) or slant_range_m <= 0.0:
        raise ValueError("selected slant range must be finite and positive")
    path_loss_db = float(
        free_space_path_loss_db(
            slant_range_m / 1_000.0,
            config.carrier_frequency_hz,
        )
    )
    path_amplitude_gain = float(
        10.0 ** (-(path_loss_db + config.other_losses_db) / 20.0)
    )

    doppler_shift_hz = float(state.doppler_shift_hz[index])
    initial_phase_rad = float(state.doppler_phase_rad[index])
    doppler_phase_rad = (
        initial_phase_rad
        + 2.0 * np.pi * doppler_shift_hz * sample_offset_s
    )
    channel_phase = np.exp(1j * doppler_phase_rad)[None, :]
    transmit_amplitude_sqrt_w = np.sqrt(config.transmit_power_w)
    noiseless = (
        transmit_amplitude_sqrt_w
        * path_amplitude_gain
        * samples
        * channel_phase
    )

    noise_power_w = (
        BOLTZMANN_J_K
        * config.system_noise_temperature_k
        * config.effective_noise_bandwidth_hz
    )
    if config.add_awgn:
        seed = config.random_seed if random_seed is None else random_seed
        if not isinstance(seed, (int, np.integer)):
            raise TypeError("random_seed must be an integer")
        if int(seed) < 0:
            raise ValueError("random_seed must be non-negative")
        generator = np.random.default_rng(int(seed))
        noise_sigma = np.sqrt(0.5 * noise_power_w)
        noise = noise_sigma * (
            generator.standard_normal(samples.shape)
            + 1j * generator.standard_normal(samples.shape)
        )
    else:
        noise = np.zeros_like(samples)

    input_average_power = float(np.mean(np.abs(samples) ** 2))
    expected_signal_power_w = (
        config.transmit_power_w
        * input_average_power
        * path_amplitude_gain**2
    )
    if expected_signal_power_w == 0.0:
        expected_snr_db = float("-inf")
    else:
        expected_snr_db = float(
            10.0 * np.log10(expected_signal_power_w / noise_power_w)
        )

    return SISOChannelResult(
        sample_time_s=sample_time_s,
        received_signal=noiseless + noise,
        noiseless_received_signal=noiseless,
        noise_signal=noise,
        doppler_phase_rad=doppler_phase_rad,
        free_space_path_loss_db=path_loss_db,
        path_amplitude_gain=path_amplitude_gain,
        propagation_delay_s=float(state.propagation_delay_s[index]),
        doppler_shift_hz=doppler_shift_hz,
        thermal_noise_power_w=float(noise_power_w),
        input_average_power=input_average_power,
        expected_signal_power_w=expected_signal_power_w,
        expected_snr_db=expected_snr_db,
        state_index=index,
    )
