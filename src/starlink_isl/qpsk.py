"""QPSK baseband waveform, AWGN, Doppler, and receiver metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize_scalar
from scipy.special import erfc

FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]
BitArray = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class QPSKSnapshot:
    """One locally stationary QPSK channel realization."""

    transmitted_symbols: ComplexArray
    received_uncompensated: ComplexArray
    received_compensated: ComplexArray
    transmitted_bits: BitArray
    detected_bits_uncompensated: BitArray
    detected_bits_compensated: BitArray
    ber_uncompensated: float
    ber_compensated: float
    evm_uncompensated_percent: float
    evm_compensated_percent: float


@dataclass(frozen=True, slots=True)
class PilotQPSKSnapshot:
    """QPSK frame received with pilot-estimated and perfect compensation."""

    transmitted_data_symbols: ComplexArray
    received_data_uncompensated: ComplexArray
    received_data_pilot_compensated: ComplexArray
    received_data_perfect_compensated: ComplexArray
    transmitted_data_bits: BitArray
    ber_uncompensated: float
    ber_pilot_compensated: float
    ber_perfect_compensated: float
    evm_uncompensated_percent: float
    evm_pilot_compensated_percent: float
    evm_perfect_compensated_percent: float
    estimated_doppler_hz: float
    doppler_estimation_error_hz: float
    estimated_common_phase_rad: float


def qpsk_modulate(bits: ArrayLike) -> ComplexArray:
    """Gray-map bit pairs to unit-energy QPSK symbols."""
    values = np.asarray(bits, dtype=np.uint8)
    if values.ndim != 1 or values.size == 0 or values.size % 2:
        raise ValueError("bits must be a non-empty one-dimensional even array")
    if np.any(values > 1):
        raise ValueError("bits must contain only 0 and 1")
    pairs = values.reshape(-1, 2)
    return (
        (1.0 - 2.0 * pairs[:, 0])
        + 1j * (1.0 - 2.0 * pairs[:, 1])
    ) / np.sqrt(2.0)


def qpsk_demodulate(symbols: ArrayLike) -> BitArray:
    """Hard-decision demodulate the QPSK mapping used by this module."""
    values = np.asarray(symbols, dtype=np.complex128)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("symbols must be a non-empty one-dimensional array")
    bits = np.empty(values.size * 2, dtype=np.uint8)
    bits[0::2] = np.real(values) < 0.0
    bits[1::2] = np.imag(values) < 0.0
    return bits


def theoretical_qpsk_ber_awgn(snr_db: ArrayLike) -> FloatArray:
    """Return coherent Gray-QPSK BER for symbol SNR ``Es/N0``."""
    snr_linear = 10.0 ** (np.asarray(snr_db, dtype=np.float64) / 10.0)
    return 0.5 * erfc(np.sqrt(snr_linear / 2.0))


def error_vector_magnitude_percent(
    reference: ArrayLike,
    measured: ArrayLike,
) -> float:
    """Return RMS EVM relative to the reference-symbol RMS magnitude."""
    expected = np.asarray(reference, dtype=np.complex128)
    actual = np.asarray(measured, dtype=np.complex128)
    if expected.shape != actual.shape or expected.size == 0:
        raise ValueError("reference and measured must have one matching shape")
    return float(
        100.0
        * np.sqrt(
            np.mean(np.abs(actual - expected) ** 2)
            / np.mean(np.abs(expected) ** 2)
        )
    )


def simulate_qpsk_snapshot(
    *,
    symbol_count: int,
    symbol_rate_hz: float,
    snr_db: float,
    doppler_hz: float,
    seed: int,
) -> QPSKSnapshot:
    """Simulate a locally constant Doppler/AWGN QPSK snapshot.

    Timing and channel amplitude are normalized after ideal AGC. The compensated
    branch uses perfect knowledge of the Doppler frequency, providing a receiver
    performance baseline.
    """
    if symbol_count <= 0:
        raise ValueError("symbol_count must be positive")
    if not np.isfinite(symbol_rate_hz) or symbol_rate_hz <= 0.0:
        raise ValueError("symbol_rate_hz must be finite and positive")
    if not np.isfinite(snr_db) or not np.isfinite(doppler_hz):
        raise ValueError("snr_db and doppler_hz must be finite")

    generator = np.random.default_rng(seed)
    transmitted_bits = generator.integers(
        0,
        2,
        size=2 * symbol_count,
        dtype=np.uint8,
    )
    transmitted_symbols = qpsk_modulate(transmitted_bits)
    sample_index = np.arange(symbol_count, dtype=np.float64)
    doppler_phase = (
        2.0 * np.pi * doppler_hz * sample_index / symbol_rate_hz
    )
    rotating_symbols = transmitted_symbols * np.exp(1j * doppler_phase)

    snr_linear = 10.0 ** (snr_db / 10.0)
    noise_sigma = np.sqrt(0.5 / snr_linear)
    noise = noise_sigma * (
        generator.standard_normal(symbol_count)
        + 1j * generator.standard_normal(symbol_count)
    )
    received_uncompensated = rotating_symbols + noise
    received_compensated = received_uncompensated * np.exp(
        -1j * doppler_phase
    )
    detected_uncompensated = qpsk_demodulate(received_uncompensated)
    detected_compensated = qpsk_demodulate(received_compensated)

    return QPSKSnapshot(
        transmitted_symbols=transmitted_symbols,
        received_uncompensated=received_uncompensated,
        received_compensated=received_compensated,
        transmitted_bits=transmitted_bits,
        detected_bits_uncompensated=detected_uncompensated,
        detected_bits_compensated=detected_compensated,
        ber_uncompensated=float(
            np.mean(detected_uncompensated != transmitted_bits)
        ),
        ber_compensated=float(
            np.mean(detected_compensated != transmitted_bits)
        ),
        evm_uncompensated_percent=error_vector_magnitude_percent(
            transmitted_symbols,
            received_uncompensated,
        ),
        evm_compensated_percent=error_vector_magnitude_percent(
            transmitted_symbols,
            received_compensated,
        ),
    )


def estimate_pilot_frequency_and_phase(
    received_pilot: ArrayLike,
    transmitted_pilot: ArrayLike,
    symbol_rate_hz: float,
) -> tuple[float, float]:
    """Estimate constant frequency offset and phase from known pilots.

    The adjacent-pilot phase-difference estimator is unambiguous for frequency
    offsets strictly inside plus or minus half the symbol rate.
    """
    received = np.asarray(received_pilot, dtype=np.complex128)
    transmitted = np.asarray(transmitted_pilot, dtype=np.complex128)
    if received.shape != transmitted.shape or received.ndim != 1:
        raise ValueError("received and transmitted pilots must match")
    if received.size < 2:
        raise ValueError("at least two pilot symbols are required")
    if not np.isfinite(symbol_rate_hz) or symbol_rate_hz <= 0.0:
        raise ValueError("symbol_rate_hz must be finite and positive")

    stripped = received * np.conj(transmitted)
    sample_index = np.arange(received.size, dtype=np.float64)
    fft_size = max(4_096, 16 * received.size)
    spectrum = np.fft.fftshift(np.fft.fft(stripped, n=fft_size))
    frequencies = np.fft.fftshift(
        np.fft.fftfreq(fft_size, d=1.0 / symbol_rate_hz)
    )
    coarse_index = int(np.argmax(np.abs(spectrum)))
    coarse_frequency = float(frequencies[coarse_index])
    bin_width_hz = symbol_rate_hz / fft_size
    lower = max(
        -0.5 * symbol_rate_hz,
        coarse_frequency - bin_width_hz,
    )
    upper = min(
        0.5 * symbol_rate_hz,
        coarse_frequency + bin_width_hz,
    )
    optimum = minimize_scalar(
        lambda frequency_hz: -abs(
            np.sum(
                stripped
                * np.exp(
                    -1j
                    * 2.0
                    * np.pi
                    * frequency_hz
                    * sample_index
                    / symbol_rate_hz
                )
            )
        ),
        bounds=(lower, upper),
        method="bounded",
        options={"xatol": 1e-6},
    )
    estimated_doppler_hz = float(optimum.x)
    phase_step = (
        2.0 * np.pi * estimated_doppler_hz / symbol_rate_hz
    )
    estimated_phase = np.angle(
        np.sum(stripped * np.exp(-1j * phase_step * sample_index))
    )
    return float(estimated_doppler_hz), float(estimated_phase)


def simulate_pilot_aided_qpsk_snapshot(
    *,
    data_symbol_count: int,
    pilot_symbol_count: int,
    symbol_rate_hz: float,
    snr_db: float,
    doppler_hz: float,
    seed: int,
    common_phase_rad: float = 0.0,
) -> PilotQPSKSnapshot:
    """Simulate one pilot-prefixed QPSK frame and three receiver branches."""
    if data_symbol_count <= 0:
        raise ValueError("data_symbol_count must be positive")
    if pilot_symbol_count < 2:
        raise ValueError("pilot_symbol_count must be at least 2")
    if not np.isfinite(symbol_rate_hz) or symbol_rate_hz <= 0.0:
        raise ValueError("symbol_rate_hz must be finite and positive")
    if not np.isfinite(snr_db) or not np.isfinite(doppler_hz):
        raise ValueError("snr_db and doppler_hz must be finite")
    if not np.isfinite(common_phase_rad):
        raise ValueError("common_phase_rad must be finite")
    if abs(doppler_hz) >= 0.5 * symbol_rate_hz:
        raise ValueError(
            "doppler_hz must be inside the pilot estimator's "
            "+/- symbol_rate_hz / 2 acquisition range"
        )

    generator = np.random.default_rng(seed)
    pilot_bits = generator.integers(
        0,
        2,
        size=2 * pilot_symbol_count,
        dtype=np.uint8,
    )
    data_bits = generator.integers(
        0,
        2,
        size=2 * data_symbol_count,
        dtype=np.uint8,
    )
    pilot_symbols = qpsk_modulate(pilot_bits)
    data_symbols = qpsk_modulate(data_bits)
    transmitted = np.concatenate((pilot_symbols, data_symbols))
    sample_index = np.arange(transmitted.size, dtype=np.float64)
    phase_step = 2.0 * np.pi * doppler_hz / symbol_rate_hz
    channel_phase = common_phase_rad + phase_step * sample_index

    snr_linear = 10.0 ** (snr_db / 10.0)
    noise_sigma = np.sqrt(0.5 / snr_linear)
    noise = noise_sigma * (
        generator.standard_normal(transmitted.size)
        + 1j * generator.standard_normal(transmitted.size)
    )
    received = transmitted * np.exp(1j * channel_phase) + noise
    estimated_doppler_hz, estimated_phase = (
        estimate_pilot_frequency_and_phase(
            received[:pilot_symbol_count],
            pilot_symbols,
            symbol_rate_hz,
        )
    )
    estimated_step = (
        2.0 * np.pi * estimated_doppler_hz / symbol_rate_hz
    )
    pilot_compensated = received * np.exp(
        -1j * (estimated_phase + estimated_step * sample_index)
    )
    perfect_compensated = received * np.exp(-1j * channel_phase)

    data_slice = slice(pilot_symbol_count, None)
    received_data = received[data_slice]
    pilot_data = pilot_compensated[data_slice]
    perfect_data = perfect_compensated[data_slice]

    def ber(samples: ComplexArray) -> float:
        return float(np.mean(qpsk_demodulate(samples) != data_bits))

    return PilotQPSKSnapshot(
        transmitted_data_symbols=data_symbols,
        received_data_uncompensated=received_data,
        received_data_pilot_compensated=pilot_data,
        received_data_perfect_compensated=perfect_data,
        transmitted_data_bits=data_bits,
        ber_uncompensated=ber(received_data),
        ber_pilot_compensated=ber(pilot_data),
        ber_perfect_compensated=ber(perfect_data),
        evm_uncompensated_percent=error_vector_magnitude_percent(
            data_symbols,
            received_data,
        ),
        evm_pilot_compensated_percent=error_vector_magnitude_percent(
            data_symbols,
            pilot_data,
        ),
        evm_perfect_compensated_percent=error_vector_magnitude_percent(
            data_symbols,
            perfect_data,
        ),
        estimated_doppler_hz=estimated_doppler_hz,
        doppler_estimation_error_hz=estimated_doppler_hz - doppler_hz,
        estimated_common_phase_rad=estimated_phase,
    )
