"""Metric-anchored calibration of the compact TID model.

The literature anchor reports three extracted device metrics per dose
(threshold, maximum transconductance, subthreshold swing) rather than raw
transfer curves.  This module turns those metrics into compact-model
parameters using the paper's own relations:

* Eq. (1):  dVth = (Qot + Qit) / Cox        -> total trapped charge
* Eq. (3):  SS   = ln10 * kT/q * (1 + Cit/Cox) -> interface-trap charge
* Eq. (2):  Gm   = mu * Cox * W/L * Vds     -> effective mobility

Two modelling choices are made explicit:

1. The dose response is a power law Q = k * D**p.  The linear law (p = 1)
   cannot follow the measured sub-linear threshold drift; p is fitted and
   reported instead of being assumed.
2. The effective mobility at each dose is obtained by *inverting* the compact
   model (find mu such that the modelled maximum transconductance equals the
   digitized value at Vds = 0.1 V).  That removes the analytic approximation
   from the calibration and makes the residual purely a statement about the
   dose law.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq, least_squares, minimize_scalar

from .config import DeviceConfig
from .device import BOLTZMANN_J_K, ELEMENTARY_CHARGE_C, drain_current, state_at_dose

METRIC_KEYS = ("vth_v", "gm_max_s", "ss_mv_dec")
PROBE_VDS_V = 0.1
#: Gate sweep used for the Gm probe, matching the paper's 0.5 V -> -2 V scan.
PROBE_VGS_MAX_V = 2.0
PROBE_POINTS = 801


@dataclass(frozen=True)
class MetricCalibration:
    """Compact parameters recovered from digitized device metrics."""

    vth0_mag_v: float
    ss0_mv_dec: float
    gm0_s: float
    slope_factor0: float
    mobility_m2_vs: float
    q_ot_c_cm2_per_krad: float
    q_it_c_cm2_per_krad: float
    mobility_degradation_per_krad: float
    dose_exponent: float
    cox_f_cm2: float
    total_charge_slope_c_cm2_per_krad: float
    residuals: pd.DataFrame = field(repr=False)
    holdout: pd.DataFrame = field(repr=False)
    diagnostics: dict = field(default_factory=dict, repr=False)

    def summary(self) -> dict:
        return {
            key: getattr(self, key)
            for key in (
                "vth0_mag_v",
                "ss0_mv_dec",
                "gm0_s",
                "slope_factor0",
                "mobility_m2_vs",
                "q_ot_c_cm2_per_krad",
                "q_it_c_cm2_per_krad",
                "mobility_degradation_per_krad",
                "dose_exponent",
                "cox_f_cm2",
                "total_charge_slope_c_cm2_per_krad",
            )
        }


def load_digitized_metrics(path: str | Path) -> pd.DataFrame:
    """Load the long-format digitized Figure 3 CSV and validate its shape."""

    frame = pd.read_csv(path)
    required = ("dose_value", "dose_unit", "metric", "value", "polarity")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"digitized metrics missing columns: {missing}")
    if frame["dose_unit"].nunique() != 1:
        raise ValueError("digitized metrics must use one dose unit")
    if set(frame["metric"].unique()) != set(METRIC_KEYS):
        raise ValueError(f"digitized metrics must contain exactly {METRIC_KEYS}")
    counts = frame.groupby(["metric", "dose_value"]).size().unstack(fill_value=0)
    if (counts == 0).any().any():
        missing_points = counts.columns[(counts == 0).any()].tolist()
        raise ValueError(f"digitized metrics are missing doses: {missing_points}")
    values = frame[["dose_value", "value"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (frame["dose_value"] < 0).any():
        raise ValueError("digitized metrics need finite, non-negative doses")
    if (frame["value"].abs() <= 0).any():
        raise ValueError("digitized metrics contain a zero-valued point")
    return frame.sort_values(["metric", "dose_value"]).reset_index(drop=True)


def wide_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Pivot the long table into one row per dose with value/error columns."""

    wide = frame.pivot_table(
        index="dose_value", columns="metric", values="value", aggfunc="first"
    ).sort_index()
    for column in ("err_minus", "err_plus"):
        if column not in frame.columns:
            continue
        extra = frame.pivot_table(
            index="dose_value", columns="metric", values=column, aggfunc="first"
        )
        extra.columns = [f"{name}_{column}" for name in extra.columns]
        wide = wide.join(extra)
    wide.index.name = "dose_krad"
    if wide.isna().any().any():
        raise ValueError("digitized metrics contain gaps after pivoting")
    return wide


def _fit_power_law(doses: np.ndarray, values: np.ndarray) -> tuple[float, float]:
    """Fit values = k * dose**p with p constrained to a physical range."""

    if doses.size < 2:
        raise ValueError("power-law fit needs at least two non-zero doses")

    def residual(params: np.ndarray) -> np.ndarray:
        k, p = params
        return k * doses**p - values

    fit = least_squares(
        residual,
        x0=np.array([values[-1] / doses[-1] ** 0.6, 0.6]),
        bounds=([0.0, 0.15], [np.inf, 2.0]),
        method="trf",
    )
    return float(fit.x[0]), float(fit.x[1])


def _probe_config(base: DeviceConfig, mobility: float) -> DeviceConfig:
    """Zero-dose probe: mobility is the only free variable."""

    return DeviceConfig(
        polarity=base.polarity,
        width_um=base.width_um,
        length_nm=base.length_nm,
        oxide_thickness_nm=base.oxide_thickness_nm,
        oxide_relative_permittivity=base.oxide_relative_permittivity,
        mobility_m2_vs=mobility,
        threshold_v=base.threshold_v,
        slope_factor=base.slope_factor,
        channel_length_modulation=base.channel_length_modulation,
        qot_slope_c_cm2_per_krad=0.0,
        qit_slope_c_cm2_per_krad=0.0,
        mobility_degradation_per_krad=0.0,
        slope_factor_per_krad=0.0,
        dose_exponent=1.0,
        slope_factor_from_qit=False,
    )


def model_max_gm(config: DeviceConfig, dose_krad: float, temperature_k: float) -> float:
    """Modelled maximum transconductance at the probe drain bias."""

    state = state_at_dose(config, dose_krad, temperature_k)
    vgs = np.linspace(0.0, PROBE_VGS_MAX_V, PROBE_POINTS)
    current = drain_current(state, vgs, PROBE_VDS_V)
    return float(np.max(np.gradient(current, vgs)))


def mobility_from_gm(
    base: DeviceConfig,
    dose_krad: float,
    target_gm_s: float,
    temperature_k: float,
) -> float:
    """Invert the compact model so its maximum Gm matches the digitized value."""

    def objective(mobility: float) -> float:
        return model_max_gm(_probe_config(base, mobility), dose_krad, temperature_k) - target_gm_s

    low, high = 1e-7, 0.5
    if objective(low) > 0 or objective(high) < 0:
        raise ValueError(
            f"mobility inversion failed at {dose_krad:g} krad: "
            "target Gm is outside the reachable range"
        )
    return float(brentq(objective, low, high, xtol=1e-12, maxiter=200))


def fit_mobility_degradation(
    doses: np.ndarray,
    mobility0: float,
    q_total_slope: float,
    q_it_slope: float,
    exponent: float,
    cox_f_cm2: float,
    vth0_mag_v: float,
    slope_factor0: float,
    gm_s: np.ndarray,
    probe: dict,
    temperature_k: float,
) -> float:
    """Fit alpha in mu = mu0 / (1 + alpha D) against the modelled Gm.

    Fitting alpha through the model (rather than through a linear regression of
    1/mu) keeps the threshold and swing drift, which also move the maximum
    transconductance, inside the fit instead of pretending they are fixed.
    """

    scale = doses**exponent
    vth_fit = vth0_mag_v + q_total_slope * scale / cox_f_cm2
    slope_fit = slope_factor0 + q_it_slope * scale / cox_f_cm2

    def objective(alpha: float) -> float:
        mobility = mobility0 / (1.0 + alpha * doses)
        gm_model = np.array(
            [
                _probe_gm(mu, vth, slope, probe, temperature_k)
                for mu, vth, slope in zip(mobility, vth_fit, slope_fit, strict=True)
            ]
        )
        return float(np.sum(((gm_model - gm_s) / gm_s) ** 2))

    result = minimize_scalar(
        objective, bounds=(0.0, 1e-2), method="bounded", options={"xatol": 1e-12}
    )
    return float(result.x)


def calibrate_from_metrics(
    metrics: pd.DataFrame,
    *,
    oxide_thickness_nm: float,
    oxide_relative_permittivity: float,
    width_um: float,
    length_nm: float,
    temperature_k: float,
) -> MetricCalibration:
    """Fit the dose laws from digitized threshold, Gm and swing metrics."""

    wide = wide_metrics(metrics)
    doses = wide.index.to_numpy(dtype=float)
    if doses.size < 3:
        raise ValueError("at least three doses are required (zero + two non-zero)")
    if doses[0] != 0.0:
        raise ValueError("a zero-dose reference point is required")

    thermal_v = BOLTZMANN_J_K * temperature_k / ELEMENTARY_CHARGE_C
    ideal_ss_mv = 1000.0 * np.log(10.0) * thermal_v

    vth_mag = np.abs(wide["vth_v"].to_numpy(dtype=float))
    ss_mv = wide["ss_mv_dec"].to_numpy(dtype=float)
    gm_s = wide["gm_max_s"].to_numpy(dtype=float)

    slope_factor = ss_mv / ideal_ss_mv
    base = DeviceConfig(
        polarity="p",
        width_um=width_um,
        length_nm=length_nm,
        oxide_thickness_nm=oxide_thickness_nm,
        oxide_relative_permittivity=oxide_relative_permittivity,
        mobility_m2_vs=0.01,
        threshold_v=float(vth_mag[0]),
        slope_factor=float(slope_factor[0]),
    )
    cox_f_cm2 = base.cox_f_cm2
    probe = {
        "width_um": width_um,
        "length_nm": length_nm,
        "oxide_thickness_nm": oxide_thickness_nm,
        "oxide_relative_permittivity": oxide_relative_permittivity,
    }
    ideal_ss_mv = 1000.0 * np.log(10.0) * thermal_v

    # Eq. (2): invert the compact model at every dose instead of trusting the
    # closed-form strong-inversion expression.
    mobility = np.array(
        [mobility_from_gm(base, dose, gm, temperature_k) for dose, gm in zip(doses, gm_s, strict=True)]
    )

    nonzero = doses > 0.0
    shift_v = vth_mag - vth_mag[0]
    k_shift, exponent = _fit_power_law(doses[nonzero], shift_v[nonzero])
    total_charge_slope = k_shift * cox_f_cm2

    # Eq. (3): the swing degradation is the interface-charge channel.
    q_it_values = cox_f_cm2 * (slope_factor - slope_factor[0])
    design = doses[nonzero] ** exponent
    q_it_slope = float(np.sum(q_it_values[nonzero] * design) / np.sum(design**2))
    q_ot_slope = float(total_charge_slope - q_it_slope)
    if q_it_slope <= 0:
        raise ValueError("fitted interface-charge slope is not positive; check the metrics")
    if q_ot_slope <= 0:
        raise ValueError("interface charge exceeds total charge; the split is not physical")

    mobility_degradation = fit_mobility_degradation(
        doses,
        mobility[0],
        total_charge_slope,
        q_it_slope,
        exponent,
        cox_f_cm2,
        float(vth_mag[0]),
        float(slope_factor[0]),
        gm_s,
        probe,
        temperature_k,
    )

    model = _predict(
        doses,
        vth_mag[0],
        mobility[0],
        slope_factor[0],
        q_ot_slope,
        q_it_slope,
        mobility_degradation,
        exponent,
        cox_f_cm2,
        probe,
        temperature_k,
    )
    def error_column(metric: str, suffix: str) -> np.ndarray:
        name = f"{metric}_{suffix}"
        return wide[name].to_numpy(dtype=float) if name in wide.columns else np.zeros_like(doses)

    residuals = pd.DataFrame(
        {
            "dose_krad": doses,
            "vth_v_data": vth_mag,
            "vth_v_model": model["vth_mag_v"],
            "vth_residual_mv": 1000.0 * (vth_mag - model["vth_mag_v"]),
            "vth_err_minus_v": error_column("vth_v", "err_minus"),
            "vth_err_plus_v": error_column("vth_v", "err_plus"),
            "gm_err_minus_s": error_column("gm_max_s", "err_minus"),
            "gm_err_plus_s": error_column("gm_max_s", "err_plus"),
            "ss_err_minus_mv": error_column("ss_mv_dec", "err_minus"),
            "ss_err_plus_mv": error_column("ss_mv_dec", "err_plus"),
            "gm_s_data": gm_s,
            "gm_s_model": model["gm_s"],
            "gm_residual_rel": (gm_s - model["gm_s"]) / gm_s,
            "ss_mv_data": ss_mv,
            "ss_mv_model": ideal_ss_mv * model["slope_factor"],
            "ss_residual_mv": ss_mv - ideal_ss_mv * model["slope_factor"],
        }
    )

    holdout_rows = []
    for held in doses[nonzero]:
        train = nonzero & (doses != held)
        k_shift_i, exponent_i = _fit_power_law(doses[train], shift_v[train])
        total_i = k_shift_i * cox_f_cm2
        design_i = doses[train] ** exponent_i
        q_it_i = float(np.sum(q_it_values[train] * design_i) / np.sum(design_i**2))
        q_ot_i = float(total_i - q_it_i)
        alpha_i = fit_mobility_degradation(
            doses[train],
            mobility[0],
            total_i,
            q_it_i,
            exponent_i,
            cox_f_cm2,
            float(vth_mag[0]),
            float(slope_factor[0]),
            gm_s[train],
            probe,
            temperature_k,
        )
        prediction = _predict(
            np.array([held]),
            vth_mag[0],
            mobility[0],
            slope_factor[0],
            q_ot_i,
            q_it_i,
            alpha_i,
            exponent_i,
            cox_f_cm2,
            probe,
            temperature_k,
        )
        actual_ss = float(ss_mv[doses == held][0])
        holdout_rows.append(
            {
                "held_out_dose_krad": held,
                "vth_v_actual": float(vth_mag[doses == held][0]),
                "vth_v_predicted": float(prediction["vth_mag_v"][0]),
                "vth_residual_mv": float(
                    1000.0 * (vth_mag[doses == held][0] - prediction["vth_mag_v"][0])
                ),
                "gm_s_actual": float(gm_s[doses == held][0]),
                "gm_s_predicted": float(prediction["gm_s"][0]),
                "gm_residual_rel": float(
                    (gm_s[doses == held][0] - prediction["gm_s"][0]) / gm_s[doses == held][0]
                ),
                "ss_mv_actual": actual_ss,
                "ss_mv_predicted": float(ideal_ss_mv * prediction["slope_factor"][0]),
                "ss_residual_mv": float(actual_ss - ideal_ss_mv * prediction["slope_factor"][0]),
            }
        )

    diagnostics = {
        "width_over_length": (width_um * 1e-6) / (length_nm * 1e-9),
        "probe_vds_v": PROBE_VDS_V,
        "ideal_ss_mv_per_dec": float(ideal_ss_mv),
        "zero_dose_q_it_c_cm2": 0.0,
        "max_abs_vth_residual_mv": float(residuals["vth_residual_mv"].abs().max()),
        "max_abs_vth_residual_v": float(0.001 * residuals["vth_residual_mv"].abs().max()),
        "max_abs_gm_residual_rel": float(residuals["gm_residual_rel"].abs().max()),
        "max_abs_ss_residual_mv": float(residuals["ss_residual_mv"].abs().max()),
        "q_it_at_max_dose_c_cm2": float(q_it_slope * doses.max() ** exponent),
        "q_ot_at_max_dose_c_cm2": float(q_ot_slope * doses.max() ** exponent),
    }

    return MetricCalibration(
        vth0_mag_v=float(vth_mag[0]),
        ss0_mv_dec=float(ss_mv[0]),
        gm0_s=float(gm_s[0]),
        slope_factor0=float(slope_factor[0]),
        mobility_m2_vs=float(mobility[0]),
        q_ot_c_cm2_per_krad=q_ot_slope,
        q_it_c_cm2_per_krad=q_it_slope,
        mobility_degradation_per_krad=mobility_degradation,
        dose_exponent=float(exponent),
        cox_f_cm2=float(cox_f_cm2),
        total_charge_slope_c_cm2_per_krad=float(total_charge_slope),
        residuals=residuals,
        holdout=pd.DataFrame(holdout_rows),
        diagnostics=diagnostics,
    )


def _probe_gm(
    mobility: float,
    threshold_v: float,
    slope_factor: float,
    probe: dict,
    temperature_k: float,
) -> float:
    """Model maximum Gm for one set of compact parameters at the probe bias."""

    config = DeviceConfig(
        polarity="p",
        width_um=probe["width_um"],
        length_nm=probe["length_nm"],
        oxide_thickness_nm=probe["oxide_thickness_nm"],
        oxide_relative_permittivity=probe["oxide_relative_permittivity"],
        mobility_m2_vs=mobility,
        threshold_v=threshold_v,
        slope_factor=slope_factor,
        qot_slope_c_cm2_per_krad=0.0,
        qit_slope_c_cm2_per_krad=0.0,
        mobility_degradation_per_krad=0.0,
        slope_factor_per_krad=0.0,
        slope_factor_from_qit=False,
    )
    return model_max_gm(config, 0.0, temperature_k)


def _predict(
    doses: np.ndarray,
    vth0_mag_v: float,
    mobility0: float,
    slope_factor0: float,
    q_ot_slope: float,
    q_it_slope: float,
    mobility_degradation: float,
    exponent: float,
    cox_f_cm2: float,
    probe: dict,
    temperature_k: float,
) -> dict:
    """Prediction of the calibrated laws, including the modelled Gm.

    Gm is evaluated on the compact model itself rather than from the
    strong-inversion closed form, because the threshold and swing also move with
    dose and both feed back into the maximum transconductance.
    """

    scale = doses**exponent
    q_total = (q_ot_slope + q_it_slope) * scale
    vth_mag = vth0_mag_v + q_total / cox_f_cm2
    slope_factor = slope_factor0 + (q_it_slope * scale) / cox_f_cm2
    mobility = mobility0 / (1.0 + mobility_degradation * doses)
    gm = np.array(
        [
            _probe_gm(mu, vth, slope, probe, temperature_k)
            for mu, vth, slope in zip(mobility, vth_mag, slope_factor, strict=True)
        ]
    )
    return {
        "vth_mag_v": vth_mag,
        "slope_factor": slope_factor,
        "mobility_m2_vs": mobility,
        "gm_s": gm,
    }


def calibration_payload(calibration: MetricCalibration) -> dict:
    """JSON-safe description of a calibration result."""

    payload = {"parameters": calibration.summary(), "diagnostics": calibration.diagnostics}
    payload["residuals"] = calibration.residuals.to_dict(orient="records")
    payload["holdout"] = calibration.holdout.to_dict(orient="records")
    return payload


