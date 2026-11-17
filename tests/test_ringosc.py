"""Tests for the quasi-static ring-oscillator dose scan."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from cnt_tid.circuit import static_operating_current
from cnt_tid.config import load_config
from cnt_tid.device import state_at_dose
from cnt_tid.ringosc import (
    run_ring_oscillator_scan,
    stage_delay,
    stage_load_capacitance,
)

ROOT = Path(__file__).resolve().parents[1]
P0_CONFIG = ROOT / "configs" / "p0" / "cntfet_tid_p0.toml"


def test_load_capacitance_is_the_next_stage_gate_cap():
    config = load_config(P0_CONFIG)
    device = config.p_device
    expected = device.cox_f_m2 * device.width_m * device.length_m
    assert stage_load_capacitance(config) == pytest.approx(expected, rel=1e-12)
    assert stage_load_capacitance(config) == pytest.approx(1.59e-12, rel=0.05)


def test_delay_scales_inversely_with_mobility():
    """The compact current is linear in mu, so the delay integral is 1/mu exact."""

    config = load_config(P0_CONFIG)
    n_state = state_at_dose(config.n_device, 0.0, config.temperature_k)
    p_state = state_at_dose(config.p_device, 0.0, config.temperature_k)
    n_half = state_at_dose(
        replace(config.n_device, mobility_m2_vs=config.n_device.mobility_m2_vs * 0.5),
        0.0,
        config.temperature_k,
    )
    p_half = state_at_dose(
        replace(config.p_device, mobility_m2_vs=config.p_device.mobility_m2_vs * 0.5),
        0.0,
        config.temperature_k,
    )
    load = stage_load_capacitance(config)
    base = stage_delay(n_state, p_state, load, config.vdd_v)
    halved = stage_delay(n_half, p_half, load, config.vdd_v)
    assert halved == pytest.approx(2.0 * base, rel=1e-9)


def test_frequency_identity_and_scan_shape():
    config = load_config(P0_CONFIG)
    scan = run_ring_oscillator_scan(config)
    assert not scan.isna().any().any()
    row = scan.iloc[0]
    assert row["frequency_hz"] == pytest.approx(
        1.0 / (2.0 * config.ro_stages * row["stage_delay_s"]), rel=1e-12
    )
    assert (scan["frequency_hz"].diff().dropna() < 0).all()
    assert scan["load_cap_f"].nunique() == 1


def test_static_current_explodes_when_the_n_threshold_crosses_zero():
    config = load_config(P0_CONFIG)
    n_state = state_at_dose(config.n_device, 0.0, config.temperature_k)
    p_state = state_at_dose(config.p_device, 0.0, config.temperature_k)
    healthy = static_operating_current(n_state, p_state, config.vdd_v, 0.0)
    # An irradiated n-device whose threshold fell below 0 V cannot switch off:
    # the through-current is the on-current scale, not the leakage scale.
    burnt = static_operating_current(
        replace(n_state, threshold_v=-0.2), p_state, config.vdd_v, 0.0
    )
    assert healthy < 1e-7
    # The exact factor is set by the operating point (the weakened pull-up
    # still sources the through-current); hundreds-fold is the point.
    assert burnt > 100.0 * healthy


def test_odd_stage_count_is_enforced():
    config = load_config(P0_CONFIG)
    scan = run_ring_oscillator_scan(replace(config, ro_stages=9))
    base = run_ring_oscillator_scan(config)
    ratio = scan["frequency_hz"].iloc[0] / base["frequency_hz"].iloc[0]
    assert ratio == pytest.approx(11.0 / 9.0, rel=1e-9)
    with pytest.raises(ValueError, match="odd"):
        run_ring_oscillator_scan(replace(config, ro_stages=10))
