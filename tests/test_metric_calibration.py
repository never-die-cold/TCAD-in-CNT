"""Tests for the digitized-metric calibration path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cnt_tid.config import EPSILON_0_F_M, DeviceConfig
from cnt_tid.metric_calibration import (
    calibrate_from_metrics,
    load_digitized_metrics,
    wide_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "data" / "literature" / "cui2023_topgate" / "fig3_metrics_digitized.csv"
IDEAL_SS_MV = 1000.0 * np.log(10.0) * 1.380649e-23 * 300.0 / 1.602176634e-19


def synthetic_metrics(
    *,
    vth0: float = 0.53,
    ss0: float = 208.0,
    gm0: float = 1.07e-5,
    q_total: float = 1.2e-8,
    q_it: float = 0.5e-8,
    exponent: float = 0.6,
    alpha: float = 5.5e-4,
    cox: float = 1.33e-6,
    doses=(0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0),
) -> pd.DataFrame:
    rows = []
    for dose in doses:
        scale = dose**exponent
        vth = vth0 + q_total * scale / cox
        ss = ss0 + (q_it * scale / cox) * IDEAL_SS_MV
        gm = gm0 / (1.0 + alpha * dose)
        for metric, value, unit in (
            ("vth_v", -vth, "V"),
            ("gm_max_s", gm, "S"),
            ("ss_mv_dec", ss, "mV/dec"),
        ):
            rows.append(
                {
                    "source": "synthetic",
                    "device_id": "synth",
                    "polarity": "p",
                    "dose_value": dose,
                    "dose_unit": "krad(Si)",
                    "vds_signed_v": -0.1,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "err_minus": abs(value) * 1e-3,
                    "err_plus": abs(value) * 1e-3,
                }
            )
    return pd.DataFrame(rows)


def test_digitized_file_has_the_expected_shape():
    frame = load_digitized_metrics(METRICS)
    assert len(frame) == 18
    wide = wide_metrics(frame)
    assert list(wide.index) == [0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0]
    assert set(wide.columns.str.extract(r"^([a-z_]+?)(?:_err)?$")[0].dropna()) >= {
        "vth_v",
        "gm_max_s",
        "ss_mv_dec",
    }


def test_digitized_values_match_the_published_figure():
    wide = wide_metrics(load_digitized_metrics(METRICS))
    assert wide.loc[0.0, "vth_v"] == pytest.approx(-0.529954, abs=1e-6)
    assert wide.loc[3000.0, "vth_v"] == pytest.approx(-1.62233, abs=1e-5)
    assert wide.loc[0.0, "ss_mv_dec"] == pytest.approx(207.951, abs=1e-3)
    assert wide.loc[200.0, "ss_mv_dec"] == pytest.approx(185.391, abs=1e-3)
    assert wide.loc[3000.0, "gm_max_s"] == pytest.approx(4.11906e-6, rel=1e-5)


def test_calibration_recovers_a_synthetic_power_law():
    frame = synthetic_metrics()
    calibration = calibrate_from_metrics(
        frame,
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        width_um=30.0,
        length_nm=4000.0,
        temperature_k=300.0,
    )
    assert calibration.dose_exponent == pytest.approx(0.6, abs=0.02)
    assert calibration.total_charge_slope_c_cm2_per_krad == pytest.approx(1.2e-8, rel=0.03)
    assert calibration.q_it_c_cm2_per_krad == pytest.approx(0.5e-8, rel=0.05)
    # The synthetic Gm follows the closed form while the fit evaluates the
    # compact model, whose Gm also responds to the threshold and swing drift;
    # alpha is therefore an effective coefficient, recovered to ~15 %.
    assert calibration.mobility_degradation_per_krad == pytest.approx(5.5e-4, rel=0.2)
    assert calibration.residuals["vth_residual_mv"].abs().max() < 2.0
    assert calibration.residuals["ss_residual_mv"].abs().max() < 1.0


def test_repository_calibration_is_physical():
    calibration = calibrate_from_metrics(
        load_digitized_metrics(METRICS),
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        width_um=30.0,
        length_nm=4000.0,
        temperature_k=300.0,
    )
    assert 0.2 < calibration.dose_exponent < 1.0
    assert calibration.q_ot_c_cm2_per_krad > 0
    assert calibration.q_it_c_cm2_per_krad > 0
    assert calibration.q_ot_c_cm2_per_krad > calibration.q_it_c_cm2_per_krad
    assert abs(calibration.residuals["vth_residual_mv"]).max() < 100.0
    assert calibration.holdout["vth_residual_mv"].abs().max() < 150.0


def test_swing_and_threshold_share_one_exponent():
    calibration = calibrate_from_metrics(
        synthetic_metrics(exponent=0.75, q_total=3.6e-9, q_it=1.2e-9),
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        width_um=30.0,
        length_nm=4000.0,
        temperature_k=300.0,
    )
    device = DeviceConfig(
        polarity="p",
        width_um=30.0,
        length_nm=4000.0,
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        mobility_m2_vs=calibration.mobility_m2_vs,
        threshold_v=calibration.vth0_mag_v,
        slope_factor=calibration.slope_factor0,
        qot_slope_c_cm2_per_krad=calibration.q_ot_c_cm2_per_krad,
        qit_slope_c_cm2_per_krad=calibration.q_it_c_cm2_per_krad,
        mobility_degradation_per_krad=calibration.mobility_degradation_per_krad,
        slope_factor_per_krad=0.0,
        dose_exponent=calibration.dose_exponent,
        slope_factor_from_qit=True,
    )
    from cnt_tid.device import state_at_dose

    state = state_at_dose(device, 1000.0, 300.0)
    n_model = state.slope_factor
    n_expected = calibration.slope_factor0 + (
        calibration.q_it_c_cm2_per_krad * 1000.0**calibration.dose_exponent
    ) / device.cox_f_cm2
    assert n_model == pytest.approx(n_expected, rel=1e-12)
    assert device.cox_f_cm2 == pytest.approx(EPSILON_0_F_M * 15.0 / 10e-9 / 1e4, rel=1e-12)
