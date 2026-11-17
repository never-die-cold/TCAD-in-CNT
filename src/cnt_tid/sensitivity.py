"""One-at-a-time (OAT) parameter sensitivity for the dose sweep workflow.

Each selected parameter is perturbed by ± a relative magnitude while all
others stay at baseline. Inverter and device metrics are recomputed at every
dose point, and normalized sensitivity coefficients are reported together
with a tornado chart at the maximum dose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from .circuit import solve_inverter
from .config import SimulationConfig
from .device import state_at_dose

# (label, attribute path) for parameters exposed to OAT sensitivity.
PARAMETERS: dict[str, tuple[str, str]] = {
    "n.threshold_v": ("n_device", "threshold_v"),
    "n.mobility_m2_vs": ("n_device", "mobility_m2_vs"),
    "n.qot_slope": ("n_device", "qot_slope_c_cm2_per_krad"),
    "n.qit_slope": ("n_device", "qit_slope_c_cm2_per_krad"),
    "n.mobility_degradation": ("n_device", "mobility_degradation_per_krad"),
    "n.slope_factor_per_krad": ("n_device", "slope_factor_per_krad"),
    "p.threshold_v": ("p_device", "threshold_v"),
    "p.mobility_m2_vs": ("p_device", "mobility_m2_vs"),
    "p.qot_slope": ("p_device", "qot_slope_c_cm2_per_krad"),
    "p.qit_slope": ("p_device", "qit_slope_c_cm2_per_krad"),
    "p.mobility_degradation": ("p_device", "mobility_degradation_per_krad"),
    "p.slope_factor_per_krad": ("p_device", "slope_factor_per_krad"),
}

METRICS = ("vm_v", "nml_v", "nmh_v", "n_threshold_shift_v", "p_threshold_shift_v")


@dataclass(frozen=True)
class SensitivityResult:
    output_dir: Path
    table: pd.DataFrame
    baseline: pd.DataFrame


def _getattr_path(config: SimulationConfig, section: str, attr: str) -> Any:
    return getattr(getattr(config, section), attr)


def _with_param(
    config: SimulationConfig, section: str, attr: str, value: float
) -> SimulationConfig:
    device = getattr(config, section)
    updated = type(device)(**{**device.__dict__, attr: value})
    return type(config)(
        **{
            field: getattr(config, field)
            for field in config.__dataclass_fields__
        }
        | {section: updated}
    )


def _metric_frame(config: SimulationConfig) -> pd.DataFrame:
    rows = []
    for dose in config.doses_krad:
        n_state = state_at_dose(config.n_device, dose, config.temperature_k)
        p_state = state_at_dose(config.p_device, dose, config.temperature_k)
        inverter = solve_inverter(n_state, p_state, config.vdd_v, config.inverter_points)
        rows.append(
            {
                "dose_krad": dose,
                "vm_v": inverter.vm_v,
                "nml_v": inverter.nml_v,
                "nmh_v": inverter.nmh_v,
                "n_threshold_shift_v": n_state.delta_threshold_v,
                "p_threshold_shift_v": p_state.delta_threshold_v,
            }
        )
    return pd.DataFrame(rows)


def run_sensitivity(
    config: SimulationConfig,
    output_dir: str | Path,
    magnitude: float = 0.1,
    parameters: tuple[str, ...] = tuple(PARAMETERS),
) -> SensitivityResult:
    """Perturb each parameter by ± ``magnitude`` and record metric changes."""

    if not 0 < magnitude < 1:
        raise ValueError("magnitude must be in (0, 1)")
    unknown = [name for name in parameters if name not in PARAMETERS]
    if unknown:
        raise ValueError(f"Unknown sensitivity parameters: {unknown}")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    baseline = _metric_frame(config)
    max_dose = float(baseline["dose_krad"].max())
    rows = []
    for name in parameters:
        section, attr = PARAMETERS[name]
        base_value = float(_getattr_path(config, section, attr))
        if base_value == 0:
            continue
        for direction in (-1.0, 1.0):
            perturbed_value = base_value * (1.0 + direction * magnitude)
            if attr == "threshold_v" and perturbed_value <= 0:
                continue
            trial = _with_param(config, section, attr, perturbed_value)
            trial_frame = _metric_frame(trial)
            for metric in METRICS:
                merged = baseline[["dose_krad", metric]].merge(
                    trial_frame[["dose_krad", metric]],
                    on="dose_krad",
                    suffixes=("_base", "_trial"),
                )
                delta = merged[f"{metric}_trial"] - merged[f"{metric}_base"]
                scale = merged[f"{metric}_base"].abs()
                scale = scale.where(scale > 1e-12, np.nan)
                sensitivity = (delta / (direction * magnitude * base_value)).mean()
                rows.append(
                    {
                        "parameter": name,
                        "direction": "plus" if direction > 0 else "minus",
                        "relative_change": direction * magnitude,
                        "metric": metric,
                        "max_abs_delta": float(delta.abs().max()),
                        "mean_normalized_sensitivity": float(
                            (delta / scale).mean() / (direction * magnitude)
                        )
                        if np.isfinite(delta / scale).any()
                        else np.nan,
                        "sensitivity_per_unit": float(sensitivity),
                    }
                )
    table = pd.DataFrame(rows)
    table.to_csv(destination / "sensitivity.csv", index=False)
    baseline.to_csv(destination / "sensitivity_baseline.csv", index=False)
    _plot_tornado(table, max_dose, destination / "sensitivity_tornado.png")
    metadata = {
        "schema_version": "1.0",
        "method": "oat_relative_perturbation",
        "magnitude": magnitude,
        "dose_unit": config.dose_unit,
        "max_dose_krad": max_dose,
        "parameters": list(parameters),
        "calibration_status": config.calibration_status,
    }
    with (destination / "sensitivity_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    return SensitivityResult(destination, table, baseline)


def _plot_tornado(
    table: pd.DataFrame, max_dose: float, path: Path
) -> None:
    metrics = [metric for metric in ("vm_v", "nml_v", "nmh_v") if metric in table["metric"].unique()]
    if not metrics:
        return
    fig, axes = plt.subplots(
        1, len(metrics), figsize=(4.2 * len(metrics), 4.0), constrained_layout=True
    )
    if len(metrics) == 1:
        axes = [axes]
    for axis, metric in zip(axes, metrics, strict=True):
        subset = table[table["metric"] == metric]
        pivot = subset.pivot_table(
            index="parameter",
            columns="direction",
            values="mean_normalized_sensitivity",
            aggfunc="mean",
        )
        pivot = pivot.reindex(
            pivot["plus"].abs().sort_values(ascending=False).index
        )
        y = np.arange(len(pivot))
        axis.barh(
            y,
            pivot["plus"],
            color="tab:red",
            alpha=0.7,
            label="+ perturbation",
        )
        axis.barh(
            y,
            pivot["minus"],
            color="tab:blue",
            alpha=0.7,
            label="- perturbation",
        )
        axis.axvline(0.0, color="black", linewidth=0.8)
        axis.set_yticks(y, pivot.index, fontsize=7)
        axis.set_title(f"{metric} @ {max_dose:g} krad")
        axis.set_xlabel("Normalized sensitivity")
        axis.invert_yaxis()
    axes[0].legend(fontsize=7, frameon=False)
    fig.savefig(path)
    plt.close(fig)
