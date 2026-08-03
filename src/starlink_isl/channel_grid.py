"""Explicit time and frequency axes for an OFDM downlink channel grid.

This module defines only the coordinates of ``H[m, k]``.  It does not create
OFDM samples or evaluate the physical channel response.  Signed subcarrier
indices use the mathematical convention ``f_k = k * delta_f``; the matching
NumPy FFT-bin indices are provided separately for waveform integration.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.research_config import OFDMNumerology

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

SYMBOL_TIME_REFERENCES = frozenset(
    {"symbol_start", "fft_window_start", "fft_window_center"}
)
SUPPORTED_CENTERED_LAYOUTS = frozenset(
    {"centered_dc_null_provisional", "centered_dc_active_provisional"}
)
MINYOUNG_FFTSHIFT_LAYOUT = "minyoung_fftshift_guard16_dc_null"


def _read_only(values: NDArray) -> NDArray:
    result = np.array(values, copy=True)
    result.setflags(write=False)
    return result


def _finite_float(value: float, name: str) -> float:
    converted = float(value)
    if not np.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, np.integer),
    ):
        raise TypeError(f"{name} must be an integer")
    converted = int(value)
    if converted <= 0:
        raise ValueError(f"{name} must be positive")
    return converted


@dataclass(frozen=True, slots=True)
class OFDMTimeAxis:
    """One channel-evaluation time for every OFDM symbol.

    ``time_s`` uses the same relative time origin as ``DownlinkStateSI.time_s``.
    The default reference is the centre of the useful FFT window, after the
    cyclic prefix, because it is a clear representative time for a channel
    that is approximately constant over one symbol.
    """

    symbol_indices: IntArray
    symbol_start_time_s: FloatArray
    time_s: FloatArray
    symbol_time_reference: str
    reference_offset_s: float
    total_symbol_duration_s: float

    @property
    def symbol_count(self) -> int:
        return int(self.symbol_indices.size)


@dataclass(frozen=True, slots=True)
class OFDMFrequencyAxis:
    """Active subcarriers in mathematical and waveform-bin conventions."""

    signed_subcarrier_indices: IntArray
    fft_bin_indices: IntArray
    fftshift_bin_indices: IntArray
    baseband_frequency_hz: FloatArray
    rf_frequency_hz: FloatArray
    carrier_frequency_hz: float
    subcarrier_spacing_hz: float
    fft_size: int

    @property
    def subcarrier_count(self) -> int:
        return int(self.signed_subcarrier_indices.size)


@dataclass(frozen=True, slots=True)
class OFDMChannelGridAxes:
    """Coordinates and shape convention for a SISO ``H[m, k]`` grid."""

    time: OFDMTimeAxis
    frequency: OFDMFrequencyAxis

    @property
    def shape(self) -> tuple[int, int]:
        """Return ``(OFDM symbol count, active subcarrier count)``."""

        return (self.time.symbol_count, self.frequency.subcarrier_count)


def centered_active_subcarrier_indices(
    fft_size: int,
    active_subcarrier_count: int,
    *,
    dc_subcarrier_null: bool,
) -> IntArray:
    """Return a frequency-sorted, centred provisional active-bin layout.

    A truly symmetric DC-null layout needs an even number of active carriers;
    a truly symmetric layout containing DC needs an odd number.  Requiring
    symmetry here prevents an unnoticed one-bin frequency bias.
    """

    size = _positive_integer(fft_size, "fft_size")
    active_count = _positive_integer(
        active_subcarrier_count,
        "active_subcarrier_count",
    )
    if size % 2 != 0:
        raise ValueError("fft_size must be even for signed FFT indexing")
    available_count = size - int(dc_subcarrier_null)
    if active_count > available_count:
        raise ValueError("active_subcarrier_count exceeds available FFT bins")

    if dc_subcarrier_null:
        if active_count % 2 != 0:
            raise ValueError(
                "a centred DC-null layout requires an even active count"
            )
        side_count = active_count // 2
        signed_indices = np.concatenate(
            (
                np.arange(-side_count, 0, dtype=np.int64),
                np.arange(1, side_count + 1, dtype=np.int64),
            )
        )
    else:
        if active_count % 2 != 1:
            raise ValueError(
                "a centred DC-active layout requires an odd active count"
            )
        side_count = active_count // 2
        signed_indices = np.arange(
            -side_count,
            side_count + 1,
            dtype=np.int64,
        )

    minimum_signed_index = -size // 2
    maximum_signed_index = size // 2 - 1
    if signed_indices[0] < minimum_signed_index or (
        signed_indices[-1] > maximum_signed_index
    ):
        raise ValueError("centred active layout exceeds signed FFT-bin range")
    return _read_only(signed_indices)


def fftshift_guard_active_subcarrier_indices(
    fft_size: int,
    *,
    left_guard_bins: int,
    right_guard_bins: int,
    dc_subcarrier_null: bool,
) -> IntArray:
    """Return signed indices for an ``fftshift`` grid with edge guards.

    ``left_guard_bins`` and ``right_guard_bins`` count array positions at the
    low- and high-frequency ends of the shifted waveform grid.  With
    ``NFFT=256``, 16 guards per side, and null DC, this yields the 223 active
    positions used by Minyoung's no-CP OFDM implementation.
    """

    size = _positive_integer(fft_size, "fft_size")
    if size % 2 != 0:
        raise ValueError("fft_size must be even for fftshift indexing")
    for value, name in (
        (left_guard_bins, "left_guard_bins"),
        (right_guard_bins, "right_guard_bins"),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value, (int, np.integer)
        ):
            raise TypeError(f"{name} must be an integer")
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
    first = int(left_guard_bins)
    stop = size - int(right_guard_bins)
    if first >= stop:
        raise ValueError("guard bins leave no active waveform positions")
    shifted_indices = np.arange(first, stop, dtype=np.int64)
    if dc_subcarrier_null:
        shifted_indices = shifted_indices[shifted_indices != size // 2]
    signed_indices = shifted_indices - size // 2
    return _read_only(signed_indices)


def build_ofdm_time_axis(
    numerology: OFDMNumerology,
    symbol_count: int,
    *,
    frame_start_time_s: float = 0.0,
    symbol_time_reference: str = "fft_window_center",
) -> OFDMTimeAxis:
    """Build the ``m`` axis used to evaluate one channel per OFDM symbol."""

    count = _positive_integer(symbol_count, "symbol_count")
    start_time_s = _finite_float(frame_start_time_s, "frame_start_time_s")
    if symbol_time_reference not in SYMBOL_TIME_REFERENCES:
        choices = ", ".join(sorted(SYMBOL_TIME_REFERENCES))
        raise ValueError(f"symbol_time_reference must be one of: {choices}")

    reference_offsets_s = {
        "symbol_start": 0.0,
        "fft_window_start": numerology.cyclic_prefix_duration_s,
        "fft_window_center": (
            numerology.cyclic_prefix_duration_s
            + 0.5 * numerology.useful_symbol_duration_s
        ),
    }
    reference_offset_s = reference_offsets_s[symbol_time_reference]
    symbol_indices = np.arange(count, dtype=np.int64)
    symbol_start_time_s = (
        start_time_s
        + symbol_indices.astype(np.float64)
        * numerology.total_symbol_duration_s
    )
    evaluation_time_s = symbol_start_time_s + reference_offset_s
    return OFDMTimeAxis(
        symbol_indices=_read_only(symbol_indices),
        symbol_start_time_s=_read_only(symbol_start_time_s),
        time_s=_read_only(evaluation_time_s),
        symbol_time_reference=symbol_time_reference,
        reference_offset_s=float(reference_offset_s),
        total_symbol_duration_s=numerology.total_symbol_duration_s,
    )


def _explicit_signed_indices(
    values: ArrayLike,
    numerology: OFDMNumerology,
) -> IntArray:
    indices = np.asarray(values)
    if indices.ndim != 1 or indices.size == 0:
        raise ValueError(
            "active_subcarrier_indices must be a non-empty one-dimensional array"
        )
    if not np.issubdtype(indices.dtype, np.integer):
        raise TypeError("active_subcarrier_indices must contain integers")
    signed_indices = np.asarray(indices, dtype=np.int64)
    if signed_indices.size != numerology.active_subcarrier_count:
        raise ValueError(
            "active_subcarrier_indices size must equal active_subcarrier_count"
        )
    if np.any(np.diff(signed_indices) <= 0):
        raise ValueError(
            "active_subcarrier_indices must be unique and strictly increasing"
        )
    minimum_signed_index = -numerology.fft_size // 2
    maximum_signed_index = numerology.fft_size // 2 - 1
    if signed_indices[0] < minimum_signed_index or (
        signed_indices[-1] > maximum_signed_index
    ):
        raise ValueError("active_subcarrier_indices exceed signed FFT-bin range")
    if numerology.dc_subcarrier_null and np.any(signed_indices == 0):
        raise ValueError("DC subcarrier must be absent when dc_subcarrier_null=True")
    return _read_only(signed_indices)


def build_ofdm_frequency_axis(
    numerology: OFDMNumerology,
    carrier_frequency_hz: float,
    *,
    active_subcarrier_indices: ArrayLike | None = None,
) -> OFDMFrequencyAxis:
    """Build the active ``k`` axis in signed-index, FFT-bin, and Hz forms.

    An explicit signed-index array always takes precedence.  When it is not
    supplied, only a named executable layout is accepted.  The team-aligned
    layout maps directly to Minyoung's shifted waveform array.
    """

    carrier_hz = _finite_float(carrier_frequency_hz, "carrier_frequency_hz")
    if carrier_hz <= 0.0:
        raise ValueError("carrier_frequency_hz must be positive")

    if active_subcarrier_indices is None:
        layout = numerology.active_subcarrier_layout
        if layout == MINYOUNG_FFTSHIFT_LAYOUT:
            if numerology.fft_size != 256:
                raise ValueError("Minyoung layout requires fft_size=256")
            if not numerology.dc_subcarrier_null:
                raise ValueError("Minyoung layout requires a null DC bin")
            signed_indices = fftshift_guard_active_subcarrier_indices(
                numerology.fft_size,
                left_guard_bins=16,
                right_guard_bins=16,
                dc_subcarrier_null=True,
            )
            if signed_indices.size != numerology.active_subcarrier_count:
                raise ValueError(
                    "Minyoung layout requires active_subcarrier_count=223"
                )
        elif layout not in SUPPORTED_CENTERED_LAYOUTS:
            raise ValueError(
                "active_subcarrier_layout is not executable; supply explicit "
                "signed indices or select a supported provisional layout"
            )
        else:
            layout_has_null_dc = layout == "centered_dc_null_provisional"
            if layout_has_null_dc != numerology.dc_subcarrier_null:
                raise ValueError(
                    "active_subcarrier_layout conflicts with dc_subcarrier_null"
                )
            signed_indices = centered_active_subcarrier_indices(
                numerology.fft_size,
                numerology.active_subcarrier_count,
                dc_subcarrier_null=numerology.dc_subcarrier_null,
            )
    else:
        signed_indices = _explicit_signed_indices(
            active_subcarrier_indices,
            numerology,
        )

    fft_bin_indices = np.mod(signed_indices, numerology.fft_size).astype(
        np.int64
    )
    fftshift_bin_indices = np.mod(
        signed_indices + numerology.fft_size // 2,
        numerology.fft_size,
    ).astype(np.int64)
    baseband_frequency_hz = (
        signed_indices.astype(np.float64) * numerology.subcarrier_spacing_hz
    )
    rf_frequency_hz = carrier_hz + baseband_frequency_hz
    if np.any(rf_frequency_hz <= 0.0):
        raise ValueError("all active RF subcarrier frequencies must be positive")
    return OFDMFrequencyAxis(
        signed_subcarrier_indices=_read_only(signed_indices),
        fft_bin_indices=_read_only(fft_bin_indices),
        fftshift_bin_indices=_read_only(fftshift_bin_indices),
        baseband_frequency_hz=_read_only(baseband_frequency_hz),
        rf_frequency_hz=_read_only(rf_frequency_hz),
        carrier_frequency_hz=carrier_hz,
        subcarrier_spacing_hz=numerology.subcarrier_spacing_hz,
        fft_size=numerology.fft_size,
    )


def build_ofdm_channel_grid_axes(
    numerology: OFDMNumerology,
    carrier_frequency_hz: float,
    symbol_count: int,
    *,
    frame_start_time_s: float = 0.0,
    symbol_time_reference: str = "fft_window_center",
    active_subcarrier_indices: ArrayLike | None = None,
) -> OFDMChannelGridAxes:
    """Build both axes for a SISO channel array shaped ``(m, k)``."""

    return OFDMChannelGridAxes(
        time=build_ofdm_time_axis(
            numerology,
            symbol_count,
            frame_start_time_s=frame_start_time_s,
            symbol_time_reference=symbol_time_reference,
        ),
        frequency=build_ofdm_frequency_axis(
            numerology,
            carrier_frequency_hz,
            active_subcarrier_indices=active_subcarrier_indices,
        ),
    )
