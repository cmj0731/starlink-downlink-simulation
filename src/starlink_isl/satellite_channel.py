"""Waveform-independent SISO satellite downlink channel.

This module deliberately does not generate or demodulate OFDM symbols. It
accepts an arbitrary complex-baseband waveform and applies only the propagation
effects owned by the channel model: free-space attenuation, locally constant
Doppler phase rotation, and optional receiver thermal noise. Long waveforms can
be divided into blocks so that geometry is updated without resetting phase.
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
    sample_rate_hz: float
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


@dataclass(frozen=True, slots=True)
class SISOChannelSequenceResult:
    """Time-varying SISO channel output divided into contiguous blocks.

    Signal arrays have shape ``(1, sample_count)``. Block metadata arrays have
    shape ``(block_count,)`` and ``block_boundaries`` has shape
    ``(block_count + 1,)``. Geometry is locally constant inside each block,
    while ``doppler_phase_rad`` is integrated continuously across boundaries.
    """

    sample_time_s: FloatArray
    sample_rate_hz: float
    received_signal: ComplexArray
    noiseless_received_signal: ComplexArray
    noise_signal: ComplexArray
    doppler_phase_rad: FloatArray
    block_boundaries: NDArray[np.int64]
    state_indices: NDArray[np.int64]
    block_start_time_s: FloatArray
    free_space_path_loss_db: FloatArray
    path_amplitude_gain: FloatArray
    propagation_delay_s: FloatArray
    doppler_shift_hz: FloatArray
    block_initial_phase_rad: FloatArray
    thermal_noise_power_w: float
    input_average_power: float
    expected_signal_power_w: FloatArray
    expected_snr_db: FloatArray
    timing_aligned: bool = True

    @property
    def sample_count(self) -> int:
        """Number of waveform samples in the sequence."""

        return int(self.received_signal.shape[1])

    @property
    def block_count(self) -> int:
        """Number of locally constant channel blocks."""

        return int(self.state_indices.size)


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


def _integer_vector(values: ArrayLike, name: str) -> NDArray[np.int64]:
    array = np.asarray(values)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    if not np.issubdtype(array.dtype, np.integer):
        raise TypeError(f"{name} must contain integers")
    return np.asarray(array, dtype=np.int64)


def _sequence_layout(
    sample_count: int,
    state: DownlinkStateSI,
    block_boundaries: ArrayLike,
    state_indices: ArrayLike,
    sample_rate_hz: float,
) -> tuple[NDArray[np.int64], NDArray[np.int64], FloatArray]:
    boundaries = _integer_vector(block_boundaries, "block_boundaries")
    indices = _integer_vector(state_indices, "state_indices")
    if boundaries.size < 2:
        raise ValueError("block_boundaries must contain at least [0, sample_count]")
    if boundaries[0] != 0 or boundaries[-1] != sample_count:
        raise ValueError("block_boundaries must start at 0 and end at sample_count")
    if np.any(np.diff(boundaries) <= 0):
        raise ValueError("block_boundaries must be strictly increasing")
    if indices.size != boundaries.size - 1:
        raise ValueError("state_indices must contain one index per block")
    if np.any(indices < 0) or np.any(indices >= state.sample_count):
        raise IndexError("state_indices contains an index outside the downlink state")

    sequence_start_time_s = float(state.time_s[indices[0]])
    expected_start_times_s = (
        sequence_start_time_s + boundaries[:-1] / sample_rate_hz
    )
    selected_start_times_s = np.asarray(state.time_s[indices], dtype=np.float64)
    time_tolerance_s = max(1.0e-9, 1.0 / sample_rate_hz)
    if not np.allclose(
        selected_start_times_s,
        expected_start_times_s,
        rtol=0.0,
        atol=time_tolerance_s,
    ):
        raise ValueError(
            "selected state times must match block starts on the waveform sample clock"
        )
    return boundaries, indices, expected_start_times_s


def _path_amplitude(
    slant_range_m: float,
    config: SISOChannelConfig,
) -> tuple[float, float]:
    if not np.isfinite(slant_range_m) or slant_range_m <= 0.0:
        raise ValueError("selected slant range must be finite and positive")
    path_loss_db = float(
        free_space_path_loss_db(
            slant_range_m / 1_000.0,
            config.carrier_frequency_hz,
        )
    )
    amplitude_gain = float(
        10.0 ** (-(path_loss_db + config.other_losses_db) / 20.0)
    )
    return path_loss_db, amplitude_gain


def _thermal_noise(
    shape: tuple[int, int],
    config: SISOChannelConfig,
    random_seed: int | None,
) -> tuple[ComplexArray, float]:
    noise_power_w = (
        BOLTZMANN_J_K
        * config.system_noise_temperature_k
        * config.effective_noise_bandwidth_hz
    )
    if not config.add_awgn:
        return np.zeros(shape, dtype=np.complex128), float(noise_power_w)

    seed = config.random_seed if random_seed is None else random_seed
    if not isinstance(seed, (int, np.integer)):
        raise TypeError("random_seed must be an integer")
    if int(seed) < 0:
        raise ValueError("random_seed must be non-negative")
    generator = np.random.default_rng(int(seed))
    noise_sigma = np.sqrt(0.5 * noise_power_w)
    noise = noise_sigma * (
        generator.standard_normal(shape) + 1j * generator.standard_normal(shape)
    )
    return np.asarray(noise, dtype=np.complex128), float(noise_power_w)


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

    path_loss_db, path_amplitude_gain = _path_amplitude(
        float(state.slant_range_m[index]),
        config,
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

    noise, noise_power_w = _thermal_noise(samples.shape, config, random_seed)

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
        sample_rate_hz=config.sample_rate_hz,
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


def apply_siso_downlink_sequence(
    tx_signal: ArrayLike,
    state: DownlinkStateSI,
    config: SISOChannelConfig,
    *,
    block_boundaries: ArrayLike,
    state_indices: ArrayLike,
    initial_phase_rad: float | None = None,
    random_seed: int | None = None,
) -> SISOChannelSequenceResult:
    """Apply a piecewise-constant, phase-continuous SISO downlink channel.

    ``block_boundaries`` are waveform sample indices such as
    ``[0, 1024, 2048]``. ``state_indices`` selects one geometry sample for each
    block. Selected state times must coincide with those block starts on the
    sample clock. This keeps the sequence physically timed while remaining
    independent of OFDM symbols, pilots, and modulation.

    The first phase defaults to the first selected state's absolute Doppler
    phase. Later block phases are obtained by continuous piecewise integration
    of Doppler frequency, so no artificial phase reset occurs at a boundary.
    """

    samples = _siso_signal(tx_signal)
    boundaries, indices, block_start_times_s = _sequence_layout(
        samples.shape[1],
        state,
        block_boundaries,
        state_indices,
        config.sample_rate_hz,
    )
    if initial_phase_rad is None:
        first_phase_rad = float(state.doppler_phase_rad[indices[0]])
    else:
        first_phase_rad = float(initial_phase_rad)
        if not np.isfinite(first_phase_rad):
            raise ValueError("initial_phase_rad must be finite")

    sample_time_s = (
        block_start_times_s[0]
        + np.arange(samples.shape[1], dtype=np.float64) / config.sample_rate_hz
    )
    phase = np.empty(samples.shape[1], dtype=np.float64)
    noiseless = np.empty_like(samples)
    block_count = indices.size
    path_loss_db = np.empty(block_count, dtype=np.float64)
    amplitude_gain = np.empty(block_count, dtype=np.float64)
    delay_s = np.empty(block_count, dtype=np.float64)
    doppler_hz = np.empty(block_count, dtype=np.float64)
    block_initial_phase_rad = np.empty(block_count, dtype=np.float64)
    expected_signal_power_w = np.empty(block_count, dtype=np.float64)
    expected_snr_db = np.empty(block_count, dtype=np.float64)
    transmit_amplitude_sqrt_w = np.sqrt(config.transmit_power_w)
    noise_power_w = (
        BOLTZMANN_J_K
        * config.system_noise_temperature_k
        * config.effective_noise_bandwidth_hz
    )

    current_phase_rad = first_phase_rad
    for block_index, state_index in enumerate(indices):
        start = int(boundaries[block_index])
        stop = int(boundaries[block_index + 1])
        block_length = stop - start
        local_offset_s = (
            np.arange(block_length, dtype=np.float64) / config.sample_rate_hz
        )
        loss_db, gain = _path_amplitude(
            float(state.slant_range_m[state_index]),
            config,
        )
        frequency_hz = float(state.doppler_shift_hz[state_index])
        if not np.isfinite(frequency_hz):
            raise ValueError("selected Doppler shift must be finite")

        block_phase = current_phase_rad + 2.0 * np.pi * frequency_hz * local_offset_s
        phase[start:stop] = block_phase
        noiseless[:, start:stop] = (
            transmit_amplitude_sqrt_w
            * gain
            * samples[:, start:stop]
            * np.exp(1j * block_phase)[None, :]
        )
        block_input_power = float(np.mean(np.abs(samples[:, start:stop]) ** 2))
        block_signal_power_w = (
            config.transmit_power_w * block_input_power * gain**2
        )

        path_loss_db[block_index] = loss_db
        amplitude_gain[block_index] = gain
        delay_s[block_index] = float(state.propagation_delay_s[state_index])
        doppler_hz[block_index] = frequency_hz
        block_initial_phase_rad[block_index] = current_phase_rad
        expected_signal_power_w[block_index] = block_signal_power_w
        expected_snr_db[block_index] = (
            float("-inf")
            if block_signal_power_w == 0.0
            else 10.0 * np.log10(block_signal_power_w / noise_power_w)
        )
        current_phase_rad += (
            2.0 * np.pi * frequency_hz * block_length / config.sample_rate_hz
        )

    noise, thermal_noise_power_w = _thermal_noise(
        samples.shape,
        config,
        random_seed,
    )
    return SISOChannelSequenceResult(
        sample_time_s=sample_time_s,
        sample_rate_hz=config.sample_rate_hz,
        received_signal=noiseless + noise,
        noiseless_received_signal=noiseless,
        noise_signal=noise,
        doppler_phase_rad=phase,
        block_boundaries=boundaries,
        state_indices=indices,
        block_start_time_s=block_start_times_s,
        free_space_path_loss_db=path_loss_db,
        path_amplitude_gain=amplitude_gain,
        propagation_delay_s=delay_s,
        doppler_shift_hz=doppler_hz,
        block_initial_phase_rad=block_initial_phase_rad,
        thermal_noise_power_w=thermal_noise_power_w,
        input_average_power=float(np.mean(np.abs(samples) ** 2)),
        expected_signal_power_w=expected_signal_power_w,
        expected_snr_db=expected_snr_db,
    )
