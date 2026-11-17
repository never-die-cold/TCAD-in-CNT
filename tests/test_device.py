import numpy as np
import pytest

from cnt_tid.config import DeviceConfig
from cnt_tid.device import drain_current, state_at_dose


def test_zero_dose_preserves_baseline() -> None:
    config = DeviceConfig(polarity="n")
    state = state_at_dose(config, 0.0)
    assert state.threshold_v == config.threshold_v
    assert state.mobility_m2_vs == config.mobility_m2_vs
    assert state.qot_c_cm2 == 0.0
    assert state.qit_c_cm2 == 0.0


def test_positive_trapped_charge_has_polarity_correct_threshold_shift() -> None:
    n_state = state_at_dose(DeviceConfig(polarity="n"), 1000.0)
    p_state = state_at_dose(DeviceConfig(polarity="p"), 1000.0)
    assert n_state.threshold_v < n_state.config.threshold_v
    assert p_state.threshold_v > p_state.config.threshold_v
    assert n_state.mobility_m2_vs < n_state.config.mobility_m2_vs


def test_current_obeys_boundary_and_monotonicity() -> None:
    state = state_at_dose(DeviceConfig(polarity="n"), 100.0)
    assert drain_current(state, 0.8, 0.0) == 0.0
    vds = np.linspace(0.0, 0.8, 20)
    current_vds = drain_current(state, 0.6, vds)
    assert np.all(np.diff(current_vds) >= 0)
    vgs = np.linspace(0.0, 0.8, 20)
    current_vgs = drain_current(state, vgs, 0.8)
    assert np.all(np.diff(current_vgs) >= 0)


def test_negative_vds_is_rejected() -> None:
    state = state_at_dose(DeviceConfig(polarity="n"), 0.0)
    with pytest.raises(ValueError, match="non-negative"):
        drain_current(state, 0.5, -0.1)
