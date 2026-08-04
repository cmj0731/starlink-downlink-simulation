"""Portable CSV exchange for the complex OFDM channel grid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from starlink_isl.ofdm_channel import SISOChannelGrid

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
ComplexArray = NDArray[np.complex128]

CHANNEL_CSV_SCHEMA_VERSION = 2
RAW_CHANNEL_VARIANT = "raw"
NO_CHANNEL_COMPENSATION = "none"
SUPPORTED_CHANNEL_VARIANTS = frozenset(
    {
        RAW_CHANNEL_VARIANT,
        "block_start_compensated",
        "perfectly_compensated",
    }
)
CHANNEL_CSV_REQUIRED_COLUMNS = (
    "schema_version",
    "channel_variant",
    "delay_compensation",
    "doppler_compensation",
    "symbol_index",
    "symbol_start_time_s",
    "channel_evaluation_time_s",
    "channel_evaluation_utc",
    "grid_column",
    "signed_subcarrier_index",
    "fft_bin_index",
    "fftshift_bin_index",
    "baseband_frequency_hz",
    "rf_frequency_hz",
    "h_real",
    "h_imag",
    "h_magnitude",
    "h_phase_rad",
    "free_space_path_loss_db",
    "path_amplitude_gain",
    "carrier_doppler_phase_rad",
    "delay_phase_rad",
    "slant_range_m",
    "propagation_delay_s",
    "radial_velocity_m_s",
    "doppler_shift_hz",
    "other_losses_db",
)


@dataclass(frozen=True, slots=True)
class ChannelGridCSVData:
    """Validated arrays reconstructed from the long-format exchange CSV."""

    channel_response: ComplexArray
    channel_variant: str
    delay_compensation: str
    doppler_compensation: str
    symbol_indices: IntArray
    symbol_start_time_s: FloatArray
    time_s: FloatArray
    channel_evaluation_utc: tuple[str, ...]
    grid_columns: IntArray
    signed_subcarrier_indices: IntArray
    fft_bin_indices: IntArray
    fftshift_bin_indices: IntArray
    baseband_frequency_hz: FloatArray
    rf_frequency_hz: FloatArray
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
        """Return ``(time, frequency)`` for ``channel_response``."""

        return self.channel_response.shape


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("reference_utc must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def save_channel_grid_csv(
    grid: SISOChannelGrid,
    path: str | Path,
    *,
    reference_utc: datetime,
) -> Path:
    """Save ``H[m,k]`` as one real/imaginary row per time-frequency cell.

    NPZ remains the canonical lossless format. This long CSV is the portable
    module boundary for tools that cannot consume NumPy archives directly.
    Row order is time-major: all frequency bins of symbol ``m`` are adjacent.
    """

    if reference_utc.tzinfo is None:
        raise ValueError("reference_utc must be timezone-aware")
    reference = reference_utc.astimezone(timezone.utc)
    time_count, frequency_count = grid.shape
    repeat_time = lambda values: np.repeat(values, frequency_count)
    tile_frequency = lambda values: np.tile(values, time_count)
    evaluation_utc = np.asarray(
        [
            _iso(reference + timedelta(seconds=float(offset)))
            for offset in grid.axes.time.time_s
        ]
    )
    response = np.asarray(grid.channel_response)
    frame = pd.DataFrame(
        {
            "schema_version": CHANNEL_CSV_SCHEMA_VERSION,
            "channel_variant": RAW_CHANNEL_VARIANT,
            "delay_compensation": NO_CHANNEL_COMPENSATION,
            "doppler_compensation": NO_CHANNEL_COMPENSATION,
            "symbol_index": repeat_time(grid.axes.time.symbol_indices),
            "symbol_start_time_s": repeat_time(
                grid.axes.time.symbol_start_time_s
            ),
            "channel_evaluation_time_s": repeat_time(
                grid.axes.time.time_s
            ),
            "channel_evaluation_utc": repeat_time(evaluation_utc),
            "grid_column": tile_frequency(
                np.arange(frequency_count, dtype=np.int64)
            ),
            "signed_subcarrier_index": tile_frequency(
                grid.axes.frequency.signed_subcarrier_indices
            ),
            "fft_bin_index": tile_frequency(
                grid.axes.frequency.fft_bin_indices
            ),
            "fftshift_bin_index": tile_frequency(
                grid.axes.frequency.fftshift_bin_indices
            ),
            "baseband_frequency_hz": tile_frequency(
                grid.axes.frequency.baseband_frequency_hz
            ),
            "rf_frequency_hz": tile_frequency(
                grid.axes.frequency.rf_frequency_hz
            ),
            "h_real": response.real.reshape(-1),
            "h_imag": response.imag.reshape(-1),
            "h_magnitude": np.abs(response).reshape(-1),
            "h_phase_rad": np.angle(response).reshape(-1),
            "free_space_path_loss_db": np.asarray(
                grid.free_space_path_loss_db
            ).reshape(-1),
            "path_amplitude_gain": np.asarray(
                grid.path_amplitude_gain
            ).reshape(-1),
            "carrier_doppler_phase_rad": repeat_time(
                grid.carrier_doppler_phase_rad
            ),
            "delay_phase_rad": np.asarray(grid.delay_phase_rad).reshape(-1),
            "slant_range_m": repeat_time(grid.slant_range_m),
            "propagation_delay_s": repeat_time(grid.propagation_delay_s),
            "radial_velocity_m_s": repeat_time(grid.radial_velocity_m_s),
            "doppler_shift_hz": repeat_time(grid.doppler_shift_hz),
            "other_losses_db": grid.other_losses_db,
        }
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, float_format="%.17g")
    return output_path


def _constant_by_symbol(
    frame: pd.DataFrame,
    column: str,
    frequency_count: int,
) -> np.ndarray:
    values = frame[column].to_numpy().reshape(-1, frequency_count)
    first = values[:, 0]
    if np.issubdtype(values.dtype, np.number):
        matches = np.all(values == first[:, None])
    else:
        matches = np.all(values.astype(str) == first.astype(str)[:, None])
    if not matches:
        raise ValueError(f"{column} must be constant within each symbol")
    return first


def _constant_by_frequency(
    frame: pd.DataFrame,
    column: str,
    time_count: int,
    frequency_count: int,
) -> np.ndarray:
    values = frame[column].to_numpy().reshape(time_count, frequency_count)
    first = values[0]
    if not np.all(values == first[None, :]):
        raise ValueError(f"{column} must be constant for each grid column")
    return first


def _constant_text(frame: pd.DataFrame, column: str) -> str:
    values = frame[column].astype(str).str.strip().unique()
    if values.size != 1 or not values[0]:
        raise ValueError(f"{column} must be one non-empty constant value")
    return str(values[0])


def load_channel_grid_csv(path: str | Path) -> ChannelGridCSVData:
    """Load and validate a time-major channel exchange CSV."""

    source_path = Path(path)
    frame = pd.read_csv(source_path, float_precision="round_trip")
    missing = [
        column for column in CHANNEL_CSV_REQUIRED_COLUMNS if column not in frame
    ]
    if missing:
        raise ValueError(
            "channel CSV is missing required columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise ValueError("channel CSV must contain at least one row")
    if set(frame["schema_version"].tolist()) != {CHANNEL_CSV_SCHEMA_VERSION}:
        raise ValueError("unsupported channel CSV schema_version")
    if frame[list(CHANNEL_CSV_REQUIRED_COLUMNS)].isnull().any().any():
        raise ValueError("channel CSV contains missing required values")
    if frame.duplicated(["symbol_index", "grid_column"]).any():
        raise ValueError("channel CSV contains duplicate (symbol, grid) cells")

    channel_variant = _constant_text(frame, "channel_variant")
    if channel_variant not in SUPPORTED_CHANNEL_VARIANTS:
        raise ValueError(f"unsupported channel_variant: {channel_variant}")
    delay_compensation = _constant_text(frame, "delay_compensation")
    doppler_compensation = _constant_text(frame, "doppler_compensation")
    if channel_variant == RAW_CHANNEL_VARIANT and (
        delay_compensation != NO_CHANNEL_COMPENSATION
        or doppler_compensation != NO_CHANNEL_COMPENSATION
    ):
        raise ValueError("raw channel CSV must not declare compensation")
    if channel_variant != RAW_CHANNEL_VARIANT and (
        delay_compensation == NO_CHANNEL_COMPENSATION
        and doppler_compensation == NO_CHANNEL_COMPENSATION
    ):
        raise ValueError(
            "compensated channel CSV must declare a compensation method"
        )

    frame = frame.sort_values(
        ["symbol_index", "grid_column"], kind="stable"
    ).reset_index(drop=True)
    symbols = np.sort(frame["symbol_index"].unique())
    columns = np.sort(frame["grid_column"].unique())
    time_count = symbols.size
    frequency_count = columns.size
    if len(frame) != time_count * frequency_count:
        raise ValueError("channel CSV does not contain a complete rectangular grid")
    expected_symbols = np.repeat(symbols, frequency_count)
    expected_columns = np.tile(columns, time_count)
    if not np.array_equal(frame["symbol_index"].to_numpy(), expected_symbols):
        raise ValueError("channel CSV symbol ordering is not rectangular")
    if not np.array_equal(frame["grid_column"].to_numpy(), expected_columns):
        raise ValueError("channel CSV frequency ordering is not rectangular")

    h_real = frame["h_real"].to_numpy(dtype=np.float64).reshape(
        time_count, frequency_count
    )
    h_imag = frame["h_imag"].to_numpy(dtype=np.float64).reshape(
        time_count, frequency_count
    )
    response = np.asarray(h_real + 1j * h_imag, dtype=np.complex128)
    saved_magnitude = frame["h_magnitude"].to_numpy(dtype=np.float64).reshape(
        time_count, frequency_count
    )
    if not np.allclose(
        saved_magnitude,
        np.abs(response),
        rtol=1.0e-12,
        atol=0.0,
    ):
        raise ValueError("channel CSV magnitude is inconsistent with real/imag")
    saved_phase = frame["h_phase_rad"].to_numpy(dtype=np.float64).reshape(
        time_count, frequency_count
    )
    wrapped_phase_error = np.angle(
        np.exp(1j * (saved_phase - np.angle(response)))
    )
    if not np.allclose(wrapped_phase_error, 0.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("channel CSV phase is inconsistent with real/imag")

    scalar_losses = frame["other_losses_db"].to_numpy(dtype=np.float64)
    if not np.all(scalar_losses == scalar_losses[0]):
        raise ValueError("other_losses_db must be constant")
    return ChannelGridCSVData(
        channel_response=response,
        channel_variant=channel_variant,
        delay_compensation=delay_compensation,
        doppler_compensation=doppler_compensation,
        symbol_indices=np.asarray(symbols, dtype=np.int64),
        symbol_start_time_s=np.asarray(
            _constant_by_symbol(
                frame, "symbol_start_time_s", frequency_count
            ),
            dtype=np.float64,
        ),
        time_s=np.asarray(
            _constant_by_symbol(
                frame, "channel_evaluation_time_s", frequency_count
            ),
            dtype=np.float64,
        ),
        channel_evaluation_utc=tuple(
            str(value)
            for value in _constant_by_symbol(
                frame, "channel_evaluation_utc", frequency_count
            )
        ),
        grid_columns=np.asarray(columns, dtype=np.int64),
        signed_subcarrier_indices=np.asarray(
            _constant_by_frequency(
                frame,
                "signed_subcarrier_index",
                time_count,
                frequency_count,
            ),
            dtype=np.int64,
        ),
        fft_bin_indices=np.asarray(
            _constant_by_frequency(
                frame, "fft_bin_index", time_count, frequency_count
            ),
            dtype=np.int64,
        ),
        fftshift_bin_indices=np.asarray(
            _constant_by_frequency(
                frame, "fftshift_bin_index", time_count, frequency_count
            ),
            dtype=np.int64,
        ),
        baseband_frequency_hz=np.asarray(
            _constant_by_frequency(
                frame,
                "baseband_frequency_hz",
                time_count,
                frequency_count,
            ),
            dtype=np.float64,
        ),
        rf_frequency_hz=np.asarray(
            _constant_by_frequency(
                frame, "rf_frequency_hz", time_count, frequency_count
            ),
            dtype=np.float64,
        ),
        free_space_path_loss_db=frame[
            "free_space_path_loss_db"
        ].to_numpy(dtype=np.float64).reshape(time_count, frequency_count),
        path_amplitude_gain=frame["path_amplitude_gain"].to_numpy(
            dtype=np.float64
        ).reshape(time_count, frequency_count),
        carrier_doppler_phase_rad=np.asarray(
            _constant_by_symbol(
                frame, "carrier_doppler_phase_rad", frequency_count
            ),
            dtype=np.float64,
        ),
        delay_phase_rad=frame["delay_phase_rad"].to_numpy(
            dtype=np.float64
        ).reshape(time_count, frequency_count),
        slant_range_m=np.asarray(
            _constant_by_symbol(frame, "slant_range_m", frequency_count),
            dtype=np.float64,
        ),
        propagation_delay_s=np.asarray(
            _constant_by_symbol(
                frame, "propagation_delay_s", frequency_count
            ),
            dtype=np.float64,
        ),
        radial_velocity_m_s=np.asarray(
            _constant_by_symbol(
                frame, "radial_velocity_m_s", frequency_count
            ),
            dtype=np.float64,
        ),
        doppler_shift_hz=np.asarray(
            _constant_by_symbol(frame, "doppler_shift_hz", frequency_count),
            dtype=np.float64,
        ),
        other_losses_db=float(scalar_losses[0]),
    )
