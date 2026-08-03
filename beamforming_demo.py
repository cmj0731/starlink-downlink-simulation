"""Ku-band OFDM transmit-beamforming and satellite-channel baseline.

Conventions
-----------
* Position and distance: metre
* Velocity and radial velocity: metre/second
* Time: simulation seconds
* Angles: radian
* LOS: unit vector from satellite to UE
* Radial velocity: positive when satellite and UE move farther apart
* State-vector shape: (sample_count, 3)
* Per-antenna waveform shape: (antenna_count, sample_count)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np


SPEED_OF_LIGHT_MPS = 299_792_458.0


@dataclass(frozen=True)
class LinkConfig:
    carrier_hz: float = 11.7e9
    fft_size: int = 256
    subcarrier_spacing_hz: float = 30e3
    active_subcarriers: int = 200
    cp_samples: int = 32
    num_ofdm_symbols: int = 8
    antenna_count: int = 8
    orbit_state_interval_s: float = 1.0
    channel_interval_s: float = 1e-3
    simulation_duration_s: float = 2.0

    @property
    def sample_rate_hz(self) -> float:
        return self.fft_size * self.subcarrier_spacing_hz

    @property
    def sample_period_s(self) -> float:
        return 1.0 / self.sample_rate_hz

    @property
    def occupied_bandwidth_hz(self) -> float:
        return self.active_subcarriers * self.subcarrier_spacing_hz

    @property
    def ofdm_symbol_duration_s(self) -> float:
        return (self.fft_size + self.cp_samples) / self.sample_rate_hz

    @property
    def wavelength_m(self) -> float:
        return SPEED_OF_LIGHT_MPS / self.carrier_hz

    def validate(self) -> None:
        if self.fft_size <= 0 or self.fft_size % 2:
            raise ValueError("fft_size must be a positive even integer")
        if self.active_subcarriers <= 0 or self.active_subcarriers >= self.fft_size:
            raise ValueError("active_subcarriers must be between 1 and fft_size - 1")
        if self.active_subcarriers % 2:
            raise ValueError("active_subcarriers must be even so DC can be excluded symmetrically")
        if self.cp_samples < 0 or self.cp_samples > self.fft_size:
            raise ValueError("cp_samples must be between 0 and fft_size")


def generate_qpsk_symbols(num_symbols: int, rng: np.random.Generator) -> np.ndarray:
    """Generate unit-average-power QPSK symbols."""
    bits = rng.integers(0, 2, size=(num_symbols, 2))
    return ((2 * bits[:, 0] - 1) + 1j * (2 * bits[:, 1] - 1)) / np.sqrt(2.0)


def signed_active_subcarrier_indices(active_count: int) -> np.ndarray:
    """Return signed FFT indices, symmetric about and excluding DC."""
    if active_count <= 0 or active_count % 2:
        raise ValueError("active_count must be a positive even number")
    half = active_count // 2
    return np.concatenate((np.arange(-half, 0), np.arange(1, half + 1)))


def generate_ofdm_waveform(
    config: LinkConfig, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create CP-OFDM waveform and return waveform, QPSK grid, signed indices."""
    signed_indices = signed_active_subcarrier_indices(config.active_subcarriers)
    qpsk_grid = generate_qpsk_symbols(
        config.num_ofdm_symbols * config.active_subcarriers, rng
    ).reshape(config.num_ofdm_symbols, config.active_subcarriers)

    frequency_grid = np.zeros((config.num_ofdm_symbols, config.fft_size), dtype=complex)
    fft_bins = np.mod(signed_indices, config.fft_size)
    frequency_grid[:, fft_bins] = qpsk_grid

    # sqrt(N) scaling makes Parseval power bookkeeping convenient.
    useful = np.fft.ifft(frequency_grid, axis=1) * np.sqrt(config.fft_size)
    with_cp = np.concatenate((useful[:, -config.cp_samples :], useful), axis=1)
    return with_cp.reshape(-1), qpsk_grid, signed_indices


def steering_vector(
    azimuth_rad: float,
    elevation_rad: float,
    num_elements: int,
    spacing_m: float,
    wavelength_m: float,
    geometry: str = "ula",
) -> np.ndarray:
    """Return the receive-manifold convention a(theta)=exp(-j k r.u)."""
    k = 2.0 * np.pi / wavelength_m
    if geometry == "ula":
        x = np.arange(num_elements) * spacing_m
        phase = k * x * np.sin(azimuth_rad) * np.cos(elevation_rad)
    elif geometry == "planar":
        side = int(np.ceil(np.sqrt(num_elements)))
        x = np.repeat(np.arange(side), side)[:num_elements] * spacing_m
        y = np.tile(np.arange(side), side)[:num_elements] * spacing_m
        phase = k * (
            x * np.sin(azimuth_rad) * np.cos(elevation_rad)
            + y * np.sin(elevation_rad)
        )
    else:
        raise ValueError("geometry must be 'ula' or 'planar'")
    return np.exp(-1j * phase)


def normalize_weights(weights: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(weights)
    return weights / norm if norm else weights


def update_beam_weights(
    target_az_rad: float,
    target_el_rad: float,
    num_elements: int,
    spacing_m: float,
    wavelength_m: float,
    geometry: str = "ula",
) -> np.ndarray:
    """Return unit-norm transmit weights for the target direction."""
    manifold = steering_vector(
        target_az_rad,
        target_el_rad,
        num_elements,
        spacing_m,
        wavelength_m,
        geometry,
    )
    return normalize_weights(np.conjugate(manifold))


def tx_beamform(baseband: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Produce shape (antenna_count, sample_count)."""
    return weights[:, np.newaxis] * baseband[np.newaxis, :]


def circular_leo_states(times_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic circular-LEO fallback states in an inertial Cartesian frame."""
    earth_radius_m = 6_378_137.0
    altitude_m = 550_000.0
    earth_mu = 3.986004418e14
    radius_m = earth_radius_m + altitude_m
    angular_rate = np.sqrt(earth_mu / radius_m**3)
    phase = angular_rate * times_s
    inclination_rad = np.deg2rad(53.0)

    positions = np.column_stack(
        (
            radius_m * np.cos(phase),
            radius_m * np.sin(phase) * np.cos(inclination_rad),
            radius_m * np.sin(phase) * np.sin(inclination_rad),
        )
    )
    velocities = np.column_stack(
        (
            -radius_m * angular_rate * np.sin(phase),
            radius_m * angular_rate * np.cos(phase) * np.cos(inclination_rad),
            radius_m * angular_rate * np.cos(phase) * np.sin(inclination_rad),
        )
    )
    return positions, velocities


def sgp4_state_provider() -> tuple[Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]], str] | None:
    """Return an SGP4 TEME state provider when the optional package is installed."""
    try:
        from sgp4.api import Satrec, jday
    except ImportError:
        return None

    # Fixed public example TLE: reproducible validation baseline, not live ephemeris.
    line1 = "1 25544U 98067A   24001.50000000  .00016717  00000+0  30100-3 0  9997"
    line2 = "2 25544  51.6416  21.2866 0004245  83.0404  45.2076 15.50000000430000"
    satellite = Satrec.twoline2rv(line1, line2)
    epoch = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def provider(times_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        positions = np.empty((len(times_s), 3))
        velocities = np.empty((len(times_s), 3))
        for index, seconds in enumerate(times_s):
            instant = epoch + timedelta(seconds=float(seconds))
            jd, fraction = jday(
                instant.year,
                instant.month,
                instant.day,
                instant.hour,
                instant.minute,
                instant.second + instant.microsecond * 1e-6,
            )
            error, position_km, velocity_km_s = satellite.sgp4(jd, fraction)
            if error:
                raise RuntimeError(f"SGP4 propagation failed with code {error}")
            positions[index] = np.asarray(position_km) * 1000.0
            velocities[index] = np.asarray(velocity_km_s) * 1000.0
        return positions, velocities

    return provider, "sgp4_fixed_tle_teme"


def cubic_hermite_resample(
    source_times_s: np.ndarray,
    positions_m: np.ndarray,
    velocities_mps: np.ndarray,
    target_times_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample position/velocity states using piecewise cubic Hermite polynomials."""
    if positions_m.shape != velocities_mps.shape or positions_m.shape != (len(source_times_s), 3):
        raise ValueError("positions and velocities must both have shape (sample_count, 3)")
    if np.any(np.diff(source_times_s) <= 0):
        raise ValueError("source_times_s must be strictly increasing")
    if target_times_s[0] < source_times_s[0] or target_times_s[-1] > source_times_s[-1]:
        raise ValueError("target times must lie inside the source time range")

    segment = np.searchsorted(source_times_s, target_times_s, side="right") - 1
    segment = np.clip(segment, 0, len(source_times_s) - 2)
    t0 = source_times_s[segment]
    t1 = source_times_s[segment + 1]
    h = t1 - t0
    u = (target_times_s - t0) / h
    u2, u3 = u * u, u * u * u

    p0, p1 = positions_m[segment], positions_m[segment + 1]
    v0, v1 = velocities_mps[segment], velocities_mps[segment + 1]
    h_col = h[:, None]
    positions = (
        (2 * u3 - 3 * u2 + 1)[:, None] * p0
        + (u3 - 2 * u2 + u)[:, None] * h_col * v0
        + (-2 * u3 + 3 * u2)[:, None] * p1
        + (u3 - u2)[:, None] * h_col * v1
    )
    velocities = (
        ((6 * u2 - 6 * u) / h)[:, None] * p0
        + (3 * u2 - 4 * u + 1)[:, None] * v0
        + ((-6 * u2 + 6 * u) / h)[:, None] * p1
        + (3 * u2 - 2 * u)[:, None] * v1
    )
    return positions, velocities


def compute_channel_geometry(
    satellite_positions_m: np.ndarray,
    satellite_velocities_mps: np.ndarray,
    ue_positions_m: np.ndarray,
    ue_velocities_mps: np.ndarray,
    carrier_hz: float,
) -> dict[str, np.ndarray]:
    """Compute satellite-to-UE LOS, range, range rate, and Doppler."""
    shapes = {
        satellite_positions_m.shape,
        satellite_velocities_mps.shape,
        ue_positions_m.shape,
        ue_velocities_mps.shape,
    }
    if len(shapes) != 1 or satellite_positions_m.ndim != 2 or satellite_positions_m.shape[1] != 3:
        raise ValueError("all position and velocity arrays must have shape (sample_count, 3)")

    displacement = ue_positions_m - satellite_positions_m
    ranges_m = np.linalg.norm(displacement, axis=1)
    if np.any(ranges_m == 0.0):
        raise ValueError("satellite and UE positions cannot coincide")
    los_sat_to_ue = displacement / ranges_m[:, None]
    relative_velocity = ue_velocities_mps - satellite_velocities_mps
    radial_velocity_mps = np.einsum("ij,ij->i", relative_velocity, los_sat_to_ue)
    # Positive recession produces negative received-frequency shift.
    doppler_hz = -carrier_hz * radial_velocity_mps / SPEED_OF_LIGHT_MPS
    return {
        "los_satellite_to_ue": los_sat_to_ue,
        "range_m": ranges_m,
        "radial_velocity_mps": radial_velocity_mps,
        "doppler_hz": doppler_hz,
    }


def validate_hermite_against_provider(
    provider: Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]],
    source_times_s: np.ndarray,
    positions_m: np.ndarray,
    velocities_mps: np.ndarray,
) -> dict[str, float]:
    """Compare interpolation at half-second points with direct propagation."""
    check_times = (source_times_s[:-1] + source_times_s[1:]) / 2.0
    interpolated_p, interpolated_v = cubic_hermite_resample(
        source_times_s, positions_m, velocities_mps, check_times
    )
    direct_p, direct_v = provider(check_times)
    position_error = np.linalg.norm(interpolated_p - direct_p, axis=1)
    velocity_error = np.linalg.norm(interpolated_v - direct_v, axis=1)
    return {
        "check_sample_count": int(len(check_times)),
        "max_position_error_m": float(np.max(position_error, initial=0.0)),
        "max_velocity_error_mps": float(np.max(velocity_error, initial=0.0)),
    }


def compute_beam_pattern(
    weights: np.ndarray, wavelength_m: float, spacing_m: float, resolution: int = 361
) -> tuple[np.ndarray, np.ndarray]:
    angles_rad = np.linspace(-np.pi, np.pi, resolution)
    response = np.empty(resolution)
    for index, angle in enumerate(angles_rad):
        manifold = steering_vector(angle, 0.0, len(weights), spacing_m, wavelength_m)
        response[index] = abs(np.dot(weights, manifold))
    response /= max(np.max(response), np.finfo(float).tiny)
    return angles_rad, 20.0 * np.log10(np.maximum(response, 1e-12))


def save_beam_pattern_plot(output_folder: str, angles_rad: np.ndarray, pattern_db: np.ndarray) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed; skipping beam-pattern plot")
        return
    plt.figure(figsize=(8, 4))
    plt.plot(angles_rad, pattern_db)
    plt.title("Normalized Ku-band TX beam pattern")
    plt.xlabel("Azimuth (rad)")
    plt.ylabel("Relative gain (dB)")
    plt.ylim(-60, 1)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(output_folder, "beam_pattern_initial.png"))
    plt.close()


def save_outputs(output_folder: str, arrays: dict[str, np.ndarray], metadata: dict) -> None:
    os.makedirs(output_folder, exist_ok=True)
    np.savez_compressed(os.path.join(output_folder, "simulation_outputs.npz"), **arrays)
    with open(os.path.join(output_folder, "outputs_metadata.json"), "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)


def main() -> dict[str, object]:
    config = LinkConfig()
    config.validate()
    rng = np.random.default_rng(20260803)

    baseband, qpsk_grid, signed_indices = generate_ofdm_waveform(config, rng)
    target_az_rad = np.deg2rad(30.0)
    target_el_rad = np.deg2rad(5.0)
    spacing_m = config.wavelength_m / 2.0
    weights = update_beam_weights(
        target_az_rad,
        target_el_rad,
        config.antenna_count,
        spacing_m,
        config.wavelength_m,
    )
    antenna_signals = tx_beamform(baseband, weights)

    provider_info = sgp4_state_provider()
    if provider_info is None:
        state_provider = circular_leo_states
        orbit_source = "analytic_circular_leo_fallback"
        sgp4_available = False
    else:
        state_provider, orbit_source = provider_info
        sgp4_available = True

    orbit_times_s = np.arange(
        0.0,
        config.simulation_duration_s + config.orbit_state_interval_s / 2.0,
        config.orbit_state_interval_s,
    )
    satellite_positions_1s_m, satellite_velocities_1s_mps = state_provider(orbit_times_s)
    channel_times_s = np.arange(
        0.0,
        config.simulation_duration_s + config.channel_interval_s / 2.0,
        config.channel_interval_s,
    )
    satellite_positions_m, satellite_velocities_mps = cubic_hermite_resample(
        orbit_times_s,
        satellite_positions_1s_m,
        satellite_velocities_1s_mps,
        channel_times_s,
    )

    # Stationary UE in the same Cartesian frame as the selected orbit source.
    ue_position = np.array([6_378_137.0, 0.0, 0.0])
    ue_positions_m = np.repeat(ue_position[None, :], len(channel_times_s), axis=0)
    ue_velocities_mps = np.zeros_like(ue_positions_m)
    channel = compute_channel_geometry(
        satellite_positions_m,
        satellite_velocities_mps,
        ue_positions_m,
        ue_velocities_mps,
        config.carrier_hz,
    )
    validation = validate_hermite_against_provider(
        state_provider,
        orbit_times_s,
        satellite_positions_1s_m,
        satellite_velocities_1s_mps,
    )

    # Channel time is the centre of the useful FFT interval, excluding the CP.
    fft_center_offsets_s = (
        config.cp_samples + (config.fft_size - 1) / 2.0
    ) / config.sample_rate_hz
    ofdm_fft_center_times_s = (
        np.arange(config.num_ofdm_symbols) * config.ofdm_symbol_duration_s
        + fft_center_offsets_s
    )

    arrays = {
        "antenna_signals_baseband": antenna_signals,
        "qpsk_grid": qpsk_grid,
        "signed_subcarrier_indices": signed_indices,
        "beam_weights": weights,
        "ofdm_fft_center_times_s": ofdm_fft_center_times_s,
        "orbit_times_s": orbit_times_s,
        "satellite_positions_1s_m": satellite_positions_1s_m,
        "satellite_velocities_1s_mps": satellite_velocities_1s_mps,
        "channel_times_s": channel_times_s,
        "satellite_positions_m": satellite_positions_m,
        "satellite_velocities_mps": satellite_velocities_mps,
        "ue_positions_m": ue_positions_m,
        "ue_velocities_mps": ue_velocities_mps,
        **channel,
    }
    metadata = {
        "config": asdict(config),
        "derived": {
            "sample_rate_hz": config.sample_rate_hz,
            "sample_period_s": config.sample_period_s,
            "occupied_bandwidth_hz": config.occupied_bandwidth_hz,
            "ofdm_symbol_duration_s": config.ofdm_symbol_duration_s,
            "wavelength_m": config.wavelength_m,
            "antenna_signal_shape": list(antenna_signals.shape),
            "channel_state_shape": list(satellite_positions_m.shape),
        },
        "conventions": {
            "position": "m",
            "velocity_and_radial_velocity": "m/s",
            "time": "simulation s",
            "angle": "rad",
            "radial_velocity_sign": "positive when range increases; negative when approaching",
            "los": "unit vector from satellite to UE",
            "state_shape": "(sample_count, 3)",
            "antenna_signal_shape": "(antenna_count, sample_count)",
            "channel_grid_time_reference": "centre of useful OFDM FFT interval",
            "subcarrier_index": "signed FFT index, DC excluded",
        },
        "orbit": {
            "source": orbit_source,
            "sgp4_available_and_used": sgp4_available,
            "state_resampling": "piecewise cubic Hermite using position and velocity",
            "direct_provider_validation": validation,
        },
    }

    output_folder = os.path.join(".", "output")
    save_outputs(output_folder, arrays, metadata)
    angles_rad, pattern_db = compute_beam_pattern(weights, config.wavelength_m, spacing_m)
    save_beam_pattern_plot(output_folder, angles_rad, pattern_db)

    print("=== Ku-band OFDM beamforming baseline ===")
    print(f"Carrier: {config.carrier_hz / 1e9:.1f} GHz")
    print(f"FFT / active / CP: {config.fft_size} / {config.active_subcarriers} / {config.cp_samples}")
    print(f"Sample rate: {config.sample_rate_hz / 1e6:.2f} MHz")
    print(f"Occupied bandwidth: {config.occupied_bandwidth_hz / 1e6:.2f} MHz")
    print(f"OFDM symbol duration incl. CP: {config.ofdm_symbol_duration_s * 1e6:.1f} us")
    print(f"Antenna waveform shape: {antenna_signals.shape}")
    print(f"Channel state shape: {satellite_positions_m.shape}")
    print(f"Orbit source: {orbit_source}")
    print(f"Hermite validation: {validation}")
    print(f"Saved outputs in: {os.path.abspath(output_folder)}")
    return {"arrays": arrays, "metadata": metadata}


if __name__ == "__main__":
    main()
