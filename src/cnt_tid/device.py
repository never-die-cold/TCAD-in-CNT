"""Dose-degraded, EKV-inspired compact CNTFET current model.

This is a workflow baseline, not a replacement for calibrated quantum TCAD.
All voltages and currents are positive terminal magnitudes for both polarities.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .config import DeviceConfig

BOLTZMANN_J_K = 1.380649e-23
ELEMENTARY_CHARGE_C = 1.602176634e-19


@dataclass(frozen=True)
class DeviceState:
    config: DeviceConfig
    dose_krad: float
    temperature_k: float
    threshold_v: float
    mobility_m2_vs: float
    slope_factor: float
    qot_c_cm2: float
    qit_c_cm2: float

    @property
    def delta_threshold_v(self) -> float:
        baseline = self.config.threshold_v
        return self.threshold_v - baseline


def state_at_dose(
    config: DeviceConfig, dose_krad: float, temperature_k: float = 300.0
) -> DeviceState:
    """Map absorbed dose to trapped charge and compact parameter degradation.

    Positive trapped charge shifts nFET threshold down and pFET threshold
    magnitude up. The linear dose law is deliberately simple and uncalibrated.
    """

    if dose_krad < 0 or temperature_k <= 0:
        raise ValueError("dose_krad must be non-negative and temperature_k positive")
    # Power-law build-up: Q = k * D**p.  p = 1 reproduces the original linear
    # law; p < 1 describes the sub-linear trap build-up seen in the literature
    # anchors (see docs/p0-report.md).
    dose_scale = float(dose_krad) ** config.dose_exponent
    qot = config.qot_slope_c_cm2_per_krad * dose_scale
    qit = config.qit_slope_c_cm2_per_krad * dose_scale
    charge_shift = (qot + qit) / config.cox_f_cm2
    threshold = config.threshold_v + (-charge_shift if config.polarity == "n" else charge_shift)
    mobility = config.mobility_m2_vs / (
        1.0 + config.mobility_degradation_per_krad * dose_krad
    )
    if config.slope_factor_from_qit:
        # Eq. (3) of the literature anchor: SS = ln10 * kT/q * (1 + Cit/Cox),
        # so a swing-equivalent interface charge qit = Cox * (n - n0) is the
        # only driver of the slope factor.
        slope_factor = config.slope_factor + qit / config.cox_f_cm2
    else:
        slope_factor = config.slope_factor + config.slope_factor_per_krad * dose_krad
    return DeviceState(
        config=config,
        dose_krad=float(dose_krad),
        temperature_k=float(temperature_k),
        threshold_v=float(threshold),
        mobility_m2_vs=float(mobility),
        slope_factor=float(slope_factor),
        qot_c_cm2=float(qot),
        qit_c_cm2=float(qit),
    )


def _softplus(value: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.logaddexp(0.0, value)


def drain_current(
    state: DeviceState, vgs_v: ArrayLike, vds_v: ArrayLike
) -> NDArray[np.float64]:
    """Return drain current in amperes using a smooth compact expression.

    The expression smoothly connects exponential subthreshold behavior to a
    saturated above-threshold response. It contains no Schottky-contact,
    quantum-capacitance, direct-source-drain tunneling or trap-kinetics model.
    """

    vgs, vds = np.broadcast_arrays(
        np.asarray(vgs_v, dtype=float), np.asarray(vds_v, dtype=float)
    )
    if np.any(vds < 0):
        raise ValueError("vds_v must be non-negative; use positive terminal magnitudes")
    thermal_v = BOLTZMANN_J_K * state.temperature_k / ELEMENTARY_CHARGE_C
    smoothing_v = 2.0 * state.slope_factor * thermal_v
    overdrive = smoothing_v * _softplus((vgs - state.threshold_v) / smoothing_v)
    # Avoid 0/0 at deep subthreshold while preserving the small-vds limit.
    safe_overdrive = np.maximum(overdrive, np.finfo(float).tiny)
    effective_vds = overdrive * (-np.expm1(-vds / safe_overdrive))
    beta = (
        state.mobility_m2_vs
        * state.config.cox_f_m2
        * state.config.width_m
        / state.config.length_m
    )
    current = (
        0.5
        * beta
        * overdrive
        * effective_vds
        * (1.0 + state.config.channel_length_modulation * vds)
    )
    return np.maximum(current, 0.0)
