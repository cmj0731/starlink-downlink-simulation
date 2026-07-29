"""Free-space downlink budget with receiver thermal noise."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from starlink_isl.downlink_dynamics import SPEED_OF_LIGHT_KM_S
from starlink_isl.downlink_geometry import downlink_geometry
from starlink_isl.ideal_orbit import IdealOrbitConfig

BOLTZMANN_J_K = 1.380_649e-23
REFERENCE_NOISE_TEMPERATURE_K = 290.0
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


def _positive_finite(value: float, name: str) -> None:
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class LinkBudgetConfig:
    """Radio parameters for a one-way free-space link budget."""

    carrier_frequency_hz: float
    bandwidth_hz: float
    transmit_power_dbw: float
    transmit_antenna_gain_dbi: float = 0.0
    receive_antenna_gain_dbi: float = 0.0
    system_noise_temperature_k: float = REFERENCE_NOISE_TEMPERATURE_K
    other_losses_db: float = 0.0

    def __post_init__(self) -> None:
        _positive_finite(self.carrier_frequency_hz, "carrier_frequency_hz")
        _positive_finite(self.bandwidth_hz, "bandwidth_hz")
        _positive_finite(
            self.system_noise_temperature_k,
            "system_noise_temperature_k",
        )
        for name in (
            "transmit_power_dbw",
            "transmit_antenna_gain_dbi",
            "receive_antenna_gain_dbi",
            "other_losses_db",
        ):
            if not np.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.other_losses_db < 0.0:
            raise ValueError("other_losses_db must be non-negative")


@dataclass(frozen=True, slots=True)
class LinkBudgetResult:
    """Time-varying received power and thermal-noise metrics."""

    free_space_path_loss_db: FloatArray
    received_power_dbw: FloatArray
    thermal_noise_power_dbw: float
    carrier_to_noise_density_db_hz: FloatArray
    snr_db: FloatArray
    visible: BoolArray


def equivalent_receiver_noise_temperature_k(
    noise_figure_db: float,
    *,
    reference_temperature_k: float = REFERENCE_NOISE_TEMPERATURE_K,
) -> float:
    """Convert receiver noise figure to equivalent input noise temperature."""
    if not np.isfinite(noise_figure_db) or noise_figure_db < 0.0:
        raise ValueError("noise_figure_db must be finite and non-negative")
    _positive_finite(reference_temperature_k, "reference_temperature_k")
    noise_factor = 10.0 ** (noise_figure_db / 10.0)
    return reference_temperature_k * (noise_factor - 1.0)


def system_noise_temperature_k(
    antenna_noise_temperature_k: float,
    noise_figure_db: float,
    *,
    reference_temperature_k: float = REFERENCE_NOISE_TEMPERATURE_K,
) -> float:
    """Combine antenna noise and receiver equivalent noise temperature."""
    if (
        not np.isfinite(antenna_noise_temperature_k)
        or antenna_noise_temperature_k < 0.0
    ):
        raise ValueError(
            "antenna_noise_temperature_k must be finite and non-negative"
        )
    receiver_temperature = equivalent_receiver_noise_temperature_k(
        noise_figure_db,
        reference_temperature_k=reference_temperature_k,
    )
    return antenna_noise_temperature_k + receiver_temperature


def thermal_noise_power_dbw(
    bandwidth_hz: float,
    system_temperature_k: float,
) -> float:
    """Return available thermal-noise power ``k*T*B`` in dBW."""
    _positive_finite(bandwidth_hz, "bandwidth_hz")
    _positive_finite(system_temperature_k, "system_temperature_k")
    return float(
        10.0
        * np.log10(BOLTZMANN_J_K * system_temperature_k * bandwidth_hz)
    )


def free_space_path_loss_db(
    slant_range_km: ArrayLike,
    carrier_frequency_hz: float,
) -> FloatArray:
    """Return free-space path loss for range in km and frequency in Hz."""
    _positive_finite(carrier_frequency_hz, "carrier_frequency_hz")
    distance = np.asarray(slant_range_km, dtype=np.float64)
    if not np.all(np.isfinite(distance)) or np.any(distance <= 0.0):
        raise ValueError("slant_range_km must contain finite positive values")
    return 20.0 * np.log10(
        4.0
        * np.pi
        * distance
        * carrier_frequency_hz
        / SPEED_OF_LIGHT_KM_S
    )


def link_budget(
    times_s: ArrayLike,
    radio: LinkBudgetConfig,
    orbit: IdealOrbitConfig = IdealOrbitConfig(),
    *,
    minimum_elevation_deg: float = 0.0,
) -> LinkBudgetResult:
    """Calculate free-space received power and thermal-noise link metrics.

    Values are retained outside the visibility window for numerical inspection;
    callers should use the returned ``visible`` mask for a physically usable
    downlink.
    """
    geometry = downlink_geometry(
        times_s,
        orbit,
        minimum_elevation_deg=minimum_elevation_deg,
    )
    path_loss = free_space_path_loss_db(
        geometry.slant_range_km,
        radio.carrier_frequency_hz,
    )
    received_power = (
        radio.transmit_power_dbw
        + radio.transmit_antenna_gain_dbi
        + radio.receive_antenna_gain_dbi
        - path_loss
        - radio.other_losses_db
    )
    noise_power = thermal_noise_power_dbw(
        radio.bandwidth_hz,
        radio.system_noise_temperature_k,
    )
    noise_density_dbw_hz = 10.0 * np.log10(
        BOLTZMANN_J_K * radio.system_noise_temperature_k
    )
    carrier_to_noise_density = received_power - noise_density_dbw_hz
    snr = received_power - noise_power

    return LinkBudgetResult(
        free_space_path_loss_db=path_loss,
        received_power_dbw=received_power,
        thermal_noise_power_dbw=noise_power,
        carrier_to_noise_density_db_hz=carrier_to_noise_density,
        snr_db=snr,
        visible=geometry.visible,
    )

