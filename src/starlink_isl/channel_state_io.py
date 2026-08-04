"""Compact full-pass LOS channel-state CSV exchange."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S
from starlink_isl.sgp4_orbit import GroundStation
from starlink_isl.si_interface import DownlinkStateSI

FloatArray = NDArray[np.float64]
SPEED_OF_LIGHT_M_S = 1_000.0 * SPEED_OF_LIGHT_KM_S
CHANNEL_STATE_CSV_SCHEMA_VERSION = 1
CHANNEL_STATE_REPRESENTATION = "raw_los_state_without_frequency_grid"
CHANNEL_STATE_REQUIRED_COLUMNS = (
    "schema_version",
    "state_representation",
    "reference_utc",
    "utc",
    "time_s",
    "coordinate_frame",
    "carrier_frequency_hz",
    "other_losses_db",
    "station_latitude_deg",
    "station_longitude_deg",
    "station_altitude_m",
    "satellite_x_m",
    "satellite_y_m",
    "satellite_z_m",
    "satellite_vx_m_s",
    "satellite_vy_m_s",
    "satellite_vz_m_s",
    "ue_x_m",
    "ue_y_m",
    "ue_z_m",
    "ue_vx_m_s",
    "ue_vy_m_s",
    "ue_vz_m_s",
    "los_satellite_to_ue_x",
    "los_satellite_to_ue_y",
    "los_satellite_to_ue_z",
    "slant_range_m",
    "surface_distance_m",
    "azimuth_deg",
    "propagation_delay_s",
    "radial_velocity_m_s",
    "doppler_shift_hz",
    "doppler_phase_rad",
    "free_space_path_loss_db_at_carrier",
    "path_amplitude_gain_at_carrier",
    "elevation_deg",
    "visible",
    "event",
)


@dataclass(frozen=True, slots=True)
class ChannelStateCSVData:
    """Validated compact state used to build frame-sized ``H[m,k]`` grids."""

    state: DownlinkStateSI
    reference_utc: datetime
    datetimes_utc: tuple[datetime, ...]
    carrier_frequency_hz: float
    other_losses_db: float
    station: GroundStation
    free_space_path_loss_db_at_carrier: FloatArray
    path_amplitude_gain_at_carrier: FloatArray
    event_labels: tuple[str, ...]

    @property
    def sample_count(self) -> int:
        return self.state.sample_count


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "UTC value").isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO-8601 string")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), name)


def _constant_text(frame: pd.DataFrame, column: str) -> str:
    values = frame[column].dropna().astype(str).str.strip().unique()
    if values.size != 1 or not values[0]:
        raise ValueError(f"{column} must be one non-empty constant value")
    return str(values[0])


def _constant_float(frame: pd.DataFrame, column: str) -> float:
    values = frame[column].to_numpy(dtype=np.float64)
    if not np.all(np.isfinite(values)) or not np.all(values == values[0]):
        raise ValueError(f"{column} must be one finite constant value")
    return float(values[0])


def _state_arrays(state: DownlinkStateSI) -> tuple[np.ndarray, ...]:
    arrays = (
        np.asarray(state.time_s, dtype=np.float64),
        np.asarray(state.satellite_position_m, dtype=np.float64),
        np.asarray(state.satellite_velocity_m_s, dtype=np.float64),
        np.asarray(state.ue_position_m, dtype=np.float64),
        np.asarray(state.ue_velocity_m_s, dtype=np.float64),
        np.asarray(state.los_satellite_to_ue_unit, dtype=np.float64),
        np.asarray(state.slant_range_m, dtype=np.float64),
        np.asarray(state.surface_distance_m, dtype=np.float64),
        np.asarray(state.azimuth_rad, dtype=np.float64),
        np.asarray(state.elevation_rad, dtype=np.float64),
        np.asarray(state.radial_velocity_m_s, dtype=np.float64),
        np.asarray(state.propagation_delay_s, dtype=np.float64),
        np.asarray(state.doppler_shift_hz, dtype=np.float64),
        np.asarray(state.doppler_phase_rad, dtype=np.float64),
        np.asarray(state.visible, dtype=np.bool_),
    )
    if not all(np.all(np.isfinite(values)) for values in arrays[:-1]):
        raise ValueError("channel state must contain only finite numeric values")
    sample_count = state.sample_count
    scalar_shape = (sample_count,)
    vector_shape = (sample_count, 3)
    if sample_count < 2:
        raise ValueError("channel state must contain at least two samples")
    if arrays[0].shape != scalar_shape:
        raise ValueError("channel-state time_s must be one-dimensional")
    if any(values.shape != vector_shape for values in arrays[1:6]):
        raise ValueError("channel-state vectors must have shape (sample_count, 3)")
    if any(values.shape != scalar_shape for values in arrays[6:]):
        raise ValueError("channel-state scalar fields must match time_s")
    if np.any(np.diff(arrays[0]) <= 0.0):
        raise ValueError("channel-state time_s must be strictly increasing")
    return arrays


def save_channel_state_csv(
    state: DownlinkStateSI,
    path: str | Path,
    *,
    reference_utc: datetime,
    carrier_frequency_hz: float,
    station: GroundStation,
    other_losses_db: float = 0.0,
    event_labels: Sequence[str] | None = None,
) -> Path:
    """Save one compact raw LOS state row per full-pass observation time."""

    reference = _utc(reference_utc, "reference_utc")
    carrier_hz = float(carrier_frequency_hz)
    losses_db = float(other_losses_db)
    if not np.isfinite(carrier_hz) or carrier_hz <= 0.0:
        raise ValueError("carrier_frequency_hz must be finite and positive")
    if not np.isfinite(losses_db) or losses_db < 0.0:
        raise ValueError("other_losses_db must be finite and non-negative")
    if state.coordinate_frame != "ECEF":
        raise ValueError("full-pass channel state must use the ECEF frame")
    (
        time_s,
        satellite_position_m,
        satellite_velocity_m_s,
        ue_position_m,
        ue_velocity_m_s,
        los_unit,
        slant_range_m,
        surface_distance_m,
        azimuth_rad,
        elevation_rad,
        radial_velocity_m_s,
        propagation_delay_s,
        doppler_shift_hz,
        doppler_phase_rad,
        visible,
    ) = _state_arrays(state)
    labels = (
        tuple("" for _ in range(state.sample_count))
        if event_labels is None
        else tuple(str(value) for value in event_labels)
    )
    if len(labels) != state.sample_count:
        raise ValueError("event_labels must match the channel-state sample count")
    utc_values = [
        _iso(reference + timedelta(seconds=float(offset))) for offset in time_s
    ]
    free_space_path_loss_db = 20.0 * np.log10(
        4.0 * np.pi * slant_range_m * carrier_hz / SPEED_OF_LIGHT_M_S
    )
    path_amplitude_gain = 10.0 ** (
        -(free_space_path_loss_db + losses_db) / 20.0
    )
    frame = pd.DataFrame(
        {
            "schema_version": CHANNEL_STATE_CSV_SCHEMA_VERSION,
            "state_representation": CHANNEL_STATE_REPRESENTATION,
            "reference_utc": _iso(reference),
            "utc": utc_values,
            "time_s": time_s,
            "coordinate_frame": state.coordinate_frame,
            "carrier_frequency_hz": carrier_hz,
            "other_losses_db": losses_db,
            "station_latitude_deg": station.latitude_deg,
            "station_longitude_deg": station.longitude_deg,
            "station_altitude_m": station.altitude_m,
            "satellite_x_m": satellite_position_m[:, 0],
            "satellite_y_m": satellite_position_m[:, 1],
            "satellite_z_m": satellite_position_m[:, 2],
            "satellite_vx_m_s": satellite_velocity_m_s[:, 0],
            "satellite_vy_m_s": satellite_velocity_m_s[:, 1],
            "satellite_vz_m_s": satellite_velocity_m_s[:, 2],
            "ue_x_m": ue_position_m[:, 0],
            "ue_y_m": ue_position_m[:, 1],
            "ue_z_m": ue_position_m[:, 2],
            "ue_vx_m_s": ue_velocity_m_s[:, 0],
            "ue_vy_m_s": ue_velocity_m_s[:, 1],
            "ue_vz_m_s": ue_velocity_m_s[:, 2],
            "los_satellite_to_ue_x": los_unit[:, 0],
            "los_satellite_to_ue_y": los_unit[:, 1],
            "los_satellite_to_ue_z": los_unit[:, 2],
            "slant_range_m": slant_range_m,
            "surface_distance_m": surface_distance_m,
            "azimuth_deg": np.rad2deg(azimuth_rad),
            "propagation_delay_s": propagation_delay_s,
            "radial_velocity_m_s": radial_velocity_m_s,
            "doppler_shift_hz": doppler_shift_hz,
            "doppler_phase_rad": doppler_phase_rad,
            "free_space_path_loss_db_at_carrier": free_space_path_loss_db,
            "path_amplitude_gain_at_carrier": path_amplitude_gain,
            "elevation_deg": np.rad2deg(elevation_rad),
            "visible": visible,
            "event": labels,
        }
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, float_format="%.17g")
    return output_path


def load_channel_state_csv(path: str | Path) -> ChannelStateCSVData:
    """Load and validate a compact full-pass channel-state CSV."""

    frame = pd.read_csv(
        Path(path),
        dtype={"utc": str, "reference_utc": str, "event": str},
        float_precision="round_trip",
        keep_default_na=False,
    )
    missing = [
        column for column in CHANNEL_STATE_REQUIRED_COLUMNS if column not in frame
    ]
    if missing:
        raise ValueError(
            "channel-state CSV is missing required columns: "
            + ", ".join(missing)
        )
    if len(frame) < 2:
        raise ValueError("channel-state CSV must contain at least two samples")
    if set(frame["schema_version"].tolist()) != {
        CHANNEL_STATE_CSV_SCHEMA_VERSION
    }:
        raise ValueError("unsupported channel-state CSV schema_version")
    representation = _constant_text(frame, "state_representation")
    if representation != CHANNEL_STATE_REPRESENTATION:
        raise ValueError("unsupported channel-state representation")
    coordinate_frame = _constant_text(frame, "coordinate_frame")
    if coordinate_frame != "ECEF":
        raise ValueError("channel-state coordinate_frame must be ECEF")
    reference = _parse_utc(
        _constant_text(frame, "reference_utc"), "reference_utc"
    )
    datetimes = tuple(_parse_utc(value, "utc") for value in frame["utc"])
    time_s = frame["time_s"].to_numpy(dtype=np.float64)
    if not np.all(np.isfinite(time_s)) or np.any(np.diff(time_s) <= 0.0):
        raise ValueError("channel-state time_s must be finite and increasing")
    expected_time_s = np.asarray(
        [(value - reference).total_seconds() for value in datetimes]
    )
    if not np.allclose(time_s, expected_time_s, rtol=0.0, atol=1.0e-6):
        raise ValueError("channel-state UTC and time_s axes are inconsistent")

    def vectors(prefix: str) -> FloatArray:
        suffixes = ("x_m", "y_m", "z_m")
        if prefix.endswith("_v"):
            suffixes = ("x_m_s", "y_m_s", "z_m_s")
        return frame[[f"{prefix}{suffix}" for suffix in suffixes]].to_numpy(
            dtype=np.float64
        )

    satellite_position_m = vectors("satellite_")
    satellite_velocity_m_s = vectors("satellite_v")
    ue_position_m = vectors("ue_")
    ue_velocity_m_s = vectors("ue_v")
    los_unit = frame[
        [
            "los_satellite_to_ue_x",
            "los_satellite_to_ue_y",
            "los_satellite_to_ue_z",
        ]
    ].to_numpy(dtype=np.float64)

    def scalars(column: str) -> FloatArray:
        return frame[column].to_numpy(dtype=np.float64)

    slant_range_m = scalars("slant_range_m")
    surface_distance_m = scalars("surface_distance_m")
    azimuth_rad = np.deg2rad(scalars("azimuth_deg"))
    propagation_delay_s = scalars("propagation_delay_s")
    radial_velocity_m_s = scalars("radial_velocity_m_s")
    doppler_shift_hz = scalars("doppler_shift_hz")
    doppler_phase_rad = scalars("doppler_phase_rad")
    fspl_db = scalars("free_space_path_loss_db_at_carrier")
    path_gain = scalars("path_amplitude_gain_at_carrier")
    elevation_rad = np.deg2rad(scalars("elevation_deg"))
    carrier_hz = _constant_float(frame, "carrier_frequency_hz")
    losses_db = _constant_float(frame, "other_losses_db")
    if carrier_hz <= 0.0:
        raise ValueError("channel-state carrier_frequency_hz must be positive")
    if losses_db < 0.0:
        raise ValueError("channel-state other_losses_db must be non-negative")
    numeric_arrays = (
        satellite_position_m,
        satellite_velocity_m_s,
        ue_position_m,
        ue_velocity_m_s,
        los_unit,
        slant_range_m,
        surface_distance_m,
        azimuth_rad,
        propagation_delay_s,
        radial_velocity_m_s,
        doppler_shift_hz,
        doppler_phase_rad,
        fspl_db,
        path_gain,
        elevation_rad,
    )
    if not all(np.all(np.isfinite(values)) for values in numeric_arrays):
        raise ValueError("channel-state CSV contains non-finite numeric values")
    if np.any(slant_range_m <= 0.0):
        raise ValueError("channel-state slant_range_m must be positive")
    if not np.allclose(
        propagation_delay_s,
        slant_range_m / SPEED_OF_LIGHT_M_S,
        rtol=1.0e-12,
        atol=0.0,
    ):
        raise ValueError("channel-state delay is inconsistent with slant range")
    expected_doppler_hz = -radial_velocity_m_s / SPEED_OF_LIGHT_M_S * carrier_hz
    if not np.allclose(
        doppler_shift_hz, expected_doppler_hz, rtol=1.0e-12, atol=1.0e-9
    ):
        raise ValueError("channel-state Doppler is inconsistent with velocity")
    los_norm = np.linalg.norm(los_unit, axis=1)
    if not np.allclose(los_norm, 1.0, rtol=0.0, atol=1.0e-12):
        raise ValueError("channel-state LOS vectors must have unit length")
    satellite_to_ue_m = ue_position_m - satellite_position_m
    expected_slant_range_m = np.linalg.norm(satellite_to_ue_m, axis=1)
    expected_los_unit = satellite_to_ue_m / expected_slant_range_m[:, None]
    if not np.allclose(
        slant_range_m,
        expected_slant_range_m,
        rtol=1.0e-12,
        atol=1.0e-6,
    ) or not np.allclose(
        los_unit,
        expected_los_unit,
        rtol=0.0,
        atol=1.0e-12,
    ):
        raise ValueError("channel-state LOS geometry is internally inconsistent")
    expected_fspl_db = 20.0 * np.log10(
        4.0 * np.pi * slant_range_m * carrier_hz / SPEED_OF_LIGHT_M_S
    )
    if not np.allclose(fspl_db, expected_fspl_db, rtol=0.0, atol=1.0e-10):
        raise ValueError("channel-state FSPL is inconsistent with range")
    expected_path_gain = 10.0 ** (-(fspl_db + losses_db) / 20.0)
    if not np.allclose(path_gain, expected_path_gain, rtol=1.0e-12, atol=0.0):
        raise ValueError("channel-state path gain is inconsistent with FSPL")
    visible_text = frame["visible"].astype(str).str.lower()
    if not visible_text.isin(("true", "false")).all():
        raise ValueError("channel-state visible values must be true or false")
    visible = visible_text.eq("true").to_numpy(dtype=np.bool_)
    state = DownlinkStateSI(
        coordinate_frame="ECEF",
        time_s=time_s,
        satellite_position_m=satellite_position_m,
        satellite_velocity_m_s=satellite_velocity_m_s,
        ue_position_m=ue_position_m,
        ue_velocity_m_s=ue_velocity_m_s,
        los_satellite_to_ue_unit=los_unit,
        slant_range_m=slant_range_m,
        surface_distance_m=surface_distance_m,
        azimuth_rad=azimuth_rad,
        elevation_rad=elevation_rad,
        radial_velocity_m_s=radial_velocity_m_s,
        propagation_delay_s=propagation_delay_s,
        doppler_shift_hz=doppler_shift_hz,
        doppler_phase_rad=doppler_phase_rad,
        visible=visible,
    )
    return ChannelStateCSVData(
        state=state,
        reference_utc=reference,
        datetimes_utc=datetimes,
        carrier_frequency_hz=carrier_hz,
        other_losses_db=losses_db,
        station=GroundStation(
            latitude_deg=_constant_float(frame, "station_latitude_deg"),
            longitude_deg=_constant_float(frame, "station_longitude_deg"),
            altitude_m=_constant_float(frame, "station_altitude_m"),
        ),
        free_space_path_loss_db_at_carrier=fspl_db,
        path_amplitude_gain_at_carrier=path_gain,
        event_labels=tuple(frame["event"].astype(str)),
    )
