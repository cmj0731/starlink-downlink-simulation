"""Starlink inter-satellite link analysis tools."""

from starlink_isl.downlink_dynamics import (
    SPEED_OF_LIGHT_KM_S,
    DownlinkDynamics,
    downlink_dynamics,
)
from starlink_isl.downlink_geometry import (
    DownlinkGeometry,
    VisibilityWindow,
    downlink_geometry,
    visibility_window,
)
from starlink_isl.ideal_orbit import (
    IdealOrbitConfig,
    KinematicState,
    ground_station_state,
    satellite_state,
)

__version__ = "0.1.0"

__all__ = [
    "DownlinkDynamics",
    "DownlinkGeometry",
    "IdealOrbitConfig",
    "KinematicState",
    "SPEED_OF_LIGHT_KM_S",
    "VisibilityWindow",
    "downlink_dynamics",
    "downlink_geometry",
    "ground_station_state",
    "satellite_state",
    "visibility_window",
]
