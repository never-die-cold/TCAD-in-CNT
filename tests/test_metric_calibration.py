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
    # Two-stage swing channel: generated density and anneal are both fitted,
    # every swing residual stays inside ~1.3 sigma of the digitized bars, and
    # the modelled swing dips below its zero-dose value (the 200 krad valley).
    assert calibration.qit_density_slope_c_cm2_per_krad > 0
    assert calibration.qit_anneal_c_cm2 > 0
    assert 10.0 <= calibration.qit_anneal_dose_krad <= 20000.0
    assert calibration.residuals["ss_residual_mv"].abs().max() < 25.0
    valley = calibration.residuals.loc[calibration.residuals["ss_mv_model"].idxmin()]
    assert valley["ss_mv_model"] < calibration.ss0_mv_dec
    # The modelled dip is broader than the measured one: its minimum lands
    # one grid point past the measured valley, but inside the same window.
    assert valley["dose_krad"] in (200.0, 500.0)


def test_calibration_recovers_a_synthetic_two_stage_swing():
    """A swing that dips below its zero-dose value is recovered by the fit."""

    vth0, ss0, gm0 = 0.53, 208.0, 1.07e-5
    q_total, k_density, q_anneal, anneal_dose, exponent = 3.0e-8, 4.0e-8, 2.5e-6, 250.0, 0.6
    cox = 1.33e-6
    rows = []
    for dose in (0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0):
        scale = dose**exponent
        anneal = q_anneal * -np.expm1(-dose / anneal_dose)
        vth = vth0 + q_total * scale / cox
        ss = ss0 + ((k_density * scale - anneal) / cox) * IDEAL_SS_MV
        gm = gm0 / (1.0 + 5.5e-4 * dose)
        for metric, value, unit in (
            ("vth_v", -vth, "V"),
            ("gm_max_s", gm, "S"),
            ("ss_mv_dec", ss, "mV/dec"),
        ):
            rows.append(
                {
                    "source": "synthetic",
                    "device_id": "synth_two_stage",
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
    calibration = calibrate_from_metrics(
        pd.DataFrame(rows),
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        width_um=30.0,
        length_nm=4000.0,
        temperature_k=300.0,
    )
    assert calibration.dose_exponent == pytest.approx(exponent, abs=0.02)
    assert calibration.qit_density_slope_c_cm2_per_krad == pytest.approx(k_density, rel=0.1)
    assert calibration.qit_anneal_c_cm2 == pytest.approx(q_anneal, rel=0.15)
    assert calibration.qit_anneal_dose_krad == pytest.approx(anneal_dose, rel=0.5)
    assert calibration.residuals["ss_residual_mv"].abs().max() < 5.0
    # The anneal term lives only in the swing channel: the threshold fit is
    # exactly the power law it would have been without the dip.
    assert calibration.residuals["vth_residual_mv"].abs().max() < 2.0


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


def test_anneal_channel_is_absent_from_the_threshold():
    """The two-stage anneal bends the swing but must not move the threshold."""

    from dataclasses import replace

    from cnt_tid.device import state_at_dose

    config = DeviceConfig(
        polarity="p",
        width_um=30.0,
        length_nm=4000.0,
        oxide_thickness_nm=10.0,
        oxide_relative_permittivity=15.0,
        mobility_m2_vs=2.1e-3,
        threshold_v=0.53,
        slope_factor=3.49,
        qot_slope_c_cm2_per_krad=2.2e-8,
        qit_slope_c_cm2_per_krad=8.9e-9,
        dose_exponent=0.48,
        slope_factor_from_qit=True,
        qit_density_slope_c_cm2_per_krad=3.9e-8,
        qit_anneal_c_cm2=1.1e-6,
        qit_anneal_dose_krad=239.0,
    )
    dose = 200.0
    state = state_at_dose(config, dose)
    no_anneal = state_at_dose(replace(config, qit_anneal_c_cm2=0.0), dose)

    # The threshold sees only the charged-trap power law; the anneal term
    # must not leak into it.
    assert state.threshold_v == pytest.approx(no_anneal.threshold_v, rel=1e-12)
    assert state.qit_c_cm2 == pytest.approx(no_anneal.qit_c_cm2, rel=1e-12)

    # The swing sees the anneal: it dips below the no-anneal swing, and at
    # zero dose both reduce to the baseline slope factor.
    anneal = config.qit_anneal_c_cm2 * -np.expm1(-dose / config.qit_anneal_dose_krad)
    assert state.slope_factor == pytest.approx(
        no_anneal.slope_factor - anneal / config.cox_f_cm2, rel=1e-12
    )
    assert state.slope_factor < no_anneal.slope_factor
    zero = state_at_dose(config, 0.0)
    assert zero.slope_factor == pytest.approx(config.slope_factor, rel=1e-12)
    assert zero.qit_density_net_c_cm2 == 0.0

    # Legacy configs without density fields keep the single-power-law swing.
    legacy = DeviceConfig(
        polarity="p",
        qit_slope_c_cm2_per_krad=8.9e-9,
        dose_exponent=0.48,
        slope_factor_from_qit=True,
    )
    legacy_state = state_at_dose(legacy, 1000.0)
    assert legacy_state.slope_factor == pytest.approx(
        legacy.slope_factor
        + legacy.qit_slope_c_cm2_per_krad * 1000.0**0.48 / legacy.cox_f_cm2,
        rel=1e-12,
    )
    assert legacy_state.qit_density_net_c_cm2 == pytest.approx(
        legacy.qit_slope_c_cm2_per_krad * 1000.0**0.48, rel=1e-12
    )
