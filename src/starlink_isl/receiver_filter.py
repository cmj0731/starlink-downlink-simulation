"""Waveform-independent complex-baseband receiver filtering.

The filter operates on one or more signal streams without inspecting OFDM
symbols, pilots, cyclic prefixes, or modulation. A real, linear-phase FIR
low-pass response is applied independently along the final sample axis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.signal import firwin, get_window, lfilter

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]


def _positive_finite(value: float, name: str) -> float:
    converted = float(value)
    if not np.isfinite(converted) or converted <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return converted


@dataclass(frozen=True, slots=True)
class ReceiverFilterConfig:
    """Design settings for a real linear-phase FIR baseband low-pass filter.

    Frequency edges are positive one-sided baseband magnitudes. A signal with
    full occupied bandwidth ``B`` therefore normally needs
    ``passband_edge_hz >= B / 2``. The FIR cutoff is placed halfway between the
    passband and stopband edges.
    """

    sample_rate_hz: float
    passband_edge_hz: float
    stopband_edge_hz: float
    num_taps: int = 129
    window: str = "hamming"

    def __post_init__(self) -> None:
        sample_rate_hz = _positive_finite(
            self.sample_rate_hz,
            "sample_rate_hz",
        )
        passband_edge_hz = _positive_finite(
            self.passband_edge_hz,
            "passband_edge_hz",
        )
        stopband_edge_hz = _positive_finite(
            self.stopband_edge_hz,
            "stopband_edge_hz",
        )
        if not passband_edge_hz < stopband_edge_hz:
            raise ValueError(
                "passband_edge_hz must be smaller than stopband_edge_hz"
            )
        if stopband_edge_hz >= 0.5 * sample_rate_hz:
            raise ValueError("stopband_edge_hz must be below the Nyquist frequency")
        if (
            not isinstance(self.num_taps, (int, np.integer))
            or isinstance(self.num_taps, (bool, np.bool_))
        ):
            raise TypeError("num_taps must be an integer")
        if int(self.num_taps) < 3 or int(self.num_taps) % 2 == 0:
            raise ValueError("num_taps must be an odd integer of at least 3")
        if not isinstance(self.window, str) or not self.window:
            raise TypeError("window must be a non-empty SciPy window name")
        try:
            get_window(self.window, int(self.num_taps), fftbins=False)
        except ValueError as error:
            raise ValueError(f"unsupported window: {self.window}") from error

    @property
    def cutoff_hz(self) -> float:
        """FIR half-amplitude cutoff placed at the transition midpoint."""

        return 0.5 * (self.passband_edge_hz + self.stopband_edge_hz)

    @property
    def group_delay_samples(self) -> int:
        """Integer group delay of the odd-length linear-phase FIR."""

        return (int(self.num_taps) - 1) // 2


@dataclass(frozen=True, slots=True)
class ReceiverFilterResult:
    """Filtered streams and synchronization-relevant FIR metadata.

    ``filtered_signal`` has the same shape as the input. The operation is
    causal: it does not automatically remove group delay or append the missing
    convolution tail. ``final_state`` can be supplied as the next call's
    ``initial_state`` to process a stream in chunks without resetting the FIR.
    """

    filtered_signal: ComplexArray
    filter_taps: FloatArray
    final_state: ComplexArray
    sample_rate_hz: float
    passband_edge_hz: float
    stopband_edge_hz: float
    cutoff_hz: float
    group_delay_samples: int
    group_delay_s: float
    transient_length_samples: int
    equivalent_noise_bandwidth_hz: float
    input_average_power: FloatArray
    output_average_power: FloatArray


def _signal_streams(signal: ArrayLike) -> ComplexArray:
    samples = np.asarray(signal, dtype=np.complex128)
    if (
        samples.ndim != 2
        or samples.shape[0] == 0
        or samples.shape[1] == 0
    ):
        raise ValueError(
            "received_signal must have shape (stream_count, sample_count)"
        )
    if not np.all(np.isfinite(samples.real)) or not np.all(
        np.isfinite(samples.imag)
    ):
        raise ValueError("received_signal must contain only finite samples")
    return samples


def design_receiver_filter(config: ReceiverFilterConfig) -> FloatArray:
    """Return unity-DC-gain FIR taps for the configured transition band."""

    taps = firwin(
        int(config.num_taps),
        config.cutoff_hz,
        window=config.window,
        pass_zero="lowpass",
        scale=True,
        fs=config.sample_rate_hz,
    )
    return np.asarray(taps, dtype=np.float64)


def _initial_filter_state(
    initial_state: ArrayLike | None,
    stream_count: int,
    state_length: int,
) -> ComplexArray:
    expected_shape = (stream_count, state_length)
    if initial_state is None:
        return np.zeros(expected_shape, dtype=np.complex128)
    state = np.asarray(initial_state, dtype=np.complex128)
    if state.shape != expected_shape:
        raise ValueError(f"initial_state must have shape {expected_shape}")
    if not np.all(np.isfinite(state.real)) or not np.all(np.isfinite(state.imag)):
        raise ValueError("initial_state must contain only finite values")
    return state


def apply_receiver_filter(
    received_signal: ArrayLike,
    config: ReceiverFilterConfig,
    *,
    initial_state: ArrayLike | None = None,
) -> ReceiverFilterResult:
    """Apply the FIR independently to each complex-baseband signal stream.

    Filtering a complete multi-block channel result in one call preserves FIR
    memory across channel boundaries. For external chunked processing, pass
    each result's ``final_state`` into the following call.
    """

    samples = _signal_streams(received_signal)
    taps = design_receiver_filter(config)
    state = _initial_filter_state(
        initial_state,
        samples.shape[0],
        taps.size - 1,
    )
    filtered, final_state = lfilter(
        taps,
        [1.0],
        samples,
        axis=-1,
        zi=state,
    )
    dc_gain = float(np.sum(taps))
    equivalent_noise_bandwidth_hz = float(
        config.sample_rate_hz * np.sum(taps**2) / dc_gain**2
    )
    return ReceiverFilterResult(
        filtered_signal=np.asarray(filtered, dtype=np.complex128),
        filter_taps=taps,
        final_state=np.asarray(final_state, dtype=np.complex128),
        sample_rate_hz=config.sample_rate_hz,
        passband_edge_hz=config.passband_edge_hz,
        stopband_edge_hz=config.stopband_edge_hz,
        cutoff_hz=config.cutoff_hz,
        group_delay_samples=config.group_delay_samples,
        group_delay_s=config.group_delay_samples / config.sample_rate_hz,
        transient_length_samples=taps.size - 1,
        equivalent_noise_bandwidth_hz=equivalent_noise_bandwidth_hz,
        input_average_power=np.mean(np.abs(samples) ** 2, axis=1),
        output_average_power=np.mean(np.abs(filtered) ** 2, axis=1),
    )
