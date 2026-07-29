"""Starlink inter-satellite link analysis tools."""

from starlink_isl.actual_downlink import (
    ActualPass,
    find_visibility_passes,
    geometry_from_ecef_states,
)
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
from starlink_isl.link_budget import (
    BOLTZMANN_J_K,
    REFERENCE_NOISE_TEMPERATURE_K,
    LinkBudgetConfig,
    LinkBudgetResult,
    equivalent_receiver_noise_temperature_k,
    free_space_path_loss_db,
    link_budget,
    system_noise_temperature_k,
    thermal_noise_power_dbw,
)
from starlink_isl.sgp4_orbit import (
    GroundStation,
    SGP4PropagationError,
    geodetic_to_ecef,
    propagate_ecef,
    propagate_teme,
    satrec_from_omm,
)

__version__ = "0.1.0"

__all__ = [
    "ActualPass",
    "DownlinkDynamics",
    "DownlinkGeometry",
    "IdealOrbitConfig",
    "KinematicState",
    "LinkBudgetConfig",
    "LinkBudgetResult",
    "GroundStation",
    "SGP4PropagationError",
    "BOLTZMANN_J_K",
    "REFERENCE_NOISE_TEMPERATURE_K",
    "SPEED_OF_LIGHT_KM_S",
    "VisibilityWindow",
    "downlink_dynamics",
    "downlink_geometry",
    "equivalent_receiver_noise_temperature_k",
    "free_space_path_loss_db",
    "find_visibility_passes",
    "geodetic_to_ecef",
    "geometry_from_ecef_states",
    "ground_station_state",
    "link_budget",
    "propagate_ecef",
    "propagate_teme",
    "satellite_state",
    "satrec_from_omm",
    "system_noise_temperature_k",
    "thermal_noise_power_dbw",
    "visibility_window",
]
