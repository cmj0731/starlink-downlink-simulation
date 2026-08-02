import numpy as np
import pytest

from starlink_isl import (
    SISOChannelConfig,
    apply_siso_downlink_channel,
    ideal_downlink_state_si,
)
from starlink_isl.link_budget import BOLTZMANN_J_K, free_space_path_loss_db


CARRIER_FREQUENCY_HZ = 10.0e9
SAMPLE_RATE_HZ = 1.0e6


def test_noiseless_overhead_channel_applies_physical_path_amplitude():
    state = ideal_downlink_state_si(0.0, CARRIER_FREQUENCY_HZ)
    tx_signal = np.ones((1, 1_024), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        transmit_power_w=4.0,
        add_awgn=False,
    )

    result = apply_siso_downlink_channel(tx_signal, state, config)
    expected_loss_db = float(
        free_space_path_loss_db(572.0, CARRIER_FREQUENCY_HZ)
    )
    expected_amplitude = 10.0 ** (-expected_loss_db / 20.0)

    assert result.received_signal.shape == tx_signal.shape
    assert result.noiseless_received_signal == pytest.approx(
        result.received_signal
    )
    assert result.noise_signal == pytest.approx(np.zeros_like(tx_signal))
    assert result.free_space_path_loss_db == pytest.approx(expected_loss_db)
    assert result.path_amplitude_gain == pytest.approx(expected_amplitude)
    assert np.abs(result.received_signal) == pytest.approx(
        2.0 * expected_amplitude
    )
    assert result.expected_signal_power_w == pytest.approx(
        4.0 * expected_amplitude**2
    )
    assert result.propagation_delay_s == pytest.approx(
        state.propagation_delay_s[0]
    )
    assert result.timing_aligned is True


def test_doppler_phase_advances_at_selected_state_frequency():
    state = ideal_downlink_state_si(-100.0, CARRIER_FREQUENCY_HZ)
    tx_signal = np.ones((1, 2_048), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        add_awgn=False,
    )

    result = apply_siso_downlink_channel(tx_signal, state, config)
    expected_step = 2.0 * np.pi * state.doppler_shift_hz[0] / SAMPLE_RATE_HZ

    assert np.diff(result.doppler_phase_rad) == pytest.approx(expected_step)
    assert result.doppler_shift_hz == pytest.approx(
        state.doppler_shift_hz[0]
    )
    assert result.sample_time_s[0] == pytest.approx(state.time_s[0])
    assert result.sample_time_s[-1] == pytest.approx(
        state.time_s[0] + (tx_signal.shape[1] - 1) / SAMPLE_RATE_HZ
    )


def test_path_amplitude_is_inversely_proportional_to_range():
    state = ideal_downlink_state_si(
        [0.0, 200.0],
        CARRIER_FREQUENCY_HZ,
    )
    tx_signal = np.ones((1, 16), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        add_awgn=False,
    )

    overhead = apply_siso_downlink_channel(
        tx_signal,
        state,
        config,
        state_index=0,
    )
    later = apply_siso_downlink_channel(
        tx_signal,
        state,
        config,
        state_index=1,
    )

    assert overhead.path_amplitude_gain / later.path_amplitude_gain == (
        pytest.approx(state.slant_range_m[1] / state.slant_range_m[0])
    )


def test_other_losses_use_amplitude_not_power_conversion():
    state = ideal_downlink_state_si(0.0, CARRIER_FREQUENCY_HZ)
    tx_signal = np.ones((1, 8), dtype=np.complex128)
    baseline = apply_siso_downlink_channel(
        tx_signal,
        state,
        SISOChannelConfig(
            carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
            sample_rate_hz=SAMPLE_RATE_HZ,
            add_awgn=False,
        ),
    )
    with_loss = apply_siso_downlink_channel(
        tx_signal,
        state,
        SISOChannelConfig(
            carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
            sample_rate_hz=SAMPLE_RATE_HZ,
            other_losses_db=6.0,
            add_awgn=False,
        ),
    )

    assert with_loss.path_amplitude_gain / baseline.path_amplitude_gain == (
        pytest.approx(10.0 ** (-6.0 / 20.0))
    )


def test_awgn_is_deterministic_and_matches_ktb_power():
    state = ideal_downlink_state_si(0.0, CARRIER_FREQUENCY_HZ)
    tx_signal = np.zeros((1, 200_000), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        transmit_power_w=0.0,
        noise_bandwidth_hz=500.0e3,
        system_noise_temperature_k=290.0,
        random_seed=1234,
    )

    first = apply_siso_downlink_channel(tx_signal, state, config)
    second = apply_siso_downlink_channel(tx_signal, state, config)
    expected_noise_power = BOLTZMANN_J_K * 290.0 * 500.0e3

    assert first.noise_signal == pytest.approx(second.noise_signal)
    assert first.received_signal == pytest.approx(first.noise_signal)
    assert first.thermal_noise_power_w == pytest.approx(expected_noise_power)
    assert np.mean(np.abs(first.noise_signal) ** 2) == pytest.approx(
        expected_noise_power,
        rel=0.01,
    )
    assert first.expected_snr_db == float("-inf")


@pytest.mark.parametrize(
    "tx_signal",
    [
        np.ones(8, dtype=np.complex128),
        np.ones((2, 8), dtype=np.complex128),
        np.ones((1, 0), dtype=np.complex128),
    ],
)
def test_siso_channel_rejects_non_siso_shapes(tx_signal):
    state = ideal_downlink_state_si(0.0, CARRIER_FREQUENCY_HZ)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )

    with pytest.raises(ValueError, match="shape"):
        apply_siso_downlink_channel(tx_signal, state, config)


def test_siso_channel_rejects_invalid_state_index():
    state = ideal_downlink_state_si(0.0, CARRIER_FREQUENCY_HZ)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
    )

    with pytest.raises(IndexError, match="state_index"):
        apply_siso_downlink_channel(
            np.ones((1, 8), dtype=np.complex128),
            state,
            config,
            state_index=1,
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"carrier_frequency_hz": 0.0}, "carrier_frequency_hz"),
        ({"sample_rate_hz": 0.0}, "sample_rate_hz"),
        ({"transmit_power_w": -1.0}, "transmit_power_w"),
        ({"noise_bandwidth_hz": 2.0e6}, "noise_bandwidth_hz"),
        ({"system_noise_temperature_k": 0.0}, "system_noise_temperature_k"),
        ({"other_losses_db": -1.0}, "other_losses_db"),
        ({"random_seed": -1}, "random_seed"),
    ],
)
def test_siso_channel_config_rejects_invalid_values(kwargs, message):
    values = {
        "carrier_frequency_hz": CARRIER_FREQUENCY_HZ,
        "sample_rate_hz": SAMPLE_RATE_HZ,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        SISOChannelConfig(**values)
