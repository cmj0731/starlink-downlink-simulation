from dataclasses import replace

import numpy as np
import pytest

from starlink_isl.downlink_geometry import (
    downlink_geometry,
    visibility_window,
)
from starlink_isl.ideal_orbit import IdealOrbitConfig
from starlink_isl.link_budget import (
    LinkBudgetConfig,
    equivalent_receiver_noise_temperature_k,
    free_space_path_loss_db,
    link_budget,
    system_noise_temperature_k,
    thermal_noise_power_dbw,
)


ORBIT = IdealOrbitConfig()
RADIO = LinkBudgetConfig(
    carrier_frequency_hz=10.0e9,
    bandwidth_hz=100.0e6,
    transmit_power_dbw=10.0,
    transmit_antenna_gain_dbi=30.0,
    receive_antenna_gain_dbi=40.0,
    system_noise_temperature_k=290.0,
    other_losses_db=2.0,
)


def test_thermal_noise_at_room_temperature_and_100_mhz():
    noise_dbw = thermal_noise_power_dbw(100.0e6, 290.0)

    assert noise_dbw == pytest.approx(-123.975, abs=0.001)
    assert noise_dbw + 30.0 == pytest.approx(-93.975, abs=0.001)


def test_noise_bandwidth_and_temperature_scaling():
    baseline = thermal_noise_power_dbw(1.0e6, 290.0)
    ten_times_bandwidth = thermal_noise_power_dbw(10.0e6, 290.0)
    twice_temperature = thermal_noise_power_dbw(1.0e6, 580.0)

    assert ten_times_bandwidth - baseline == pytest.approx(10.0)
    assert twice_temperature - baseline == pytest.approx(
        10.0 * np.log10(2.0)
    )


def test_noise_figure_temperature_conversion():
    equivalent = equivalent_receiver_noise_temperature_k(3.0)
    combined = system_noise_temperature_k(100.0, 3.0)
    expected = 290.0 * (10.0 ** 0.3 - 1.0)

    assert equivalent == pytest.approx(expected)
    assert combined == pytest.approx(100.0 + expected)
    assert equivalent_receiver_noise_temperature_k(0.0) == pytest.approx(0.0)


def test_link_budget_equation_at_overhead():
    result = link_budget(0.0, RADIO, ORBIT)
    expected_fspl = 20.0 * np.log10(
        4.0
        * np.pi
        * ORBIT.altitude_km
        * RADIO.carrier_frequency_hz
        / 299_792.458
    )
    expected_received = (
        RADIO.transmit_power_dbw
        + RADIO.transmit_antenna_gain_dbi
        + RADIO.receive_antenna_gain_dbi
        - expected_fspl
        - RADIO.other_losses_db
    )

    assert result.free_space_path_loss_db == pytest.approx(expected_fspl)
    assert result.received_power_dbw == pytest.approx(expected_received)
    assert result.snr_db == pytest.approx(
        expected_received - result.thermal_noise_power_dbw
    )
    assert bool(result.visible)


def test_cn0_and_snr_are_consistent_with_bandwidth():
    result = link_budget(0.0, RADIO, ORBIT)

    assert result.snr_db == pytest.approx(
        result.carrier_to_noise_density_db_hz
        - 10.0 * np.log10(RADIO.bandwidth_hz)
    )


def test_range_only_power_difference_reproduces_reference_value():
    static_orbit = replace(ORBIT, earth_rotation_rate_rad_s=0.0)
    window = visibility_window(static_orbit)
    result = link_budget(
        np.array([window.start_s, 0.0]),
        RADIO,
        static_orbit,
    )
    geometry = downlink_geometry(
        np.array([window.start_s, 0.0]),
        static_orbit,
    )
    expected_difference = 20.0 * np.log10(
        geometry.slant_range_km[0] / geometry.slant_range_km[1]
    )

    received_difference = (
        result.received_power_dbw[1] - result.received_power_dbw[0]
    )
    assert received_difference == pytest.approx(expected_difference)
    assert received_difference == pytest.approx(13.67, abs=0.02)
    assert result.snr_db[1] - result.snr_db[0] == pytest.approx(
        received_difference
    )


def test_larger_bandwidth_reduces_snr_without_changing_received_power():
    wideband_radio = replace(RADIO, bandwidth_hz=1.0e9)
    baseline = link_budget(0.0, RADIO, ORBIT)
    wideband = link_budget(0.0, wideband_radio, ORBIT)

    assert wideband.received_power_dbw == pytest.approx(
        baseline.received_power_dbw
    )
    assert wideband.snr_db == pytest.approx(baseline.snr_db - 10.0)


def test_visibility_mask_uses_minimum_elevation():
    times = np.array([0.0, 300.0, 1_000.0])
    result = link_budget(
        times,
        RADIO,
        ORBIT,
        minimum_elevation_deg=10.0,
    )

    assert result.visible[0]
    assert not result.visible[-1]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("carrier_frequency_hz", 0.0),
        ("bandwidth_hz", -1.0),
        ("system_noise_temperature_k", np.nan),
        ("other_losses_db", -0.1),
    ],
)
def test_invalid_radio_parameters_are_rejected(field, value):
    parameters = {
        "carrier_frequency_hz": 10.0e9,
        "bandwidth_hz": 100.0e6,
        "transmit_power_dbw": 10.0,
    }
    parameters[field] = value

    with pytest.raises(ValueError):
        LinkBudgetConfig(**parameters)


def test_invalid_noise_and_range_inputs_are_rejected():
    with pytest.raises(ValueError):
        thermal_noise_power_dbw(0.0, 290.0)
    with pytest.raises(ValueError):
        equivalent_receiver_noise_temperature_k(-1.0)
    with pytest.raises(ValueError):
        system_noise_temperature_k(-1.0, 3.0)
    with pytest.raises(ValueError):
        free_space_path_loss_db([572.0, 0.0], 10.0e9)

