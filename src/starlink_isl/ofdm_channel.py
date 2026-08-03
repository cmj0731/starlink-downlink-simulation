"""Frequency-domain SISO downlink channel on an explicit OFDM grid."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.channel_grid import OFDMChannelGridAxes
from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S
from starlink_isl.si_interface import DownlinkStateSI

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]
SPEED_OF_LIGHT_M_S = 1_000.0 * SPEED_OF_LIGHT_KM_S


def _read_only(values: NDArray) -> NDArray:
    result = np.array(values, copy=True)
    result.setflags(write=False)
    return result


def _state_values(
    values: ArrayLike,
    expected_shape: tuple[int, ...],
    name: str,
) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.shape != expected_shape:
        raise ValueError(f"state.{name} must have shape {expected_shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"state.{name} must contain only finite values")
    return array


@dataclass(frozen=True, slots=True)
class SISOChannelGrid:
    """Ground-truth complex channel with shape ``(symbol, subcarrier)``.

    ``channel_response`` includes free-space attenuation, optional scalar
    losses, carrier-frequency Doppler phase, and the absolute-delay phase slope
    across baseband subcarriers. It samples the channel once per OFDM symbol;
    uncompensated within-symbol Doppler/ICI must still be modelled in the time
    domain or by a separate ICI operator.
    """

    axes: OFDMChannelGridAxes
    channel_response: ComplexArray
    free_space_path_loss_db: FloatArray
    path_amplitude_gain: FloatArray
    carrier_doppler_phase_rad: FloatArray
    delay_phase_rad: FloatArray
    slant_range_m: FloatArray
    propagation_delay_s: FloatArray
    radial_velocity_m_s: FloatArray
    doppler_shift_hz: FloatArray
    other_losses_db: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.axes.shape


@dataclass(frozen=True, slots=True)
class SynchronizedSISOChannelGrid:
    """Raw channel after predicted bulk delay and Doppler phase removal.

    Only deterministic phase terms are removed. Free-space attenuation and
    optional scalar losses remain in ``channel_response``. Residual fields are
    truth minus prediction, so perfect prediction produces a positive-real
    response equal to the raw path-amplitude gain.
    """

    raw_grid: SISOChannelGrid
    channel_response: ComplexArray
    predicted_propagation_delay_s: FloatArray
    predicted_carrier_doppler_phase_rad: FloatArray
    residual_propagation_delay_s: FloatArray
    residual_carrier_doppler_phase_rad: FloatArray
    residual_delay_phase_rad: FloatArray
    residual_total_phase_rad: FloatArray
    prediction_label: str

    @property
    def axes(self) -> OFDMChannelGridAxes:
        return self.raw_grid.axes

    @property
    def shape(self) -> tuple[int, int]:
        return self.raw_grid.shape


def evaluate_siso_ofdm_channel_grid(
    state: DownlinkStateSI,
    axes: OFDMChannelGridAxes,
    *,
    other_losses_db: float = 0.0,
) -> SISOChannelGrid:
    """Evaluate the LOS SISO channel at every ``(m, k)`` coordinate.

    The state must already be sampled at ``axes.time.time_s``. A typical caller
    first evaluates 1 s SGP4 anchors and then calls
    ``resample_downlink_state_si(source, axes.time.time_s, carrier_hz)``.

    The deterministic channel is

    ``H[m,k] = a[m,k] exp(j*phi_D[m]) exp(-j*2*pi*f_k*tau[m])``.

    The carrier phase uses the reference range embedded in
    ``state.doppler_phase_rad``. Consequently an arbitrary constant carrier
    phase is omitted, while all time variation is retained.
    """

    loss_db = float(other_losses_db)
    if not np.isfinite(loss_db) or loss_db < 0.0:
        raise ValueError("other_losses_db must be finite and non-negative")

    symbol_count, subcarrier_count = axes.shape
    if state.sample_count != symbol_count:
        raise ValueError("state sample count must equal the grid symbol count")
    state_time_s = _state_values(
        state.time_s,
        (symbol_count,),
        "time_s",
    )
    if not np.allclose(
        state_time_s,
        axes.time.time_s,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise ValueError("state.time_s must match the grid evaluation times")

    slant_range_m = _state_values(
        state.slant_range_m,
        (symbol_count,),
        "slant_range_m",
    )
    if np.any(slant_range_m <= 0.0):
        raise ValueError("state.slant_range_m must be positive")
    propagation_delay_s = _state_values(
        state.propagation_delay_s,
        (symbol_count,),
        "propagation_delay_s",
    )
    expected_delay_s = slant_range_m / SPEED_OF_LIGHT_M_S
    if not np.allclose(
        propagation_delay_s,
        expected_delay_s,
        rtol=1.0e-12,
        atol=1.0e-15,
    ):
        raise ValueError("state delay is inconsistent with slant range")
    radial_velocity_m_s = _state_values(
        state.radial_velocity_m_s,
        (symbol_count,),
        "radial_velocity_m_s",
    )
    doppler_shift_hz = _state_values(
        state.doppler_shift_hz,
        (symbol_count,),
        "doppler_shift_hz",
    )
    carrier_hz = axes.frequency.carrier_frequency_hz
    expected_doppler_hz = (
        -radial_velocity_m_s / SPEED_OF_LIGHT_M_S * carrier_hz
    )
    if not np.allclose(
        doppler_shift_hz,
        expected_doppler_hz,
        rtol=1.0e-10,
        atol=1.0e-6,
    ):
        raise ValueError(
            "state Doppler is inconsistent with the grid carrier frequency"
        )
    carrier_phase_rad = _state_values(
        state.doppler_phase_rad,
        (symbol_count,),
        "doppler_phase_rad",
    )

    rf_frequency_hz = np.asarray(
        axes.frequency.rf_frequency_hz,
        dtype=np.float64,
    )
    baseband_frequency_hz = np.asarray(
        axes.frequency.baseband_frequency_hz,
        dtype=np.float64,
    )
    if rf_frequency_hz.shape != (subcarrier_count,) or (
        baseband_frequency_hz.shape != (subcarrier_count,)
    ):
        raise ValueError("grid frequency arrays do not match the grid shape")

    free_space_loss_db = 20.0 * np.log10(
        4.0
        * np.pi
        * slant_range_m[:, None]
        * rf_frequency_hz[None, :]
        / SPEED_OF_LIGHT_M_S
    )
    amplitude_gain = 10.0 ** (
        -(free_space_loss_db + loss_db) / 20.0
    )
    delay_phase_rad = (
        -2.0
        * np.pi
        * propagation_delay_s[:, None]
        * baseband_frequency_hz[None, :]
    )
    total_phase_rad = carrier_phase_rad[:, None] + delay_phase_rad
    channel_response = amplitude_gain * np.exp(1j * total_phase_rad)

    return SISOChannelGrid(
        axes=axes,
        channel_response=_read_only(
            np.asarray(channel_response, dtype=np.complex128)
        ),
        free_space_path_loss_db=_read_only(free_space_loss_db),
        path_amplitude_gain=_read_only(amplitude_gain),
        carrier_doppler_phase_rad=_read_only(carrier_phase_rad),
        delay_phase_rad=_read_only(delay_phase_rad),
        slant_range_m=_read_only(slant_range_m),
        propagation_delay_s=_read_only(propagation_delay_s),
        radial_velocity_m_s=_read_only(radial_velocity_m_s),
        doppler_shift_hz=_read_only(doppler_shift_hz),
        other_losses_db=loss_db,
    )


def synchronize_siso_ofdm_channel_grid(
    grid: SISOChannelGrid,
    predicted_propagation_delay_s: ArrayLike,
    predicted_carrier_doppler_phase_rad: ArrayLike,
    *,
    prediction_label: str = "external_prediction",
) -> SynchronizedSISOChannelGrid:
    """Remove predicted bulk delay and carrier-Doppler phase from ``grid``.

    The synchronized channel is evaluated from residual phase quantities for
    numerical stability instead of multiplying two very large, nearly
    cancelling absolute-delay phasors:

    ``H_sync = a exp(j*(phi_D-phi_D_pred))``
    ``             exp(-j*2*pi*f_k*(tau-tau_pred))``.

    This is a channel-side ideal phase-synchronization model, not a receiver
    estimator and not an OFDM transmitter/receiver integration.
    """

    if not isinstance(prediction_label, str) or not prediction_label.strip():
        raise ValueError("prediction_label must be a non-empty string")
    symbol_count, subcarrier_count = grid.shape
    expected_time_shape = (symbol_count,)
    predicted_delay_s = _state_values(
        predicted_propagation_delay_s,
        expected_time_shape,
        "predicted_propagation_delay_s",
    )
    if np.any(predicted_delay_s <= 0.0):
        raise ValueError("predicted propagation delay must be positive")
    predicted_carrier_phase_rad = _state_values(
        predicted_carrier_doppler_phase_rad,
        expected_time_shape,
        "predicted_carrier_doppler_phase_rad",
    )

    residual_delay_s = grid.propagation_delay_s - predicted_delay_s
    residual_carrier_phase_rad = (
        grid.carrier_doppler_phase_rad - predicted_carrier_phase_rad
    )
    baseband_frequency_hz = np.asarray(
        grid.axes.frequency.baseband_frequency_hz,
        dtype=np.float64,
    )
    if baseband_frequency_hz.shape != (subcarrier_count,):
        raise ValueError("grid frequency axis is inconsistent with its shape")
    residual_delay_phase_rad = (
        -2.0
        * np.pi
        * residual_delay_s[:, None]
        * baseband_frequency_hz[None, :]
    )
    residual_total_phase_rad = (
        residual_carrier_phase_rad[:, None] + residual_delay_phase_rad
    )
    synchronized_response = grid.path_amplitude_gain * np.exp(
        1j * residual_total_phase_rad
    )
    return SynchronizedSISOChannelGrid(
        raw_grid=grid,
        channel_response=_read_only(
            np.asarray(synchronized_response, dtype=np.complex128)
        ),
        predicted_propagation_delay_s=_read_only(predicted_delay_s),
        predicted_carrier_doppler_phase_rad=_read_only(
            predicted_carrier_phase_rad
        ),
        residual_propagation_delay_s=_read_only(residual_delay_s),
        residual_carrier_doppler_phase_rad=_read_only(
            residual_carrier_phase_rad
        ),
        residual_delay_phase_rad=_read_only(residual_delay_phase_rad),
        residual_total_phase_rad=_read_only(residual_total_phase_rad),
        prediction_label=prediction_label.strip(),
    )


def save_siso_channel_grid_npz(
    grid: SISOChannelGrid,
    path: str | Path,
) -> Path:
    """Save the complex grid, its coordinates, and physical metadata."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        channel_response=grid.channel_response,
        time_s=grid.axes.time.time_s,
        symbol_indices=grid.axes.time.symbol_indices,
        symbol_start_time_s=grid.axes.time.symbol_start_time_s,
        symbol_time_reference=np.asarray(
            grid.axes.time.symbol_time_reference
        ),
        signed_subcarrier_indices=(
            grid.axes.frequency.signed_subcarrier_indices
        ),
        fft_bin_indices=grid.axes.frequency.fft_bin_indices,
        fftshift_bin_indices=grid.axes.frequency.fftshift_bin_indices,
        baseband_frequency_hz=grid.axes.frequency.baseband_frequency_hz,
        rf_frequency_hz=grid.axes.frequency.rf_frequency_hz,
        carrier_frequency_hz=np.asarray(
            grid.axes.frequency.carrier_frequency_hz
        ),
        free_space_path_loss_db=grid.free_space_path_loss_db,
        path_amplitude_gain=grid.path_amplitude_gain,
        carrier_doppler_phase_rad=grid.carrier_doppler_phase_rad,
        delay_phase_rad=grid.delay_phase_rad,
        slant_range_m=grid.slant_range_m,
        propagation_delay_s=grid.propagation_delay_s,
        radial_velocity_m_s=grid.radial_velocity_m_s,
        doppler_shift_hz=grid.doppler_shift_hz,
        other_losses_db=np.asarray(grid.other_losses_db),
        model=np.asarray(
            "LOS SISO FSPL + carrier Doppler phase + absolute delay phase"
        ),
    )
    return output_path


def save_synchronized_siso_channel_grid_npz(
    synchronized: SynchronizedSISOChannelGrid,
    path: str | Path,
) -> Path:
    """Save synchronized and raw responses with phase-error metadata."""

    grid = synchronized.raw_grid
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        channel_response=synchronized.channel_response,
        raw_channel_response=grid.channel_response,
        time_s=grid.axes.time.time_s,
        symbol_indices=grid.axes.time.symbol_indices,
        signed_subcarrier_indices=(
            grid.axes.frequency.signed_subcarrier_indices
        ),
        fft_bin_indices=grid.axes.frequency.fft_bin_indices,
        fftshift_bin_indices=grid.axes.frequency.fftshift_bin_indices,
        baseband_frequency_hz=grid.axes.frequency.baseband_frequency_hz,
        rf_frequency_hz=grid.axes.frequency.rf_frequency_hz,
        path_amplitude_gain=grid.path_amplitude_gain,
        predicted_propagation_delay_s=(
            synchronized.predicted_propagation_delay_s
        ),
        predicted_carrier_doppler_phase_rad=(
            synchronized.predicted_carrier_doppler_phase_rad
        ),
        residual_propagation_delay_s=(
            synchronized.residual_propagation_delay_s
        ),
        residual_carrier_doppler_phase_rad=(
            synchronized.residual_carrier_doppler_phase_rad
        ),
        residual_delay_phase_rad=synchronized.residual_delay_phase_rad,
        residual_total_phase_rad=synchronized.residual_total_phase_rad,
        prediction_label=np.asarray(synchronized.prediction_label),
        model=np.asarray(
            "SISO raw channel with predicted delay and Doppler phase removed"
        ),
    )
    return output_path
