"""Tests for the post-irradiation annealing scenario module."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cnt_tid.annealing import (
    annealed_config,
    plot_annealing_recovery,
    run_annealing_scan,
)
from cnt_tid.config import load_config
from cnt_tid.ringosc import run_ring_oscillator_scan

ROOT = Path(__file__).resolve().parents[1]
P0_CONFIG = ROOT / "configs" / "p0" / "cntfet_tid_p0.toml"
REGISTRY = ROOT / "data" / "parameters" / "tid_parameters.csv"
FRACTION = 0.3
TAU_S = 1e4


def test_zero_time_reproduces_the_baseline_bitwise():
    config = load_config(P0_CONFIG)
    annealed = annealed_config(config, 0.0, FRACTION, TAU_S)
    baseline = run_ring_oscillator_scan(config)
    zero = run_ring_oscillator_scan(annealed)
    assert np.allclose(baseline["frequency_hz"], zero["frequency_hz"], rtol=1e-12)
    assert np.allclose(baseline["static_power_w"], zero["static_power_w"], rtol=1e-12)


def test_full_recovery_retains_exactly_the_residual_fraction():
    """t -> infinity anneals the fraction away; the (1-f) part stays forever."""

    config = load_config(P0_CONFIG)
    annealed = annealed_config(config, 1e12, FRACTION, TAU_S)
    factor = 1.0 - FRACTION
    for polarity in ("n_device", "p_device"):
        device = getattr(annealed, polarity)
        original = getattr(config, polarity)
        assert device.qot_slope_c_cm2_per_krad == pytest.approx(
            original.qot_slope_c_cm2_per_krad * factor, rel=1e-12
        )
        assert device.qit_anneal_c_cm2 == pytest.approx(
            original.qit_anneal_c_cm2 * factor, rel=1e-12
        )
    # And the threshold shift shrinks by exactly that factor.
    from cnt_tid.device import state_at_dose

    dose = config.doses_krad[-1]
    shift_base = state_at_dose(config.p_device, dose).delta_threshold_v
    shift_late = state_at_dose(annealed.p_device, dose).delta_threshold_v
    assert shift_late == pytest.approx(shift_base * factor, rel=1e-12)


def test_recovery_is_monotone_between_the_extremes():
    config = load_config(P0_CONFIG)
    scan = run_annealing_scan(
        config, FRACTION, TAU_S, times_s=(0.0, 3600.0, 86400.0, 1e12)
    )
    late = scan[scan["dose_krad"] == config.doses_krad[-1]].sort_values("time_s")
    frequencies = late["frequency_hz"].to_numpy(dtype=float)
    assert (np.diff(frequencies) > 0).all()
    # tau = 1e4 s = 2.8 h: after one day the residual factor is
    # exp(-86400/1e4) = 1.8e-4, so the recovery is saturated to ~1e-4.
    assert frequencies[-1] == pytest.approx(frequencies[-2], rel=5e-4)


def test_fraction_and_time_validation():
    config = load_config(P0_CONFIG)
    with pytest.raises(ValueError, match="fraction"):
        annealed_config(config, 100.0, 1.5, TAU_S)
    with pytest.raises(ValueError, match="tau_s"):
        annealed_config(config, 100.0, FRACTION, 0.0)
    with pytest.raises(ValueError, match="time_s"):
        annealed_config(config, -1.0, FRACTION, TAU_S)


def test_registry_declares_the_annealing_assumptions():
    from cnt_tid.registry import load_registry, number

    registry = load_registry(REGISTRY)
    fraction = number(registry, "assume.annealed_charge_fraction")
    tau = number(registry, "assume.annealing_time_constant_s")
    assert 0.1 <= fraction <= 0.6
    assert 1e3 <= tau <= 1e6


def test_scan_artifacts_and_figure(tmp_path: Path):
    from cnt_tid.annealing import write_annealing_artifacts

    config = load_config(P0_CONFIG)
    scan_path, metadata = write_annealing_artifacts(
        config, FRACTION, TAU_S, (0.0, 3600.0), tmp_path / "anneal"
    )
    scan = pd.read_csv(scan_path)
    assert len(scan) == 2 * len(config.doses_krad)
    assert metadata["annealed_charge_fraction"] == FRACTION
    plot_annealing_recovery(scan, tmp_path / "fig10.png")
    assert (tmp_path / "fig10.png").exists()
