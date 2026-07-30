"""QPSK baseband waveform, AWGN, Doppler, and receiver metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
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
