import numpy as np
import pytest

from cnt_tid.circuit import solve_inverter
from cnt_tid.config import DeviceConfig
from cnt_tid.device import state_at_dose


def test_symmetric_inverter_has_valid_static_metrics() -> None:
    n_state = state_at_dose(DeviceConfig(polarity="n"), 0.0)
    p_state = state_at_dose(DeviceConfig(polarity="p"), 0.0)
    result = solve_inverter(n_state, p_state, vdd_v=0.8, points=501)
    assert result.vout_v[0] > 0.79
    assert result.vout_v[-1] < 0.01
    assert np.all(np.diff(result.vout_v) <= 1e-8)
    assert result.vm_v == 0.4
    assert 0 < result.vil_v < result.vm_v < result.vih_v < 0.8
    assert 0 < result.nml_v < 0.4
    assert 0 < result.nmh_v < 0.4


def test_dose_moves_switching_threshold_for_asymmetric_defaults() -> None:
    fresh = solve_inverter(
        state_at_dose(DeviceConfig(polarity="n"), 0.0),
        state_at_dose(DeviceConfig(polarity="p"), 0.0),
        0.8,
        501,
    )
    irradiated = solve_inverter(
        state_at_dose(DeviceConfig(polarity="n"), 1000.0),
        state_at_dose(DeviceConfig(polarity="p"), 1000.0),
        0.8,
        501,
    )
    assert irradiated.vm_v < fresh.vm_v
    assert irradiated.nml_v > 0
    assert irradiated.nmh_v > 0


def test_failed_crossing_extraction_warns_instead_of_silently_zeroing() -> None:
    # Deep-subthreshold-only devices keep |gain| < 1 across the whole VTC,
    # so VIL/VIH crossings do not exist and must surface as NaN + warning.
    n_state = state_at_dose(
        DeviceConfig(polarity="n", threshold_v=0.5, slope_factor=5.0), 0.0
    )
    p_state = state_at_dose(
        DeviceConfig(polarity="p", threshold_v=0.5, slope_factor=5.0), 0.0
    )
    with pytest.warns(UserWarning, match="crossing extraction failed"):
        result = solve_inverter(n_state, p_state, vdd_v=0.1, points=501)
    assert np.isnan(result.vil_v) and np.isnan(result.vih_v)
