import numpy as np
import pandas as pd
import pytest

from cnt_tid.calibration import (
    apply_calibration,
    calibrate,
    calibrate_device,
    calibration_report_dict,
    calibration_summary_frame,
    dump_config_toml,
    load_measurements,
)
from cnt_tid.config import DeviceConfig, SimulationConfig, load_config
from cnt_tid.device import drain_current, state_at_dose

TRUE_N = DeviceConfig(
    polarity="n",
    mobility_m2_vs=0.02,
    threshold_v=0.25,
    slope_factor=1.3,
    qot_slope_c_cm2_per_krad=1.0e-11,
    qit_slope_c_cm2_per_krad=2.0e-12,
    mobility_degradation_per_krad=2.0e-4,
    slope_factor_per_krad=5.0e-5,
)
TRUE_P = DeviceConfig(
    polarity="p",
    mobility_m2_vs=0.018,
    threshold_v=0.28,
    slope_factor=1.35,
    qot_slope_c_cm2_per_krad=8.0e-12,
    qit_slope_c_cm2_per_krad=2.0e-12,
    mobility_degradation_per_krad=2.5e-4,
    slope_factor_per_krad=5.0e-5,
)
DOSES = (0.0, 100.0, 300.0, 1000.0)


def _synthetic_frame(seed: int = 7, noise: float = 0.02) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    vgs = np.linspace(0.0, 0.8, 41)
    rows = []
    for polarity, device in (("n", TRUE_N), ("p", TRUE_P)):
        for dose in DOSES:
            state = state_at_dose(device, dose)
            current = drain_current(state, vgs, 0.8)
            current = current * (1.0 + noise * rng.standard_normal(vgs.size))
            for vg, value in zip(vgs, current, strict=True):
                rows.append(
                    {
                        "source": "synthetic",
                        "device_id": f"{polarity}fet",
                        "polarity": polarity,
                        "dose_value": dose,
                        "dose_unit": "krad(SiO2)",
                        "bias_condition": "on",
                        "temperature_k": 300.0,
                        "vgs_v": vg,
                        "vds_v": 0.8,
                        "id_a": value,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return _synthetic_frame()


def test_load_measurements_rejects_bad_columns(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_measurements(path)


def test_load_measurements_rejects_mixed_dose_units(tmp_path) -> None:
    data = _synthetic_frame().iloc[:10].copy()
    data.loc[data.index[0], "dose_unit"] = "krad(Si)"
    path = tmp_path / "mixed.csv"
    data.to_csv(path, index=False)
    with pytest.raises(ValueError, match="dose_unit"):
        load_measurements(path)


def test_calibrate_device_recovers_dose_coefficients(frame) -> None:
    fit = calibrate_device(frame, "n", DeviceConfig(polarity="n"))
    expected_total = (
        TRUE_N.qot_slope_c_cm2_per_krad + TRUE_N.qit_slope_c_cm2_per_krad
    )
    assert fit.total_charge_slope_c_cm2_per_krad == pytest.approx(expected_total, rel=0.1)
    assert fit.zero_dose.threshold_v == pytest.approx(TRUE_N.threshold_v, abs=0.01)
    assert fit.zero_dose.mobility_m2_vs == pytest.approx(TRUE_N.mobility_m2_vs, rel=0.1)
    assert fit.mobility_degradation_per_krad == pytest.approx(
        TRUE_N.mobility_degradation_per_krad, rel=0.2
    )
    assert len(fit.holdout_residuals_v) == len(DOSES) - 1
    assert all(
        abs(item["residual_v"]) < 0.1 for item in fit.holdout_residuals_v
    )


def test_calibrate_requires_two_nonzero_doses(frame) -> None:
    reduced = frame[frame["dose_value"].isin([0.0, 50.0])]
    with pytest.raises(ValueError, match="non-zero doses"):
        calibrate_device(reduced, "n", DeviceConfig(polarity="n"))


def test_apply_calibration_updates_config_and_round_trips(frame, tmp_path) -> None:
    config = SimulationConfig(doses_krad=DOSES)
    result = calibrate(frame, config)
    fitted = apply_calibration(config, result)
    assert fitted.calibration_status == "calibrated_compact_fit"
    assert fitted.n_device.qot_slope_c_cm2_per_krad != config.n_device.qot_slope_c_cm2_per_krad
    path = tmp_path / "fitted.toml"
    path.write_text(dump_config_toml(fitted), encoding="utf-8")
    reloaded = load_config(path)
    assert reloaded.n_device.threshold_v == pytest.approx(fitted.n_device.threshold_v)
    assert reloaded.p_device.qot_slope_c_cm2_per_krad == pytest.approx(
        fitted.p_device.qot_slope_c_cm2_per_krad
    )
    assert reloaded.doses_krad == fitted.doses_krad


def test_calibration_report_and_summary_are_serializable(frame) -> None:
    result = calibrate(_synthetic_frame(), SimulationConfig(doses_krad=DOSES))
    summary = calibration_summary_frame(result)
    assert set(summary["polarity"]) == {"n", "p"}
    assert set(summary["dose_krad"]) == set(DOSES)
    report = calibration_report_dict(result)
    assert report["n_device"]["zero_dose"]["threshold_v"] > 0
