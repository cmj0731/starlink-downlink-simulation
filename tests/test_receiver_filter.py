import numpy as np
import pytest
from scipy.signal import freqz

from starlink_isl import (
    ReceiverFilterConfig,
    SISOChannelConfig,
    apply_siso_downlink_channel,
    apply_receiver_filter,
    compensate_siso_channel_doppler,
    design_receiver_filter,
    ideal_downlink_state_si,
)
from starlink_isl.link_budget import BOLTZMANN_J_K


SAMPLE_RATE_HZ = 1.0e6


def _config(**overrides):
    values = {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "passband_edge_hz": 100.0e3,
        "stopband_edge_hz": 180.0e3,
        "num_taps": 129,
    }
    values.update(overrides)
    return ReceiverFilterConfig(**values)


def test_filter_design_is_symmetric_with_unity_dc_gain():
    config = _config()
    taps = design_receiver_filter(config)

    assert taps.shape == (config.num_taps,)
    assert taps == pytest.approx(taps[::-1])
    assert np.sum(taps) == pytest.approx(1.0)
    assert config.group_delay_samples == 64


def test_filter_meets_representative_passband_and_stopband_response():
    config = _config()
    taps = design_receiver_filter(config)
    frequencies_hz = np.array([0.0, config.passband_edge_hz, config.stopband_edge_hz])
    angular_frequency = 2.0 * np.pi * frequencies_hz / SAMPLE_RATE_HZ
    _, response = freqz(taps, worN=angular_frequency)

    assert abs(response[0]) == pytest.approx(1.0)
    assert abs(response[1]) > 0.99
    assert abs(response[2]) < 0.01


def test_causal_filter_returns_group_delay_and_preserves_stream_shape():
    config = _config(num_taps=33)
    signal = np.zeros((2, 128), dtype=np.complex128)
    signal[0, 0] = 1.0
    signal[1, 0] = 2.0j

    result = apply_receiver_filter(signal, config)

    assert result.filtered_signal.shape == signal.shape
    assert result.final_state.shape == (2, config.num_taps - 1)
    assert result.filtered_signal[0, : config.num_taps] == pytest.approx(
        result.filter_taps
    )
    assert result.filtered_signal[1, : config.num_taps] == pytest.approx(
        2.0j * result.filter_taps
    )
    assert result.group_delay_samples == 16
    assert result.group_delay_s == pytest.approx(16.0 / SAMPLE_RATE_HZ)
    assert result.transient_length_samples == 32


def test_chunked_filtering_matches_one_continuous_call():
    generator = np.random.default_rng(52_285)
    signal = (
        generator.standard_normal((2, 4_096))
        + 1j * generator.standard_normal((2, 4_096))
    )
    config = _config()
    split_index = 1_731

    complete = apply_receiver_filter(signal, config)
    first = apply_receiver_filter(signal[:, :split_index], config)
    second = apply_receiver_filter(
        signal[:, split_index:],
        config,
        initial_state=first.final_state,
    )
    joined = np.concatenate(
        [first.filtered_signal, second.filtered_signal],
        axis=1,
    )

    assert joined == pytest.approx(complete.filtered_signal, abs=1e-13)
    assert second.final_state == pytest.approx(complete.final_state, abs=1e-13)


def test_complex_white_noise_power_reduction_matches_fir_noise_bandwidth():
    generator = np.random.default_rng(1234)
    signal = (
        generator.standard_normal((1, 200_000))
        + 1j * generator.standard_normal((1, 200_000))
    ) / np.sqrt(2.0)
    config = _config()

    result = apply_receiver_filter(signal, config)
    settled = result.filtered_signal[:, result.transient_length_samples :]
    measured_power_ratio = float(
        np.mean(np.abs(settled) ** 2) / np.mean(np.abs(signal) ** 2)
    )
    expected_power_ratio = float(np.sum(result.filter_taps**2))

    assert measured_power_ratio == pytest.approx(expected_power_ratio, rel=0.02)
    assert result.equivalent_noise_bandwidth_hz == pytest.approx(
        SAMPLE_RATE_HZ * expected_power_ratio
    )


def test_prefilter_ktfs_noise_becomes_kt_times_equivalent_bandwidth():
    temperature_k = 290.0
    state = ideal_downlink_state_si(0.0, carrier_frequency_hz=10.0e9)
    channel = apply_siso_downlink_channel(
        np.zeros((1, 200_000), dtype=np.complex128),
        state,
        SISOChannelConfig(
            carrier_frequency_hz=10.0e9,
            sample_rate_hz=SAMPLE_RATE_HZ,
            transmit_power_w=0.0,
            noise_bandwidth_hz=SAMPLE_RATE_HZ,
            system_noise_temperature_k=temperature_k,
            random_seed=99,
        ),
    )

    result = apply_receiver_filter(channel.received_signal, _config())
    settled = result.filtered_signal[:, result.transient_length_samples :]
    expected_noise_power_w = (
        BOLTZMANN_J_K
        * temperature_k
        * result.equivalent_noise_bandwidth_hz
    )

    assert np.mean(np.abs(settled) ** 2) == pytest.approx(
        expected_noise_power_w,
        rel=0.02,
    )


def test_channel_compensation_and_receiver_filter_pipeline_is_compatible():
    state = ideal_downlink_state_si(-100.0, carrier_frequency_hz=10.0e9)
    transmitted = np.ones((1, 4_096), dtype=np.complex128)
    channel = apply_siso_downlink_channel(
        transmitted,
        state,
        SISOChannelConfig(
            carrier_frequency_hz=10.0e9,
            sample_rate_hz=SAMPLE_RATE_HZ,
            transmit_power_w=4.0,
            add_awgn=False,
        ),
    )
    compensated = compensate_siso_channel_doppler(channel)

    result = apply_receiver_filter(compensated.compensated_signal, _config())
    settled = result.filtered_signal[:, result.transient_length_samples :]

    assert settled == pytest.approx(
        2.0 * channel.path_amplitude_gain * transmitted[:, : settled.shape[1]],
        abs=1e-18,
    )


@pytest.mark.parametrize(
    "overrides, error, message",
    [
        ({"sample_rate_hz": 0.0}, ValueError, "sample_rate_hz"),
        ({"passband_edge_hz": 0.0}, ValueError, "passband_edge_hz"),
        (
            {"passband_edge_hz": 200.0e3, "stopband_edge_hz": 100.0e3},
            ValueError,
            "passband_edge_hz",
        ),
        ({"stopband_edge_hz": 500.0e3}, ValueError, "Nyquist"),
        ({"num_taps": 32}, ValueError, "num_taps"),
        ({"num_taps": 2}, ValueError, "num_taps"),
        ({"num_taps": 32.0}, TypeError, "num_taps"),
        ({"window": "not-a-window"}, ValueError, "window"),
    ],
)
def test_filter_config_rejects_invalid_values(overrides, error, message):
    with pytest.raises(error, match=message):
        _config(**overrides)


@pytest.mark.parametrize(
    "signal",
    [
        np.ones(16, dtype=np.complex128),
        np.ones((0, 16), dtype=np.complex128),
        np.ones((1, 0), dtype=np.complex128),
    ],
)
def test_filter_rejects_invalid_signal_shapes(signal):
    with pytest.raises(ValueError, match="shape"):
        apply_receiver_filter(signal, _config())


def test_filter_rejects_wrong_initial_state_shape():
    with pytest.raises(ValueError, match="initial_state"):
        apply_receiver_filter(
            np.ones((2, 64), dtype=np.complex128),
            _config(num_taps=17),
            initial_state=np.zeros((1, 16), dtype=np.complex128),
        )
