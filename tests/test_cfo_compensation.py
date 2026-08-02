import numpy as np
import pytest

from starlink_isl import (
    SISOChannelConfig,
    apply_siso_downlink_channel,
    apply_siso_downlink_sequence,
    compensate_cfo,
    compensate_siso_channel_doppler,
    compensate_siso_channel_sequence_doppler,
    ideal_downlink_state_si,
)


CARRIER_FREQUENCY_HZ = 10.0e9
SAMPLE_RATE_HZ = 1.0e6


@pytest.mark.parametrize("cfo_hz", [-184_000.0, 184_000.0])
def test_generic_compensator_perfectly_removes_signed_cfo_and_phase(cfo_hz):
    generator = np.random.default_rng(42)
    transmitted = (
        generator.standard_normal((1, 4_096))
        + 1j * generator.standard_normal((1, 4_096))
    )
    initial_phase = 0.37
    sample_index = np.arange(transmitted.shape[1])
    received = transmitted * np.exp(
        1j
        * (
            initial_phase
            + 2.0 * np.pi * cfo_hz * sample_index / SAMPLE_RATE_HZ
        )
    )[None, :]

    result = compensate_cfo(
        received,
        SAMPLE_RATE_HZ,
        cfo_hz,
        estimated_initial_phase_rad=initial_phase,
        true_cfo_hz=cfo_hz,
        true_initial_phase_rad=initial_phase,
    )

    assert result.compensated_signal == pytest.approx(transmitted, abs=1e-10)
    assert result.residual_cfo_hz == pytest.approx(0.0)
    assert result.residual_initial_phase_rad == pytest.approx(0.0)
    assert result.output_average_power_w == pytest.approx(
        result.input_average_power_w
    )


def test_perfect_channel_compensation_keeps_only_path_gain():
    state = ideal_downlink_state_si(-100.0, CARRIER_FREQUENCY_HZ)
    transmitted = np.exp(
        1j * np.linspace(0.0, 1.0, 2_048, dtype=np.float64)
    )[None, :]
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        transmit_power_w=4.0,
        add_awgn=False,
    )
    channel = apply_siso_downlink_channel(transmitted, state, config)

    compensation = compensate_siso_channel_doppler(channel)
    expected = 2.0 * channel.path_amplitude_gain * transmitted

    assert compensation.compensated_signal == pytest.approx(
        expected,
        abs=1e-18,
    )
    assert compensation.residual_cfo_hz == pytest.approx(0.0)
    assert compensation.residual_initial_phase_rad == pytest.approx(0.0)


def test_imperfect_frequency_estimate_leaves_reported_residual_cfo():
    state = ideal_downlink_state_si(-100.0, CARRIER_FREQUENCY_HZ)
    transmitted = np.ones((1, 4_096), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        add_awgn=False,
    )
    channel = apply_siso_downlink_channel(transmitted, state, config)
    residual_cfo_hz = 300.0
    estimate = channel.doppler_shift_hz - residual_cfo_hz

    compensation = compensate_siso_channel_doppler(
        channel,
        estimated_doppler_hz=estimate,
    )
    phase = np.unwrap(np.angle(compensation.compensated_signal[0]))
    measured_step = float(np.mean(np.diff(phase)))

    assert compensation.residual_cfo_hz == pytest.approx(residual_cfo_hz)
    assert measured_step == pytest.approx(
        2.0 * np.pi * residual_cfo_hz / SAMPLE_RATE_HZ,
        abs=5e-12,
    )


def test_imperfect_phase_estimate_leaves_constant_phase_error():
    state = ideal_downlink_state_si(0.0, CARRIER_FREQUENCY_HZ)
    transmitted = np.ones((1, 64), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        add_awgn=False,
    )
    channel = apply_siso_downlink_channel(transmitted, state, config)
    residual_phase_rad = 0.2

    compensation = compensate_siso_channel_doppler(
        channel,
        estimated_initial_phase_rad=(
            channel.doppler_phase_rad[0] - residual_phase_rad
        ),
    )
    normalized = (
        compensation.compensated_signal
        / (channel.path_amplitude_gain * transmitted)
    )

    assert compensation.residual_initial_phase_rad == pytest.approx(
        residual_phase_rad
    )
    assert np.angle(normalized) == pytest.approx(residual_phase_rad)


def test_phase_only_compensation_preserves_received_power_with_awgn():
    state = ideal_downlink_state_si(-100.0, CARRIER_FREQUENCY_HZ)
    transmitted = np.ones((1, 8_192), dtype=np.complex128)
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        transmit_power_w=1.0,
        noise_bandwidth_hz=1.0e6,
        add_awgn=True,
    )
    channel = apply_siso_downlink_channel(transmitted, state, config)

    compensation = compensate_siso_channel_doppler(channel)

    assert compensation.output_average_power_w == pytest.approx(
        compensation.input_average_power_w,
        rel=1e-14,
    )


@pytest.mark.parametrize(
    "received_signal",
    [
        np.ones(16, dtype=np.complex128),
        np.ones((2, 16), dtype=np.complex128),
        np.ones((1, 0), dtype=np.complex128),
    ],
)
def test_compensator_rejects_non_siso_shapes(received_signal):
    with pytest.raises(ValueError, match="shape"):
        compensate_cfo(received_signal, SAMPLE_RATE_HZ, 0.0)


@pytest.mark.parametrize(
    "sample_rate_hz, cfo_hz, phase_rad, message",
    [
        (0.0, 0.0, 0.0, "sample_rate_hz"),
        (np.nan, 0.0, 0.0, "sample_rate_hz"),
        (SAMPLE_RATE_HZ, np.nan, 0.0, "estimated_cfo_hz"),
        (SAMPLE_RATE_HZ, 0.0, np.nan, "estimated_initial_phase_rad"),
    ],
)
def test_compensator_rejects_invalid_parameters(
    sample_rate_hz,
    cfo_hz,
    phase_rad,
    message,
):
    with pytest.raises(ValueError, match=message):
        compensate_cfo(
            np.ones((1, 16), dtype=np.complex128),
            sample_rate_hz,
            cfo_hz,
            estimated_initial_phase_rad=phase_rad,
        )


def _three_block_channel(add_awgn=False):
    state_times_s = np.array([-0.002, 0.0, 0.002])
    state = ideal_downlink_state_si(state_times_s, CARRIER_FREQUENCY_HZ)
    transmitted = np.exp(
        1j * np.linspace(0.0, 1.0, 6_000, dtype=np.float64)
    )[None, :]
    config = SISOChannelConfig(
        carrier_frequency_hz=CARRIER_FREQUENCY_HZ,
        sample_rate_hz=SAMPLE_RATE_HZ,
        transmit_power_w=4.0,
        add_awgn=add_awgn,
        random_seed=987,
    )
    channel = apply_siso_downlink_sequence(
        transmitted,
        state,
        config,
        block_boundaries=[0, 2_000, 4_000, 6_000],
        state_indices=[0, 1, 2],
    )
    return transmitted, channel


def test_perfect_sequence_compensation_removes_phase_in_every_block():
    transmitted, channel = _three_block_channel()

    compensation = compensate_siso_channel_sequence_doppler(channel)
    expected = np.empty_like(transmitted)
    for block_index in range(channel.block_count):
        start = channel.block_boundaries[block_index]
        stop = channel.block_boundaries[block_index + 1]
        expected[:, start:stop] = (
            2.0 * channel.path_amplitude_gain[block_index] * transmitted[:, start:stop]
        )

    assert compensation.compensated_signal == pytest.approx(
        expected,
        abs=1e-18,
    )
    assert compensation.residual_cfo_hz == pytest.approx(np.zeros(3))
    assert compensation.residual_block_initial_phase_rad == pytest.approx(
        np.zeros(3)
    )


def test_sequence_compensation_reports_per_block_residual_slopes():
    transmitted, channel = _three_block_channel()
    residual_hz = np.array([100.0, -200.0, 300.0])
    estimates = channel.doppler_shift_hz - residual_hz

    compensation = compensate_siso_channel_sequence_doppler(
        channel,
        estimated_doppler_hz=estimates,
    )
    normalized = compensation.compensated_signal.copy()
    for block_index in range(channel.block_count):
        start = channel.block_boundaries[block_index]
        stop = channel.block_boundaries[block_index + 1]
        normalized[:, start:stop] /= (
            2.0 * channel.path_amplitude_gain[block_index] * transmitted[:, start:stop]
        )
        measured_step = np.angle(
            normalized[0, start + 1 : stop]
            * np.conj(normalized[0, start : stop - 1])
        )
        assert measured_step == pytest.approx(
            2.0 * np.pi * residual_hz[block_index] / SAMPLE_RATE_HZ,
            abs=1e-11,
        )

    assert compensation.residual_cfo_hz == pytest.approx(residual_hz)
    expected_boundary_residual_rad = np.array(
        [
            0.0,
            2.0 * np.pi * residual_hz[0] * 2_000 / SAMPLE_RATE_HZ,
            2.0
            * np.pi
            * (residual_hz[0] + residual_hz[1])
            * 2_000
            / SAMPLE_RATE_HZ,
        ]
    )
    assert compensation.residual_block_initial_phase_rad == pytest.approx(
        expected_boundary_residual_rad,
        abs=1e-11,
    )
    assert compensation.output_average_power_w == pytest.approx(
        compensation.input_average_power_w,
        rel=1e-14,
    )


def test_sequence_compensation_rejects_wrong_estimate_count():
    _, channel = _three_block_channel()

    with pytest.raises(ValueError, match="shape"):
        compensate_siso_channel_sequence_doppler(
            channel,
            estimated_doppler_hz=[1.0, 2.0],
        )
