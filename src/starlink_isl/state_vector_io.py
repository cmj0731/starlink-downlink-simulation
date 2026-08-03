"""CSV contract for externally supplied satellite position/velocity states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.interpolate import CubicHermiteSpline

from starlink_isl.actual_downlink import (
    dynamics_from_ecef_states,
    geometry_from_ecef_states,
)
from starlink_isl.ideal_orbit import KinematicState
from starlink_isl.sgp4_orbit import (
    GroundStation,
    ground_station_ecef_state,
    teme_to_ecef,
)
from starlink_isl.si_interface import DownlinkStateSI, downlink_state_si

STATE_VECTOR_CSV_SCHEMA_VERSION = 1
STATE_VECTOR_REQUIRED_COLUMNS = (
    "schema_version",
    "utc",
    "coordinate_frame",
    "satellite_x_m",
    "satellite_y_m",
    "satellite_z_m",
    "satellite_vx_m_s",
    "satellite_vy_m_s",
    "satellite_vz_m_s",
)
SUPPORTED_STATE_FRAMES = {"TEME", "ECEF"}


@dataclass(frozen=True, slots=True)
class ExternalSatelliteState:
    """Time-ordered external states normalized to ECEF kilometres and km/s."""

    datetimes_utc: tuple[datetime, ...]
    state_ecef: KinematicState
    source_coordinate_frame: str
    object_name: str | None = None
    norad_catalog_id: int | None = None

    @property
    def sample_count(self) -> int:
        return len(self.datetimes_utc)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("state-vector UTC values must be ISO-8601 strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("state-vector UTC values must include a timezone")
    return parsed.astimezone(timezone.utc)


def _constant_optional_text(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame:
        return None
    values = frame[column].dropna().astype(str).unique()
    if values.size > 1:
        raise ValueError(f"{column} must be constant in a state-vector CSV")
    return None if values.size == 0 else str(values[0])


def save_satellite_state_csv(
    path: str | Path,
    datetimes: Sequence[datetime],
    state: KinematicState,
    *,
    coordinate_frame: str,
    object_name: str | None = None,
    norad_catalog_id: int | None = None,
) -> Path:
    """Write an external-state CSV in SI units without changing its frame."""

    epochs = tuple(datetimes)
    if not epochs:
        raise ValueError("at least one satellite state is required")
    frame_name = coordinate_frame.upper()
    if frame_name not in SUPPORTED_STATE_FRAMES:
        raise ValueError("coordinate_frame must be TEME or ECEF")
    if state.position_km.shape != (len(epochs), 3) or (
        state.velocity_km_s.shape != (len(epochs), 3)
    ):
        raise ValueError("state position and velocity must have shape (time, 3)")
    utc_values = []
    for value in epochs:
        if value.tzinfo is None:
            raise ValueError("all state datetimes must be timezone-aware")
        utc_values.append(
            value.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    position_m = 1_000.0 * np.asarray(state.position_km, dtype=np.float64)
    velocity_m_s = 1_000.0 * np.asarray(
        state.velocity_km_s, dtype=np.float64
    )
    frame = pd.DataFrame(
        {
            "schema_version": STATE_VECTOR_CSV_SCHEMA_VERSION,
            "utc": utc_values,
            "coordinate_frame": frame_name,
            "satellite_x_m": position_m[:, 0],
            "satellite_y_m": position_m[:, 1],
            "satellite_z_m": position_m[:, 2],
            "satellite_vx_m_s": velocity_m_s[:, 0],
            "satellite_vy_m_s": velocity_m_s[:, 1],
            "satellite_vz_m_s": velocity_m_s[:, 2],
        }
    )
    if object_name is not None:
        frame["object_name"] = object_name
    if norad_catalog_id is not None:
        frame["norad_catalog_id"] = int(norad_catalog_id)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, float_format="%.17g")
    return output_path


def load_satellite_state_csv(path: str | Path) -> ExternalSatelliteState:
    """Load TEME/ECEF SI vectors and normalize them to ECEF states."""

    source_path = Path(path)
    frame = pd.read_csv(
        source_path,
        dtype={"utc": str},
        float_precision="round_trip",
    )
    missing = [
        column for column in STATE_VECTOR_REQUIRED_COLUMNS if column not in frame
    ]
    if missing:
        raise ValueError(
            "state-vector CSV is missing required columns: "
            + ", ".join(missing)
        )
    if len(frame) < 2:
        raise ValueError("state-vector CSV must contain at least two samples")
    if set(frame["schema_version"].tolist()) != {
        STATE_VECTOR_CSV_SCHEMA_VERSION
    }:
        raise ValueError("unsupported state-vector CSV schema_version")
    frames = frame["coordinate_frame"].astype(str).str.upper().unique()
    if frames.size != 1 or frames[0] not in SUPPORTED_STATE_FRAMES:
        raise ValueError(
            "coordinate_frame must be one constant value: TEME or ECEF"
        )
    source_frame = str(frames[0])
    datetimes = tuple(_parse_utc(value) for value in frame["utc"])
    timestamps = np.asarray([value.timestamp() for value in datetimes])
    if np.any(np.diff(timestamps) <= 0.0):
        raise ValueError("state-vector UTC samples must be strictly increasing")

    position_columns = [
        "satellite_x_m",
        "satellite_y_m",
        "satellite_z_m",
    ]
    velocity_columns = [
        "satellite_vx_m_s",
        "satellite_vy_m_s",
        "satellite_vz_m_s",
    ]
    try:
        position_m = frame[position_columns].to_numpy(dtype=np.float64)
        velocity_m_s = frame[velocity_columns].to_numpy(dtype=np.float64)
    except ValueError as exc:
        raise ValueError("state-vector position and velocity must be numeric") from exc
    if not np.all(np.isfinite(position_m)) or not np.all(
        np.isfinite(velocity_m_s)
    ):
        raise ValueError("state-vector position and velocity must be finite")
    source_state = KinematicState(position_m / 1_000.0, velocity_m_s / 1_000.0)
    state_ecef = (
        source_state
        if source_frame == "ECEF"
        else teme_to_ecef(source_state, datetimes)
    )
    norad_text = _constant_optional_text(frame, "norad_catalog_id")
    norad_id = None if norad_text is None else int(float(norad_text))
    return ExternalSatelliteState(
        datetimes_utc=datetimes,
        state_ecef=state_ecef,
        source_coordinate_frame=source_frame,
        object_name=_constant_optional_text(frame, "object_name"),
        norad_catalog_id=norad_id,
    )


def external_state_downlink_si(
    external: ExternalSatelliteState,
    reference_utc: datetime,
    carrier_frequency_hz: float,
    station: GroundStation = GroundStation(),
    *,
    minimum_elevation_deg: float = 0.0,
) -> DownlinkStateSI:
    """Convert external ECEF states into the existing SI channel interface."""

    if reference_utc.tzinfo is None:
        raise ValueError("reference_utc must be timezone-aware")
    reference = reference_utc.astimezone(timezone.utc)
    time_s = np.asarray(
        [
            (epoch - reference).total_seconds()
            for epoch in external.datetimes_utc
        ],
        dtype=np.float64,
    )
    if not time_s[0] <= 0.0 <= time_s[-1]:
        raise ValueError("external state samples must bracket reference_utc")
    ground = ground_station_ecef_state(station, external.sample_count)
    geometry = geometry_from_ecef_states(
        external.state_ecef,
        ground,
        station,
        minimum_elevation_deg=minimum_elevation_deg,
    )

    satellite_position_spline = CubicHermiteSpline(
        time_s,
        external.state_ecef.position_km,
        external.state_ecef.velocity_km_s,
        axis=0,
        extrapolate=False,
    )
    reference_position_km = np.asarray(
        satellite_position_spline(0.0), dtype=np.float64
    )
    reference_ground_km = ground_station_ecef_state(station, 1).position_km[0]
    phase_reference_range_km = float(
        np.linalg.norm(reference_position_km - reference_ground_km)
    )
    dynamics = dynamics_from_ecef_states(
        geometry,
        external.state_ecef,
        ground,
        carrier_frequency_hz,
        phase_reference_range_km=phase_reference_range_km,
    )
    return downlink_state_si(
        time_s,
        external.state_ecef,
        ground,
        geometry,
        dynamics,
        coordinate_frame="ECEF",
    )
