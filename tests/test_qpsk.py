import numpy as np
import pytest

from starlink_isl.qpsk import (
    error_vector_magnitude_percent,
    qpsk_demodulate,
    qpsk_modulate,
    simulate_qpsk_snapshot,
    theoretical_qpsk_ber_awgn,
)


def test_qpsk_mapping_round_trip():
    bits = np.array([0, 0, 0, 1, 1, 1, 1, 0], dtype=np.uint8)
    symbols = qpsk_modulate(bits)

    assert np.abs(symbols) == pytest.approx(np.ones(4))
    assert qpsk_demodulate(symbols).tolist() == bits.tolist()
    assert error_vector_magnitude_percent(symbols, symbols) == 0.0


def test_theoretical_qpsk_ber_uses_symbol_snr():
    assert theoretical_qpsk_ber_awgn(0.0) == pytest.approx(
        0.158_655_253_9
    )


def test_perfect_doppler_compensation_recovers_awgn_baseline():
    snapshot = simulate_qpsk_snapshot(
        symbol_count=200_000,
        symbol_rate_hz=1.0e6,
        snr_db=6.0,
        doppler_hz=223_102.0,
        seed=1234,
    )
    theoretical = float(theoretical_qpsk_ber_awgn(6.0))

    assert snapshot.ber_compensated == pytest.approx(
        theoretical,
        abs=8e-4,
    )
    assert snapshot.ber_uncompensated > 0.4
    assert snapshot.evm_compensated_percent == pytest.approx(
        100.0 / np.sqrt(10.0 ** 0.6),
        rel=0.01,
    )


@pytest.mark.parametrize("bad_bits", ([], [0], [0, 2]))
def test_qpsk_rejects_invalid_bits(bad_bits):
    with pytest.raises(ValueError):
        qpsk_modulate(bad_bits)
