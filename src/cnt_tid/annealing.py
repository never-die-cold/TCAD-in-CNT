"""Post-irradiation annealing scenarios for the calibrated compact model.

Neither anchor paper provides annealing data, so the time axis is a
*scenario exploration* with registry-declared assumptions: a fraction
``f`` of every dose-built charge channel anneals away with a single
exponential time constant ``tau`` after irradiation stops,

    Q(D, t) = Q(D) * (1 - f + f * exp(-t / tau)),

applied identically to the oxide-trap, interface-trap and swing-density
channels (the simplest defensible kinetics), while the mobility degradation
is assumed permanent.  Every number from this module is conditional on those
two assumed parameters and must be quoted as a scenario, not a prediction.

The implementation never touches device.state_at_dose: annealing is a
re-parameterisation of the calibrated config (dataclasses.replace), so the
t = 0 scan is bitwise the baseline pipeline output.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .circuit import solve_inverter
from .config import SimulationConfig, config_sha256
from .device import state_at_dose
from .ringosc import stage_delay, stage_load_capacitance

DEFAULT_TIMES_S = (0.0, 3600.0, 86400.0, 604800.0, 2592000.0)
#: human-readable labels for the default annealing times
TIME_LABELS = {0: "as irradiated", 3600: "1 h", 86400: "1 day", 604800: "1 week", 2592000: "30 d"}


def annealed_config(
    config: SimulationConfig, time_s: float, fraction: float, tau_s: float
) -> SimulationConfig:
    """Re-parameterise the calibrated config after ``time_s`` of annealing."""

    if time_s < 0 or tau_s <= 0:
        raise ValueError("time_s must be non-negative and tau_s positive")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be in [0, 1]")
    factor = 1.0 - fraction + fraction * float(np.exp(-time_s / tau_s))

    def device(device_config):
        return replace(
            device_config,
            qot_slope_c_cm2_per_krad=device_config.qot_slope_c_cm2_per_krad * factor,
            qit_slope_c_cm2_per_krad=device_config.qit_slope_c_cm2_per_krad * factor,
            qit_density_slope_c_cm2_per_krad=device_config.qit_density_slope_c_cm2_per_krad * factor,
            qit_anneal_c_cm2=device_config.qit_anneal_c_cm2 * factor,
        )

    return replace(config, n_device=device(config.n_device), p_device=device(config.p_device))


def run_annealing_scan(
    config: SimulationConfig,
    fraction: float,
    tau_s: float,
    times_s: tuple[float, ...] = DEFAULT_TIMES_S,
) -> pd.DataFrame:
    """Device, inverter and ring metrics at every dose and annealing time."""

    load_cap_f = stage_load_capacitance(config)
    rows = []
    for time_s in times_s:
        annealed = annealed_config(config, time_s, fraction, tau_s)
        for dose in config.doses_krad:
            n_state = state_at_dose(annealed.n_device, dose, config.temperature_k)
            p_state = state_at_dose(annealed.p_device, dose, config.temperature_k)
            inverter = solve_inverter(n_state, p_state, config.vdd_v, config.inverter_points)
            delay_s = stage_delay(n_state, p_state, load_cap_f, config.vdd_v)
            rows.append(
                {
                    "time_s": time_s,
                    "time_label": TIME_LABELS.get(int(time_s), f"{time_s:g} s"),
                    "dose_krad": dose,
                    "p_threshold_shift_v": p_state.delta_threshold_v,
                    "ss_mv_dec": 1000.0
                    * np.log(10.0)
                    * 1.380649e-23
                    * config.temperature_k
                    / 1.602176634e-19
                    * p_state.slope_factor,
                    "vm_v": inverter.vm_v,
                    "nml_v": inverter.nml_v,
                    "nmh_v": inverter.nmh_v,
                    "stage_delay_s": delay_s,
                    "frequency_hz": float(1.0 / (2.0 * config.ro_stages * delay_s)),
                }
            )
    return pd.DataFrame(rows)


def write_annealing_artifacts(
    config: SimulationConfig,
    fraction: float,
    tau_s: float,
    times_s: tuple[float, ...],
    output_dir: str | Path,
) -> tuple[Path, dict]:
    """Run the scenario scan and write CSV + metadata."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    scan = run_annealing_scan(config, fraction, tau_s, times_s)
    scan.to_csv(destination / "annealing_scan.csv", index=False)
    metadata = {
        "schema_version": "1.0",
        "software_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(),
        "model_type": "fractional_exponential_annealing_scenario",
        "annealed_charge_fraction": fraction,
        "annealing_time_constant_s": tau_s,
        "times_s": list(times_s),
        "config_sha256": config_sha256(config),
        "warning": "No annealing data exists in either anchor paper; every number "
        "here is a scenario conditional on the two registry assumptions.",
    }
    (destination / "annealing_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return destination / "annealing_scan.csv", metadata


def plot_annealing_recovery(scan: pd.DataFrame, path: Path) -> None:
    """Recovery of VM, swing and ring frequency after irradiation stops."""

    from .p0_plots import _style  # package-internal: keep the figure style identical

    _style()
    import matplotlib.pyplot as plt

    max_dose = float(scan["dose_krad"].max())
    subset = scan[scan["dose_krad"] == max_dose].sort_values("time_s")
    times_h = subset["time_s"].to_numpy(dtype=float) / 3600.0
    # The recovery saturates within a few tau; a log time axis keeps the
    # interesting decade visible.  t = 0 is drawn at 10^-2 h.
    plot_times_h = np.maximum(times_h, 1e-2)
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.0), constrained_layout=True)
    panels = (
        ("vm_v", "Switching threshold VM (V)", "#7b3294"),
        ("ss_mv_dec", "Subthreshold swing (mV/dec)", "#1b7837"),
        ("frequency_hz", "Ring frequency (Hz)", "#4c78a8"),
    )
    for axis, (column, label, color) in zip(axes, panels, strict=True):
        values = subset[column].to_numpy(dtype=float)
        axis.plot(plot_times_h, values, "o-", color=color, linewidth=1.5, markersize=4.5)
        axis.axhline(values[0], color="#999999", linewidth=0.9, linestyle="--")
        axis.set_xscale("log")
        axis.set(
            xlabel="Annealing time (h, log; t=0 drawn at 10^-2 h)",
            ylabel=label,
            title=f"@ {max_dose:g} krad(Si)",
        )
        axis.grid(True, alpha=0.25)
        if column == "frequency_hz":
            axis.set_yscale("log")
    fig.text(
        0.006,
        0.004,
        "cnt-tid anneal | fig10 | post-irradiation recovery scenario | "
        "dashed = as-irradiated level; kinetics are registry assumptions, not measurements",
        fontsize=6.5,
        color="#555555",
    )
    fig.savefig(path)
    plt.close(fig)
