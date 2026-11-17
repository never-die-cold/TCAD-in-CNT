"""Calibrate compact TID dose coefficients from measured or TCAD transfer curves.

Input data follows ``data/calibration_template.csv``: positive terminal
magnitudes, one dose unit per file, and a zero-dose reference curve. The
calibrator fits the compact model itself to each measured transfer curve,
then fits linear dose laws across dose points, mirroring the mapping in
``state_at_dose``. At least two distinct non-zero doses are required.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .config import DeviceConfig, SimulationConfig
from .device import drain_current, state_at_dose

REQUIRED_COLUMNS = (
    "source",
    "device_id",
    "polarity",
    "dose_value",
    "dose_unit",
    "bias_condition",
    "temperature_k",
    "vgs_v",
    "vds_v",
    "id_a",
)


@dataclass(frozen=True)
class TransferCurveFit:
    """Compact parameters recovered from a single measured transfer curve."""

    dose_krad: float
    threshold_v: float
    mobility_m2_vs: float
    slope_factor: float
    rmse_log10: float


@dataclass(frozen=True)
class DeviceCalibration:
    """Dose coefficients for one polarity, fitted from multi-dose curves."""

    polarity: str
    zero_dose: TransferCurveFit
    curve_fits: tuple[TransferCurveFit, ...]
    total_charge_slope_c_cm2_per_krad: float
    qot_slope_c_cm2_per_krad: float
    qit_slope_c_cm2_per_krad: float
    mobility_degradation_per_krad: float
    slope_factor_per_krad: float
    holdout_residuals_v: tuple[dict[str, float], ...]


@dataclass(frozen=True)
class CalibrationResult:
    n_device: DeviceCalibration
    p_device: DeviceCalibration


def load_measurements(path: str | Path) -> pd.DataFrame:
    """Load and validate a calibration CSV following the template conventions."""

    frame = pd.read_csv(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Calibration data missing columns: {missing}")
    if frame["polarity"].isin(["n", "p"]).sum() != len(frame):
        raise ValueError("polarity must be 'n' or 'p' in every row")
    if frame["dose_unit"].nunique() != 1:
        raise ValueError("dose_unit must be consistent within one calibration file")
    numeric = frame[["dose_value", "vgs_v", "vds_v", "id_a", "temperature_k"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("calibration data contains NaN or infinite values")
    if (frame["dose_value"] < 0).any():
        raise ValueError("dose_value must be non-negative")
    if (frame["vgs_v"] < 0).any() or (frame["vds_v"] < 0).any():
        raise ValueError("vgs_v and vds_v must use positive terminal magnitudes")
    if (frame["id_a"] <= 0).any():
        raise ValueError("id_a must be positive; drop non-conducting points")
    return frame


def _fit_transfer_curve(
    vgs_v: np.ndarray,
    id_a: np.ndarray,
    vds_v: float,
    base: DeviceConfig,
    dose_krad: float,
    temperature_k: float,
) -> TransferCurveFit:
    """Fit (threshold, mobility, slope_factor) of the compact model to one curve."""

    log_measured = np.log10(id_a)
    scale = np.array([max(base.threshold_v, 1e-3), base.mobility_m2_vs, base.slope_factor])

    def residual(params: np.ndarray) -> np.ndarray:
        threshold_v, mobility, slope = params * scale
        trial = DeviceConfig(
            polarity=base.polarity,
            width_um=base.width_um,
            length_nm=base.length_nm,
            oxide_thickness_nm=base.oxide_thickness_nm,
            oxide_relative_permittivity=base.oxide_relative_permittivity,
            mobility_m2_vs=mobility,
            threshold_v=threshold_v,
            slope_factor=slope,
            channel_length_modulation=base.channel_length_modulation,
        )
        # Zero dose here: fitted parameters ARE the degraded values at this
        # dose, so the dose law must not be applied a second time.
        state = state_at_dose(trial, 0.0, temperature_k)
        modeled = drain_current(state, vgs_v, vds_v)
        return np.log10(np.maximum(modeled, 1e-30)) - log_measured

    lower = np.array([0.01, 0.02, 1.0])
    upper = np.array([10.0, 50.0, 6.0])
    initial = np.array([1.0, 1.0, 1.0])
    fit = least_squares(
        residual, initial, bounds=(lower, upper), method="trf", x_scale="jac"
    )
    rmse = float(np.sqrt(np.mean(fit.fun**2)))
    threshold_v, mobility, slope = fit.x * scale
    return TransferCurveFit(
        dose_krad=float(dose_krad),
        threshold_v=float(threshold_v),
        mobility_m2_vs=float(mobility),
        slope_factor=float(slope),
        rmse_log10=rmse,
    )


def _linear_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Return (slope, intercept) of a least-squares line through all points."""

    if x.size < 2:
        raise ValueError("at least two dose points are required for a linear fit")
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def _fit_device_curves(
    frame: pd.DataFrame, polarity: str, base: DeviceConfig, temperature_k: float
) -> tuple[TransferCurveFit, ...]:
    subset = frame[frame["polarity"] == polarity]
    if subset.empty:
        raise ValueError(f"no calibration rows for polarity '{polarity}'")
    fits: list[TransferCurveFit] = []
    for (device_id, dose), group in subset.groupby(["device_id", "dose_value"]):
        if len(group) < 10:
            raise ValueError(
                f"curve {device_id}@{dose:g} krad has {len(group)} points; need >= 10"
            )
        vds_values = group["vds_v"].unique()
        if vds_values.size != 1:
            raise ValueError(
                f"curve {device_id}@{dose:g} krad mixes {vds_values.size} vds_v values"
            )
        fits.append(
            _fit_transfer_curve(
                group.sort_values("vgs_v")["vgs_v"].to_numpy(dtype=float),
                group.sort_values("vgs_v")["id_a"].to_numpy(dtype=float),
                float(vds_values[0]),
                base,
                float(dose),
                temperature_k,
            )
        )
    return tuple(sorted(fits, key=lambda fit: fit.dose_krad))


def calibrate_device(
    frame: pd.DataFrame, polarity: str, base: DeviceConfig, temperature_k: float = 300.0
) -> DeviceCalibration:
    """Fit dose coefficients for one polarity from validated measurements.

    The total trapped-charge slope comes from the linear threshold shift.
    The interface-trap share is estimated from subthreshold-swing degradation
    via ``Qit ~ Δn · Cox``; the remainder is assigned to oxide traps. This
    split is a documented heuristic, not a trap-spectroscopy result.
    """

    fits = _fit_device_curves(frame, polarity, base, temperature_k)
    doses = np.array([fit.dose_krad for fit in fits])
    if not np.any(doses == 0.0):
        raise ValueError("a zero-dose reference curve is required")
    if np.unique(doses[doses > 0]).size < 2:
        raise ValueError("at least two distinct non-zero doses are required")
    zero_fit = next(fit for fit in fits if fit.dose_krad == 0.0)

    shift_v = np.array([fit.threshold_v for fit in fits]) - zero_fit.threshold_v
    signed_slope_v_per_krad, _ = _linear_slope(doses, shift_v)
    cox = base.cox_f_cm2
    # nFET thresholds decrease with positive trapped charge, pFET magnitudes
    # increase; the dose law only stores the positive charge slope.
    total_charge_slope = abs(signed_slope_v_per_krad) * cox

    slope_per_krad, _ = _linear_slope(
        doses, np.array([fit.slope_factor for fit in fits])
    )
    # TID does not improve the subthreshold swing; clamp noise-level negative
    # fits instead of emitting a non-physical coefficient.
    slope_per_krad = max(slope_per_krad, 0.0)
    # Interface-trap share is estimated from swing degradation and capped at
    # the total charge so the split never exceeds the observed threshold shift.
    qit_slope = min(slope_per_krad * cox, total_charge_slope)
    qot_slope = total_charge_slope - qit_slope

    inverse_mu = 1.0 / np.array([fit.mobility_m2_vs for fit in fits])
    mob_a, mob_b = _linear_slope(doses, inverse_mu)
    if mob_a <= 0 or mob_b <= 0:
        raise ValueError("mobility dose law is non-physical; check data quality")
    mobility_degradation = mob_a / mob_b

    residuals: list[dict[str, float]] = []
    positive = doses[doses > 0]
    if positive.size >= 2:
        for held in positive:
            train = doses != held
            slope, intercept = np.polyfit(doses[train], shift_v[train], 1)
            predicted = slope * held + intercept
            actual = float(shift_v[doses == held][0])
            residuals.append(
                {
                    "dose_krad": float(held),
                    "actual_shift_v": actual,
                    "predicted_shift_v": float(predicted),
                    "residual_v": float(actual - predicted),
                }
            )

    return DeviceCalibration(
        polarity=polarity,
        zero_dose=zero_fit,
        curve_fits=fits,
        total_charge_slope_c_cm2_per_krad=float(total_charge_slope),
        qot_slope_c_cm2_per_krad=float(qot_slope),
        qit_slope_c_cm2_per_krad=float(qit_slope),
        mobility_degradation_per_krad=float(mobility_degradation),
        slope_factor_per_krad=float(slope_per_krad),
        holdout_residuals_v=tuple(residuals),
    )


def calibrate(
    frame: pd.DataFrame, config: SimulationConfig
) -> CalibrationResult:
    """Calibrate both polarities against a baseline simulation configuration."""

    return CalibrationResult(
        n_device=calibrate_device(frame, "n", config.n_device, config.temperature_k),
        p_device=calibrate_device(frame, "p", config.p_device, config.temperature_k),
    )


def _apply_device_calibration(
    base: DeviceConfig, fit: DeviceCalibration
) -> DeviceConfig:
    return DeviceConfig(
        polarity=base.polarity,
        width_um=base.width_um,
        length_nm=base.length_nm,
        oxide_thickness_nm=base.oxide_thickness_nm,
        oxide_relative_permittivity=base.oxide_relative_permittivity,
        mobility_m2_vs=fit.zero_dose.mobility_m2_vs,
        threshold_v=fit.zero_dose.threshold_v,
        slope_factor=fit.zero_dose.slope_factor,
        channel_length_modulation=base.channel_length_modulation,
        qot_slope_c_cm2_per_krad=fit.qot_slope_c_cm2_per_krad,
        qit_slope_c_cm2_per_krad=fit.qit_slope_c_cm2_per_krad,
        mobility_degradation_per_krad=fit.mobility_degradation_per_krad,
        slope_factor_per_krad=fit.slope_factor_per_krad,
    )


def apply_calibration(
    config: SimulationConfig, result: CalibrationResult
) -> SimulationConfig:
    """Return a copy of ``config`` with fitted devices and updated status."""

    return SimulationConfig(
        name=f"{config.name}_calibrated",
        vdd_v=config.vdd_v,
        temperature_k=config.temperature_k,
        dose_unit=config.dose_unit,
        doses_krad=config.doses_krad,
        transfer_points=config.transfer_points,
        inverter_points=config.inverter_points,
        calibration_status="calibrated_compact_fit",
        n_device=_apply_device_calibration(config.n_device, result.n_device),
        p_device=_apply_device_calibration(config.p_device, result.p_device),
    )


def _toml_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if not isinstance(value, float):
        return str(value)
    # 17 significant digits round-trip exactly through TOML, and an explicit
    # decimal point keeps TOML from parsing the value back as an integer, so
    # the frozen config reproduces the same config_sha256 as the in-memory one.
    text = f"{value:.17g}"
    return text if ("." in text or "e" in text or "n" in text) else text + ".0"


def dump_config_toml(config: SimulationConfig) -> str:
    """Serialize a SimulationConfig to TOML text (dataclass-aware writer)."""

    lines = ["# Generated by cnt-tid calibrate; review before publishing."]
    plain: dict[str, object] = {}
    devices: dict[str, dict[str, object]] = {}
    for key, value in asdict(config).items():
        if isinstance(value, dict):
            devices[key] = value
        else:
            plain[key] = value
    for key, value in plain.items():
        lines.append(f"{key} = {_toml_value(value)}")
    for section, values in devices.items():
        lines.append("")
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def calibration_summary_frame(result: CalibrationResult) -> pd.DataFrame:
    rows = []
    for fit in (result.n_device, result.p_device):
        for curve in fit.curve_fits:
            rows.append(
                {
                    "polarity": fit.polarity,
                    "dose_krad": curve.dose_krad,
                    "threshold_v": curve.threshold_v,
                    "mobility_m2_vs": curve.mobility_m2_vs,
                    "slope_factor": curve.slope_factor,
                    "rmse_log10": curve.rmse_log10,
                }
            )
    return pd.DataFrame(rows)


def calibration_report_dict(result: CalibrationResult) -> dict[str, object]:
    def device_dict(fit: DeviceCalibration) -> dict[str, object]:
        return {
            **{k: v for k, v in asdict(fit).items() if k != "curve_fits"},
            "curve_fits": [asdict(curve) for curve in fit.curve_fits],
        }

    return {
        "schema_version": "1.0",
        "model_type": "compact_equivalent_tid_calibration",
        "polarity_split_heuristic": "Qit from swing degradation (Qit ~ dn/dD * Cox); "
        "remainder assigned to Qot.",
        "n_device": device_dict(result.n_device),
        "p_device": device_dict(result.p_device),
    }
