import numpy as np
import pytest

from starlink_isl.qpsk import (
    error_vector_magnitude_percent,
    estimate_pilot_frequency_and_phase,
    qpsk_demodulate,
    qpsk_modulate,
    simulate_qpsk_snapshot,
    simulate_pilot_aided_qpsk_snapshot,
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


def test_noiseless_pilot_estimates_doppler_and_phase_exactly():
    symbol_rate_hz = 1.0e6
    doppler_hz = -223_102.0
    common_phase_rad = 0.37
    pilot = qpsk_modulate(
        np.tile(np.array([0, 0, 0, 1], dtype=np.uint8), 64)
    )
    index = np.arange(len(pilot))
    received = pilot * np.exp(
        1j
        * (
            common_phase_rad
            + 2.0 * np.pi * doppler_hz * index / symbol_rate_hz
        )
    )

    estimated_doppler, estimated_phase = (
        estimate_pilot_frequency_and_phase(
            received,
            pilot,
            symbol_rate_hz,
        )
    )

    assert estimated_doppler == pytest.approx(doppler_hz, abs=1e-3)
    assert estimated_phase == pytest.approx(common_phase_rad, abs=1e-6)


def test_pilot_receiver_approaches_perfect_compensation():
    snapshot = simulate_pilot_aided_qpsk_snapshot(
        data_symbol_count=8_192,
        pilot_symbol_count=256,
        symbol_rate_hz=1.0e6,
        snr_db=44.0,
        doppler_hz=223_102.0,
        common_phase_rad=0.35,
        seed=99,
    )

    assert abs(snapshot.doppler_estimation_error_hz) < 2.0
    assert snapshot.ber_uncompensated > 0.4
    assert snapshot.ber_pilot_compensated < 1e-3
    assert snapshot.ber_perfect_compensated < 1e-3
    assert snapshot.evm_pilot_compensated_percent < 3.0


def test_pilot_estimator_rejects_aliased_doppler():
    with pytest.raises(ValueError, match="acquisition range"):
        simulate_pilot_aided_qpsk_snapshot(
            data_symbol_count=10,
            pilot_symbol_count=8,
            symbol_rate_hz=1.0e6,
            snr_db=20.0,
            doppler_hz=500_000.0,
            seed=1,
        )


@pytest.mark.parametrize("bad_bits", ([], [0], [0, 2]))
def test_qpsk_rejects_invalid_bits(bad_bits):
    with pytest.raises(ValueError):
        qpsk_modulate(bad_bits)
