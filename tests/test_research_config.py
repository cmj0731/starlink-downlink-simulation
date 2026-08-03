from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy.signal import freqz

from starlink_isl import (
    ReceiverFilterConfig,
    design_receiver_filter,
    load_research_baseline,
)


BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "ofdm_baseline.yaml"
)


def _baseline_mapping():
    return yaml.safe_load(BASELINE_PATH.read_text(encoding="utf-8"))


def _write_config(tmp_path, mapping):
    path = tmp_path / "baseline.yaml"
    path.write_text(
        yaml.safe_dump(mapping, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_provisional_baseline_loads_with_expected_derived_numerology():
    config = load_research_baseline(BASELINE_PATH)

    assert config.scenario.status == "provisional"
    assert config.scenario.represents_actual_starlink_waveform is False
    assert config.radio.link_direction == "downlink"
    assert config.radio.carrier_frequency_hz == pytest.approx(11.7e9)
    assert config.ofdm.sample_rate_hz == pytest.approx(30.72e6)
    assert config.ofdm.sample_period_s == pytest.approx(1.0 / 30.72e6)
    assert config.ofdm.occupied_bandwidth_hz == pytest.approx(26.76e6)
    assert config.ofdm.total_guard_bandwidth_hz == pytest.approx(3.96e6)
    assert config.ofdm.useful_symbol_duration_s == pytest.approx(1.0 / 120.0e3)
    assert config.ofdm.cyclic_prefix_duration_s == 0.0
    assert config.ofdm.total_symbol_duration_s == pytest.approx(1.0 / 120.0e3)
    assert config.ofdm.cyclic_prefix_samples == 0
    assert 1.0e-3 / config.ofdm.total_symbol_duration_s == pytest.approx(120.0)
    assert (
        config.ofdm.active_subcarrier_layout
        == "minyoung_fftshift_guard16_dc_null"
    )
    assert config.pilot.placement == "frequency_comb"
    assert config.pilot.spacing_active_subcarriers == 16
    assert config.pilot.pilot_subcarrier_count == 15
    assert config.pilot.fftshift_bin_indices == (
        16,
        32,
        48,
        64,
        80,
        96,
        112,
        129,
        145,
        161,
        177,
        193,
        209,
        225,
        239,
    )
    assert (
        config.ofdm.active_subcarrier_count
        - config.pilot.pilot_subcarrier_count
        == 208
    )


def test_baseline_separates_geometry_source_and_channel_update_intervals():
    config = load_research_baseline(BASELINE_PATH)

    assert config.channel_state.geometry_source_step_s == pytest.approx(1.0)
    assert config.channel_state.update_interval_s == pytest.approx(0.001)
    assert config.channel_state.resampling_method == "cubic_hermite"
    assert config.channel_state.validate_against_direct_sgp4 is True
    assert config.channel_grid.time_axis == "ofdm_symbol"
    assert config.channel_grid.symbol_time_reference == "fft_window_center"
    assert config.channel_grid.subcarrier_index_convention == "signed_fft"
    assert config.channel_grid.waveform_bin_order == "fftshifted"


def test_baseline_receiver_filter_is_compatible_with_ofdm_bandwidth():
    config = load_research_baseline(BASELINE_PATH)
    filter_config = ReceiverFilterConfig(
        sample_rate_hz=config.ofdm.sample_rate_hz,
        passband_edge_hz=config.receiver_filter.passband_edge_hz,
        stopband_edge_hz=config.receiver_filter.stopband_edge_hz,
        num_taps=config.receiver_filter.num_taps,
        window=config.receiver_filter.window,
    )

    assert filter_config.passband_edge_hz > (
        0.5 * config.ofdm.occupied_bandwidth_hz
    )
    assert filter_config.stopband_edge_hz < 0.5 * config.ofdm.sample_rate_hz

    taps = design_receiver_filter(filter_config)
    frequencies_hz = np.array(
        [filter_config.passband_edge_hz, filter_config.stopband_edge_hz]
    )
    angular_frequency = (
        2.0 * np.pi * frequencies_hz / filter_config.sample_rate_hz
    )
    _, response = freqz(taps, worN=angular_frequency)
    assert abs(response[0]) > 0.99
    assert abs(response[1]) < 0.01


def test_baseline_marks_fields_requiring_team_confirmation():
    config = load_research_baseline(BASELINE_PATH)

    assert config.team_confirmation.required_before_final_integration is True
    assert "ofdm.active_subcarrier_layout" not in config.team_confirmation.fields
    assert "channel_grid.symbol_time_reference" in (
        config.team_confirmation.fields
    )
    assert "ofdm.pilot_layout" not in config.team_confirmation.fields
    assert "ofdm.waveform_normalization" in config.team_confirmation.fields


def test_config_rejects_pilot_on_null_dc_bin(tmp_path):
    mapping = _baseline_mapping()
    mapping["ofdm"]["pilot"]["fftshift_bin_indices"][7] = 128

    with pytest.raises(ValueError, match="null DC"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_pilot_layout_inconsistent_with_spacing(tmp_path):
    mapping = _baseline_mapping()
    mapping["ofdm"]["pilot"]["fftshift_bin_indices"][8] = 146

    with pytest.raises(ValueError, match="configured spacing"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_more_active_subcarriers_than_available(tmp_path):
    mapping = _baseline_mapping()
    mapping["ofdm"]["active_subcarrier_count"] = 256

    with pytest.raises(ValueError, match="active_subcarrier_count"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_filter_that_cuts_occupied_bandwidth(tmp_path):
    mapping = _baseline_mapping()
    mapping["receiver_filter"]["passband_edge_hz"] = 2.5e6

    with pytest.raises(ValueError, match="occupied bandwidth"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_channel_update_slower_than_source(tmp_path):
    mapping = _baseline_mapping()
    mapping["channel_state"]["update_interval_s"] = 2.0

    with pytest.raises(ValueError, match="cannot exceed"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_unsupported_channel_grid_convention(tmp_path):
    mapping = _baseline_mapping()
    mapping["channel_grid"]["subcarrier_index_convention"] = "fftshifted"

    with pytest.raises(ValueError, match="signed_fft"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_unsupported_waveform_bin_order(tmp_path):
    mapping = _baseline_mapping()
    mapping["channel_grid"]["waveform_bin_order"] = "natural_fft"

    with pytest.raises(ValueError, match="waveform_bin_order"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_sweep_without_baseline_spacing(tmp_path):
    mapping = _baseline_mapping()
    mapping["experiments"]["subcarrier_spacing_candidates_hz"] = [15e3, 60e3]

    with pytest.raises(ValueError, match="baseline spacing"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_missing_required_setting(tmp_path):
    mapping = _baseline_mapping()
    del mapping["ofdm"]["fft_size"]

    with pytest.raises(ValueError, match="ofdm.fft_size"):
        load_research_baseline(_write_config(tmp_path, mapping))


def test_config_rejects_invalid_yaml(tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text("ofdm: [unterminated", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid YAML"):
        load_research_baseline(path)
