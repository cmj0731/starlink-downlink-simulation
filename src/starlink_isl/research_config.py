"""Validated, team-shared research baseline configuration."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

DEFAULT_BASELINE_PATH = Path("configs/ofdm_baseline.yaml")


def _mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return value


def _required(mapping: Mapping[str, Any], key: str, prefix: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing required setting: {prefix}.{key}")
    return mapping[key]


def _float_value(mapping: Mapping[str, Any], key: str, prefix: str) -> float:
    value = _required(mapping, key, prefix)
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{prefix}.{key} must be numeric")
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{prefix}.{key} must be numeric") from error
    if not np.isfinite(converted):
        raise ValueError(f"{prefix}.{key} must be finite")
    return converted


def _int_value(mapping: Mapping[str, Any], key: str, prefix: str) -> int:
    value = _required(mapping, key, prefix)
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, np.integer),
    ):
        raise TypeError(f"{prefix}.{key} must be an integer")
    return int(value)


def _int_tuple(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
) -> tuple[int, ...]:
    values = _required(mapping, key, prefix)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError(f"{prefix}.{key} must be a sequence")
    converted: list[int] = []
    for index, value in enumerate(values):
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value,
            (int, np.integer),
        ):
            raise TypeError(f"{prefix}.{key}[{index}] must be an integer")
        converted.append(int(value))
    if not converted:
        raise ValueError(f"{prefix}.{key} must not be empty")
    return tuple(converted)


def _bool_value(mapping: Mapping[str, Any], key: str, prefix: str) -> bool:
    value = _required(mapping, key, prefix)
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{prefix}.{key} must be a bool")
    return bool(value)


def _str_value(mapping: Mapping[str, Any], key: str, prefix: str) -> str:
    value = _required(mapping, key, prefix)
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{prefix}.{key} must be a non-empty string")
    return value.strip()


def _float_tuple(
    mapping: Mapping[str, Any],
    key: str,
    prefix: str,
) -> tuple[float, ...]:
    values = _required(mapping, key, prefix)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise TypeError(f"{prefix}.{key} must be a sequence")
    converted: list[float] = []
    for index, value in enumerate(values):
        if isinstance(value, (bool, np.bool_)):
            raise TypeError(f"{prefix}.{key}[{index}] must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise TypeError(
                f"{prefix}.{key}[{index}] must be numeric"
            ) from error
        if not np.isfinite(number):
            raise ValueError(f"{prefix}.{key}[{index}] must be finite")
        converted.append(number)
    if not converted:
        raise ValueError(f"{prefix}.{key} must not be empty")
    return tuple(converted)


@dataclass(frozen=True, slots=True)
class ScenarioMetadata:
    """Identity and claim boundary for the shared scenario."""

    name: str
    status: str
    represents_actual_starlink_waveform: bool
    description: str


@dataclass(frozen=True, slots=True)
class RadioBaseline:
    """RF carrier assumptions used by propagation physics."""

    link_direction: str
    carrier_frequency_hz: float

    def __post_init__(self) -> None:
        if self.link_direction not in {"downlink", "uplink"}:
            raise ValueError("radio.link_direction must be downlink or uplink")
        if not np.isfinite(self.carrier_frequency_hz) or (
            self.carrier_frequency_hz <= 0.0
        ):
            raise ValueError("radio.carrier_frequency_hz must be positive")


@dataclass(frozen=True, slots=True)
class OFDMNumerology:
    """Waveform grid assumptions, independent of modulation implementation."""

    fft_size: int
    subcarrier_spacing_hz: float
    active_subcarrier_count: int
    cyclic_prefix_samples: int
    modulation: str
    dc_subcarrier_null: bool
    active_subcarrier_layout: str

    def __post_init__(self) -> None:
        if self.fft_size < 2:
            raise ValueError("ofdm.fft_size must be at least 2")
        if self.fft_size & (self.fft_size - 1):
            raise ValueError("ofdm.fft_size must be a power of two")
        if not np.isfinite(self.subcarrier_spacing_hz) or (
            self.subcarrier_spacing_hz <= 0.0
        ):
            raise ValueError("ofdm.subcarrier_spacing_hz must be positive")
        available_subcarriers = self.fft_size - int(self.dc_subcarrier_null)
        if not 0 < self.active_subcarrier_count <= available_subcarriers:
            raise ValueError(
                "ofdm.active_subcarrier_count exceeds available subcarriers"
            )
        if not 0 <= self.cyclic_prefix_samples < self.fft_size:
            raise ValueError(
                "ofdm.cyclic_prefix_samples must be in [0, fft_size)"
            )
        if not self.modulation:
            raise ValueError("ofdm.modulation must not be empty")
        if not self.active_subcarrier_layout:
            raise ValueError("ofdm.active_subcarrier_layout must not be empty")

    @property
    def sample_rate_hz(self) -> float:
        return self.fft_size * self.subcarrier_spacing_hz

    @property
    def sample_period_s(self) -> float:
        return 1.0 / self.sample_rate_hz

    @property
    def useful_symbol_duration_s(self) -> float:
        return 1.0 / self.subcarrier_spacing_hz

    @property
    def cyclic_prefix_duration_s(self) -> float:
        return self.cyclic_prefix_samples / self.sample_rate_hz

    @property
    def total_symbol_duration_s(self) -> float:
        return (
            self.fft_size + self.cyclic_prefix_samples
        ) / self.sample_rate_hz

    @property
    def occupied_bandwidth_hz(self) -> float:
        return self.active_subcarrier_count * self.subcarrier_spacing_hz

    @property
    def total_guard_bandwidth_hz(self) -> float:
        return self.sample_rate_hz - self.occupied_bandwidth_hz


@dataclass(frozen=True, slots=True)
class OFDMPilotLayout:
    """Frequency-domain pilot contract shared with the OFDM transmitter."""

    placement: str
    spacing_active_subcarriers: int
    fftshift_bin_indices: tuple[int, ...]

    def validate_for(self, numerology: OFDMNumerology) -> None:
        if self.placement != "frequency_comb":
            raise ValueError("ofdm.pilot.placement must be frequency_comb")
        if self.spacing_active_subcarriers <= 0:
            raise ValueError(
                "ofdm.pilot.spacing_active_subcarriers must be positive"
            )
        indices = np.asarray(self.fftshift_bin_indices, dtype=np.int64)
        if indices.size < 2:
            raise ValueError("ofdm.pilot requires at least two subcarriers")
        if np.any(np.diff(indices) <= 0):
            raise ValueError(
                "ofdm.pilot.fftshift_bin_indices must be strictly increasing"
            )
        if indices[0] < 0 or indices[-1] >= numerology.fft_size:
            raise ValueError(
                "ofdm.pilot.fftshift_bin_indices exceed the FFT grid"
            )
        if numerology.dc_subcarrier_null and np.any(
            indices == numerology.fft_size // 2
        ):
            raise ValueError("ofdm.pilot must not use the null DC bin")
        if len(indices) >= numerology.active_subcarrier_count:
            raise ValueError("ofdm.pilot must leave at least one data subcarrier")

        if (
            numerology.active_subcarrier_layout
            == "minyoung_fftshift_guard16_dc_null"
        ):
            active_bins = np.concatenate(
                (
                    np.arange(16, 128, dtype=np.int64),
                    np.arange(129, 240, dtype=np.int64),
                )
            )
            active_positions = np.searchsorted(active_bins, indices)
            if np.any(active_positions >= active_bins.size) or not np.array_equal(
                active_bins[active_positions], indices
            ):
                raise ValueError("ofdm.pilot uses a guard or inactive bin")
            if active_positions[0] != 0 or active_positions[-1] != (
                active_bins.size - 1
            ):
                raise ValueError(
                    "ofdm.pilot must anchor both active-band edges"
                )
            position_steps = np.diff(active_positions)
            if not np.all(
                position_steps[:-1] == self.spacing_active_subcarriers
            ) or not 0 < position_steps[-1] <= self.spacing_active_subcarriers:
                raise ValueError(
                    "ofdm.pilot indices do not match the configured spacing"
                )

    @property
    def pilot_subcarrier_count(self) -> int:
        return len(self.fftshift_bin_indices)


@dataclass(frozen=True, slots=True)
class OFDMWaveformNormalization:
    """Team contract for mapping unit-energy symbols to waveform samples."""

    data_symbol_average_energy: float
    pilot_symbol_magnitude: float
    ifft_convention: str
    time_domain_scale: str
    channel_input_average_power: float

    def __post_init__(self) -> None:
        for name, value in (
            ("data_symbol_average_energy", self.data_symbol_average_energy),
            ("pilot_symbol_magnitude", self.pilot_symbol_magnitude),
            ("channel_input_average_power", self.channel_input_average_power),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(
                    f"ofdm.waveform_normalization.{name} must be positive"
                )
        if self.ifft_convention != "numpy_backward":
            raise ValueError(
                "ofdm.waveform_normalization.ifft_convention must be "
                "numpy_backward"
            )
        if self.time_domain_scale != "nfft_over_sqrt_active_subcarriers":
            raise ValueError(
                "ofdm.waveform_normalization.time_domain_scale must be "
                "nfft_over_sqrt_active_subcarriers"
            )

    def ifft_scale(self, numerology: OFDMNumerology) -> float:
        """Scale a default NumPy IFFT to unit mean time-domain power."""

        return numerology.fft_size / np.sqrt(
            numerology.active_subcarrier_count
        )


@dataclass(frozen=True, slots=True)
class ChannelStateSampling:
    """Orbit-state source and time-varying channel update assumptions."""

    geometry_source_step_s: float
    update_interval_s: float
    resampling_method: str
    validate_against_direct_sgp4: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("geometry_source_step_s", self.geometry_source_step_s),
            ("update_interval_s", self.update_interval_s),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"channel_state.{name} must be positive")
        if self.update_interval_s > self.geometry_source_step_s:
            raise ValueError(
                "channel_state.update_interval_s cannot exceed source step"
            )
        if self.resampling_method not in {"cubic_hermite", "direct_sgp4"}:
            raise ValueError(
                "channel_state.resampling_method must be cubic_hermite "
                "or direct_sgp4"
            )


@dataclass(frozen=True, slots=True)
class ChannelGridBaseline:
    """Coordinate conventions for the provisional SISO ``H[m, k]`` grid."""

    time_axis: str
    symbol_time_reference: str
    subcarrier_index_convention: str
    waveform_bin_order: str

    def __post_init__(self) -> None:
        if self.time_axis != "ofdm_symbol":
            raise ValueError("channel_grid.time_axis must be ofdm_symbol")
        if self.symbol_time_reference not in {
            "symbol_start",
            "fft_window_start",
            "fft_window_center",
        }:
            raise ValueError(
                "channel_grid.symbol_time_reference is not supported"
            )
        if self.subcarrier_index_convention != "signed_fft":
            raise ValueError(
                "channel_grid.subcarrier_index_convention must be signed_fft"
            )
        if self.waveform_bin_order != "fftshifted":
            raise ValueError(
                "channel_grid.waveform_bin_order must be fftshifted"
            )


@dataclass(frozen=True, slots=True)
class ReceiverFilterBaseline:
    """Provisional complex-baseband receiver-filter edges."""

    passband_edge_hz: float
    stopband_edge_hz: float
    num_taps: int
    window: str

    def validate_for(self, numerology: OFDMNumerology) -> None:
        if not 0.0 < self.passband_edge_hz < self.stopband_edge_hz:
            raise ValueError(
                "receiver_filter edges must be positive and increasing"
            )
        if self.passband_edge_hz < 0.5 * numerology.occupied_bandwidth_hz:
            raise ValueError(
                "receiver_filter passband does not contain occupied bandwidth"
            )
        if self.stopband_edge_hz >= 0.5 * numerology.sample_rate_hz:
            raise ValueError(
                "receiver_filter stopband must be below Nyquist frequency"
            )
        if self.num_taps < 3 or self.num_taps % 2 == 0:
            raise ValueError(
                "receiver_filter.num_taps must be an odd integer of at least 3"
            )
        if not self.window:
            raise ValueError("receiver_filter.window must not be empty")


@dataclass(frozen=True, slots=True)
class ExperimentSweeps:
    """Initial CFO and SNR experiment axes."""

    subcarrier_spacing_candidates_hz: tuple[float, ...]
    normalized_cfo_candidates: tuple[float, ...]
    snr_db: tuple[float, ...]

    def validate_for(self, numerology: OFDMNumerology) -> None:
        if any(value <= 0.0 for value in self.subcarrier_spacing_candidates_hz):
            raise ValueError("experiment subcarrier spacings must be positive")
        if not any(
            np.isclose(value, numerology.subcarrier_spacing_hz)
            for value in self.subcarrier_spacing_candidates_hz
        ):
            raise ValueError(
                "experiment spacings must include the baseline spacing"
            )


@dataclass(frozen=True, slots=True)
class TeamConfirmation:
    """Fields that remain provisional until team integration."""

    required_before_final_integration: bool
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.required_before_final_integration and not self.fields:
            raise ValueError(
                "team_confirmation.fields must identify pending decisions"
            )
        if not self.required_before_final_integration and self.fields:
            raise ValueError(
                "team_confirmation.fields must be empty after confirmation"
            )


@dataclass(frozen=True, slots=True)
class ResearchBaselineConfig:
    """Validated shared baseline and its derived physical values."""

    schema_version: int
    scenario: ScenarioMetadata
    radio: RadioBaseline
    ofdm: OFDMNumerology
    pilot: OFDMPilotLayout
    waveform_normalization: OFDMWaveformNormalization
    channel_state: ChannelStateSampling
    channel_grid: ChannelGridBaseline
    receiver_filter: ReceiverFilterBaseline
    experiments: ExperimentSweeps
    team_confirmation: TeamConfirmation

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported research-config schema_version")
        self.pilot.validate_for(self.ofdm)
        self.receiver_filter.validate_for(self.ofdm)
        self.experiments.validate_for(self.ofdm)

    def derived_values(self) -> dict[str, float]:
        """Return numerology values derived from independent YAML inputs."""

        return {
            "sample_rate_hz": self.ofdm.sample_rate_hz,
            "sample_period_s": self.ofdm.sample_period_s,
            "occupied_bandwidth_hz": self.ofdm.occupied_bandwidth_hz,
            "total_guard_bandwidth_hz": self.ofdm.total_guard_bandwidth_hz,
            "useful_symbol_duration_s": self.ofdm.useful_symbol_duration_s,
            "cyclic_prefix_duration_s": self.ofdm.cyclic_prefix_duration_s,
            "total_symbol_duration_s": self.ofdm.total_symbol_duration_s,
        }


def load_research_baseline(path: str | Path) -> ResearchBaselineConfig:
    """Load and validate a team-shared YAML research baseline."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML in {config_path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError("research configuration root must be a mapping")

    scenario = _mapping(raw, "scenario")
    radio = _mapping(raw, "radio")
    ofdm = _mapping(raw, "ofdm")
    pilot = _mapping(ofdm, "pilot")
    waveform_normalization = _mapping(ofdm, "waveform_normalization")
    channel = _mapping(raw, "channel_state")
    channel_grid = _mapping(raw, "channel_grid")
    receiver_filter = _mapping(raw, "receiver_filter")
    experiments = _mapping(raw, "experiments")
    confirmation = _mapping(raw, "team_confirmation")
    confirmation_fields = _required(
        confirmation,
        "fields",
        "team_confirmation",
    )
    if not isinstance(confirmation_fields, Sequence) or isinstance(
        confirmation_fields,
        (str, bytes),
    ):
        raise TypeError("team_confirmation.fields must be a sequence")
    if not all(isinstance(value, str) and value for value in confirmation_fields):
        raise TypeError("team_confirmation.fields must contain non-empty strings")

    return ResearchBaselineConfig(
        schema_version=_int_value(raw, "schema_version", "root"),
        scenario=ScenarioMetadata(
            name=_str_value(scenario, "name", "scenario"),
            status=_str_value(scenario, "status", "scenario"),
            represents_actual_starlink_waveform=_bool_value(
                scenario,
                "represents_actual_starlink_waveform",
                "scenario",
            ),
            description=_str_value(scenario, "description", "scenario"),
        ),
        radio=RadioBaseline(
            link_direction=_str_value(radio, "link_direction", "radio"),
            carrier_frequency_hz=_float_value(
                radio,
                "carrier_frequency_hz",
                "radio",
            ),
        ),
        ofdm=OFDMNumerology(
            fft_size=_int_value(ofdm, "fft_size", "ofdm"),
            subcarrier_spacing_hz=_float_value(
                ofdm,
                "subcarrier_spacing_hz",
                "ofdm",
            ),
            active_subcarrier_count=_int_value(
                ofdm,
                "active_subcarrier_count",
                "ofdm",
            ),
            cyclic_prefix_samples=_int_value(
                ofdm,
                "cyclic_prefix_samples",
                "ofdm",
            ),
            modulation=_str_value(ofdm, "modulation", "ofdm"),
            dc_subcarrier_null=_bool_value(
                ofdm,
                "dc_subcarrier_null",
                "ofdm",
            ),
            active_subcarrier_layout=_str_value(
                ofdm,
                "active_subcarrier_layout",
                "ofdm",
            ),
        ),
        pilot=OFDMPilotLayout(
            placement=_str_value(pilot, "placement", "ofdm.pilot"),
            spacing_active_subcarriers=_int_value(
                pilot,
                "spacing_active_subcarriers",
                "ofdm.pilot",
            ),
            fftshift_bin_indices=_int_tuple(
                pilot,
                "fftshift_bin_indices",
                "ofdm.pilot",
            ),
        ),
        waveform_normalization=OFDMWaveformNormalization(
            data_symbol_average_energy=_float_value(
                waveform_normalization,
                "data_symbol_average_energy",
                "ofdm.waveform_normalization",
            ),
            pilot_symbol_magnitude=_float_value(
                waveform_normalization,
                "pilot_symbol_magnitude",
                "ofdm.waveform_normalization",
            ),
            ifft_convention=_str_value(
                waveform_normalization,
                "ifft_convention",
                "ofdm.waveform_normalization",
            ),
            time_domain_scale=_str_value(
                waveform_normalization,
                "time_domain_scale",
                "ofdm.waveform_normalization",
            ),
            channel_input_average_power=_float_value(
                waveform_normalization,
                "channel_input_average_power",
                "ofdm.waveform_normalization",
            ),
        ),
        channel_state=ChannelStateSampling(
            geometry_source_step_s=_float_value(
                channel,
                "geometry_source_step_s",
                "channel_state",
            ),
            update_interval_s=_float_value(
                channel,
                "update_interval_s",
                "channel_state",
            ),
            resampling_method=_str_value(
                channel,
                "resampling_method",
                "channel_state",
            ),
            validate_against_direct_sgp4=_bool_value(
                channel,
                "validate_against_direct_sgp4",
                "channel_state",
            ),
        ),
        channel_grid=ChannelGridBaseline(
            time_axis=_str_value(
                channel_grid,
                "time_axis",
                "channel_grid",
            ),
            symbol_time_reference=_str_value(
                channel_grid,
                "symbol_time_reference",
                "channel_grid",
            ),
            subcarrier_index_convention=_str_value(
                channel_grid,
                "subcarrier_index_convention",
                "channel_grid",
            ),
            waveform_bin_order=_str_value(
                channel_grid,
                "waveform_bin_order",
                "channel_grid",
            ),
        ),
        receiver_filter=ReceiverFilterBaseline(
            passband_edge_hz=_float_value(
                receiver_filter,
                "passband_edge_hz",
                "receiver_filter",
            ),
            stopband_edge_hz=_float_value(
                receiver_filter,
                "stopband_edge_hz",
                "receiver_filter",
            ),
            num_taps=_int_value(receiver_filter, "num_taps", "receiver_filter"),
            window=_str_value(receiver_filter, "window", "receiver_filter"),
        ),
        experiments=ExperimentSweeps(
            subcarrier_spacing_candidates_hz=_float_tuple(
                experiments,
                "subcarrier_spacing_candidates_hz",
                "experiments",
            ),
            normalized_cfo_candidates=_float_tuple(
                experiments,
                "normalized_cfo_candidates",
                "experiments",
            ),
            snr_db=_float_tuple(experiments, "snr_db", "experiments"),
        ),
        team_confirmation=TeamConfirmation(
            required_before_final_integration=_bool_value(
                confirmation,
                "required_before_final_integration",
                "team_confirmation",
            ),
            fields=tuple(confirmation_fields),
        ),
    )


def main() -> None:
    """Validate a baseline YAML and print its derived numerology."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
    )
    args = parser.parse_args()
    config = load_research_baseline(args.path)
    output = {
        "scenario": config.scenario.name,
        "status": config.scenario.status,
        "represents_actual_starlink_waveform": (
            config.scenario.represents_actual_starlink_waveform
        ),
        "derived": config.derived_values(),
        "pilot": {
            "placement": config.pilot.placement,
            "spacing_active_subcarriers": (
                config.pilot.spacing_active_subcarriers
            ),
            "pilot_subcarrier_count": config.pilot.pilot_subcarrier_count,
            "fftshift_bin_indices": config.pilot.fftshift_bin_indices,
        },
        "waveform_normalization": {
            "data_symbol_average_energy": (
                config.waveform_normalization.data_symbol_average_energy
            ),
            "pilot_symbol_magnitude": (
                config.waveform_normalization.pilot_symbol_magnitude
            ),
            "ifft_convention": config.waveform_normalization.ifft_convention,
            "time_domain_scale": (
                config.waveform_normalization.time_domain_scale
            ),
            "ifft_scale": config.waveform_normalization.ifft_scale(
                config.ofdm
            ),
            "channel_input_average_power": (
                config.waveform_normalization.channel_input_average_power
            ),
        },
        "channel_grid": {
            "time_axis": config.channel_grid.time_axis,
            "symbol_time_reference": (
                config.channel_grid.symbol_time_reference
            ),
            "subcarrier_index_convention": (
                config.channel_grid.subcarrier_index_convention
            ),
            "waveform_bin_order": config.channel_grid.waveform_bin_order,
        },
        "team_confirmation_required": (
            config.team_confirmation.required_before_final_integration
        ),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
